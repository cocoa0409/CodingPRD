"""Customer registration, order intake validation, auth, and envelope rules.

Covers PRD §2.1 (roles/auth), §2.2 (envelope), §2.3 (pagination), §2.4 (common
fields), §2.8 (existence), and §3.1 (customer/lane/order intake rules).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer, assert_fab_order,
    create_customer_payload, create_fab_order_payload, create_lane_payload,
    create_customer, create_lane, create_order,
    make_customer_headers, TEST_USERS,
    DEFAULT_SHIP_DATE,
)

FAB_ADMIN = TEST_USERS["fab_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
CAM = TEST_USERS["cam_operator_headers"]
ENG = TEST_USERS["process_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


class TestCustomerCreate:
    def test_create_customer_applies_tax_exempt_default(self, api):
        """PRD §3.1: "an optional `tax_exempt` flag that defaults to false and is
        carried purely for invoice display — all pricing in the system is pre-tax."
        PRD §2.4: "All resources carry a server-minted `id` formatted as a UUID
        with no type prefix, and a `created_at` timestamp recorded as ISO 8601 UTC
        with three fractional digits."

        Design: Corner/entities/create_customer_applies_defaults
        """
        payload = create_customer_payload(
            company_name="Defaults Co", contact_email="defaults@co.example",
            credit_limit_cents=5000,
        )
        payload.pop("tax_exempt")  # omitted entirely: server applies the default
        resp = api.create_customer(payload, FAB_ADMIN)
        customer = validate_success(resp, expected_status=201)
        assert_customer(customer)
        assert customer["tax_exempt"] is False, (
            f"tax_exempt must default to false when omitted, got {customer['tax_exempt']!r}"
        )

    def test_create_customer_ignores_client_supplied_system_fields(self, api):
        """PRD §2.4: "All resources carry a server-minted `id` formatted as a UUID
        with no type prefix" — client-supplied identity fields are not echoed back.

        Design: Corner/entities/system_fields_input_ignored
        """
        payload = create_customer_payload(
            company_name="Ignore Co", contact_email="ignore@co.example",
            credit_limit_cents=5000,
        )
        payload["id"] = "11111111-1111-1111-1111-111111111111"
        payload["version"] = 99
        payload["created_at"] = "1999-01-01T00:00:00Z"
        resp = api.create_customer(payload, FAB_ADMIN)
        customer = validate_success(resp, expected_status=201)
        assert customer["id"] != "11111111-1111-1111-1111-111111111111", (
            "server must mint its own id, not echo the client-supplied one"
        )
        assert customer["version"] != 99, "client-supplied version must be ignored"
        assert customer["created_at"] != "1999-01-01T00:00:00Z", (
            "client-supplied created_at must be ignored"
        )


class TestOrderIntakeValidation:
    def test_create_order_missing_quantity_boards_rejected(self, api):
        """PRD §3.1: "a `quantity_boards` of at least one" is part of the intake
        payload. PRD §2.9: "Field-level shape validation — required fields
        present, enum members in range, numeric bounds satisfied — is evaluated
        last and reported as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_order_missing_quantity_returns_validation
        """
        cust = create_customer("Req Co", "req@co.example", 5000)
        payload = create_fab_order_payload(cust["id"])
        payload.pop("quantity_boards")
        resp = api.create_fab_order(payload, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_create_order_layer_count_outside_enum_rejected(self, api):
        """PRD §3.1: "a `layer_count` that must be one of 2, 4, 6, or 8".

        Design: Corner/entities/create_order_invalid_layer_count_returns_validation
        """
        cust = create_customer("Enum Co", "enum@co.example", 5000)
        payload = create_fab_order_payload(cust["id"], layer_count=3)
        resp = api.create_fab_order(payload, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_ship_date_in_past_rejected(self, api):
        """PRD §3.1: "a `requested_ship_date` that must fall strictly after the
        logical clock — a date in the past or at the present instant is rejected
        with `ERR_SHIP_DATE_IN_PAST`."

        Design: Corner/validations/ship_date_in_past_rejected
        """
        cust = create_customer("Past Co", "past@co.example", 5000)
        payload = create_fab_order_payload(
            cust["id"], requested_ship_date="2026-07-01T00:00:00Z",
        )
        resp = api.create_fab_order(payload, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIP_DATE_IN_PAST)

    def test_inactive_lane_order_create_rejected(self, api):
        """PRD §3.1: "An inactive lane rejects both new order references and
        releases with `ERR_LANE_INACTIVE`."

        Design: Corner/validations/inactive_lane_rejected
        """
        lane = create_lane(lane_code="QT5", turn_days=5,
                           capacity_boards_per_day=800, premium_multiplier=1.25,
                           active=False)
        cust = create_customer("Inact Co", "inact@co.example", 5000)
        payload = create_fab_order_payload(
            cust["id"], service_lane="QUICK_TURN", quantity_boards=10,
        )
        payload["quick_turn_lane_id"] = lane["id"]
        resp = api.create_fab_order(payload, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_LANE_INACTIVE)

    def test_finish_lane_incompatible_rejected(self, api):
        """PRD §3.1: "`IMMERSION_SILVER` is chemically incompatible with the
        fastest lanes, so pairing that finish with a lane whose `turn_days` is
        three days or fewer is rejected with `ERR_FINISH_LANE_INCOMPATIBLE`."

        Design: Corner/validations/finish_lane_incompatible_rejected
        """
        lane = create_lane(lane_code="QT3", turn_days=3)
        cust = create_customer("Fin Co", "fin@co.example", 5000)
        payload = create_fab_order_payload(
            cust["id"], service_lane="QUICK_TURN",
            surface_finish="IMMERSION_SILVER", quantity_boards=10,
        )
        payload["quick_turn_lane_id"] = lane["id"]
        resp = api.create_fab_order(payload, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_FINISH_LANE_INCOMPATIBLE)


class TestReadAndListing:
    def test_get_missing_fab_order_returns_not_found(self, api):
        """PRD §2.8: "the server validates existence strictly left-to-right and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve".

        Design: Corner/entities/get_missing_order_returns_not_found
        """
        resp = api.get_fab_order(NON_EXISTENT_UUID, FAB_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_fab_orders_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned"
        and "every list response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope." PRD §2.2: "The
        `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`."

        Design: Corner/entities/list_orders_pagination_envelope
        """
        cust = create_customer("Page Co", "page@co.example", 5000)
        create_order(cust["id"], quantity_boards=10)
        create_order(cust["id"], quantity_boards=20)
        resp = api.list_fab_orders(SALES, params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return exactly 1 row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error. The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_fab_order(NON_EXISTENT_UUID, FAB_ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(error_data["message"], str) and error_data["message"], (
            "error message must be a non-empty human-readable string"
        )
        assert body["meta"]["api_request_id"].startswith("req_")


class TestAuthAndOwnership:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose declared role
        is not one of these seven, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_customers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_on_customer_create(self, api):
        """PRD §2.1: "A request whose role is well-formed but not on the
        endpoint's authorized-role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /pcb/customers is FabAdmin-only.

        Design: Corner/validations/forbidden_role_on_customer_create
        """
        payload = create_customer_payload(
            company_name="Nope Co", contact_email="nope@co.example",
            credit_limit_cents=1,
        )
        resp = api.create_customer(payload, QI)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_customer_reading_other_customers_order_rejected(self, api):
        """PRD §2.1: "ownership checks on any order-scoped resource compare the
        resource's `customer_id` ... against `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_OWNER` (HTTP 403)."

        Design: Corner/validations/customer_not_owner_read_rejected
        """
        cust_a = create_customer("Owner A", "a@co.example", 5000)
        cust_b = create_customer("Owner B", "b@co.example", 5000)
        order = create_order(cust_a["id"], quantity_boards=10)
        resp = api.get_fab_order(order["id"], make_customer_headers(cust_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)

    def test_duplicate_customer_email_rejected(self, api):
        """PRD §3.1: "a `contact_email` that must be unique across all customers
        (a duplicate is rejected with `ERR_DUPLICATE_EMAIL`)".

        Design: Corner/validations/duplicate_email_rejected
        """
        create_customer("First", "dupe@co.example", 1)
        payload = create_customer_payload(
            company_name="Second", contact_email="dupe@co.example",
            credit_limit_cents=2,
        )
        resp = api.create_customer(payload, FAB_ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestRbacMatrix:
    def test_customer_creates_own_order(self, api):
        """PRD §3.1: "Order intake itself is performed by a `Customer` (for its
        own account only) or a `SalesEngineer` on the customer's behalf." and
        "A newly created order opens with `fab_status` of `QUOTED`".

        Design: Corner/rbac/customer_creates_own_order_positive
        """
        cust = create_customer("Self Co", "self@co.example", 5000)
        resp = api.create_fab_order(
            create_fab_order_payload(cust["id"], quantity_boards=10),
            make_customer_headers(cust["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert_fab_order(order)
        assert order["fab_status"] == "QUOTED"
        assert order["customer_id"] == cust["id"]

    def test_all_roles_can_read_order(self, api):
        """PRD §4: GET /pcb/fab-orders/{id} lists all seven roles; PRD §2.1:
        "A `Customer` may therefore read only its own customer record, its own
        orders, and its own orders' stackups, arrays, drill programs, coupons,
        defects, and invoices".

        Design: Corner/rbac/rbac_shared_read_positive
        """
        cust = create_customer("Share Co", "share@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        readers = [
            make_customer_headers(cust["id"]),
            SALES, CAM, ENG, QI, PLANNER, FAB_ADMIN,
        ]
        for headers in readers:
            resp = api.get_fab_order(order["id"], headers)
            data = validate_success(resp, expected_status=200)
            assert data["fab_status"] == "QUOTED", (
                f"read as {headers} must return the order, got {data}"
            )
