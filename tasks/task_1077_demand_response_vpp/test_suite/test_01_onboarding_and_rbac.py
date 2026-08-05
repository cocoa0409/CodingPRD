"""Onboarding, listing, and role-based access control.

Translates queue-B (corner) instances from the entities / endpoints / rbac
sections: envelope, required-field, not-found, FK, enum, system-field,
pagination, role-denied, ownership-denied, and unauthenticated claims.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS, ANON_HEADERS,
    make_aggregator_headers, make_customer_headers,
    create_program_payload, create_aggregator_payload,
    create_customer_payload, create_device_payload,
    onboard_aggregator, onboard_customer,
    assert_aggregator,
)

OP = TEST_USERS["program_operator_headers"]
AUD = TEST_USERS["auditor_headers"]
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_aggregator_returns_object_envelope_with_zeroed_ledgers(api):
    """PRD §3.2: "the aggregator is created in ACTIVE status (its other allowed
    status is SUSPENDED) with its computed ledgers — enrolled_committed_kw,
    season_delivered_kwh, and paid_balance_cents — all starting at 0."

    Design: Corner/entities/create_aggregator_success_envelope
    """
    resp = api.create_aggregator(create_aggregator_payload(name="Agg", contact_email="a@x.com"), OP)
    data = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert_aggregator(data)
    assert data["paid_balance_cents"] == 0
    assert data["enrolled_committed_kw"] == 0


def test_create_program_missing_name_rejected(api):
    """PRD §3.1: "Any enum value outside its declared set yields ERR_INVALID_ENUM;
    a missing required field or a wrong-typed value yields ERR_VALIDATION."

    Design: Corner/entities/create_program_missing_required_name
    """
    payload = create_program_payload()
    payload.pop("name")
    resp = api.create_program(payload, OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_unknown_program_returns_not_found(api):
    """PRD §2.7: "The not-found errors are resource-specific — ERR_PROGRAM_NOT_FOUND,
    ERR_AGGREGATOR_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND, ERR_DEVICE_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND, ERR_DISPATCH_EVENT_NOT_FOUND, ERR_DISPATCH_NOT_FOUND,
    ERR_METER_READING_NOT_FOUND, ERR_SETTLEMENT_NOT_FOUND, and ERR_PAYMENT_NOT_FOUND
    — each returning HTTP 404."

    Design: Corner/entities/program_not_found_returns_404
    """
    resp = api.get_program(UNKNOWN_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_register_device_with_unknown_customer_rejected(api):
    """PRD §3.2: "The customer_id must reference an existing customer, else
    ERR_CUSTOMER_NOT_FOUND."

    Design: Corner/entities/device_customer_fk_not_found
    """
    agg = onboard_aggregator()
    resp = api.create_device(
        create_device_payload(UNKNOWN_UUID, device_type="BATTERY", nameplate_kw=10, capacity_kwh=20),
        make_aggregator_headers(agg["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_register_device_with_invalid_device_type_enum_rejected(api):
    """PRD §3.2: "An Aggregator registers a flexible asset by supplying the owning
    customer_id, the device_type (one of BATTERY, THERMOSTAT, or EV_CHARGER), the
    rated nameplate_kw, and optionally capacity_kwh."
    PRD §2.8: "(7) enum fields hold a declared value, else ERR_INVALID_ENUM (HTTP 422)".

    Design: Corner/entities/invalid_enum_device_type_rejected
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    resp = api.create_device(
        create_device_payload(cust["id"], device_type="FURNACE", nameplate_kw=10, capacity_kwh=20),
        make_aggregator_headers(agg["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_device_aggregator_id_set_from_acting_user(api):
    """PRD §3.2: "The device's aggregator_id is not supplied in the body — it is
    set from the acting aggregator's X-User-ID, binding the device to its
    registrar — and the device is created in ACTIVE status."

    Design: Corner/entities/device_aggregator_id_system_assigned
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    resp = api.create_device(
        create_device_payload(cust["id"], device_type="BATTERY", nameplate_kw=10, capacity_kwh=20),
        make_aggregator_headers(agg["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["aggregator_id"] == agg["id"]
    assert data["status"] == "ACTIVE"


def test_list_programs_returns_array_with_pagination_meta(api):
    """PRD §2.3: "The meta block of a list response carries limit, offset,
    total_count (the count of all matching records before pagination), and
    has_more (true when records remain beyond the returned page)."

    Design: Corner/endpoints/list_programs_pagination_envelope
    """
    get_success_data(api.create_program(create_program_payload(name="P1"), OP))
    get_success_data(api.create_program(create_program_payload(name="P2"), OP))
    resp = api.list_programs(AUD)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_auditor_cannot_create_program(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §2.1: "An auditor may perform any GET read but no write operation."

    Design: Corner/rbac/auditor_cannot_create_program
    """
    resp = api.create_program(create_program_payload(name="P"), AUD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_register_device(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/customer_cannot_register_device
    """
    cust = onboard_customer()
    resp = api.create_device(
        create_device_payload(cust["id"], device_type="BATTERY", nameplate_kw=10, capacity_kwh=20),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_foreign_aggregator_cannot_decommission_device(api):
    """PRD §3.2: "The acting aggregator's X-User-ID must equal the device's
    aggregator_id, else ERR_FORBIDDEN_OWNERSHIP."

    Design: Corner/rbac/foreign_aggregator_forbidden_device_decommission
    """
    a1 = onboard_aggregator(name="A1", email="a1@x.com")
    a2 = onboard_aggregator(name="A2", email="a2@x.com")
    cust = onboard_customer()
    dev = get_success_data(api.create_device(
        create_device_payload(cust["id"], device_type="BATTERY", nameplate_kw=10, capacity_kwh=20),
        make_aggregator_headers(a1["id"]),
    ))
    resp = api.decommission_device(dev["id"], make_aggregator_headers(a2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_aggregator(create_aggregator_payload(name="Agg", contact_email="a@x.com"), ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
