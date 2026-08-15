"""Roster onboarding defaults, catalog reads, request-shape and auth gates."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_technician,
    assert_unit,
    create_call_ticket_payload,
    create_rotation_shift_payload,
    create_technician_payload,
    create_unit_payload,
    make_technician,
    make_unit,
    make_vendor,
    make_vendor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_technician_creation_applies_system_defaults(api, property_admin_headers):
    """PRD §3.1: "A new technician starts with `status` `ACTIVE`, a
    `callback_minutes_168h` of zero, and a null `fatigue_block_until`."

    Design: Corner/entities/technician_creation_applies_system_defaults
    """
    resp = api.create_technician(
        create_technician_payload(
            full_name="New Tech",
            capability="TECHNICIAN",
            base_hourly_rate_cents=5000,
            on_call_differential_bp=1000,
        ),
        property_admin_headers,
    )
    data = validate_success(resp, 201)
    assert_technician(data)
    assert data["status"] == "ACTIVE", "new technician must start ACTIVE"
    assert data["callback_minutes_168h"] == 0, "fatigue ledger starts zeroed"
    assert data["fatigue_block_until"] is None, "no rest block at onboarding"


def test_unit_get_roundtrip_returns_stored_fields(api, property_admin_headers,
                                                  dispatcher_headers):
    """PRD §3.1: "Units are registered with a property-wide unique `unit_number`
    — a duplicate is rejected with `ERR_UNIT_NUMBER_EXISTS` — plus a
    `building_code`. Every unit carries a `habitability_status` that begins at
    `HABITABLE` and is flipped only as a side effect of relocation approval and
    relocation end; there is no direct unit-status edit."

    Design: Corner/entities/unit_get_roundtrip_returns_stored_fields
    """
    created = validate_success(
        api.create_unit(
            create_unit_payload(unit_number="A-1", building_code="BA"),
            property_admin_headers,
        ),
        201,
    )
    data = validate_success(api.get_unit(created["id"], dispatcher_headers), 200)
    assert_unit(data)
    assert data["unit_number"] == "A-1"
    assert data["building_code"] == "BA"
    assert data["habitability_status"] == "HABITABLE"


def test_ticket_create_invalid_enum_returns_invalid_request(
    api, property_admin_headers, dispatcher_headers
):
    """PRD §2.9: "4. **Request body shape** — required fields present, enum
    values valid, datetimes and integers well-formed, window ends strictly
    after their starts, amounts strictly positive (`ERR_INVALID_REQUEST`, HTTP
    400)."

    Design: Corner/entities/ticket_create_invalid_enum_returns_invalid_request
    """
    unit = make_unit(unit_number="A-2", building_code="BA")
    resp = api.create_call_ticket(
        create_call_ticket_payload(
            unit_id=unit["id"],
            caller_name="X",
            caller_phone="555",
            category="BROKEN_PIPE",
            description="bad enum",
        ),
        dispatcher_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    # The rejected create leaves no row behind.
    rows, meta = validate_paginated(
        api.list_call_tickets(dispatcher_headers, params={"unit_id": unit["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_shift_create_inverted_window_returns_invalid_request(
    api, property_admin_headers
):
    """PRD §2.9: "4. **Request body shape** — required fields present, enum
    values valid, datetimes and integers well-formed, window ends strictly
    after their starts, amounts strictly positive (`ERR_INVALID_REQUEST`, HTTP
    400)."

    Design: Corner/entities/shift_create_inverted_window_returns_invalid_request
    """
    tech = make_technician()
    resp = api.create_rotation_shift(
        create_rotation_shift_payload(
            technician_id=tech["id"],
            start_at="2026-08-01T16:00:00Z",
            end_at="2026-08-01T08:00:00Z",
        ),
        property_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestResourceNotFound:
    def test_get_technician_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_technician_not_found_returns_404
        """
        resp = api.get_technician(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_FOUND)

    def test_get_unit_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_unit_not_found_returns_404
        """
        resp = api.get_unit(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)

    def test_get_vendor_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_vendor_not_found_returns_404
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND)

    def test_get_rotation_shift_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_rotation_shift_not_found_returns_404
        """
        resp = api.get_rotation_shift(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ROTATION_SHIFT_NOT_FOUND)

    def test_get_call_ticket_not_found_returns_404(self, api, dispatcher_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_call_ticket_not_found_returns_404
        """
        resp = api.get_call_ticket(NON_EXISTENT_UUID, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CALL_TICKET_NOT_FOUND)

    def test_get_work_order_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_work_order_not_found_returns_404
        """
        resp = api.get_work_order(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND)

    def test_get_vendor_authorization_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_vendor_authorization_not_found_returns_404
        """
        resp = api.get_vendor_authorization(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_VENDOR_AUTHORIZATION_NOT_FOUND)

    def test_get_relocation_case_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_relocation_case_not_found_returns_404
        """
        resp = api.get_relocation_case(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RELOCATION_CASE_NOT_FOUND)

    def test_get_incident_record_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_incident_record_not_found_returns_404
        """
        resp = api.get_incident_record(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_RECORD_NOT_FOUND)

    def test_get_pay_period_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_pay_period_not_found_returns_404
        """
        resp = api.get_pay_period(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PAY_PERIOD_NOT_FOUND)

    def test_get_pay_statement_not_found_returns_404(self, api, property_admin_headers):
        """PRD §2.8: "Existence failures map to the resource-specific errors
        `ERR_TECHNICIAN_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_ROTATION_SHIFT_NOT_FOUND`,
        `ERR_CALL_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_VENDOR_AUTHORIZATION_NOT_FOUND`,
        `ERR_RELOCATION_CASE_NOT_FOUND`, `ERR_INCIDENT_RECORD_NOT_FOUND`,
        `ERR_PAY_PERIOD_NOT_FOUND`, and `ERR_PAY_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/get_pay_statement_not_found_returns_404
        """
        resp = api.get_pay_statement(NON_EXISTENT_UUID, property_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PAY_STATEMENT_NOT_FOUND)


def test_unit_number_duplicate_rejected(api, property_admin_headers):
    """PRD §3.1: "Units are registered with a property-wide unique
    `unit_number` — a duplicate is rejected with `ERR_UNIT_NUMBER_EXISTS` —
    plus a `building_code`."

    Design: Corner/validations/unit_number_duplicate_rejected
    """
    make_unit(unit_number="DUP-1", building_code="BD")
    resp = api.create_unit(
        create_unit_payload(unit_number="DUP-1", building_code="BE"),
        property_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NUMBER_EXISTS)


def test_technician_create_missing_auth_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a role the
    system does not declare, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/validations/technician_create_missing_auth_returns_401
    """
    resp = api.create_technician(
        create_technician_payload(
            full_name="No Header",
            capability="TECHNICIAN",
            base_hourly_rate_cents=5000,
            on_call_differential_bp=1000,
        ),
        headers=None,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_missing_auth_on_unknown_ticket_returns_401(api):
    """PRD §2.9: "When several validations could reject the same request, the
    system evaluates them in a single global order, and the earliest failing
    tier determines the error returned:" with "1. **Authentication context** —
    presence of the headers and a declared role
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)." ahead of "3. **Existence**
    — path identifiers left to right, then body foreign keys (the 404 family)."

    Design: Corner/validations/missing_auth_on_unknown_ticket_returns_401
    """
    resp = api.get_call_ticket(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_vendor_cannot_read_unit(api, property_admin_headers):
    """PRD §2.1: "A request whose role is not in the endpoint's allowed set is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4 narrows the unit
    read to PropertyAdmin, Dispatcher, OnCallTechnician, MaintenanceSupervisor.

    Design: Corner/rbac/vendor_cannot_read_unit
    """
    unit = make_unit(unit_number="R-8", building_code="BR")
    vendor = make_vendor(name="NoseyCo", trade="GENERAL",
                         per_incident_limit_cents=100000)
    resp = api.get_unit(unit["id"], make_vendor_headers(vendor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
