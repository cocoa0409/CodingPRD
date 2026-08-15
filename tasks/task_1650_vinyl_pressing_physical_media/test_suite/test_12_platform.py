"""Platform behavior: not-found catalog, response envelopes, pagination,
list filters, auth context validation, and the RBAC matrix."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_customer,
    create_inventory_lot,
    create_order,
    create_release,
    make_customer_headers,
    quote_order,
    set_clock,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BILLING, CSR, OPERATOR, PLANNER, PM, QA
from test_helpers.test_users import make_qa_headers


class TestNotFoundCatalog:
    def test_resource_not_found_spot_sweep(self, api):
        """PRD §2.8: "Each resource type has its own not-found error:
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`,
        `ERR_PRESS_ORDER_NOT_FOUND`, `ERR_TOOLING_JOB_NOT_FOUND`,
        `ERR_TEST_PRESSING_NOT_FOUND`, `ERR_PRINT_JOB_NOT_FOUND`,
        `ERR_PRESS_LINE_NOT_FOUND`, `ERR_PLATING_BATH_NOT_FOUND`,
        `ERR_QC_REPORT_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`,
        `ERR_SHIPMENT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`."
        PRD §2.8: "When an endpoint path contains a resource identifier, the
        system validates that the identifier exists before doing any other work
        on it"

        Design: Corner/entities/resource_not_found_spot_sweep
        """
        bogus = NON_EXISTENT_UUID
        get_cases = [
            (api.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api.get_release, ApiErrorId.ERR_RELEASE_NOT_FOUND),
            (api.get_press_order, ApiErrorId.ERR_PRESS_ORDER_NOT_FOUND),
            (api.get_press_line, ApiErrorId.ERR_PRESS_LINE_NOT_FOUND),
            (api.get_plating_bath, ApiErrorId.ERR_PLATING_BATH_NOT_FOUND),
            (api.get_inventory_lot, ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND),
            (api.get_shipment, ApiErrorId.ERR_SHIPMENT_NOT_FOUND),
            (api.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        ]
        for call, error_id in get_cases:
            resp = call(bogus, CSR)
            validate_error(resp, error_id)

        action_cases = [
            (api.advance_tooling_job(bogus, {"event": "START_CUT"}, OPERATOR),
             ApiErrorId.ERR_TOOLING_JOB_NOT_FOUND),
            (api.ship_test_pressing(bogus, PLANNER),
             ApiErrorId.ERR_TEST_PRESSING_NOT_FOUND),
            (api.advance_print_job(bogus, {"event": "DISPATCH"}, CSR),
             ApiErrorId.ERR_PRINT_JOB_NOT_FOUND),
            (api.decide_qc_report(bogus, {"decision": "ACCEPT", "fault": "NONE"}, PM),
             ApiErrorId.ERR_QC_REPORT_NOT_FOUND),
        ]
        for resp, error_id in action_cases:
            validate_error(resp, error_id)


class TestEnvelopeShape:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and
        "`data`: { "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING", "message":
        "A human-readable explanation of the error." }"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/errors/error_envelope_shape
        """
        set_clock()
        ok = api.create_customer(
            {"name": "ENV", "contact_email": "env@x.com",
             "credit_limit_cents": 1000},
            CSR,
        )
        assert ok.status_code == 201
        body = ok.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        err = api.get_customer(NON_EXISTENT_UUID, CSR)
        assert err.status_code == 404
        ebody = err.json()
        assert ebody["response_type"] == "error"
        assert ebody["data"]["error_id"] == "ERR_CUSTOMER_NOT_FOUND"
        assert isinstance(ebody["data"]["message"], str)
        assert len(ebody["data"]["message"].strip()) > 0


class TestPaginationAndFilters:
    def test_pagination_defaults_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, must be at least 1, and may not exceed
        100. The `offset` parameter skips a number of items from the front of
        the result set and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_and_has_more
        """
        set_clock()
        for i in range(12):
            create_customer(name=f"PG-{i + 1:02d}", contact_email=f"p{i + 1}@x.com",
                            credit_limit_cents=1000)

        page1, meta1 = validate_paginated(api.list_customers(CSR))
        assert len(page1) == 10, "the default page size must be 10"
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_customers(CSR, params={"offset": 10})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_list_filters_by_fk_and_status(self, api):
        """PRD §3.2: "Orders may be listed with filters on `release_id` and
        `production_status`."
        PRD §3.8: "Lots may be listed with filters on `release_id` and `zone`."

        Design: Corner/endpoints/list_filters_by_fk_and_status
        """
        world = setup_world(with_line=False, with_bath=False)
        rel = world["release"]
        o1 = create_order(rel["id"], quantity_ordered=100)
        quote_order(o1)  # o1 is now QUOTED
        o2 = create_order(rel["id"], quantity_ordered=200)  # stays DRAFT

        drafts, _m = validate_paginated(
            api.list_press_orders(CSR, params={"production_status": "DRAFT"})
        )
        assert [o["id"] for o in drafts] == [o2["id"]], (
            "the DRAFT filter must exclude the QUOTED order"
        )
        by_release, _m = validate_paginated(
            api.list_press_orders(CSR, params={"release_id": rel["id"]})
        )
        assert {o["id"] for o in by_release} == {o1["id"], o2["id"]}

        create_inventory_lot(rel["id"], zone="A")
        lot_b = create_inventory_lot(rel["id"], zone="B")
        zone_b, _m = validate_paginated(
            api.list_inventory_lots(CSR, params={"zone": "B"})
        )
        assert [l["id"] for l in zone_b] == [lot_b["id"]]


class TestAuthContext:
    def test_missing_or_invalid_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or carrying a role
        the system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_or_invalid_role_header_rejected
        """
        payload = {"name": "Anon", "contact_email": "a@x.com",
                   "credit_limit_cents": 1000}

        # Undeclared role.
        r1 = api.create_customer(payload, build_user_headers("anon-1", "Anonymous"))
        validate_error(r1, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Missing X-User-Role header entirely.
        r2 = api.create_customer(
            payload, {"X-User-ID": "anon-1", "Content-Type": "application/json"}
        )
        validate_error(r2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # Missing both auth headers.
        r3 = api.create_customer(payload, {"Content-Type": "application/json"})
        validate_error(r3, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRbac:
    def test_rbac_customer_cannot_create_press_line_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted to use the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: POST /press-lines is authorized for ProductionPlanner.

        Design: Corner/rbac/rbac_customer_cannot_create_press_line_forbidden
        """
        set_clock()
        cust = create_customer(name="RB1", contact_email="rb1@x.com",
                               credit_limit_cents=1000000)
        resp = api.create_press_line(
            {"line_code": "LX", "tonnage_class": "STANDARD", "hours_per_day": 16,
             "daily_unit_capacity": 5000},
            make_customer_headers(cust["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        lines, _m = validate_paginated(api.list_press_lines(CSR))
        assert lines == [], "no line may be created by a Customer"

    def test_rbac_qa_role_cannot_decide_forbidden(self, api):
        """PRD §2.9: "2. Authorization — role not in the endpoint's permitted
        set, or an entity-backed `Customer` acting on a release it does not
        own, rejected with `ERR_UNAUTHORIZED_ROLE`, on every endpoint.
        3. Existence — path identifiers left to right, then body-referenced
        identifiers, rejected with the matching not-found error."
        PRD §2.9: "the ordering above is normative, not illustrative."

        Design: Corner/rbac/rbac_qa_role_cannot_decide_forbidden
        """
        # Authorization (priority 2) precedes existence (priority 3): even a
        # non-existent report id must draw 403, not 404, for a QaInspector.
        resp = api.decide_qc_report(
            NON_EXISTENT_UUID, {"decision": "ACCEPT", "fault": "NONE"},
            make_qa_headers("qa-9"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_planner_cannot_invoice_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted to use the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: POST /press-orders/{id}/invoices is authorized for
        BillingClerk.

        Design: Corner/rbac/rbac_planner_cannot_invoice_forbidden
        """
        resp = api.issue_invoice(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_customer_ownership_enforced_forbidden(self, api):
        """PRD §2.1: "A `Customer` may confirm an order, review a test
        pressing, or decide a print proof only when the parent order's release
        belongs to that customer; any attempt against another label's work is
        rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/rbac_customer_ownership_enforced_forbidden
        """
        set_clock()
        cust_a = create_customer(name="RB4 A", contact_email="a@x.com",
                                 credit_limit_cents=100000000)
        cust_b = create_customer(name="RB4 B", contact_email="b@x.com",
                                 credit_limit_cents=100000000)
        rel = create_release(cust_a["id"], catalog_number="RB4-001")
        order = create_order(rel["id"], quantity_ordered=1000)
        quoted = quote_order(order)

        resp = api.confirm_press_order(
            order["id"],
            {"expected_press_order_version": quoted["version"]},
            make_customer_headers(cust_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        current = validate_success(api.get_press_order(order["id"], CSR), 200)
        assert current["production_status"] == "QUOTED"

    def test_rbac_shared_reads_any_role(self, api):
        """PRD §2.1: "A tenth name, `Any`, is a pseudo-role used in this
        document to mark read endpoints that any authenticated role may call."

        Design: Corner/rbac/rbac_shared_reads_any_role
        """
        set_clock()
        cust = create_customer(name="RB5", contact_email="rb5@x.com",
                               credit_limit_cents=1000)
        got = validate_success(api.get_customer(cust["id"], QA), 200)
        assert got["id"] == cust["id"]
        listed, meta = validate_paginated(api.list_customers(QA))
        assert any(c["id"] == cust["id"] for c in listed)
        assert meta["total_count"] == 1
