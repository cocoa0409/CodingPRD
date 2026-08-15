"""RBAC: authentication, role exclusivity, customer ownership scoping — and
reverse foreign-key reachability across the API surface."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_ro_in_quote_in_progress,
    api_client,
    approve_quote,
    create_asset,
    create_customer,
    create_part,
    create_part_payload,
    create_quote_for_ro,
    create_repair_order,
    get_quote,
    get_repair_order,
    get_success_data,
    issue_quote,
    issue_quote_for,
    make_customer_headers,
    make_technician_headers,
    setup_authorized_shop,
    setup_issued_quote_shop,
    setup_quote_in_progress_shop,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestAuthentication:
    def test_request_without_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the declared roles. A request whose `X-User-Role` header is missing or does not name a declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_unauthenticated_without_role_header
        """
        missing = api_client.list_customers({})
        validate_error(missing, ApiErrorId.ERR_UNAUTHENTICATED)

        undeclared = api_client.list_customers(
            {"X-User-ID": "intruder-1", "X-User-Role": "SuperUser"})
        validate_error(undeclared, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleExclusivity:
    def test_technician_cannot_certify(self, api):
        """PRD §4: "| POST | `/repair-orders/{id}/certifications` | Issue SRV certification and tag (segregation of duties enforced) | Certifier |"
        PRD §2.1: "Any attempt to perform an operation outside the caller's role, or by a customer against another customer's resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/technician_cannot_certify_returns_forbidden
        """
        customer = create_customer(name="Gruver", account_number="GR-400",
                                   credit_limit_cents=99999999, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="SRV-4001",
                             equipment_class="SAFETY_RELIEF_VALVE",
                             manufacturer="Consolidated", model="1900",
                             set_pressure_psig=100)
        ro = create_repair_order(customer["id"], asset["id"],
                                 failure_mode="SPRING_DRIFT", estimated_bay_hours=5)

        # The role gate fires regardless of the order's state (RECEIVED here).
        resp = api_client.create_certification(
            ro["id"], {"set_pressure_psig": 100, "seat_leakage_class": "CLASS_V"},
            make_technician_headers("tech-001"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_inspector_cannot_create_part(self, api):
        """PRD §4: "| POST | `/parts` | Create a catalog part | ServiceManager |"
        PRD §2.1: "Any attempt to perform an operation outside the caller's role, or by a customer against another customer's resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/inspector_cannot_create_part
        """
        resp = api_client.create_part(
            create_part_payload(part_number="ORB-1", description="Orifice",
                                unit_price_cents=100),
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        _data, meta = validate_paginated(api_client.list_parts(SM))
        assert meta["total_count"] == 0, "no part may be persisted"


class TestCustomerOwnership:
    def test_customer_cannot_approve_others_quote(self, api):
        """PRD §3.6: "The owning customer may approve, request a revision, or decline."
        PRD §2.6: "3. **Authorization** — the role must be permitted for the endpoint, and a `Customer` caller may act only on resources whose `customer_id` equals its `X-User-ID` (`ERR_FORBIDDEN`, HTTP 403)."
        PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`."

        Design: Corner/rbac/customer_cannot_approve_others_quote
        """
        shop = setup_issued_quote_shop()
        other = create_customer(name="Fort Stockton", account_number="FS-391",
                                credit_limit_cents=99999999, warranty_terms_days=365)

        resp = api_client.approve_quote(
            shop["quote"]["id"], make_customer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_quote(shop["quote"]["id"])["status"] == "ISSUED", "unchanged"

    def test_customer_cancel_scope_by_state(self, api):
        """PRD §3.9: "An `IntakeCoordinator` may cancel from any non-terminal state; a `Customer` may cancel only its own orders and only while the order is `RECEIVED`, `IN_INSPECTION`, or `QUOTE_IN_PROGRESS`."
        PRD §2.1: "Any attempt to perform an operation outside the caller's role, or by a customer against another customer's resource, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.6: "5. **State validity** — the target entity must be in a valid from-state for the requested transition, terminal states are locked, and the quote-creation version check must match (`ERR_INVALID_STATE`, HTTP 409; the version mismatch carries `ERR_STALE_VERSION`, HTTP 412, on quote creation)."

        Design: Corner/rbac/customer_cancel_scope_by_state
        """
        # Order 1 reaches QUOTE_IN_PROGRESS only; order 2 is fully AUTHORIZED.
        shop = setup_authorized_shop()
        cust = make_customer_headers(shop["customer"]["id"])
        early_ro = add_ro_in_quote_in_progress(shop)

        own_early = get_success_data(api_client.cancel_repair_order(early_ro["id"], cust))
        assert own_early["status"] == "CANCELLED"

        # A customer canceling its own AUTHORIZED order violates §3.9's
        # state-scoped cancel capability. The PRD names no error for this
        # rejection: §2.1's role-scope sentence supports ERR_FORBIDDEN, while
        # §2.6 tier 5's from-state gate supports ERR_INVALID_STATE — both
        # readings are faithful, so accept either.
        resp = api_client.cancel_repair_order(shop["ro"]["id"], cust)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_FORBIDDEN, ApiErrorId.ERR_INVALID_STATE])
        assert get_repair_order(shop["ro"]["id"])["status"] == "AUTHORIZED"


class TestReverseReachability:
    def test_fk_reverse_lookups_return_arrays(self, api):
        """PRD §2.3: "The repair order list filters by `customer_id`, `asset_id`, `status`, `capacity_window_id`, or `warranty_parent_ro_id`. The quote list filters by `repair_order_id`, `capacity_window_id`, `status`, or `supersedes_quote_id`. The parts list filters by `status` or `superseded_by_id`. The pool unit list filters by `customer_id`, `asset_id`, `pool_status`, or `reserved_for_ro_id`."
        PRD §4: "| GET | `/repair-orders/{id}/inspection-reports` | List inspection reports for an order (zero or one) | All roles |"
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/fk_reverse_reachability_gets
        """
        # Part supersession chain: P1 OBSOLETE with superseded_by_id P2.
        p1 = create_part(part_number="STEM-1", description="Stem v1", unit_price_cents=1200)
        p2 = create_part(part_number="STEM-2", description="Stem v2", unit_price_cents=1300)
        get_success_data(api_client.mark_part_obsolete(
            p1["id"], {"superseded_by_id": p2["id"]}, SM))

        # Full chain: order with a finalized report and a DRAFT quote.
        shop = setup_quote_in_progress_shop()
        quote = create_quote_for_ro(shop["ro"]["id"], shop["window"]["id"], labor_hours=1)
        ro_id = shop["ro"]["id"]

        quotes, qmeta = validate_paginated(api_client.list_quotes(
            SM, params={"repair_order_id": ro_id}))
        assert qmeta["total_count"] == 1 and quotes[0]["id"] == quote["id"]

        reports_res = api_client.list_inspection_reports(ro_id, SM)
        assert reports_res.json()["response_type"] == "array"
        reports = get_success_data(reports_res)
        assert len(reports) == 1 and reports[0]["id"] == shop["report"]["id"]

        for sub_list in ("test_runs", "certifications"):
            res = getattr(api_client, f"list_{sub_list}")(ro_id, SM)
            assert res.json()["response_type"] == "array"
            assert get_success_data(res) == []

        units, umeta = validate_paginated(api_client.list_pool_units(
            SM, params={"reserved_for_ro_id": ro_id}))
        assert units == [] and umeta["total_count"] == 0

        parts, pmeta = validate_paginated(api_client.list_parts(
            SM, params={"superseded_by_id": p2["id"]}))
        assert pmeta["total_count"] == 1 and parts[0]["id"] == p1["id"]

        orders, ometa = validate_paginated(api_client.list_repair_orders(
            SM, params={"asset_id": shop["asset"]["id"]}))
        assert ometa["total_count"] == 1 and orders[0]["id"] == ro_id
