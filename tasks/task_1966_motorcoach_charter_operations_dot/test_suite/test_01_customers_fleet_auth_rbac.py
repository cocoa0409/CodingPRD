"""Resource registration, defaults, retrieval, authentication, and RBAC basics."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_customer_account, assert_vehicle, assert_driver,
    create_customer_payload, create_vehicle_payload, create_driver_payload,
    create_certificate_payload,
    set_clock, make_customer, make_vehicle, make_driver,
    setup_pending_deposit_order,
)


class TestCustomerRegistration:
    def test_create_customer_with_required_fields_returns_201(self, api, quote_agent_headers):
        """PRD §3.1: "New accounts open with `credit_status` set to `ACTIVE`" and
        "`tax_exempt` may be declared at registration and defaults to false".
        PRD §3.1: "`total_completed_trips` counts the customer's orders that have
        reached `COMPLETED`, starting at zero. `lifetime_revenue_cents` accumulates
        the money the relationship has produced ... starting from zero."

        Design: Corner/entities/create_customer_with_required_fields_returns_201
        """
        set_clock()
        res = api.create_customer(
            create_customer_payload(company_name="New Corp"), quote_agent_headers)
        customer = validate_success(res, 201)
        assert_customer_account(customer)
        assert customer["company_name"] == "New Corp"
        assert customer["credit_status"] == "ACTIVE"
        assert customer["tax_exempt"] is False
        assert customer["total_completed_trips"] == 0
        assert customer["lifetime_revenue_cents"] == 0

    def test_get_nonexistent_customer_returns_404(self, api, quote_agent_headers):
        """PRD §2.8: "3. Existence: every identifier in the request path resolves
        to an existing resource, validated left to right, else `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_nonexistent_customer_returns_404
        """
        set_clock()
        res = api.get_customer(NON_EXISTENT_UUID, quote_agent_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_customer_missing_company_name_returns_invalid_request(
            self, api, quote_agent_headers):
        """PRD §3.1: a customer account is registered "with the organization's
        `company_name`, a `contact_email`, a `contact_phone`, and a
        `billing_address` for invoicing". PRD §2.8: "6. Request-body type and
        format validation — required fields present, enum values valid, numeric
        ranges valid — else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/error_invalid_request_missing_required_field
        """
        set_clock()
        payload = {"contact_email": "bad@x.com", "contact_phone": "555-0000",
                   "billing_address": "Nowhere"}
        res = api.create_customer(payload, quote_agent_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_new_customer_safety_audit_score_is_100(self, api, quote_agent_headers):
        """PRD §3.9: "A customer with no completed orders scores 100.0."

        Design: Corner/entities/customer_safety_audit_score_computed_field
        """
        set_clock()
        customer = make_customer(company_name="Fresh Co")
        fetched = validate_success(api.get_customer(customer["id"], quote_agent_headers))
        assert fetched["safety_audit_score"] == 100.0

    def test_list_customers_pagination(self, api, quote_agent_headers):
        """PRD §2.3: "The `meta` object of list responses carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_customers_pagination
        """
        set_clock()
        for i in range(3):
            make_customer(company_name=f"Page {chr(65 + i)}")
        data, meta = validate_paginated(api.list_customers(quote_agent_headers))
        assert meta["total_count"] == 3
        assert len(data) == 3
        assert meta["has_more"] is False


class TestFleetRegistrationDefaults:
    def test_create_vehicle_with_defaults_applied(self, api, fleet_manager_headers):
        """PRD §3.2: "Two equipment facts ride along: `ada_accessible`, recording
        a lift-equipped coach and defaulting to false, and `vehicle_class` —
        `STANDARD`, `PREMIUM`, or `EXECUTIVE` — defaulting to `STANDARD`". PRD
        §3.2: "The coach's `odometer_miles` begins at zero".

        Design: Corner/entities/create_vehicle_with_defaults_applied
        """
        set_clock()
        res = api.create_vehicle(create_vehicle_payload(), fleet_manager_headers)
        vehicle = validate_success(res, 201)
        assert_vehicle(vehicle)
        assert vehicle["ada_accessible"] is False
        assert vehicle["vehicle_class"] == "STANDARD"
        assert vehicle["status"] == "AVAILABLE"
        assert vehicle["odometer_miles"] == 0

    def test_get_nonexistent_vehicle_returns_404(self, api, fleet_manager_headers):
        """PRD §2.8: "3. Existence: every identifier in the request path resolves
        to an existing resource, validated left to right, else `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_nonexistent_vehicle_returns_404
        """
        set_clock()
        res = api.get_vehicle(NON_EXISTENT_UUID, fleet_manager_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_create_driver_defaults_hos_cycle(self, api, fleet_manager_headers):
        """PRD §3.2: "an optional `hos_cycle_type` — `CYCLE_70_8`, the default,
        permitting seventy on-duty hours in eight days, or `CYCLE_60_7`,
        permitting sixty in seven". PRD §3.2: "A driver's `safety_score` opens at
        100.0 and degrades per §3.9."

        Design: Corner/entities/create_driver_defaults_hos_cycle
        """
        set_clock()
        res = api.create_driver(create_driver_payload(), fleet_manager_headers)
        driver = validate_success(res, 201)
        assert_driver(driver)
        assert driver["hos_cycle_type"] == "CYCLE_70_8"
        assert driver["status"] == "AVAILABLE"
        assert driver["current_driving_hours_today"] == 0.0
        assert driver["safety_score"] == 100.0


class TestAuthenticationAndRbac:
    def test_missing_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role name
        the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        res = api.list_customers(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_customer_cannot_create_vehicles(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4:
        "| POST | /api/v1/vehicles | Register a new vehicle in the fleet |
        FleetManager, PlatformAdmin |".

        Design: Corner/rbac/customer_cannot_create_vehicles
        """
        set_clock()
        customer = make_customer(company_name="RBAC Test")
        res = api.create_vehicle(create_vehicle_payload(),
                                 make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_quote_agent_cannot_suspend_drivers(self, api, quote_agent_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4:
        "| POST | /api/v1/drivers/{id}/suspend | Suspend a driver |
        SafetyOfficer |".

        Design: Corner/rbac/quote_agent_cannot_suspend_drivers
        """
        set_clock()
        driver = make_driver()
        res = api.suspend_driver(driver["id"], {"reason": "Unauthorized attempt"},
                                 quote_agent_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_dispatch_manager_cannot_issue_certificates(self, api,
                                                        dispatch_manager_headers):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4:
        "| POST | /api/v1/insurance-certificates/{id}/issue | Issue an insurance
        certificate | ComplianceOfficer |".

        Design: Corner/rbac/dispatch_manager_cannot_issue_certificates
        """
        ctx = setup_pending_deposit_order()
        cert = validate_success(api.request_certificate(
            create_certificate_payload(ctx["order"]["id"]),
            make_customer_headers(ctx["customer"]["id"])), 201)
        res = api.issue_certificate(cert["id"], dispatch_manager_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
