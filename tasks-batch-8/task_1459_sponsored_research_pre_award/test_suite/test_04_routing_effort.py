"""Routing, PI effort capacity, and the institutional decision (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    create_proposal_payload,
    finalize_budget,
    get_proposal,
    get_version,
    make_analyst_headers,
    make_context,
    make_director_headers,
    make_locked_proposal,
    make_opportunity,
    make_pi,
    make_pi_headers,
    make_proposal,
    make_rate_agreement,
    make_routed_proposal,
    reset_clock,
    route_proposal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


class TestRevisionLoop:
    def _setup_routed(self, api):
        reset_clock()
        return make_routed_proposal()

    def test_return_for_revision_increments_count(self, api):
        """PRD §3.5: "the `OSPDirector` returns a `ROUTED` proposal for revision,
        supplying a `reason` ... The proposal lands in `RETURNED_FOR_REVISION`,
        its `revision_count` increments by one".

        Design: Difficulty/non_linear_state_machine/proposal_revision_loop
        """
        env = self._setup_routed(api)
        resp = api.return_for_revision(
            env["proposal"]["id"], {"reason": "budget justification incomplete"},
            DIRECTOR,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "RETURNED_FOR_REVISION"
        assert data["revision_count"] == 1

    def test_revision_cycle_completes_back_to_routed(self, api):
        """PRD §3.3: "A successful edit on a `RETURNED_FOR_REVISION` proposal
        resumes it to `DRAFT`; either way the proposal's `version` increments."
        PRD §3.3: "From `DRAFT` the proposal becomes `BUDGET_LOCKED`".
        PRD §3.5: "Routing sends a locked budget up for institutional sign-off."

        Design: Difficulty/non_linear_state_machine/proposal_revision_loop
        """
        env = self._setup_routed(api)
        prop_id = env["proposal"]["id"]
        pi_id = env["ctx"]["pi"]["id"]
        api.return_for_revision(prop_id, {"reason": "budget justification incomplete"},
                                DIRECTOR)
        # PATCH resumes drafting
        patched = validate_success(
            api.patch_proposal(prop_id, {"title": "Loop v2"}, make_pi_headers(pi_id)),
            200,
        )
        assert patched["status"] == "DRAFT"
        # Re-finalize and re-route completes the loop
        snap = finalize_budget(prop_id)
        assert snap["status"] == "CURRENT"
        routed = validate_success(
            api.route_proposal(prop_id, make_analyst_headers("analyst-1")), 200
        )
        assert routed["status"] == "ROUTED"
        final = get_proposal(prop_id)
        assert final["revision_count"] == 1


class TestEffortCapacity:
    def _setup_overlapping_portfolio(self, api):
        """PI with proposal A (effort 60, 2026 window) ROUTED and proposal B
        (effort 40, overlapping window) BUDGET_LOCKED."""
        reset_clock()
        ctx = make_context(sponsor_deadline_at="2027-09-05T17:00:00Z")
        # The default rate window starts 2026-01-01, so it covers proposal A's
        # project start.
        opp_id, pi_id = ctx["opp"]["id"], ctx["pi"]["id"]
        a = make_proposal(opp_id, pi_id, title="A", pi_effort_pct=60.00,
                          project_start_on="2026-01-01",
                          project_end_on="2026-12-31")
        add_budget_line(a["id"], fiscal_year=2026, amount_cents=1_000_000)
        finalize_budget(a["id"])
        route_proposal(a["id"])
        b = make_proposal(opp_id, pi_id, title="B", pi_effort_pct=40.00,
                          project_start_on="2026-06-01",
                          project_end_on="2027-05-31")
        add_budget_line(b["id"], amount_cents=1_000_000)
        finalize_budget(b["id"])
        return ctx, a, b

    def test_exactly_full_capacity_passes(self, api):
        """PRD §3.5: "The candidate's own `pi_effort_pct` plus the sum of the
        contributors' `pi_effort_pct` must not exceed 100.00, with a total of
        exactly 100.00 passing".

        Design: Difficulty/resource_temporal_overlap/pi_effort_aggregate_capacity
        """
        _ctx, a, b = self._setup_overlapping_portfolio(api)
        assert get_proposal(a["id"])["status"] == "ROUTED"
        routed = validate_success(
            api.route_proposal(b["id"], make_analyst_headers("analyst-1")), 200
        )
        # 60 + 40 == 100.00 passes exactly
        assert routed["status"] == "ROUTED"

    def test_overflow_and_adjacency_and_portfolio_load(self, api):
        """PRD §3.5: "two windows overlap when the candidate's start falls before
        the other's end and the other's start falls before the candidate's end —
        merely adjacent windows, one beginning exactly where the other ends, do
        not overlap." and "a breach is `ERR_PI_EFFORT_EXCEEDED` (HTTP 422)".
        PRD §3.1: "`committed_effort_pct` reports the portfolio load: the sum of
        `pi_effort_pct` across that investigator's proposals in the
        effort-contributing states `ROUTED`, `INSTITUTIONALLY_APPROVED`,
        `SUBMITTED`, `JIT_REQUESTED`, `NEGOTIATING`, `AWARDED`, and
        `SETUP_COMPLETE`, taken regardless of whether their project windows
        overlap."

        Design: Difficulty/resource_temporal_overlap/pi_effort_aggregate_capacity
        """
        ctx, a, b = self._setup_overlapping_portfolio(api)
        route_proposal(b["id"])
        opp_id, pi_id = ctx["opp"]["id"], ctx["pi"]["id"]
        # Candidate C overlapping both: 60 + 40 + 0.01 > 100 -> refused
        c = make_proposal(opp_id, pi_id, title="C", pi_effort_pct=0.01,
                          project_start_on="2026-07-01",
                          project_end_on="2027-06-30")
        add_budget_line(c["id"], amount_cents=1_000)
        finalize_budget(c["id"])
        resp = api.route_proposal(c["id"], make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_PI_EFFORT_EXCEEDED.value)
        # Candidate E starting exactly where A ends: A excluded (adjacency);
        # contributors = B alone -> 40 + 60 == 100.00 passes
        e = make_proposal(opp_id, pi_id, title="E", pi_effort_pct=60.00,
                          project_start_on="2026-12-31",
                          project_end_on="2027-06-01")
        add_budget_line(e["id"], amount_cents=1_000_000)
        finalize_budget(e["id"])
        routed_e = validate_success(
            api.route_proposal(e["id"], make_analyst_headers("analyst-1")), 200
        )
        assert routed_e["status"] == "ROUTED"
        # Portfolio load sums contributor-state proposals regardless of window:
        # A 60 + B 40 + E 60 = 160 (C never left BUDGET_LOCKED)
        pi = validate_success(
            api.get_principal_investigator(pi_id, DIRECTOR), 200
        )
        assert pi["committed_effort_pct"] == 160.0


class TestRoutePriority:
    def _setup_dual_violation(self, api):
        """Proposal B violates effort capacity (80+30=110) AND cost-share floor."""
        reset_clock()
        opp_a = make_opportunity(sponsor_code="NSF", title="OA")
        opp_b = make_opportunity(sponsor_code="NIH", title="OB",
                                 requires_cost_share=True,
                                 min_cost_share_pct_of_request=25.00)
        pi = make_pi(full_name="P Ten", department_code="ENG")
        make_rate_agreement()
        a = make_proposal(opp_a["id"], pi["id"], title="A", pi_effort_pct=80.00,
                          project_start_on="2026-09-01",
                          project_end_on="2027-08-31")
        add_budget_line(a["id"], amount_cents=1_000_000)
        finalize_budget(a["id"])
        route_proposal(a["id"])
        b = make_proposal(opp_b["id"], pi["id"], title="B", pi_effort_pct=30.00,
                          project_start_on="2027-01-01",
                          project_end_on="2027-12-31")
        add_budget_line(b["id"], amount_cents=10_000_000)
        finalize_budget(b["id"])
        return b

    def test_effort_error_beats_cost_share_error(self, api):
        """PRD §2.8: "10. **Structural constraints.** Activity-code membership,
        per-PI proposal caps, duplicate active reviews, FINAL rate-window
        overlap, PI effort capacity, a non-empty budget, an applicable rate,
        resolved reviews, a current pinned snapshot, a FINAL rate at handoff,
        subrecipient documents, high-risk acknowledgement, verified
        subrecipients, and UEI uniqueness — each with its own error code in §5.
        11. **Fiscal checks last.** The sponsor request cap
        (`ERR_REQUEST_EXCEEDS_CAP`, 422) and cost-share adequacy
        (`ERR_COST_SHARE_INADEQUATE`, 422) are evaluated only after every earlier
        category has passed".

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_route
        """
        b = self._setup_dual_violation(api)
        # Both hold: effort 80 + 30 = 110 > 100; cost-share 0 < required 3850000
        resp = api.route_proposal(b["id"], make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_PI_EFFORT_EXCEEDED.value)

    def test_fiscal_error_fires_when_constraint_passes(self, api):
        """PRD §3.5: "The second guard fires when the opportunity requires cost
        share: the proposal must currently be adequate per §3.4, else
        `ERR_COST_SHARE_INADEQUATE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/constraint_vs_fiscal_on_route
        """
        reset_clock()
        opp_a = make_opportunity(sponsor_code="NSF", title="OA")
        opp_b = make_opportunity(sponsor_code="NIH", title="OB",
                                 requires_cost_share=True,
                                 min_cost_share_pct_of_request=25.00)
        pi = make_pi(full_name="P Ten", department_code="ENG")
        make_rate_agreement()
        a = make_proposal(opp_a["id"], pi["id"], title="A", pi_effort_pct=60.00,
                          project_start_on="2026-09-01",
                          project_end_on="2027-08-31")
        add_budget_line(a["id"], amount_cents=1_000_000)
        finalize_budget(a["id"])
        route_proposal(a["id"])
        # B's effort (30) keeps the total at 90 <= 100: constraint passes, only
        # the fiscal cost-share guard can fire.
        b = make_proposal(opp_b["id"], pi["id"], title="B", pi_effort_pct=30.00,
                          project_start_on="2027-01-01",
                          project_end_on="2027-12-31")
        add_budget_line(b["id"], amount_cents=10_000_000)
        finalize_budget(b["id"])
        resp = api.route_proposal(b["id"], make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_COST_SHARE_INADEQUATE.value)


class TestInstitutionalSegregation:
    def test_router_cannot_self_approve(self, api):
        """PRD §3.5: "the approver must not be the analyst who routed it — an
        `X-User-ID` equal to `routed_by_user_id` is refused with
        `ERR_SELF_APPROVAL` (HTTP 403)".

        Design: Corner/rbac/institutional_self_approval_blocked
        """
        reset_clock()
        env = make_routed_proposal(router_user_id="director-1")
        resp = api.approve_institutional(
            env["proposal"]["id"], make_director_headers("director-1")
        )
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL.value)

    def test_distinct_director_approves(self, api):
        """PRD §3.5: "From `ROUTED`, approval moves the proposal to
        `INSTITUTIONALLY_APPROVED`" and "Approval **pins the budget**:
        `pinned_budget_snapshot_id` is set to the proposal's
        `current_snapshot_id`".

        Design: Corner/rbac/institutional_self_approval_blocked
        """
        reset_clock()
        env = make_routed_proposal(router_user_id="director-1")
        approved = validate_success(
            api.approve_institutional(
                env["proposal"]["id"], make_director_headers("director-2")
            ),
            200,
        )
        assert approved["status"] == "INSTITUTIONALLY_APPROVED"
        assert approved["pinned_budget_snapshot_id"] == approved["current_snapshot_id"]


class TestWithdrawConservation:
    def _setup(self, api):
        reset_clock()
        ctx = make_context()
        pi_id = ctx["pi"]["id"]
        before = validate_success(
            api.get_principal_investigator(pi_id, DIRECTOR), 200
        )
        prop = make_proposal(ctx["opp"]["id"], pi_id, title="Inv2",
                             pi_effort_pct=45.00)
        add_budget_line(prop["id"], amount_cents=1_000_000)
        finalize_budget(prop["id"])
        return ctx, before, prop

    def test_route_commits_effort(self, api):
        """PRD §3.1: "`committed_effort_pct` reports the portfolio load: the sum
        of `pi_effort_pct` across that investigator's proposals in the
        effort-contributing states `ROUTED`, `INSTITUTIONALLY_APPROVED`,
        `SUBMITTED`, `JIT_REQUESTED`, `NEGOTIATING`, `AWARDED`, and
        `SETUP_COMPLETE`, taken regardless of whether their project windows
        overlap."

        Design: Difficulty/compensating_invariant/pi_effort_withdraw_conservation
        """
        ctx, before, prop = self._setup(api)
        assert before["committed_effort_pct"] == 0
        route_proposal(prop["id"])
        after = validate_success(
            api.get_principal_investigator(ctx["pi"]["id"], DIRECTOR), 200
        )
        assert after["committed_effort_pct"] == 45

    def test_withdraw_releases_effort_exactly(self, api):
        """PRD §3.8: "Withdrawal is the manual escape hatch, available to the
        owning `PI` and to an `OSPDirector`. It is permitted from `DRAFT`,
        `BUDGET_LOCKED`, `ROUTED`, `RETURNED_FOR_REVISION`,
        `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, or
        `NEGOTIATING`". PRD §3.1: "`committed_effort_pct` reports the portfolio
        load: the sum of `pi_effort_pct` across that investigator's proposals in
        the effort-contributing states".

        Design: Difficulty/compensating_invariant/pi_effort_withdraw_conservation
        """
        ctx, _before, prop = self._setup(api)
        route_proposal(prop["id"])
        withdrawn = validate_success(
            api.withdraw_proposal(prop["id"], make_pi_headers(ctx["pi"]["id"])),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        after = validate_success(
            api.get_principal_investigator(ctx["pi"]["id"], DIRECTOR), 200
        )
        # WITHDRAWN is not an effort-contributing state: load returns to 0
        assert after["committed_effort_pct"] == 0
