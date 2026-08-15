"""Customer/unit registry, response envelope, and baseline auth/existence checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_credit_invariants,
    assert_customer,
    assert_gear_unit,
    create_customer_payload,
    create_unit_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_customer,
    make_loaner,
    make_order,
    make_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerRegistry:
    def test_create_customer_applies_defaults(self, api, intake_coordinator_headers):
        """PRD §2.10: "A freshly registered customer starts with
        `outstanding_approved_cents` of 0 and `credit_hold` false."
        PRD §4: "Operations that create a new resource ... return `201 Created`
        with the created resource in `data`."
        PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."

        Design: Corner/entities/create_customer_success_returns_201_and_defaults
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="Default Co",
                                    credit_limit_cents=1_000_000),
            intake_coordinator_headers)
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert data["outstanding_approved_cents"] == 0
        assert data["credit_hold"] is False
        assert_credit_invariants(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])

    def test_create_customer_missing_legal_name_rejected(
            self, api, intake_coordinator_headers):
        """PRD §2.4: "Across all resources, a request body missing a required
        field or carrying a malformed value is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_customer_missing_required_field_returns_invalid_request
        """
        resp = api.create_customer({"credit_limit_cents": 1_000_000},
                                   intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_customer_not_found(self, api, intake_coordinator_headers):
        """PRD §2.5: "the server validates their existence strictly left to
        right (customer, then unit, then order, then the child resource) and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not correspond to an existing resource".

        Design: Corner/entities/get_customer_not_found_returns_404
        """
        resp = api.get_customer("11111111-2222-4333-8444-555555555555",
                                intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestUnitRegistry:
    def test_duplicate_unit_serial_rejected_across_customers(
            self, api, intake_coordinator_headers):
        """PRD §3.1: "Under a customer, the coordinator registers each
        serialized gear unit with its manufacturer `serial_number` (unique
        across the entire unit registry — a duplicate is rejected with
        `ERR_SERIAL_EXISTS`)".

        Design: Corner/entities/gear_unit_serial_number_uniqueness_enforced
        """
        c1 = make_customer(legal_name="Dup One")
        make_unit(c1["id"], serial_number="GBX-DUP", check_in=False)
        c2 = make_customer(legal_name="Dup Two")
        resp = api.create_unit(
            c2["id"],
            create_unit_payload(serial_number="GBX-DUP", model="HZ-900",
                                rated_torque_nm=20_000),
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_SERIAL_EXISTS.value)

    def test_odometer_forward_only(self, api, intake_coordinator_headers):
        """PRD §3.1: "the odometer is forward-only, so
        `cumulative_service_hours` becomes the greater of its current value
        and the reported `hours` — a reading below the current odometer
        simply leaves it unchanged rather than erroring."

        Design: Corner/entities/record_service_hours_is_forward_only
        """
        customer = make_customer(legal_name="Odo Co")
        unit = make_unit(customer["id"], serial_number="GBX-ODO", hours=500,
                         check_in=False)
        assert unit["cumulative_service_hours"] == 500

        # Lower reading leaves the odometer unchanged (still a 200 success).
        data = validate_success(
            api.record_service_hours(unit["id"], 300, intake_coordinator_headers))
        assert data["cumulative_service_hours"] == 500

        # Higher reading advances it.
        data = validate_success(
            api.record_service_hours(unit["id"], 900, intake_coordinator_headers))
        assert data["cumulative_service_hours"] == 900
        assert_gear_unit(data)

    def test_list_unit_orders_paginated_envelope(self, api, reman_engineer_headers):
        """PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/entities/list_orders_for_unit_returns_array_envelope
        """
        customer = make_customer(legal_name="List Co")
        unit = make_unit(customer["id"], serial_number="GBX-LST")
        make_order(unit["id"], intake_hours=0, quoted_estimate_cents=100_000)

        resp = api.list_unit_orders(unit["id"], reman_engineer_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list) and len(data) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10  # PRD §2.3: "it defaults to 10 when omitted"
        assert meta["offset"] == 0
        assert resp.json()["response_type"] == "array"


class TestAuthAndExistence:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing or unrecognized `X-User-Role`
        header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "1. **Authentication** — all endpoints: the `X-User-Role`
        header must be present and recognized, else `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        no_role_headers = {"X-User-ID": "test-anon-1",
                           "Content-Type": "application/json"}
        resp = api.get_customer("11111111-2222-4333-8444-555555555555",
                                no_role_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_not_found_beats_state(self, api, reman_engineer_headers):
        """PRD §2.11: "3. **Existence** — all endpoints: path resources are
        validated left to right (customer, unit, order, child), else
        `ERR_NOT_FOUND`." and "4. **State legality** — all action endpoints:
        the target resource must be in a state from which the requested
        transition exists, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/validations/existence_checked_before_state
        """
        resp = api.start_teardown(NON_EXISTENT_UUID, reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestEnvelopeShape:
    def test_child_collections_reachable(self, api, intake_coordinator_headers):
        """PRD §4 lists a GET collection endpoint for every parent-child
        relation, and "all reads return `200 OK`".
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/fk_reverse_reachability_all_children
        """
        customer = make_customer(legal_name="FK Co")
        unit = make_unit(customer["id"], serial_number="GBX-FK")
        order = make_order(unit["id"], intake_hours=0,
                           quoted_estimate_cents=100_000)
        loaner = make_loaner(serial_number="LN-FK")

        collections = [
            (api.list_customer_units(customer["id"], intake_coordinator_headers), 1),
            (api.list_unit_orders(unit["id"], intake_coordinator_headers), 1),
            (api.list_findings(order["id"], intake_coordinator_headers), 0),
            (api.list_decisions(order["id"], intake_coordinator_headers), 0),
            (api.list_assembly_records(order["id"], intake_coordinator_headers), 0),
            (api.list_run_in_tests(order["id"], intake_coordinator_headers), 0),
            (api.list_shipments(order["id"], intake_coordinator_headers), 0),
            (api.list_warranty_claims(order["id"], intake_coordinator_headers), 0),
            (api.list_loaner_unit_assignments(loaner["id"], intake_coordinator_headers), 0),
        ]
        for resp, expected_len in collections:
            data, meta = validate_paginated(resp)
            assert resp.json()["response_type"] == "array"
            assert isinstance(data, list)
            assert len(data) == expected_len, (
                f"expected {expected_len} items, got {len(data)}: {resp.text}")

    def test_error_envelope_shape(self, api, intake_coordinator_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `message`
        provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        resp = api.get_unit("11111111-2222-4333-8444-555555555555",
                            intake_coordinator_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
        body = resp.json()
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str)
        assert len(error_data["message"].strip()) > 0
