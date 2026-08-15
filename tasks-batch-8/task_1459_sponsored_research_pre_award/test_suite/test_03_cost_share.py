"""Cost-share commitments, adequacy computation, and segregation (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    create_proposal_payload,
    finalize_budget,
    get_proposal,
    make_analyst_headers,
    make_chair_headers,
    make_context,
    make_locked_proposal,
    make_opportunity,
    make_pi,
    make_proposal,
    make_rate_agreement,
    pledge_and_approve_cost_share,
    pledge_cost_share,
    approve_cost_share,
    reset_clock,
    route_proposal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestCostShareEvaluationOrder:
    """Pinned-order adequacy: third-party cap keyed on the required minimum."""

    def _setup(self, api):
        reset_clock()
        ctx = make_context(requires_cost_share=True,
                           min_cost_share_pct_of_request=25.00)
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="CS")
        add_budget_line(prop["id"], amount_cents=10_000_000)
        finalize_budget(prop["id"])  # total_request = 15_400_000
        return prop

    def test_third_party_credit_capped_by_required_quarter(self, api):
        """PRD §3.4: "Fourth, the effective third-party credit is the lesser of
        two quantities, each rounded half up to whole cents: one half of the
        third-party-approved total, and one quarter of the required minimum.
        Fifth, `total_effective_cost_share_cents` is the cash-approved total plus
        the effective third-party credit."

        Design: Difficulty/combinatorial_formula/cost_share_requirement_evaluation_order
        """
        prop = self._setup(api)
        # required = round_half_up(25 * 15400000 / 100) = 3850000
        pledge_and_approve_cost_share(prop["id"], 2_000_000, source_type="DEPARTMENT")
        pledge_and_approve_cost_share(prop["id"], 5_000_000,
                                      source_type="THIRD_PARTY_IN_KIND")
        # tp_effective = min(2500000, round_half_up(3850000 * 0.25)=962500)
        data = get_proposal(prop["id"])
        assert data["total_approved_cost_share_cents"] == 7_000_000
        assert data["total_effective_cost_share_cents"] == 2_962_500
        assert data["is_cost_share_adequate"] is False

    def test_route_blocked_until_cash_covers_floor(self, api):
        """PRD §3.5: "The second guard fires when the opportunity requires cost
        share: the proposal must currently be adequate per §3.4, else
        `ERR_COST_SHARE_INADEQUATE` (HTTP 422)." PRD §3.4: "Finally,
        `is_cost_share_adequate` holds exactly when
        `total_effective_cost_share_cents` is at least the required minimum —
        equality is adequate".

        Design: Difficulty/combinatorial_formula/cost_share_requirement_evaluation_order
        """
        prop = self._setup(api)
        pledge_and_approve_cost_share(prop["id"], 2_000_000, source_type="DEPARTMENT")
        pledge_and_approve_cost_share(prop["id"], 5_000_000,
                                      source_type="THIRD_PARTY_IN_KIND")
        # effective 2962500 < required 3850000 -> route refused
        blocked = api.route_proposal(prop["id"], make_analyst_headers("analyst-1"))
        validate_error(blocked, ApiErrorId.ERR_COST_SHARE_INADEQUATE.value)
        # A further 1000000 cash approval lifts effective to 3962500 >= 3850000
        pledge_and_approve_cost_share(prop["id"], 1_000_000, source_type="COLLEGE")
        routed = api.route_proposal(prop["id"], make_analyst_headers("analyst-1"))
        data = validate_success(routed, 200)
        assert data["status"] == "ROUTED"


class TestCostShareFloorBoundary:
    def _setup(self, api):
        reset_clock()
        ctx = make_context(requires_cost_share=True,
                           min_cost_share_pct_of_request=10.00)
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Floor")
        add_budget_line(prop["id"], amount_cents=10_000_000)
        finalize_budget(prop["id"])  # total_request 15400000 -> floor 1540000
        return prop

    def test_one_cent_below_floor_fails(self, api):
        """PRD §3.4: "First, the required minimum `required_min_cost_share_cents`
        is zero when the opportunity's `requires_cost_share` is false; otherwise
        it is the opportunity's `min_cost_share_pct_of_request` multiplied by the
        proposal's current `total_request_cents`, divided by one hundred, and
        rounded half up to whole cents." and "`is_cost_share_adequate` holds
        exactly when `total_effective_cost_share_cents` is at least the required
        minimum — equality is adequate".

        Design: Difficulty/boundary_precision_check/cost_share_floor_boundary
        """
        prop = self._setup(api)
        pledge_and_approve_cost_share(prop["id"], 1_539_999)
        resp = api.route_proposal(prop["id"], make_analyst_headers("analyst-1"))
        # 1539999 < 1540000 by exactly one cent
        validate_error(resp, ApiErrorId.ERR_COST_SHARE_INADEQUATE.value)

    def test_exactly_at_floor_routes(self, api):
        """PRD §3.4: "`is_cost_share_adequate` holds exactly when
        `total_effective_cost_share_cents` is at least the required minimum —
        equality is adequate".

        Design: Difficulty/boundary_precision_check/cost_share_floor_boundary
        """
        prop = self._setup(api)
        pledge_and_approve_cost_share(prop["id"], 1_539_999)
        pledge_and_approve_cost_share(prop["id"], 1)
        routed = api.route_proposal(prop["id"], make_analyst_headers("analyst-1"))
        data = validate_success(routed, 200)
        assert data["status"] == "ROUTED"
        assert data["total_effective_cost_share_cents"] == 1_540_000


class TestApproveReleaseConservation:
    def test_approve_adds_amount_to_totals(self, api):
        """PRD §3.4: "On approval the commitment records `approved_by_user_id`,
        the proposal's `total_approved_cost_share_cents` grows by the
        commitment's `amount_cents`, the effective credit and adequacy are
        recomputed, and the proposal's `version` increments."

        Design: Difficulty/compensating_invariant/cost_share_approve_release_conservation
        """
        reset_clock()
        env = make_locked_proposal()
        prop_id = env["proposal"]["id"]
        assert env["proposal"]["total_approved_cost_share_cents"] == 0
        assert env["proposal"]["total_request_cents"] == 15_400_000
        pledge_and_approve_cost_share(prop_id, 1_000_000)
        data = get_proposal(prop_id)
        assert data["total_approved_cost_share_cents"] == 1_000_000
        assert data["total_effective_cost_share_cents"] == 1_000_000
        assert data["total_request_cents"] == 15_400_000

    def test_release_compensates_exactly(self, api):
        """PRD §3.4: "A `DepartmentChair` may also release an `APPROVED`
        commitment — the compensating action — moving it to `RELEASED`,
        subtracting its amount from `total_approved_cost_share_cents`,
        recomputing the derived fields, and incrementing the proposal's `version`
        again".

        Design: Difficulty/compensating_invariant/cost_share_approve_release_conservation
        """
        reset_clock()
        env = make_locked_proposal()
        prop_id = env["proposal"]["id"]
        commitment = pledge_and_approve_cost_share(prop_id, 1_000_000)
        released = validate_success(
            api.release_cost_share_commitment(
                commitment["id"], make_chair_headers("chair-1")
            ),
            200,
        )
        assert released["status"] == "RELEASED"
        data = get_proposal(prop_id)
        assert data["total_approved_cost_share_cents"] == 0
        assert data["total_effective_cost_share_cents"] == 0
        assert data["total_request_cents"] == 15_400_000


class TestCostShareStates:
    def test_release_from_pledged_rejected(self, api):
        """PRD §3.4: "releasing anything not `APPROVED` is
        `ERR_COMMITMENT_INVALID_STATE`."

        Design: Corner/state_machines/cost_share_release_from_pledged_rejected
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="CS",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        commitment = pledge_cost_share(prop["id"], 500_000)
        resp = api.release_cost_share_commitment(
            commitment["id"], make_chair_headers("chair-1")
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_INVALID_STATE.value)

    def test_pledged_commitments_contribute_nothing(self, api):
        """PRD §3.4: "Commitments in `PLEDGED`, `WITHDRAWN`, or `RELEASED` never
        contribute to any of these sums."

        Design: Corner/calculations/pledged_commitments_excluded_until_approved
        """
        reset_clock()
        ctx = make_context(requires_cost_share=True,
                           min_cost_share_pct_of_request=10.00)
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Pl",
                             pi_effort_pct=10.00)
        add_budget_line(prop["id"], amount_cents=10_000_000)
        finalize_budget(prop["id"])  # required floor = 1540000
        pledge_cost_share(prop["id"], 7_000_000)  # stays PLEDGED
        data = get_proposal(prop["id"])
        assert data["total_approved_cost_share_cents"] == 0
        assert data["total_effective_cost_share_cents"] == 0
        assert data["is_cost_share_adequate"] is False


class TestCostShareSegregation:
    def test_self_approval_blocked(self, api):
        """PRD §3.4: "Approval belongs to a `DepartmentChair` and is segregated:
        the approver's `X-User-ID` must differ from `committed_by_user_id`, or
        the attempt fails with `ERR_COST_SHARE_SELF_APPROVAL` (HTTP 403)."

        Design: Corner/rbac/cost_share_self_approval_blocked
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="SoD",
                             pi_effort_pct=10.00)
        commitment = pledge_cost_share(prop["id"], 500_000,
                                       committed_by="shared-user")
        resp = api.approve_cost_share_commitment(
            commitment["id"], make_chair_headers("shared-user")
        )
        validate_error(resp, ApiErrorId.ERR_COST_SHARE_SELF_APPROVAL.value)

    def test_distinct_chair_approves(self, api):
        """PRD §3.4: "the approver's `X-User-ID` must differ from
        `committed_by_user_id`" and "On approval the commitment records
        `approved_by_user_id`".

        Design: Corner/rbac/cost_share_self_approval_blocked
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="SoD",
                             pi_effort_pct=10.00)
        commitment = pledge_cost_share(prop["id"], 500_000,
                                       committed_by="shared-user")
        approved = validate_success(
            api.approve_cost_share_commitment(
                commitment["id"], make_chair_headers("chair-2")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "chair-2"
