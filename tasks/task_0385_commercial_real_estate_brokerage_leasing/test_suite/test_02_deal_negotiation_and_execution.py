"""Deal negotiation rounds, acceptance/execution cascades, and the conserved-dollar
commission invariant.

Covers Difficulty rules non_linear_state_machine (deal loop), transitive_cascade
(execute depth-3), and compensating_invariant (dollars), plus Corner endpoint and
state-machine instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    make_listing_broker_headers, make_tenant_broker_headers,
    setup_prospect_deal, submit_first_proposal, setup_executed_deal,
    setup_two_firms, create_property, create_active_listing, create_requirement,
    get_commission_splits_for_deal, split_by_side, assert_commission_conserves_total,
)


class TestNegotiationCycle:
    def test_countered_loop_increments_round_count_without_leaving_state(self, api):
        """PRD §3.5: "Each subsequent proposal is a counter from the opposite side and
        drives the deal from `LOI_DRAFT` to `LOI_COUNTERED`, and thereafter loops
        `LOI_COUNTERED` to `LOI_COUNTERED` for every further round."
        PRD §3.5: "Each counter flips the latest `PENDING` proposal to `COUNTERED`, creates a new
        `PENDING` proposal, increments `round_count`, and increments the deal's
        `version` by one."

        Design: Difficulty/non_linear_state_machine/deal_negotiation_cycle_countered_loop
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=55,
                                  term_months=60, max_rent_psf_yr=80)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        tb_h = make_tenant_broker_headers(ctx["tb"]["id"])
        deal_id = ctx["deal"]["id"]

        # First proposal: PROSPECT -> LOI_DRAFT
        submit_first_proposal(ctx, "LISTING", 55, 60)
        deal = get_success_data(api.get_deal(deal_id, lb_h))
        assert deal["stage"] == "LOI_DRAFT"
        # Counter 1 from TENANT: LOI_DRAFT -> LOI_COUNTERED
        v = deal["version"]
        validate_success(api.create_proposal(deal_id, {
            "from_side": "TENANT", "base_rent_psf_yr": 48, "term_months": 60,
            "expected_deal_version": v}, tb_h), expected_status=201)
        deal = get_success_data(api.get_deal(deal_id, lb_h))
        assert deal["stage"] == "LOI_COUNTERED"
        # Counter 2 from LISTING: LOI_COUNTERED -> LOI_COUNTERED (self-loop)
        v = deal["version"]
        p3 = validate_success(api.create_proposal(deal_id, {
            "from_side": "LISTING", "base_rent_psf_yr": 52, "term_months": 60,
            "expected_deal_version": v}, lb_h), expected_status=201)
        deal = get_success_data(api.get_deal(deal_id, lb_h))
        assert deal["stage"] == "LOI_COUNTERED", "stays LOI_COUNTERED on the self-loop"
        assert deal["round_count"] == 3, f"round_count should be 3 after 3 rounds, got {deal['round_count']}"
        assert p3["outcome"] == "PENDING"

    def test_first_proposal_advances_prospect_to_loi_draft(self, api):
        """PRD §3.5: "The first proposal creates a new round with `outcome` `PENDING`,
        increments `round_count`, bubbles the listing from `ACTIVE` to `UNDER_NEGOTIATION`
        and the requirement to `NEGOTIATING`, and increments the deal's `version` by one."

        Design: Difficulty/non_linear_state_machine/deal_negotiation_cycle_countered_loop
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=55,
                                  term_months=60, max_rent_psf_yr=80)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        submit_first_proposal(ctx, "LISTING", 55, 60)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal["stage"] == "LOI_DRAFT"
        assert deal["round_count"] == 1
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], lb_h))
        assert listing["status"] == "UNDER_NEGOTIATION"


class TestExecuteCascade:
    def test_execute_cascades_listing_sibling_and_space(self, api):
        """PRD §3.6: "Execution is the climactic cascade: it writes the `CommissionSplit`
        ledger rows for the `LISTING` and `PROCURING` sides as §3.8 describes, transitions
        the space from `UNDER_LOI` to the terminal `LEASED`, transitions the listing from
        `UNDER_NEGOTIATION` to the terminal `EXECUTED`, drives every sibling deal on that
        listing whose `stage` is neither `EXECUTED` nor `DEAD` to `DEAD`, transitions the
        requirement from `NEGOTIATING` to the terminal `PLACED`, cancels every other tour
        of that requirement still in `REQUESTED` or `CONFIRMED`, and appends a `Comp`
        market record."

        Design: Difficulty/transitive_cascade/execute_deep_cascade_depth_three
        """
        # One listing, two open deals A (will execute) and B (LOI_DRAFT sibling).
        lb, tb = setup_two_firms()
        prop = create_property(lb["id"], "FIDI-SF", "OFFICE", total_sf=60000)
        space, listing = create_active_listing(
            lb["id"], prop["id"], "1200", rentable_sf=5000, asking_rent_psf_yr=40,
            term_months=120, annual_escalation_pct=0)
        lb_h = make_listing_broker_headers(lb["id"])
        tb_h = make_tenant_broker_headers(tb["id"])
        req_a = create_requirement(tb["id"], "FIDI-SF", "OFFICE", 1000, 9000, 60, "Tenant A")
        req_b = create_requirement(tb["id"], "FIDI-SF", "OFFICE", 1000, 9000, 60, "Tenant B")
        deal_a = get_success_data(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req_a["id"]}, lb_h))
        deal_b = get_success_data(api.create_deal(
            {"listing_id": listing["id"], "requirement_id": req_b["id"]}, lb_h))
        # Deal B: one proposal -> LOI_DRAFT (open sibling).
        validate_success(api.create_proposal(deal_b["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 40, "term_months": 120,
            "annual_escalation_pct": 0, "expected_deal_version": deal_b["version"]}, lb_h),
            expected_status=201)
        # Deal A: proposal -> accept -> lease-out -> execute.
        a = get_success_data(api.get_deal(deal_a["id"], lb_h))
        validate_success(api.create_proposal(deal_a["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 40, "term_months": 120,
            "annual_escalation_pct": 0, "expected_deal_version": a["version"]}, lb_h),
            expected_status=201)
        a = get_success_data(api.get_deal(deal_a["id"], lb_h))
        validate_success(api.accept_deal(deal_a["id"], {
            "from_side": "TENANT", "expected_deal_version": a["version"]}, tb_h))
        a = get_success_data(api.get_deal(deal_a["id"], lb_h))
        validate_success(api.lease_out_deal(deal_a["id"], {"expected_deal_version": a["version"]}, lb_h))
        a = get_success_data(api.get_deal(deal_a["id"], lb_h))
        validate_success(api.execute_deal(deal_a["id"], {"expected_deal_version": a["version"]}, lb_h))

        assert get_success_data(api.get_deal(deal_a["id"], lb_h))["stage"] == "EXECUTED"
        assert get_success_data(api.get_listing(listing["id"], lb_h))["status"] == "EXECUTED"
        assert get_success_data(api.get_deal(deal_b["id"], lb_h))["stage"] == "DEAD", (
            "sibling deal B cascades to DEAD")
        assert get_success_data(api.get_space(space["id"], lb_h))["status"] == "LEASED"

    def test_execute_cascades_requirement_to_placed(self, api):
        """PRD §3.6: "transitions the requirement from `NEGOTIATING` to the terminal
        `PLACED`".

        Design: Difficulty/transitive_cascade/execute_deep_cascade_depth_three
        """
        ctx = setup_executed_deal(
            co_broke=True, base_rent_psf_yr=40, term_months=120, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=40, market="FIDI-SF", asset_class="OFFICE")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        req = get_success_data(api.get_requirement(ctx["requirement"]["id"], lb_h))
        assert req["status"] == "PLACED", f"requirement cascades to PLACED, got {req['status']}"
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal["stage"] == "EXECUTED"

    def test_execute_creates_comp_with_market_and_effective_rent(self, api):
        """PRD §3.6: "The appended comp stamps the executed deal's `effective_rent_psf_yr` (copied from
        the accepted proposal's net effective rent), the `market` copied from the
        property at execution time, the executed `term_months`, the `space_id` of
        the leased suite, the `deal_id` of the executing deal, and the server clock
        value as `executed_at`."

        Design: Corner/cross_cutting_complexity_layers/cascade_execute_creates_comp_record
        """
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=50, term_months=24, annual_escalation_pct=0,
            free_rent_months=0, ti_allowance_psf=0, rentable_sf=4000, asking_rent_psf_yr=50,
            market="GASLAMP-SD", asset_class="RETAIL")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        comps = get_success_data(api.list_comps(lb_h, {"deal_id": ctx["deal"]["id"]}))
        assert len(comps) == 1, f"execute appends exactly one comp, got {len(comps)}"
        comp = comps[0]
        assert comp["effective_rent_psf_yr"] == 50.00, (
            f"comp effective_rent should be 50.00, got {comp['effective_rent_psf_yr']}")
        assert comp["market"] == "GASLAMP-SD"

    def test_cascades_visible_immediately_after_execute(self, api):
        """PRD §2.5: "every cascade triggered by a single request is applied atomically
        inside that request before the response is returned."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_response
        """
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=50, term_months=24, annual_escalation_pct=0,
            rentable_sf=4000, asking_rent_psf_yr=50, market="DT-LA", asset_class="OFFICE")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        space = get_success_data(api.get_space(ctx["space"]["id"], lb_h))
        assert space["status"] == "LEASED", "space is LEASED on the immediate read"
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], lb_h))
        assert listing["status"] == "EXECUTED"


class TestCommissionConservation:
    def test_split_amounts_conserve_total_commission(self, api):
        """PRD §3.8: "In every case the `LISTING` and `PROCURING` amounts together equal
        `total_commission` exactly; this conserved-quantity invariant is the
        integrity check on the split."

        Design: Difficulty/compensating_invariant/commission_split_conserves_total_commission
        """
        ctx = setup_executed_deal(
            co_broke=True, base_rent_psf_yr=26.25, term_months=24, annual_escalation_pct=0,
            rentable_sf=3000, asking_rent_psf_yr=26.25, co_broke_offered_pct=0.3333,
            default_commission_pct=0.06, max_rent_psf_yr=40, market="MIDTOWN-NY")
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal["total_commission"] == 9450.00
        splits = get_commission_splits_for_deal(ctx)
        assert_commission_conserves_total(splits, deal["total_commission"])
        assert split_by_side(splits, "PROCURING")["amount"] == 3149.69
        assert split_by_side(splits, "LISTING")["amount"] == 6300.31

    def test_split_conservation_holds_for_in_house_deal(self, api):
        """PRD §3.8: "a `PROCURING` row is still written with an `amount` of 0.00 for
        ledger completeness. In every case the `LISTING` and `PROCURING` amounts together
        equal `total_commission` exactly".

        Design: Difficulty/compensating_invariant/commission_split_conserves_total_commission
        """
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=40, term_months=120, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=40, default_commission_pct=0.06)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal["total_commission"] == 100000.00
        splits = get_commission_splits_for_deal(ctx)
        assert_commission_conserves_total(splits, deal["total_commission"])
        assert split_by_side(splits, "PROCURING")["amount"] == 0.00


class TestDealOcc:
    def test_proposal_with_correct_version_increments_deal_version(self, api):
        """PRD §2.4: "The deal's `version` in particular advances by exactly one on each
        deal-stage transition described in §3, and that monotonic counter is the basis for
        the concurrency control in §2.8."
        PRD §3.5: "The first proposal creates a new round with `outcome` `PENDING`,
        increments `round_count`, bubbles the listing from `ACTIVE` to `UNDER_NEGOTIATION`
        and the requirement to `NEGOTIATING`, and increments the deal's `version` by one."

        Design: Corner/endpoints/occ_happy_path_version_increments
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        deal0 = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal0["version"] == 1
        validate_success(api.create_proposal(ctx["deal"]["id"], {
            "from_side": "LISTING", "base_rent_psf_yr": 50, "term_months": 60,
            "expected_deal_version": 1}, lb_h), expected_status=201)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], lb_h))
        assert deal["version"] == 2, f"version should increment 1 -> 2, got {deal['version']}"
        assert deal["stage"] == "LOI_DRAFT"
        assert deal["round_count"] == 1

    def test_proposals_reverse_reachable_by_deal(self, api):
        """PRD §4 (GET /deals/{dealId}/proposals): "List proposals for a deal".
        PRD §3.5: "The negotiation history of a deal, readable as the list of its
        proposals, records this alternating ladder of rounds."

        Design: Corner/endpoints/proposals_reverse_reachable_by_deal
        """
        ctx = setup_prospect_deal(co_broke=True, rentable_sf=3000, asking_rent_psf_yr=50,
                                  term_months=60, max_rent_psf_yr=70)
        lb_h = make_listing_broker_headers(ctx["lb"]["id"])
        tb_h = make_tenant_broker_headers(ctx["tb"]["id"])
        submit_first_proposal(ctx, "LISTING", 50, 60)
        resp = api.list_deal_proposals(ctx["deal"]["id"], tb_h)
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected one proposal, got {len(data)}"
        assert data[0]["deal_id"] == ctx["deal"]["id"]
