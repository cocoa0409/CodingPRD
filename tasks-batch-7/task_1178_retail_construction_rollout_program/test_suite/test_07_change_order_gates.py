"""Change-order tiering, approval gates (tier authority, segregation of
duties, opening lock, headroom boundary, OCC ordering), proposal gates, and
cancellation/rescission rules."""
from test_helpers import (
    ApiErrorId,
    approve_change_order_now,
    complete_vendor_window,
    create_vendor_mobilization,
    make_finance_controller_headers,
    make_site_superintendent_headers,
    open_market_bidding,
    propose_change_order,
    read_change_order,
    read_commitment_for_site,
    read_site,
    recalculate_commitment,
    set_clock,
    setup_awarded_site,
    setup_site_in_build,
    setup_site_mobilized,
    validate_error,
    validate_success,
)


class TestChangeOrderTiering:
    def test_change_order_tier_exact_boundaries(self, api):
        """PRD §3.6: "Each proposal is tiered by size relative to the site's
        contract: the absolute amount, multiplied by 10000 and divided by
        `base_contract_cents`, compared exactly with no rounding — a guarantee
        made safe because proposal only happens after an award has set a
        positive base contract. A ratio of at most 200 basis points classifies
        `STANDARD`, at most 500 classifies `ELEVATED`, and anything larger
        classifies `CRITICAL`; the computed `tier` is stored on the change
        order."

        Design: Corner/calculations/c_change_order_tier_exact_boundaries
        """
        ctx = setup_awarded_site(bid_amount_cents=10_000_000,
                                 budget_allocation_cents=20_000_000)
        site_id = ctx["site"]["id"]
        # On a 10000000-cent base, 200bp == 200000 and 500bp == 500000.
        co1 = propose_change_order(site_id, 200_000, description="tier boundary 1")
        co2 = propose_change_order(site_id, 200_001, description="tier boundary 2")
        co3 = propose_change_order(site_id, 500_000, description="tier boundary 3")
        co4 = propose_change_order(site_id, 500_001, description="tier boundary 4")
        assert co1["tier"] == "STANDARD", "exactly 200bp is STANDARD (inclusive)"
        assert co2["tier"] == "ELEVATED", "one cent above 200bp is ELEVATED"
        assert co3["tier"] == "ELEVATED", "exactly 500bp is ELEVATED (inclusive)"
        assert co4["tier"] == "CRITICAL", "one cent above 500bp is CRITICAL"


class TestApprovalAuthority:
    def test_finance_cannot_approve_critical_tier(self, api):
        """PRD §3.6: "tier authority requires a `FinanceController` for
        `STANDARD` and `ELEVATED` orders but a `ProgramDirector` for
        `CRITICAL` ones (`ERR_CO_TIER_ROLE_REQUIRED`)"

        Design: Corner/rbac/c_finance_cannot_approve_critical_tier
        """
        ctx = setup_awarded_site()
        site_id = ctx["site"]["id"]
        # 600000 * 10000 / 9000000 = 666.7bp > 500 -> CRITICAL.
        co = propose_change_order(site_id, 600_000,
                                  description="Foundation remediation")
        assert co["tier"] == "CRITICAL"

        resp = approve_change_order_now(co["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_error(resp, ApiErrorId.ERR_CO_TIER_ROLE_REQUIRED)
        assert read_change_order(co["id"])["status"] == "PROPOSED"

        # The failed attempt mutated nothing, so the same version remains
        # valid for the director's approval.
        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        assert validate_success(resp)["status"] == "APPROVED"

    def test_segregation_of_duties_same_user_approve(self, api):
        """PRD §3.6: "the approver's `X-User-ID` must differ from
        `proposed_by_user_id`, enforcing segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/rbac/c_segregation_of_duties_same_user_approve
        """
        ctx = setup_awarded_site()
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 100_000, description="Added millwork",
                                  proposer_user_id="sup-1")

        # A FinanceController carrying the proposer's operator id.
        version = read_site(site_id)["version"]
        resp = api.approve_change_order(
            co["id"], {"expected_site_version": version},
            headers=make_finance_controller_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert read_change_order(co["id"])["status"] == "PROPOSED"

    def test_state_precedes_occ_on_terminal_change_order(self, api):
        """PRD §2.10: "The server evaluates checks in a fixed order, and the
        first failing check determines which error the client receives"
        PRD §2.10: "5. State guards — the target resource is in a from-state
        that allows the operation, terminal states reject all further
        transitions, and domain state gates hold (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`,
        `ERR_MARKET_NOT_BIDDING`, `ERR_MARKET_NOT_AWARDED`,
        `ERR_BID_PACKAGE_NOT_OPEN`, `ERR_CONTRACTOR_NOT_PREQUALIFIED`,
        `ERR_SITE_NOT_IN_BUILD`, `ERR_TURNOVER_ALREADY_REQUESTED`,
        `ERR_ACTIVE_SITES_REMAIN`, `ERR_TURNOVER_NOT_ACCEPTED`)."
        PRD §2.10: "6. Optimistic concurrency — `expected_site_version`
        matches the site's current `version` (`ERR_STALE_VERSION`)."

        Design: Corner/validations/c_state_precedes_occ_on_terminal_co
        """
        ctx = setup_awarded_site()
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 100_000, description="Added millwork")
        validate_success(api.reject_change_order(
            co["id"], {"rejection_reason": "out of scope"},
            headers=make_finance_controller_headers("fin-1")))
        assert read_change_order(co["id"])["status"] == "REJECTED"

        # REJECTED is terminal for a change order: the state guard at step 5
        # fires before the OCC check at step 6, whatever version is supplied.
        resp = approve_change_order_now(co["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestProposalAndCancellation:
    def test_change_order_create_unauthorized_role_returns_403(
            self, api, design_manager_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted
        for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: change-order proposal is authorized for SiteSuperintendent.

        Design: Corner/validations/c_change_order_create_unauthorized_role_returns_403
        """
        ctx = setup_awarded_site()
        resp = api.create_change_order(
            {"site_id": ctx["site"]["id"], "description": "Design-side tweak",
             "amount_cents": 100_000, "cost_category": "SCOPE"},
            headers=design_manager_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_co_propose_before_market_award_rejected(self, api):
        """PRD §3.6: "Proposal requires the site to be in its building phase
        with an awarded market behind it, failing with
        `ERR_MARKET_NOT_AWARDED` while the market is not `AWARDED`."

        Design: Corner/errors/c_co_propose_before_market_award_rejected
        """
        ctx = setup_site_mobilized()
        open_market_bidding(ctx["market"]["id"])  # market BIDDING, no award
        resp = api.create_change_order(
            {"site_id": ctx["site"]["id"], "description": "Early scope add",
             "amount_cents": 100_000, "cost_category": "SCOPE"},
            headers=make_site_superintendent_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_AWARDED)

    def test_co_cancel_by_non_proposer_forbidden(self, api):
        """PRD §3.6: "Cancellation by the proposing superintendent — only the
        recorded proposer may cancel (`ERR_FORBIDDEN_IDENTITY`) — performs the
        same bucket compensation and lands at `CANCELLED`."

        Design: Corner/state_machines/c_co_cancel_by_non_proposer_forbidden
        """
        ctx = setup_awarded_site()
        co = propose_change_order(ctx["site"]["id"], 100_000,
                                  description="Added millwork",
                                  proposer_user_id="sup-1")

        resp = api.cancel_change_order(
            co["id"], headers=make_site_superintendent_headers("sup-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_IDENTITY)
        assert read_change_order(co["id"])["status"] == "PROPOSED"

    def test_co_rescind_from_proposed_invalid_state(self, api):
        """PRD §3.6: "Rescission by a `FinanceController`, accompanied by a
        `rescind_reason`, moves an `APPROVED` order to `RESCINDED` as the
        exact compensation of approval"
        PRD §2.10: "State guards — the target resource is in a from-state that
        allows the operation, terminal states reject all further transitions,
        and domain state gates hold (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`,
        `ERR_MARKET_NOT_BIDDING`, `ERR_MARKET_NOT_AWARDED`,
        `ERR_BID_PACKAGE_NOT_OPEN`, `ERR_CONTRACTOR_NOT_PREQUALIFIED`,
        `ERR_SITE_NOT_IN_BUILD`, `ERR_TURNOVER_ALREADY_REQUESTED`,
        `ERR_ACTIVE_SITES_REMAIN`, `ERR_TURNOVER_NOT_ACCEPTED`)."

        Design: Corner/state_machines/c_co_rescind_from_proposed_invalid_state
        """
        ctx = setup_awarded_site()
        co = propose_change_order(ctx["site"]["id"], 100_000,
                                  description="Added millwork")

        resp = api.rescind_change_order(
            co["id"], {"rescind_reason": "premature"},
            headers=make_finance_controller_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_change_order(co["id"])["status"] == "PROPOSED"


class TestHeadroomBoundary:
    def test_headroom_exact_boundary_approve_succeeds_plus_one_fails(self, api):
        """PRD §3.6: "and finally the fiscal check — a credit always passes,
        but a positive amount must fit the site's headroom, with
        `committed_cents` plus `amount_cents` not exceeding
        `budget_allocation_cents` (`ERR_BUDGET_HEADROOM_EXCEEDED`)."

        Design: Difficulty/boundary_precision_check/headroom_exact_boundary_approve_succeeds_plus_one_fails
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        co1 = propose_change_order(site_id, 1_000_000,
                                   description="Exactly-at-headroom add")
        co2 = propose_change_order(site_id, 1, description="One cent over")

        # 9000000 + 1000000 == 10000000: "not exceeding" includes equality.
        resp = approve_change_order_now(co1["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        assert validate_success(resp)["status"] == "APPROVED"
        assert read_site(site_id)["committed_cents"] == 10_000_000

        # One cent over the remaining headroom of zero is rejected. The 1-cent
        # order tiers STANDARD (1*10000/9000000 <= 200bp), and §3.6 tier
        # authority requires a FinanceController for STANDARD orders, so the
        # approver here is the controller — not the director — to reach the
        # step-11 fiscal check.
        resp = approve_change_order_now(co2["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_error(resp, ApiErrorId.ERR_BUDGET_HEADROOM_EXCEEDED)
        assert read_change_order(co2["id"])["status"] == "PROPOSED"

    def test_credit_change_order_always_passes_headroom(self, api):
        """PRD §3.6: "and finally the fiscal check — a credit always passes,
        but a positive amount must fit the site's headroom, with
        `committed_cents` plus `amount_cents` not exceeding
        `budget_allocation_cents` (`ERR_BUDGET_HEADROOM_EXCEEDED`)."
        PRD §3.6: "a signed `amount_cents` — negative amounts are credits"

        Design: Difficulty/boundary_precision_check/headroom_exact_boundary_approve_succeeds_plus_one_fails
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        # A 5000000-cent credit (5555bp -> CRITICAL tier) still approves.
        co = propose_change_order(site_id, -5_000_000,
                                  description="Scope deletion credit")
        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        assert validate_success(resp)["status"] == "APPROVED"
        assert read_site(site_id)["committed_cents"] == 4_000_000


class TestStateVersusFiscalPriority:
    def test_state_vs_fiscal_co_approve_on_removed_site(self, api,
                                                        program_director_headers):
        """PRD §3.1: "Removal cascades: every `PROPOSED` change order on the
        site moves to `REJECTED`, a `REQUESTED` turnover moves to
        `SUPERSEDED`, the site drops out of all program budget aggregates, and
        the site's `version` increments."
        PRD §2.10: "The server evaluates checks in a fixed order, and the
        first failing check determines which error the client receives"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_co_approve_on_removed_site
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 50_000_000,
                                  description="Full re-pipe")

        resp = api.remove_site(site_id, headers=program_director_headers)
        validate_success(resp)
        assert read_change_order(co["id"])["status"] == "REJECTED"

        # The auto-rejected order is terminal; the state guard (step 5) beats
        # the fiscal headroom check (step 11) that the oversized amount would
        # also trip.
        resp = approve_change_order_now(co["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        error = validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert error["error_id"] != "ERR_BUDGET_HEADROOM_EXCEEDED"

    def test_headroom_violation_reported_on_live_site(self, api):
        """PRD §3.6: "a positive amount must fit the site's headroom, with
        `committed_cents` plus `amount_cents` not exceeding
        `budget_allocation_cents` (`ERR_BUDGET_HEADROOM_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_co_approve_on_removed_site
        """
        ctx = setup_awarded_site(bid_amount_cents=9_000_000,
                                 budget_allocation_cents=10_000_000)
        site_id = ctx["site"]["id"]
        co = propose_change_order(site_id, 50_000_000,
                                  description="Full re-pipe")

        # With no state violation in play, the fiscal check fires alone.
        resp = approve_change_order_now(co["id"], site_id,
                                        role="ProgramDirector",
                                        approver_user_id="dir-1")
        validate_error(resp, ApiErrorId.ERR_BUDGET_HEADROOM_EXCEEDED)
        assert read_change_order(co["id"])["status"] == "PROPOSED"


class TestOpeningLock:
    def test_opening_lock_blocks_schedule_co_allows_scope(self, api):
        """PRD §3.6: "a `SCHEDULE`-category order may not be approved while
        the site's opening commitment sits in `AT_RISK` or `BREACHED` — the
        opening lock (`ERR_OPENING_LOCK_ENGAGED`)"

        Design: Corner/validations/c_opening_lock_blocks_schedule_co_allows_scope
        """
        ctx = setup_site_in_build()
        site_id = ctx["site"]["id"]
        complete_vendor_window(site_id, "FIXTURE", "2026-05-11", "2026-05-12",
                               "2026-05-11", vendor_name="Fixtures R Us")
        complete_vendor_window(site_id, "IT", "2026-05-12", "2026-05-13",
                               "2026-05-12", vendor_name="NetCabling Co")
        create_vendor_mobilization(site_id, vendor_type="SIGNAGE",
                                   vendor_name="SignPros",
                                   planned_start_on="2026-08-25",
                                   planned_end_on="2026-09-10")

        # Forecast: 08-25 + 16 planned days + 10 buffer = 2026-09-20 against a
        # 2026-09-01 commitment -> slip 19 -> AT_RISK.
        set_clock("2026-08-20T00:00:00Z")
        oc = read_commitment_for_site(site_id)
        assert recalculate_commitment(oc["id"])["protection_posture"] == "AT_RISK"

        co_scope = propose_change_order(site_id, 100_000, cost_category="SCOPE",
                                        description="Scope add")
        co_sched = propose_change_order(site_id, 50_000, cost_category="SCHEDULE",
                                        description="Resequence signage")

        resp = approve_change_order_now(co_scope["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        assert validate_success(resp)["status"] == "APPROVED"

        resp = approve_change_order_now(co_sched["id"], site_id,
                                        role="FinanceController",
                                        approver_user_id="fin-1")
        validate_error(resp, ApiErrorId.ERR_OPENING_LOCK_ENGAGED)
        assert read_change_order(co_sched["id"])["status"] == "PROPOSED"
