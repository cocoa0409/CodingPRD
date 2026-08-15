"""Authentication, role-based access, and list endpoints
(PRD §2.1, §2.2, §2.3, §2.11, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_assembly_order,
    create_customer,
    create_reel,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        A read with neither header -> ERR_UNAUTHENTICATED (401).

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        cust = create_customer(name="AuthCo")
        res = api.get_customer(cust["id"], headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleDenials:
    def test_counter_sales_cannot_create_reel_forbidden(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `ShopManager` owns the catalog and the customer book: only a manager registers customers and updates their flags, receives and retires hose reels, registers couplings and posts stock receipts, decommissions equipment assets, and sets the logical clock."

        POST /api/reels as CounterSales -> ERR_FORBIDDEN (403).

        Design: Corner/rbac/counter_sales_cannot_create_reel_forbidden
        """
        res = api.create_reel({
            "hose_sku": "PARK-387-8Z", "hose_diameter_in": 0.5,
            "working_pressure_psi": 3000, "price_per_meter_cents": 800,
            "initial_length_mm": 50000,
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_shop_technician_cannot_confirm_forbidden(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`CounterSales` runs the counter itself: drafting, confirming, completing, and cancelling assembly orders, registering equipment assets, booking emergency dispatches, and scheduling inspections. The `ShopTechnician` owns the build bench — completing builds, recording pressure tests, sending failed assemblies to rework, and attaching certification tags."

        Confirming as ShopTechnician -> ERR_FORBIDDEN (403); the order stays DRAFT.

        Design: Corner/rbac/shop_technician_cannot_confirm_forbidden
        """
        cust = create_customer(name="RoleCo")
        reel = create_reel(hose_sku="PARK-387-8RB", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(cust["id"], reel["id"], cut_length_mm=1000,
                                      required_working_pressure_psi=2000,
                                      crimp_diameter_spec_mm=25.0,
                                      estimated_labor_minutes=10)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["shop_technician_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "DRAFT"

    def test_customer_cannot_read_other_customer_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record, and ownership checks on any resource that references a customer compare the resource's `customer_id` field against `X-User-ID`. A portal customer reads only their own account record, their own equipment assets and those assets' inspections, and their own assembly orders with their order lines; reaching for a resource owned by another customer is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Customer C1 reading C2's record -> ERR_FORBIDDEN (403); reading their own
        record succeeds.

        Design: Corner/rbac/customer_cannot_read_other_customer_forbidden
        """
        c1 = create_customer(name="OwnCo1")
        c2 = create_customer(name="OwnCo2")

        res = api.get_customer(c2["id"], make_customer_headers(c1["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        own = api.get_customer(c1["id"], make_customer_headers(c1["id"]))
        own_data = validate_success(own, 200)
        assert own_data["id"] == c1["id"]

    def test_field_technician_cannot_create_dispatch_forbidden(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `FieldTechnician` works the road: advancing, completing, and aborting dispatches (the abort capability is shared with `ShopManager`) and performing inspections."

        Booking a dispatch is not among the FieldTechnician's admitted operations;
        POST /api/service-dispatches as FieldTechnician -> ERR_FORBIDDEN (403).

        Design: Corner/rbac/field_technician_cannot_create_dispatch_forbidden
        """
        cust = create_customer(name="FieldCo")
        res = api.create_service_dispatch({
            "customer_id": cust["id"], "van_id": "VAN-4",
            "window_start": "2026-08-03T09:00:00Z",
            "window_end": "2026-08-03T10:00:00Z",
        }, TEST_USERS["field_technician_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestNotFound:
    def test_customer_get_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        GET /api/customers/{unknown uuid} -> ERR_CUSTOMER_NOT_FOUND (404).

        Design: Corner/errors/customer_get_unknown_id_not_found
        """
        res = api.get_customer(NON_EXISTENT_UUID,
                               TEST_USERS["shop_manager_headers"])
        validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
                       expected_status=404)

    def test_reel_retire_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        POST /api/reels/{unknown uuid}/retire -> ERR_REEL_NOT_FOUND (404).

        Design: Corner/errors/reel_retire_unknown_id_not_found
        """
        res = api.retire_reel(NON_EXISTENT_UUID,
                              TEST_USERS["shop_manager_headers"])
        validate_error(res, ApiErrorId.ERR_REEL_NOT_FOUND, expected_status=404)


class TestOrderListings:
    def _setup_two_orders(self):
        cust = create_customer(name="PageCo")
        reel = create_reel(hose_sku="PARK-387-8PG", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        o1 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=1000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        o2 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=1500,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        return cust, reel, o1, o2

    def test_orders_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        limit=1 over 2 orders returns exactly 1 row plus total_count 2,
        has_more true, limit 1, offset 0, with the request meta fields present.

        Design: Corner/endpoints/orders_list_pagination_envelope
        """
        cust, reel, o1, o2 = self._setup_two_orders()
        res = api.list_assembly_orders(
            TEST_USERS["counter_sales_headers"],
            params={"customer_id": cust["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_orders_filtered_by_customer(self, api):
        """PRD §3.3: "The order list can be filtered by `customer_id`, `reel_id`, `equipment_asset_id`, or `status`, and the order's lines can be listed on their own."

        customer_id filter returns only that customer's order, not another's.

        Design: Corner/endpoints/orders_filtered_by_customer
        """
        c1 = create_customer(name="FiltCo1")
        c2 = create_customer(name="FiltCo2")
        reel = create_reel(hose_sku="PARK-387-8F", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        o1 = create_assembly_order(c1["id"], reel["id"], cut_length_mm=1000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        o2 = create_assembly_order(c2["id"], reel["id"], cut_length_mm=1000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)

        res = api.list_assembly_orders(
            TEST_USERS["counter_sales_headers"],
            params={"customer_id": c1["id"]})
        data, _meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["id"] == o1["id"]
