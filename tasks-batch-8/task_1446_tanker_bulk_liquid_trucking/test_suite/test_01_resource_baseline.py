"""Resource creation, request-shape, uniqueness, listing, and envelope claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_compatibility_rule_payload,
    create_customer,
    create_customer_payload,
    create_driver,
    create_driver_payload,
    create_product,
    create_product_payload,
    create_trailer,
    create_trailer_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_customer_created_with_defaults(api):
    """PRD 3.1: "A new customer starts with `status` `ACTIVE` and an `exposure_cents` of
    zero" and the optional `dedicated_program_enrolled` flag "defaults to false".
    PRD 2.4: "The `version` is an integer that increments by exactly one on every
    mutation" (so a freshly created resource carries version 1).

    Design: Corner/entities/customer_created_with_defaults
    """
    res = api.create_customer(create_customer_payload(name="Acme Chem", credit_limit_cents=5000000), ADMIN)
    cust = validate_success(res, 201)
    assert cust["status"] == "ACTIVE"
    assert cust["dedicated_program_enrolled"] is False
    assert cust["exposure_cents"] == 0
    assert cust["version"] == 1


def test_product_missing_required_field_rejected(api):
    """PRD 2.8 step 4: "required fields are present, enum members are valid, scalar
    ranges are sane" and "unknown body fields are rejected", with "Failures are
    `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/product_missing_required_field_rejected
    """
    payload = create_product_payload()
    del payload["placard_code"]
    res = api.create_product(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_product_invalid_enum_rejected(api):
    """PRD 3.1: "`compatibility_group` drawn from `PETROLEUM`, `SOLVENT`, `ACID`,
    `CAUSTIC`, `VEG_OIL`, `FOOD_GRADE`, or `LATEX`"; PRD 2.8 step 4 requires that
    "enum members are valid", with "Failures are `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/product_invalid_enum_rejected
    """
    payload = create_product_payload(compatibility_group="RADIOACTIVE")
    res = api.create_product(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_shipment_not_found_returns_404(api):
    """PRD 2.8 step 3: "The first unknown identifier yields that resource's dedicated
    404", and `ERR_SHIPMENT_NOT_FOUND` is one of the listed per-resource 404 codes.

    Design: Corner/entities/shipment_not_found_returns_404
    """
    res = api.get_shipment(NON_EXISTENT_UUID, DISP)
    validate_error(res, "ERR_SHIPMENT_NOT_FOUND", expected_status=404)


def test_trailer_tare_sum_rejected(api):
    """PRD 3.1: "`tare_weight_lb` decomposed into `tare_steer_lb`, `tare_drive_lb`, and
    `tare_trailer_lb`, where the three components must sum exactly to the stated tare
    weight or creation fails with `ERR_TARE_AXLE_MISMATCH`".

    Design: Corner/entities/trailer_tare_sum_rejected
    """
    payload = create_trailer_payload(tare_trailer_lb=9999)  # 6000+9000+9999 = 24999 != 25000
    res = api.create_trailer(payload, ADMIN)
    validate_error(res, "ERR_TARE_AXLE_MISMATCH", expected_status=422)


def test_trailer_duplicate_unit_number_rejected(api):
    """PRD 3.1: "a fleet `unit_number` that must be unique across all trailers (a
    duplicate is rejected with `ERR_DUPLICATE_UNIT_NUMBER`)".

    Design: Corner/entities/trailer_duplicate_unit_number_rejected
    """
    create_trailer(unit_number="T-101")
    res = api.create_trailer(create_trailer_payload(unit_number="T-101", capacity_gallons=5000), ADMIN)
    validate_error(res, "ERR_DUPLICATE_UNIT_NUMBER", expected_status=409)


def test_compatibility_rule_duplicate_pair_rejected(api):
    """PRD 3.2: "The (`prior_group`, `next_group`) pair is unique across all rules; a
    duplicate is rejected with `ERR_DUPLICATE_COMPATIBILITY_RULE`."

    Design: Corner/entities/compatibility_rule_duplicate_pair_rejected
    """
    api.create_compatibility_rule(
        create_compatibility_rule_payload(prior_group="PETROLEUM", next_group="PETROLEUM"), ADMIN)
    res = api.create_compatibility_rule(
        create_compatibility_rule_payload(
            prior_group="PETROLEUM", next_group="PETROLEUM", required_wash_level="FLUSH"),
        ADMIN)
    validate_error(res, "ERR_DUPLICATE_COMPATIBILITY_RULE", expected_status=409)


def test_shipment_create_extra_field_rejected(api):
    """PRD 2.8 step 4: "unknown body fields are rejected", with "Failures are
    `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/shipment_create_extra_field_rejected
    """
    cust = create_customer()
    prod = create_product()
    payload = {
        "customer_id": cust["id"], "product_id": prod["id"], "ordered_gallons": 1000,
        "route_miles": 100, "rate_per_gal_cents": 100, "status": "RECONCILED",
    }
    res = api.create_shipment(payload, DISP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_customers_list_pagination(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned" and "The
    `offset` parameter skips that many items from the start of the result set and
    defaults to 0", and "Every list response includes `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/customers_list_pagination
    """
    for name in ("C1", "C2", "C3"):
        api.create_customer(create_customer_payload(name=name, credit_limit_cents=1000), ADMIN)

    page1, meta1 = validate_paginated(api.list_customers(DISP, params={"limit": 2}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_customers(DISP, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_driver_duplicate_cdl_rejected(api):
    """PRD 3.1: "a `cdl_number` unique across all drivers (`ERR_DUPLICATE_CDL_NUMBER`
    on collision)".

    Design: Corner/errors/driver_duplicate_cdl_rejected
    """
    create_driver(cdl_number="CDL-1")
    res = api.create_driver(
        create_driver_payload(full_name="Eli Poe", cdl_number="CDL-1", hazmat_endorsement=False),
        ADMIN)
    validate_error(res, "ERR_DUPLICATE_CDL_NUMBER", expected_status=409)
