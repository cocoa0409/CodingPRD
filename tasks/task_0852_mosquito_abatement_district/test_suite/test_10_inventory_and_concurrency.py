"""The pesticide ledger, stock adjustments, uniqueness, and the two version
guards."""

import test_helpers as fx
from test_helpers import (
    ADMIN,
    ECOLOGIST,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_adjustment_cannot_drive_stock_negative(api):
    """PRD §3.2: "An adjustment is refused with `ERR_INVENTORY_NEGATIVE` (HTTP 422)
    when it would drive `on_hand_ml` below `0.00`, and equally when it would bring
    `received_total_ml` to `0.00` or below — a district may write a product down
    but may never write it out of existence, since a zero-received product has no
    meaningful ledger."
    PRD §3.2: "Both `on_hand_ml` and `received_total_ml` absorb the delta, which is
    exactly what keeps the four-field partition of §2.9 intact: shifting the total
    and the unreserved balance by the same amount leaves committed and applied
    stock untouched."

    Design: Corner/validations/corner_inventory_adjustment_cannot_drive_stock_negative
    """
    fx.set_clock(fx.CLOCK_BASE)
    product = fx.create_product(
        name="Small Drum", epa_reg_no="EPA-777", active_ingredient="METHOPRENE",
        label_rate_ml_per_acre=10.0, cost_cents_per_liter=5000, received_total_ml=100.0,
    )
    version = product["version"]

    too_deep = api.create_stock_adjustment(
        product["id"],
        {"delta_ml": -200.0, "reason": "Spill write-off",
         "expected_product_version": version},
        ADMIN,
    )
    validate_error(too_deep, ApiErrorId.ERR_INVENTORY_NEGATIVE.value, 422)

    adjusted = validate_success(
        api.create_stock_adjustment(
            product["id"],
            {"delta_ml": -40.0, "reason": "Partial spill write-off",
             "expected_product_version": version},
            ADMIN,
        )
    )

    fx.assert_pesticide_product(adjusted)
    fx.assert_index(adjusted["on_hand_ml"], 60.00, "on_hand_ml")
    assert adjusted["version"] == version + 1
    fx.assert_index(adjusted["received_total_ml"], 60.00, "received_total_ml")
    fx.assert_index(adjusted["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(adjusted["applied_ml"], 0.00, "applied_ml")


def test_every_uniqueness_scope_reports_duplicate_resource(api):
    """PRD §3.1: "Zone codes are unique across the whole district; a second area
    claiming a code already in use is rejected with `ERR_DUPLICATE_RESOURCE`."
    PRD §3.2: "Duplicate EPA registration numbers are rejected with
    `ERR_DUPLICATE_RESOURCE`."
    PRD §3.5: "An area may hold at most one observation per calendar day; a second
    observation for the same area and the same `obs_date` is
    `ERR_DUPLICATE_RESOURCE`."
    PRD §2.11: "**Uniqueness** — no uniqueness constraint is violated; otherwise
    `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/validations/corner_uniqueness_constraints_all_return_duplicate_resource
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    fx.create_trap_site(area["id"], site_code="T-001")
    fx.create_product(received_total_ml=1000.0)
    fx.create_observation(area["id"], obs_date="2026-05-30", tmax_c=25.1, tmin_c=20.0)

    duplicate_area = api.create_service_area(
        {"name": "Copy Zone", "code": "NW1", "season_start_date": "2026-05-01",
         "population": 10},
        ADMIN,
    )
    validate_error(duplicate_area, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    duplicate_site = api.create_trap_site(
        area["id"],
        {"site_code": "T-001", "trap_type": "GRAVID", "habitat": "WETLAND",
         "x_m": 9, "y_m": 9},
        ADMIN,
    )
    validate_error(duplicate_site, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    duplicate_product = api.create_pesticide_product(
        {"name": "Other Brand", "epa_reg_no": "EPA-202",
         "active_ingredient": "METHOPRENE", "application_method": "LARVICIDE",
         "label_rate_ml_per_acre": 10.0, "reentry_interval_hours": 0,
         "cost_cents_per_liter": 1, "received_total_ml": 10.0},
        ADMIN,
    )
    validate_error(duplicate_product, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    duplicate_observation = api.create_weather_observation(
        area["id"], {"obs_date": "2026-05-30", "tmax_c": 20.0, "tmin_c": 15.0}, ADMIN
    )
    validate_error(duplicate_observation, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)


def test_second_assessment_from_a_stale_area_version_is_rejected(api):
    """PRD §2.7: "That request must carry `expected_service_area_version`, a
    non-optional field holding the `version` of the `ServiceArea` as the client
    last read it. If the value does not equal the area's current `version`, the
    request is rejected with `ERR_STALE_SERVICE_AREA_VERSION` (HTTP 412)."
    PRD §2.7: "A successful create increments the area's `version` by 1, so two
    consecutive creates from the same observed version cannot both succeed."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_service_area_version_rejects_second_assessment
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    observed_version = fx.area_version(area["id"])

    first = validate_success(
        api.create_risk_assessment(
            area["id"],
            {"as_of_date": "2026-06-01",
             "expected_service_area_version": observed_version},
            ECOLOGIST,
        ),
        201,
    )
    stale = api.create_risk_assessment(
        area["id"],
        {"as_of_date": "2026-06-01", "expected_service_area_version": observed_version},
        ECOLOGIST,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_SERVICE_AREA_VERSION.value, 412)

    assert fx.read_assessment(first["id"])["status"] == "OPEN"
    assert fx.read_area(area["id"])["version"] == observed_version + 1

    _, meta = validate_paginated(api.list_risk_assessments(area["id"], ECOLOGIST))
    assert meta["total_count"] == 1


def test_replayed_product_version_is_rejected_and_the_ledger_holds(api):
    """PRD §2.7: "That request must carry `expected_product_version`, holding the
    `version` of the `PesticideProduct` as the client last read it; a mismatch with
    the product's current `version` is rejected with `ERR_STALE_PRODUCT_VERSION`
    (HTTP 412)."
    PRD §2.7: "A successful adjustment increments the product's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_product_version_rejects_second_adjustment
    """
    fx.set_clock(fx.CLOCK_BASE)
    product = fx.create_product(received_total_ml=1000.0)
    observed_version = fx.read_product(product["id"])["version"]

    applied = validate_success(
        api.create_stock_adjustment(
            product["id"],
            {"delta_ml": 500.0, "reason": "Drum received from state depot",
             "expected_product_version": observed_version},
            ADMIN,
        )
    )
    fx.assert_index(applied["on_hand_ml"], 1500.00, "on_hand_ml")
    assert applied["version"] == observed_version + 1

    replay = api.create_stock_adjustment(
        product["id"],
        {"delta_ml": 500.0, "reason": "Duplicate posting of the same delivery",
         "expected_product_version": observed_version},
        ADMIN,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_PRODUCT_VERSION.value, 412)

    final = fx.read_product(product["id"])
    fx.assert_index(final["received_total_ml"], 1500.00, "received_total_ml")
    fx.assert_index(final["on_hand_ml"], 1500.00, "on_hand_ml")
    fx.assert_inventory_partition(final)
