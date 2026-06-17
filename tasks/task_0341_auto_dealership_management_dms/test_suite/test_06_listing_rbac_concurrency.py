"""Listing/pagination, reverse-reference links, RBAC, optimistic concurrency,
and immediate-consistency corner cases.

Corner queue (B) sections: endpoints, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, ApiErrorId, TEST_USERS, fixtures, make_customer_headers,
    build_user_headers,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]


# ===========================================================================
# endpoints (listing / reverse-reference)
# ===========================================================================
class TestListing:
    def test_vehicles_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and accepted values range from a minimum
        of 1 to a maximum of 100."
        PRD §2.3: "Each list response carries the pagination bookkeeping in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/vehicles_list_pagination_envelope
        """
        for _ in range(3):
            fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        data, meta = validate_paginated(api.list_vehicles(INV, params={"limit": 2, "offset": 0}))
        assert len(data) == 2, f"expected 2 items, got {len(data)}"
        assert meta["total_count"] == 3, meta
        assert meta["has_more"] is True, meta

    def test_vehicles_list_filter_by_status(self, api):
        """PRD §4 (routing summary): "List vehicles; filter by status or trade
        origin".
        PRD §3.1: "A new vehicle is born in status `AVAILABLE`."

        Design: Corner/endpoints/vehicles_list_filter_by_status
        """
        fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        fixtures.create_vehicle(condition="USED", model="CPE", model_year=2023,
                                msrp_cents=1800000, list_price_cents=1600000)
        data, meta = validate_paginated(api.list_vehicles(INV, params={"status": "AVAILABLE"}))
        assert len(data) >= 2
        assert all(v["status"] == "AVAILABLE" for v in data), [v["status"] for v in data]

    def test_floorplan_reverse_list_by_vehicle(self, api):
        """PRD §2.6: "child collections are reached through the parent's
        collection (for example, the floor-plan lines of a vehicle ...), and
        these listing endpoints are the reverse-reachability path from a parent
        back to the children that carry its foreign key."

        Design: Corner/endpoints/floorplan_reverse_list_by_vehicle
        """
        veh, line = fixtures.create_floored_vehicle(principal_cents=1800000)
        data, meta = validate_paginated(api.list_floor_plan_lines_for_vehicle(veh["id"], INV))
        ids = [fp["id"] for fp in data]
        assert line["id"] in ids
        match = next(fp for fp in data if fp["id"] == line["id"])
        assert match["status"] == "ACTIVE"


# ===========================================================================
# rbac
# ===========================================================================
class TestRbac:
    def test_inventoryclerk_cannot_create_deal(self, api):
        """PRD §2.1: "When a recognized role attempts an operation outside the set
        of operations granted to it, the request is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: deals are created by SalesManager: "POST | `/deals` | Create a
        deal in DRAFT | SalesManager".

        Design: Corner/rbac/rbac_inventoryclerk_cannot_create_deal
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        resp = api.create_deal(f.create_deal_payload(
            veh["id"], cust["id"], deal_type="FINANCE", sale_price_cents=2000000,
            tax_rate_bps=725), INV)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_salesmanager_cannot_fund_deal(self, api):
        """PRD §2.8: "Authorization is next: a role not permitted for the
        operation — or a `Customer` reaching for another customer's resource —
        yields `ERR_FORBIDDEN`."
        PRD §4: funding is FinanceManager-only: "POST | `/deals/{id}/fund` | Fund
        a contracted deal (LTV/PTI gated; cascades sale, payoff, title) |
        FinanceManager".

        Design: Corner/rbac/rbac_salesmanager_cannot_fund_deal
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_B")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        resp = api.fund_deal(deal["id"], {"expected_vehicle_version": veh["version"]}, SALES)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_unauthenticated_unrecognized_role_header(self, api):
        """PRD §2.1: "If `X-User-Role` is missing or names a role the system does
        not recognize, the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/rbac_unauthenticated_missing_role_header
        """
        bad_headers = build_user_headers("nobody-1", "Nobody")
        resp = api.create_vehicle(f.create_vehicle_payload(
            condition="NEW", make="ACME", model="SED", model_year=2026,
            msrp_cents=2200000, list_price_cents=2000000), bad_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_customer_cannot_book_for_other_customer(self, api):
        """PRD §2.1: "A `Customer` may book and cancel their own test drives (the
        booking's `customer_id` must equal `X-User-ID`), read their own customer
        record, and list their own test drives; an attempt by a `Customer` to act
        on another customer's resource is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_customer_cannot_book_for_other_customer
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        c_self = fixtures.create_customer(credit_tier="TIER_B", drivers_license_valid=True)
        c_other = fixtures.create_customer(credit_tier="TIER_B", drivers_license_valid=True)
        # Acting as c_self but booking for c_other.
        headers = make_customer_headers(c_self["id"])
        resp = api.book_test_drive(
            {"vehicle_id": veh["id"], "customer_id": c_other["id"],
             "start_at": "2026-06-22T10:00:00.000Z", "end_at": "2026-06-22T10:30:00.000Z"}, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# cross_cutting_complexity_layers (OCC)
# ===========================================================================
class TestOptimisticConcurrency:
    def test_floorplan_line_stale_vehicle_version(self, api):
        """PRD §2.9: "Placing a vehicle on a new floor-plan line supersedes the
        vehicle's prior ACTIVE line. The request must include
        `expected_vehicle_version`, carrying the client's last-observed `version`
        of the target Vehicle. If the vehicle's `version` has advanced since the
        client read it — for example, because another re-floor already created a
        line and bumped the vehicle's version — the create is rejected with
        `ERR_STALE_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/occ_floorplan_line_stale_vehicle_version
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        v_ver0 = veh["version"]
        fixtures.floor_vehicle(veh["id"], v_ver0, principal_cents=1800000)
        # Re-floor with the now-stale pre-floor version.
        resp = api.create_floor_plan_line(
            veh["id"],
            f.create_floor_plan_line_payload(v_ver0, principal_cents=1700000,
                                             floored_on="2026-05-15T00:00:00.000Z"), INV)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_floorplan_line_fresh_version_supersedes(self, api):
        """PRD §3.1: "Flooring a vehicle that already has an ACTIVE line is a
        re-floor: the prior ACTIVE line transitions `ACTIVE → SUPERSEDED` with no
        principal change, the newly created line becomes the vehicle's active
        line".

        Design: Corner/cross_cutting_complexity_layers/occ_floorplan_line_fresh_version_supersedes
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        line1 = fixtures.floor_vehicle(veh["id"], veh["version"], principal_cents=1800000)
        v_now = get_success_data(api.get_vehicle(veh["id"], INV))
        line2 = validate_success(api.create_floor_plan_line(
            veh["id"],
            f.create_floor_plan_line_payload(v_now["version"], principal_cents=1700000,
                                             floored_on="2026-05-15T00:00:00.000Z"), INV),
            expected_status=201)
        assert line2["status"] == "ACTIVE"
        data, meta = validate_paginated(api.list_floor_plan_lines_for_vehicle(veh["id"], INV))
        prior = next(fp for fp in data if fp["id"] == line1["id"])
        assert prior["status"] == "SUPERSEDED"

    def test_finance_contract_stale_deal_version(self, api):
        """PRD §2.9: "The request must include `expected_deal_version`, carrying
        the client's last-observed `version` of the target Deal. If another
        writer has advanced the deal's `version` since the client read it — for
        example, because a finance contract was already created, bumping the
        deal's version and superseding the prior contract — the create is
        rejected with `ERR_STALE_VERSION` and HTTP status 412".

        Design: Corner/cross_cutting_complexity_layers/occ_finance_contract_stale_deal_version
        """
        ctx = fixtures.create_approved_deal(deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        approved_version = ctx["deal"]["version"]
        fixtures.add_finance_contract(ctx["deal_id"], ctx["lender_program_id"], approved_version,
                                      markup_bps=100, term_months=72)
        # Second create with the now-stale approval-time version.
        resp = api.create_finance_contract(
            ctx["deal_id"],
            f.create_finance_contract_payload(ctx["lender_program_id"], approved_version,
                                              markup_bps=150, term_months=72), FIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# consistency_model
# ===========================================================================
class TestImmediateConsistency:
    def test_desk_recompute_visible_in_response(self, api):
        """PRD §3.3: "Each desk recomputes the full quote: the deal's taxes,
        amount financed, front and back gross, and the provisional estimated
        monthly payment (all of these calculations are detailed in §3.4)."
        PRD §3.4: "The ESTIMATE variant runs at every desk before any lender
        approval: it uses a provisional desking sell rate of 699 basis points
        (6.99%) and a provisional term of 72 months, and writes the result into
        the deal's `estimated_payment_cents`."

        Design: Corner/consistency_model/immediate_desk_recompute_visible_in_response
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        desked = validate_success(api.desk_deal(deal["id"], SALES))
        assert desked["status"] == "DESKING"
        assert desked["total_tax_cents"] == 145000, desked["total_tax_cents"]
        assert desked["amount_financed_cents"] == 2145000, desked["amount_financed_cents"]
        assert desked["estimated_payment_cents"] == 36560, desked["estimated_payment_cents"]
