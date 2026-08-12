"""Grant projects and milestones: the pinned drawdown waterfall, award-dollar
conservation, aggregate reads, lifecycle gates, and segregation of duties
(PRD §2.7, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_milestone,
    assert_grant_award_conservation,
    create_grant_project,
    create_milestone,
    pay_milestone,
    reject_milestone,
    setup_active_project,
    submit_milestone,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
GRANT_MGR = TEST_USERS["grant_manager_headers"]
REGULATOR = TEST_USERS["regulator_officer_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _project_with_milestones(api):
    """ACTIVE project (award 1000000, match 20) with milestone 1 APPROVED and
    milestone 2 SUBMITTED (PRD §3.9)."""
    project = setup_active_project(
        title="Bridge 42.1 Rehabilitation", award_amount_cents=1000000, required_match_pct=20
    )
    m1 = create_milestone(project["id"], name="Timber replacement", milestone_value_cents=400000)
    submit_milestone(m1["id"], 500000)
    m1 = approve_milestone(m1["id"])
    m2 = create_milestone(project["id"], name="Steel repairs", milestone_value_cents=400000)
    submit_milestone(m2["id"], 200000)
    return project, m1, m2


class TestDrawdownWaterfall:
    def test_drawdown_first_milestone_caps_at_value(self, api):
        """PRD §3.9: "Approval freezes the money. When the agency officer approves
        a submitted milestone, its `drawdown_cents` is computed and frozen by a
        pinned waterfall: the cost basis is the `actual_cost_cents` multiplied by
        the grantor's share — one hundred minus the `required_match_pct`, over one
        hundred — rounded half up to whole cents; that basis is capped first at
        the milestone's own `milestone_value_cents`; and the result is capped
        again at the award remaining before this milestone, computed as the
        `award_amount_cents` minus the project's `committed_cents` and
        `drawn_cents` as they stand before this drawdown is added."

        Design: Difficulty/combinatorial_formula/grant_drawdown_pinned_evaluation_order_mode_c
        """
        project = setup_active_project(award_amount_cents=1000000, required_match_pct=20)
        m1 = create_milestone(project["id"], name="Timber replacement", milestone_value_cents=400000)
        submit_milestone(m1["id"], 500000)
        approved = approve_milestone(m1["id"])
        assert approved["drawdown_cents"] == 400000, (
            f"min(cost basis round(500000*0.8)=400000, value 400000, remaining 1000000) "
            f"must yield 400000, got {approved['drawdown_cents']}"
        )

    def test_drawdown_second_milestone_uses_remaining_before(self, api, grant_manager_headers):
        """PRD §3.9: "The drawdown is the smaller of the two caps, and the
        evaluation order — cost basis, then milestone value, then award remaining,
        with the project aggregates read before this milestone contributes — is
        fixed to break the apparent circularity between the milestone and the
        project totals."
        PRD §3.9: "Four aggregates are computed on every read and after every
        milestone status change: `committed_cents`, the sum of `drawdown_cents`
        over the project's milestones in `APPROVED`; `drawn_cents`, the same sum
        over milestones in `PAID`; `remaining_cents`, the award minus the
        committed and drawn sums; and `percent_complete`, the summed
        `milestone_value_cents` of the project's milestones in `APPROVED` or
        `PAID` divided by the `award_amount_cents`, expressed as a percentage and
        rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/grant_drawdown_pinned_evaluation_order_mode_c
        """
        project, m1, m2 = _project_with_milestones(api)
        approved2 = approve_milestone(m2["id"])
        assert approved2["drawdown_cents"] == 160000, (
            f"min(cost basis round(200000*0.8)=160000, value 400000, remaining-before 600000) "
            f"must yield 160000, got {approved2['drawdown_cents']}"
        )

        proj = validate_success(api.get_grant_project(project["id"], grant_manager_headers))
        assert proj["committed_cents"] == 560000, (
            f"both milestones APPROVED (400000 + 160000), got {proj['committed_cents']}"
        )
        assert proj["remaining_cents"] == 440000, (
            f"1000000 - 560000 - 0 must leave 440000, got {proj['remaining_cents']}"
        )
        assert proj["percent_complete"] == 80.0, (
            f"800000 approved-and-paid value over 1000000 must yield 80.0, got {proj['percent_complete']}"
        )


class TestAwardConservation:
    def _conservation_scenario(self):
        # Payment runs last: paying A while A is the only milestone would trip the
        # PRD §3.9 completion bubble-up ("when the project has at least one
        # milestone and every milestone stands PAID, the project moves itself from
        # ACTIVE to the terminal COMPLETED"), making later submissions fail with
        # ERR_GRANT_NOT_ACTIVE. With B APPROVED and C REJECTED at pay time, not
        # every milestone is PAID, so the project stays ACTIVE.
        project = setup_active_project(
            title="Siding Renewal Program", award_amount_cents=1000000, required_match_pct=20
        )
        m_a = create_milestone(project["id"], name="Phase A rail", milestone_value_cents=400000)
        submit_milestone(m_a["id"], 500000)
        approve_milestone(m_a["id"])
        m_b = create_milestone(project["id"], name="Phase B ties", milestone_value_cents=400000)
        submit_milestone(m_b["id"], 200000)
        m_b = approve_milestone(m_b["id"])
        m_c = create_milestone(project["id"], name="Phase C ballast", milestone_value_cents=200000)
        submit_milestone(m_c["id"], 100000)
        reject_milestone(m_c["id"])
        pay_milestone(m_a["id"])
        return project, m_b

    def test_grant_award_conservation_across_transitions(self, api, grant_manager_headers):
        """PRD §3.9: "Four aggregates are computed on every read and after every
        milestone status change: `committed_cents`, the sum of `drawdown_cents`
        over the project's milestones in `APPROVED`; `drawn_cents`, the same sum
        over milestones in `PAID`; `remaining_cents`, the award minus the
        committed and drawn sums; and `percent_complete`, the summed
        `milestone_value_cents` of the project's milestones in `APPROVED` or
        `PAID` divided by the `award_amount_cents`, expressed as a percentage and
        rounded half up to two decimal places."

        Design: Difficulty/compensating_invariant/grant_award_conservation
        """
        project, m_b = self._conservation_scenario()
        proj = validate_success(api.get_grant_project(project["id"], grant_manager_headers))
        assert proj["drawn_cents"] == 400000, f"milestone A PAID draws 400000, got {proj['drawn_cents']}"
        assert proj["committed_cents"] == 160000, (
            f"milestone B APPROVED commits 160000 (rejected C contributes 0), got {proj['committed_cents']}"
        )
        assert proj["remaining_cents"] == 440000, (
            f"1000000 - 160000 - 400000 must leave 440000, got {proj['remaining_cents']}"
        )
        assert_grant_award_conservation(proj)

    def test_grant_percent_complete_excludes_rejected(self, api, grant_manager_headers):
        """PRD §3.9: "and `percent_complete`, the summed `milestone_value_cents`
        of the project's milestones in `APPROVED` or `PAID` divided by the
        `award_amount_cents`, expressed as a percentage and rounded half up to two
        decimal places."

        Design: Difficulty/compensating_invariant/grant_award_conservation
        """
        project, m_b = self._conservation_scenario()
        assert m_b["drawdown_cents"] == 160000
        proj = validate_success(api.get_grant_project(project["id"], grant_manager_headers))
        assert proj["percent_complete"] == 80.0, (
            f"rejected milestones are excluded: (400000 + 400000) / 1000000 * 100 must yield "
            f"80.0, got {proj['percent_complete']}"
        )


class TestMilestoneLifecycle:
    def test_milestone_resubmit_after_reject(self, api):
        """PRD §3.9: "Submitting moves `PENDING` → `SUBMITTED`, records the
        `actual_cost_cents` — which must be zero or greater — and stamps
        `submitted_at`; a `REJECTED` milestone may be resubmitted the same way,
        its `actual_cost_cents` replaced by the new figure."

        Design: Corner/state_machines/milestone_resubmit_after_reject
        """
        project = setup_active_project(title="Tie Renewal", award_amount_cents=500000, required_match_pct=20)
        milestone = create_milestone(project["id"], name="M1", milestone_value_cents=200000)
        submit_milestone(milestone["id"], 90000)
        reject_milestone(milestone["id"])

        resubmitted = submit_milestone(milestone["id"], 150000)
        assert resubmitted["status"] == "SUBMITTED", (
            f"a rejected milestone resubmits to SUBMITTED, got {resubmitted['status']}"
        )
        assert resubmitted["actual_cost_cents"] == 150000, (
            f"resubmission replaces actual_cost_cents, got {resubmitted['actual_cost_cents']}"
        )

    def test_milestone_value_over_award_rejected(self, api, grant_manager_headers):
        """PRD §3.9: "The project's budget is guarded at creation: the sum of
        `milestone_value_cents` over the project's milestones, excluding any in
        `REJECTED` and including the new one, must not exceed the
        `award_amount_cents`, failing as `ERR_MILESTONE_VALUE_EXCEEDS_AWARD`."

        Design: Corner/validations/milestone_value_over_award_rejected
        """
        project = setup_active_project(title="Culvert Program", award_amount_cents=100000,
                                       required_match_pct=10)
        create_milestone(project["id"], name="Culvert 1", milestone_value_cents=90000)
        resp = api.create_grant_milestone(
            project["id"], {"name": "Culvert 2", "milestone_value_cents": 20001}, grant_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONE_VALUE_EXCEEDS_AWARD)

    def test_grant_submit_blocked_when_not_active(self, api, grant_manager_headers):
        """PRD §3.9: "Submission, approval, and payment all require the project to
        be `ACTIVE`, failing otherwise as `ERR_GRANT_NOT_ACTIVE`."

        Design: Corner/validations/grant_submit_blocked_when_not_active
        """
        project = create_grant_project(title="Dormant Project", award_amount_cents=300000,
                                       required_match_pct=0)
        assert project["status"] == "AWARDED"
        milestone = create_milestone(project["id"], name="M1", milestone_value_cents=100000)

        resp = api.submit_grant_milestone(milestone["id"], {"actual_cost_cents": 50000}, grant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

    def test_milestone_approve_before_submit_rejected(self, api, regulator_officer_headers):
        """PRD §3.9: "Approval and rejection are defined only from `SUBMITTED`;
        either action attempted on a milestone in any other status fails with
        `ERR_MILESTONE_NOT_SUBMITTED`."

        Design: Corner/errors/milestone_approve_before_submit_rejected
        """
        project = setup_active_project(title="Signal Upgrade", award_amount_cents=800000,
                                       required_match_pct=20)
        milestone = create_milestone(project["id"], name="Design", milestone_value_cents=100000)
        resp = api.approve_grant_milestone(milestone["id"], regulator_officer_headers)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_SUBMITTED)

    def test_grant_manager_cannot_approve_own_milestone(self, api, grant_manager_headers):
        """PRD §3.9: "Submission belongs to the `GrantManager`, ruling belongs to
        the `RegulatorOfficer`, and payment belongs to the `SettlementClerk` — a
        deliberate segregation of duties."
        PRD §2.1: "Authorization is per-endpoint: a caller whose role is not in
        the endpoint's authorized list, or whose entity-backed identity does not
        match the targeted resource, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        Design: Corner/rbac/grant_manager_cannot_approve_own_milestone
        """
        project = setup_active_project(title="Crossing Surfaces", award_amount_cents=250000,
                                       required_match_pct=20)
        milestone = create_milestone(project["id"], name="Surface M1", milestone_value_cents=100000)
        submit_milestone(milestone["id"], 120000)

        resp = api.approve_grant_milestone(milestone["id"], grant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
