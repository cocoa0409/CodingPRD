"""Breadth tests: entity creation, retrieval, listing, defaults, computed/system
fields, type constraints, and immutability (PRD §2.3, §2.4, §3.1, §3.2)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    is_valid_uuid, is_iso8601_timestamp,
    create_customer_payload, create_fee_schedule_payload, create_bill_pay_payload,
    create_money_order_payload,
    setup_verified_customer_and_drawer, create_customer, screen_customer,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_create_customer_returns_201_with_pending_kyc(api):
    """PRD §3.1: "A freshly registered customer begins with `kyc_status` of `PENDING`, a
    `risk_tier` of `STANDARD`, a `risk_score` of 0, an `outstanding_recovery_cents` of 0,
    and zeroed velocity counters".
    PRD §2.4: "an integer `version` that begins at 1".

    Design: Corner/entities/create_customer_returns_201_with_pending_kyc
    """
    res = api.create_customer(
        create_customer_payload(full_name="New Cust", id_type="DRIVERS_LICENSE",
                                id_number="DL-100", date_of_birth="1990-01-01"), TELLER)
    cust = validate_success(res, 201)
    assert cust["kyc_status"] == "PENDING"
    assert cust["risk_tier"] == "STANDARD"
    assert cust["risk_score"] == 0
    assert cust["version"] == 1


def test_get_customer_returns_stored_entity(api):
    """PRD §3.1: "Either a `Teller` or a `StoreManager` registers a customer by supplying
    the customer's legal `full_name`".
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    A registered customer fetched back exposes the stored full_name.

    Design: Corner/entities/get_customer_returns_stored_entity
    """
    created = create_customer(full_name="Read Me", id_type="PASSPORT",
                              id_number="P-101", date_of_birth="1980-02-02")
    res = api.get_customer(created["id"], TELLER)
    cust = validate_success(res, 200)
    assert cust["full_name"] == "Read Me"


def test_list_customers_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/entities/list_customers_paginated_envelope
    """
    create_customer(full_name="C One", id_type="STATE_ID", id_number="SID-102",
                    date_of_birth="1981-03-03")
    create_customer(full_name="C Two", id_type="STATE_ID", id_number="SID-103",
                    date_of_birth="1982-04-04")
    res = api.list_customers(TELLER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_customer_not_found(api):
    """PRD §2.5: "A reference to a resource that does not exist is rejected with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_customer_not_found
    """
    res = api.get_customer("00000000-0000-0000-0000-000000000000", TELLER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_customer_missing_required_field(api):
    """PRD §2.11: "A malformed body, a missing required field, or an out-of-domain value
    (for example a `face_amount_cents` below 1 or an unrecognized enum) is rejected with
    `ERR_VALIDATION`."
    PRD §3.1: a customer is registered by supplying "the `id_number` on that document".

    Design: Corner/entities/create_customer_missing_required_field
    """
    payload = create_customer_payload(full_name="No IdNum", id_type="DRIVERS_LICENSE",
                                      date_of_birth="1990-01-01")
    del payload["id_number"]
    res = api.create_customer(payload, TELLER)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_fee_schedule_active_defaults_true(api):
    """PRD §3.2: "an `active` flag (defaulting to true) governing whether the schedule may
    be selected for new transactions."

    Design: Corner/entities/fee_schedule_active_defaults_true
    """
    payload = create_fee_schedule_payload(check_type="PERSONAL", base_fee_cents=500,
                                          percent_rate_bps=300, tier_breakpoint_cents=100000,
                                          high_percent_rate_bps=400, max_fee_cents=10000)
    del payload["active"]
    res = api.create_fee_schedule(payload, MANAGER)
    sched = validate_success(res, 201)
    assert sched["active"] is True


def test_transaction_fee_computed_bill_pay_flat(api):
    """PRD §3.4: "On creation the server computes `fee_cents` per §3.2".
    PRD §3.2: "For a `BILL_PAY`, the fee is a flat 195 cents independent of the face amount."

    fee_cents is server-computed and not a client input; a BILL_PAY always yields 195.

    Design: Corner/entities/transaction_fee_computed_ignores_client_value
    """
    cust, drawer = setup_verified_customer_and_drawer("C1", opening_float_cents=1000000)
    res = api.create_transaction(
        create_bill_pay_payload(cust["id"], drawer["id"], 80000,
                                biller_code="ELEC", account_reference="ACC-1"), TELLER)
    txn = validate_success(res, 201)
    assert txn["fee_cents"] == 195


def test_customer_system_fields_generated(api):
    """PRD §2.4: "Each such resource has an `id` formatted as a UUID with no type prefix, a
    `created_at` timestamp (ISO 8601 UTC with three fractional digits) ..., and an integer
    `version` that begins at 1 and increments by one on every mutation."

    Design: Corner/entities/customer_system_fields_generated
    """
    cust = create_customer(full_name="Sys Fields", id_type="STATE_ID",
                           id_number="SID-105", date_of_birth="1988-08-08")
    assert is_valid_uuid(cust["id"]) and "_" not in cust["id"]
    assert is_iso8601_timestamp(cust["created_at"])
    assert cust["version"] == 1


def test_customer_invalid_id_type_enum_rejected(api):
    """PRD §2.11: "an out-of-domain value (for example a `face_amount_cents` below 1 or an
    unrecognized enum) is rejected with `ERR_VALIDATION`."
    PRD §3.1: "the `id_type` of the government identification presented — one of
    `DRIVERS_LICENSE`, `STATE_ID`, `PASSPORT`, or `MILITARY_ID`".

    Design: Corner/entities/customer_invalid_id_type_enum_rejected
    """
    res = api.create_customer(
        create_customer_payload(full_name="Bad Enum", id_type="FACE_TATTOO",
                                id_number="X-1", date_of_birth="1990-01-01"), TELLER)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_compliance_screen_immutable_no_version(api):
    """PRD §2.4: "A compliance screen is an immutable audit record: once written it is
    never modified. It therefore carries only an `id` (UUID) and a `created_at` timestamp —
    it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/compliance_screen_immutable_no_version
    """
    cust = create_customer(full_name="Screen Sub", id_type="PASSPORT",
                           id_number="P-106", date_of_birth="1979-09-09")
    screen = screen_customer(cust["id"], ofac_list_hit=False, kyc_documents_valid=True)
    res = api.list_customer_compliance_screens(cust["id"], MANAGER)
    data, meta = validate_paginated(res)
    ids = [s["id"] for s in data]
    assert screen["id"] in ids
    for s in data:
        assert "version" not in s, "ComplianceScreen must not expose a version field"


def test_transaction_face_amount_zero_rejected(api):
    """PRD §2.11: "an out-of-domain value (for example a `face_amount_cents` below 1 ...)
    is rejected with `ERR_VALIDATION`."
    PRD §3.4: the face amount "must be at least 1".

    Design: Corner/entities/transaction_face_amount_zero_rejected
    """
    cust, drawer = setup_verified_customer_and_drawer("C2", opening_float_cents=1000000)
    res = api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 0, "Z"), TELLER)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)
