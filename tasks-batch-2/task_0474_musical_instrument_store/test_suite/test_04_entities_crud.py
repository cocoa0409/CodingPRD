"""Breadth tests over entity creation, required fields, type constraints,
not-found, duplicate-serial scoping, defaults, and listing.
"""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    create_customer,
    ApiErrorId,
    create_unit_payload, create_customer_payload,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.1: "A new customer begins with a `store_credit_cents` balance of 0"
    PRD §2.4: "a `version` integer that begins at 1 and increases by exactly 1 on
    every mutation."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    data = validate_success(
        api.create_customer(create_customer_payload(full_name="Anna", credit_score=710), SA), 201
    )
    assert data["store_credit_cents"] == 0
    assert data["version"] == 1


def test_create_unit_missing_required_serial_returns_invalid_request(api):
    """PRD §2.7: "Request well-formedness — required fields present, enum members
    valid, numeric ranges satisfied — is enforced as part of accepting any body and
    yields ERR_INVALID_REQUEST."
    PRD §3.1: "a `serial_number`, an `acquisition_cost_cents` (what the store paid,
    at least 0)"

    Design: Corner/entities/create_unit_missing_required_serial_returns_invalid_request
    """
    payload = create_unit_payload(model_name="Oboe", category="BAND", condition="NEW",
                                  acquisition_cost_cents=30000, list_price_cents=60000,
                                  monthly_rent_cents=5000)
    payload.pop("serial_number")
    resp = api.create_unit(payload, SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_unit_invalid_condition_enum_returns_invalid_request(api):
    """PRD §3.1: "a `condition` that is one of `NEW`, `USED`, or `VINTAGE`"
    PRD §2.7: "Request well-formedness — required fields present, enum members valid,
    numeric ranges satisfied — is enforced as part of accepting any body and yields
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_unit_invalid_condition_enum_returns_invalid_request
    """
    resp = api.create_unit(create_unit_payload(condition="ANTIQUE"), SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_unit_nonexistent_returns_not_found(api):
    """PRD §2.7: "Existence comes third: every resource referenced by the request —
    both path identifiers and body foreign keys — must exist ... and the first
    missing reference yields ERR_NOT_FOUND."

    Design: Corner/entities/get_unit_nonexistent_returns_not_found
    """
    resp = api.get_unit("11111111-1111-4111-8111-111111111111", SA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_serial_same_model_returns_conflict(api):
    """PRD §3.1: "stocking a second unit of the same model with an already-used
    serial is rejected with ERR_DUPLICATE_SERIAL."

    Design: Corner/entities/duplicate_serial_same_model_returns_conflict
    """
    p = create_unit_payload(model_name="Yamaha P-45", category="KEYBOARD", condition="NEW",
                            serial_number="DUP-1", acquisition_cost_cents=40000,
                            list_price_cents=80000, monthly_rent_cents=7000)
    validate_success(api.create_unit(dict(p), SA), 201)
    resp = api.create_unit(dict(p), SA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL.value)


def test_same_serial_different_model_is_allowed(api):
    """PRD §3.1: "The serial number need only be unique among units that share the
    same model_name; two different models may carry the same manufacturer serial"

    Design: Corner/entities/same_serial_different_model_is_allowed
    """
    validate_success(
        api.create_unit(create_unit_payload(model_name="Model A", serial_number="SHARED-1"), SA), 201
    )
    data = validate_success(
        api.create_unit(create_unit_payload(model_name="Model B", serial_number="SHARED-1"), SA), 201
    )
    assert data["status"] == "AVAILABLE"


def test_unit_default_source_kind_is_store_purchase(api):
    """PRD §3.1: "An optional source_kind records how the unit entered stock and is
    one of STORE_PURCHASE, TRADE_IN, or CONSIGNMENT, defaulting to STORE_PURCHASE
    when omitted."

    Design: Corner/entities/unit_default_source_kind_is_store_purchase
    """
    payload = create_unit_payload(model_name="Default Sax")
    payload.pop("source_kind", None)
    data = validate_success(api.create_unit(payload, SA), 201)
    assert data["source_kind"] == "STORE_PURCHASE"


def test_list_units_paginated_envelope(api):
    """PRD §2.3: "The meta object of a list response carries the pagination fields
    limit, offset, total_count, and has_more."

    Design: Corner/entities/list_units_paginated_envelope
    """
    validate_success(api.create_unit(create_unit_payload(model_name="List Unit"), SA), 201)
    resp = api.list_units(SA, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta
    assert "has_more" in meta
