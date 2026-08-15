"""Facility onboarding and catalog registration defaults (PRD 3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_facility,
    assert_unit,
    base_scenario,
    create_facility,
    create_facility_payload,
    create_linen_stock_payload,
    create_par_level_payload,
    create_unit_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_create_facility_defaults_applied(api, linen_manager_headers):
    """PRD 3.1: "and optionally `monthly_cap_cents`, a contract cap on a single
    invoice's final total — when omitted it is null and no cap is enforced."
    PRD 3.1: "A new facility starts with `surge_posture` of `NORMAL` and a
    `credit_balance_cents` of zero; the credit balance is a vendor-credit pool
    that later receives credits from verified complaints whose invoice is
    already settled or not yet finalized."
    PRD 2.4: "`id` (string): a server-minted UUID with no type prefix,
    uniquely identifying the resource."

    Design: Corner/entities/create_facility_defaults_applied
    """
    facility = validate_success(
        api.create_facility(create_facility_payload(), linen_manager_headers), 201
    )
    assert_facility(facility)

    fetched = validate_success(api.get_facility(facility["id"], linen_manager_headers))
    assert fetched["monthly_cap_cents"] is None
    assert fetched["surge_posture"] == "NORMAL"
    assert fetched["credit_balance_cents"] == 0
    assert is_valid_uuid(fetched["id"])
    assert isinstance(fetched["version"], int) and fetched["version"] >= 1


def test_create_unit_with_invalid_tier_returns_invalid_request(
    api, linen_manager_headers
):
    """PRD 3.1: "Within a facility, a `LinenManager` registers each nursing
    **Unit** by supplying the `facility_id`, a unit `name` (for example
    "4 West" or "ICU"), and a `unit_tier` of either `CRITICAL` or `STANDARD` —
    the tier drives the order of surge reserve allocation."
    PRD 2.9: "Fifth, request shape — required fields present, enum members
    valid, numeric ranges respected (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_unit_with_invalid_tier_returns_invalid_request
    """
    facility = create_facility()
    res = api.create_unit(
        create_unit_payload(facility["id"], name="4 West", unit_tier="WARD"),
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_stock_missing_required_sku_returns_invalid_request(
    api, linen_manager_headers
):
    """PRD 3.1: "Registering a **LinenStock** takes the `facility_id`; a `sku`
    item code that must be unique within the facility; a `display_name` such as
    "Flat Sheet Twin"; a `category` of `FLATWORK`, `TERRY`, `PATIENT_APPAREL`,
    or `ISOLATION`."
    PRD 2.9: "Fifth, request shape — required fields present, enum members
    valid, numeric ranges respected (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_stock_missing_required_returns_invalid_request
    """
    facility = create_facility()
    payload = create_linen_stock_payload(facility["id"])
    del payload["sku"]
    res = api.create_linen_stock(payload, linen_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_cart_run_not_found_returns_404(api, linen_manager_headers):
    """PRD 2.9: "Fourth, existence — every path identifier and every body
    foreign-key reference, validated left to right, with the first missing
    reference surfacing as `ERR_NOT_FOUND`."

    Design: Corner/entities/get_cart_run_not_found_returns_404
    """
    create_facility()
    res = api.get_cart_run(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", linen_manager_headers
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_facility_ignores_client_supplied_computed_fields(
    api, linen_manager_headers
):
    """PRD 3.1: "A new facility starts with `surge_posture` of `NORMAL` and a
    `credit_balance_cents` of zero; the credit balance is a vendor-credit pool
    that later receives credits from verified complaints whose invoice is
    already settled or not yet finalized."

    Design: Corner/entities/create_facility_extra_fields_input_ignored
    """
    payload = create_facility_payload()
    payload["surge_posture"] = "SURGE"
    payload["credit_balance_cents"] = 999
    facility = validate_success(
        api.create_facility(payload, linen_manager_headers), 201
    )
    assert_facility(facility)
    assert facility["surge_posture"] == "NORMAL"
    assert facility["credit_balance_cents"] == 0


def test_create_unit_success_shape(api, linen_manager_headers):
    """PRD 3.1: "Within a facility, a `LinenManager` registers each nursing
    **Unit** by supplying the `facility_id`, a unit `name` (for example
    "4 West" or "ICU"), and a `unit_tier` of either `CRITICAL` or `STANDARD` —
    the tier drives the order of surge reserve allocation. A unit's
    `quality_flag` starts at `CLEAR`; the rule that later flips it to `WATCH`
    lives with the complaint workflow in §3.7."

    Design: Corner/entities/create_unit_with_invalid_tier_returns_invalid_request
    """
    facility = create_facility()
    unit = validate_success(
        api.create_unit(
            create_unit_payload(facility["id"], name="ICU", unit_tier="CRITICAL"),
            linen_manager_headers,
        ),
        201,
    )
    assert_unit(unit)
    assert unit["quality_flag"] == "CLEAR"
    assert unit["unit_tier"] == "CRITICAL"


def test_duplicate_par_level_returns_conflict(api, linen_manager_headers):
    """PRD 3.2: "The pair of `unit_id` and `stock_id` is unique: configuring
    a second par level for an existing pair is rejected with
    `ERR_PAR_LEVEL_CONFLICT`."

    Design: Corner/validations/duplicate_par_level_returns_conflict
    """
    ctx = base_scenario()
    res = api.create_par_level(
        create_par_level_payload(
            ctx["unit"]["id"], ctx["stock"]["id"],
            base_par_quantity=25, cart_cycle="WEEKLY",
        ),
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_PAR_LEVEL_CONFLICT)
