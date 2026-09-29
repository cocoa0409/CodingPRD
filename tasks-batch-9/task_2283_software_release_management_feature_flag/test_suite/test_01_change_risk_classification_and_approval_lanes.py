"""Risk classification, the approval lanes it selects, and the ledger it charges."""

import pytest

from test_helpers import (
    ApiErrorId,
    ApprovalKind,
    ChangeState,
    RiskClass,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import make_approval_payload
from test_helpers.fixtures import (
    read_change,
    read_release,
    record_approval,
    scenario_boundary_risk_change_pair,
    scenario_change_pair_awaiting_dependency_depth,
    scenario_critical_and_low_changes_authored,
    scenario_medium_change_authored_by_dual_role_operator,
    submit_change,
)
from test_helpers.test_users import (
    CHANGE_APPROVER,
    COMPLIANCE_OFFICER,
    DUAL_ROLE_APPROVER,
    SECOND_CHANGE_APPROVER,
)


class TestPreliminaryAndFinalRiskScores:
    """A dependency edge declared after submission only moves the final score."""

    def test_final_score_adds_five_points_per_level_of_prerequisite_depth(self, api):
        """The preliminary run treats prerequisite depth as unconditionally zero.

        "every dependency edge added after submission raises the final score by
        five points per level of depth, up to the 15-point cap", and the final run
        happens once on entry into state APPROVED.

        Design: Difficulty/dual_variant_calc/change_risk_score_preliminary_vs_final_diverge_on_dependency_depth
        """
        built = scenario_change_pair_awaiting_dependency_depth(api)
        assert built["preliminary_score_a"] == 62

        record_approval(api, built["change_a"]["id"], ApprovalKind.TECHNICAL)
        record_approval(
            api,
            built["change_a"]["id"],
            ApprovalKind.COMPLIANCE,
            comment="regulated subsystem reviewed",
        )

        change_a = read_change(api, built["change_a"]["id"])
        assert change_a["risk_score_preliminary"] == 62
        assert change_a["risk_score_final"] == 67
        assert change_a["risk_score_final"] - change_a["risk_score_preliminary"] == 5
        assert change_a["dependency_depth"] == 1
        assert change_a["risk_class"] == RiskClass.HIGH
        assert change_a["state"] == ChangeState.APPROVED

    def test_each_approval_pins_the_preliminary_score_not_the_final_one(self, api):
        """An approval stamps "``pinned_risk_score``, a snapshot of the change's
        ``risk_score_preliminary`` at the instant the approval was recorded".

        Design: Difficulty/dual_variant_calc/change_risk_score_preliminary_vs_final_diverge_on_dependency_depth
        """
        built = scenario_change_pair_awaiting_dependency_depth(api)

        technical = record_approval(api, built["change_a"]["id"], ApprovalKind.TECHNICAL)
        compliance = record_approval(
            api, built["change_a"]["id"], ApprovalKind.COMPLIANCE
        )

        assert technical["pinned_risk_score"] == 62
        assert compliance["pinned_risk_score"] == 62
        change_a = read_change(api, built["change_a"]["id"])
        assert change_a["risk_score_final"] == 67

    def test_release_budget_is_charged_the_final_score_of_every_approved_change(self, api):
        """The join adds ``risk_score_final`` to the release's
        ``risk_budget_consumed_points``, and a LOW change charges its own final
        score at submission.

        Design: Difficulty/dual_variant_calc/change_risk_score_preliminary_vs_final_diverge_on_dependency_depth
        """
        built = scenario_change_pair_awaiting_dependency_depth(api)
        record_approval(api, built["change_a"]["id"], ApprovalKind.TECHNICAL)
        record_approval(api, built["change_a"]["id"], ApprovalKind.COMPLIANCE)

        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 76
        assert release["committed_change_count"] == 2


class TestSubmissionRiskFork:
    """Submission "**immediately** takes one of three branches according to ``risk_class``"."""

    def test_critical_change_waits_in_cab_review_without_consuming_budget(self, api):
        """"A ``CRITICAL`` change moves from ``RISK_CLASSIFIED`` to ``CAB_REVIEW`` to
        await the change advisory board. **No risk budget is consumed at this
        point**".

        Design: Difficulty/non_linear_state_machine/change_request_risk_fork_critical_to_cab_review_versus_low_auto_approve
        """
        built = scenario_critical_and_low_changes_authored(api)

        submitted = submit_change(api, built["change_critical"]["id"])

        assert submitted["risk_score_preliminary"] == 85
        assert submitted["risk_class"] == RiskClass.CRITICAL
        assert submitted["state"] == ChangeState.CAB_REVIEW
        assert submitted["risk_score_final"] is None
        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 0
        assert release["committed_change_count"] == 0

    def test_low_change_auto_approves_with_no_approval_records_at_all(self, api):
        """"It moves straight from ``RISK_CLASSIFIED`` to ``APPROVED`` with **no
        approval records created at all**".

        Design: Difficulty/non_linear_state_machine/change_request_risk_fork_critical_to_cab_review_versus_low_auto_approve
        """
        built = scenario_critical_and_low_changes_authored(api)

        submitted = submit_change(api, built["change_low"]["id"])

        assert submitted["risk_score_preliminary"] == 9
        assert submitted["risk_class"] == RiskClass.LOW
        assert submitted["state"] == ChangeState.APPROVED
        assert submitted["risk_score_final"] == 9
        approvals, meta = validate_paginated(
            api.list_approvals(built["change_low"]["id"], CHANGE_APPROVER)
        )
        assert meta["total_count"] == 0
        assert approvals == []

    def test_cab_review_join_needs_all_three_lanes_before_approval(self, api):
        """"A change waiting in ``CAB_REVIEW`` reaches ``APPROVED`` when
        ``approval_technical_count``, ``approval_compliance_count`` and
        ``approval_cab_count`` are each at least 1".

        Design: Difficulty/non_linear_state_machine/change_request_risk_fork_critical_to_cab_review_versus_low_auto_approve
        """
        built = scenario_critical_and_low_changes_authored(api)
        submit_change(api, built["change_critical"]["id"])
        submit_change(api, built["change_low"]["id"])
        critical_id = built["change_critical"]["id"]

        record_approval(api, critical_id, ApprovalKind.TECHNICAL)
        after_technical = read_change(api, critical_id)
        assert after_technical["state"] == ChangeState.CAB_REVIEW

        record_approval(api, critical_id, ApprovalKind.COMPLIANCE)
        after_compliance = read_change(api, critical_id)
        assert after_compliance["state"] == ChangeState.CAB_REVIEW

        record_approval(
            api, critical_id, ApprovalKind.CAB, headers=SECOND_CHANGE_APPROVER
        )

        critical = read_change(api, critical_id)
        assert critical["state"] == ChangeState.APPROVED
        assert critical["risk_score_final"] == 85
        assert critical["approval_technical_count"] == 1
        assert critical["approval_compliance_count"] == 1
        assert critical["approval_cab_count"] == 1

    def test_two_forks_charge_the_same_release_ledger_once_each(self, api):
        """Both joins have identical effects: the release's
        ``committed_change_count`` rises by one and ``risk_score_final`` is added
        to ``risk_budget_consumed_points``.

        Design: Difficulty/non_linear_state_machine/change_request_risk_fork_critical_to_cab_review_versus_low_auto_approve
        """
        built = scenario_critical_and_low_changes_authored(api)
        submit_change(api, built["change_critical"]["id"])
        submit_change(api, built["change_low"]["id"])
        record_approval(api, built["change_critical"]["id"], ApprovalKind.TECHNICAL)
        record_approval(api, built["change_critical"]["id"], ApprovalKind.COMPLIANCE)
        record_approval(
            api,
            built["change_critical"]["id"],
            ApprovalKind.CAB,
            headers=SECOND_CHANGE_APPROVER,
        )

        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 94
        assert release["committed_change_count"] == 2


class TestRiskTierBoundary:
    """"A score of exactly 50 is ``HIGH``, and a score of exactly 70 is ``CRITICAL``."""

    def test_score_of_exactly_fifty_is_high_and_still_awaits_compliance(self, api):
        """A HIGH change "requires ``TECHNICAL`` and ``COMPLIANCE``", so a single
        technical approval leaves it in ``RISK_CLASSIFIED`` with a null final score.

        Design: Difficulty/boundary_precision_check/risk_class_boundary_score_exactly_fifty_is_high_forty_six_is_medium
        """
        built = scenario_boundary_risk_change_pair(api)

        submitted = submit_change(api, built["change_on_boundary"]["id"])
        assert submitted["risk_score_preliminary"] == 50
        assert submitted["risk_class"] == RiskClass.HIGH

        record_approval(api, built["change_on_boundary"]["id"], ApprovalKind.TECHNICAL)

        change = read_change(api, built["change_on_boundary"]["id"])
        assert change["state"] == ChangeState.RISK_CLASSIFIED
        assert change["risk_score_final"] is None
        assert change["approval_technical_count"] == 1

    def test_score_of_forty_six_is_medium_and_approves_on_technical_alone(self, api):
        """"A ``MEDIUM`` change requires only ``TECHNICAL``", and the tier runs
        "``MEDIUM`` from 25 up to but not including 50".

        Design: Difficulty/boundary_precision_check/risk_class_boundary_score_exactly_fifty_is_high_forty_six_is_medium
        """
        built = scenario_boundary_risk_change_pair(api)

        submitted = submit_change(api, built["change_below_boundary"]["id"])
        assert submitted["risk_score_preliminary"] == 46
        assert submitted["risk_class"] == RiskClass.MEDIUM

        record_approval(api, built["change_below_boundary"]["id"], ApprovalKind.TECHNICAL)

        change = read_change(api, built["change_below_boundary"]["id"])
        assert change["state"] == ChangeState.APPROVED
        assert change["risk_score_final"] == 46

    def test_only_the_approved_change_of_the_pair_charges_the_ledger(self, api):
        """Budget is charged only on entry to ``APPROVED``, so the boundary change
        still waiting in ``RISK_CLASSIFIED`` contributes nothing.

        Design: Difficulty/boundary_precision_check/risk_class_boundary_score_exactly_fifty_is_high_forty_six_is_medium
        """
        built = scenario_boundary_risk_change_pair(api)
        submit_change(api, built["change_on_boundary"]["id"])
        submit_change(api, built["change_below_boundary"]["id"])
        record_approval(api, built["change_on_boundary"]["id"], ApprovalKind.TECHNICAL)
        record_approval(api, built["change_below_boundary"]["id"], ApprovalKind.TECHNICAL)

        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 46
        assert release["committed_change_count"] == 1


class TestSegregationOfDutiesOutranksLaneCheck:
    """Rank 11 segregation of duties is evaluated before the rank-27 lane check."""

    def test_author_approving_own_change_is_refused_before_the_lane_is_examined(
        self, api
    ):
        """"the approver's ``X-User-ID`` must differ from the change's
        ``author_user_id`` in every lane" -- so a CAB decision the MEDIUM change
        does not even require still reports the self-approval failure.

        Design: Difficulty/priority_pair_validation_conflict/self_approval_safety_beats_approval_kind_referential_check
        """
        built = scenario_medium_change_authored_by_dual_role_operator(api)

        response = api.create_approval(
            built["change"]["id"],
            make_approval_payload(kind=ApprovalKind.CAB),
            DUAL_ROLE_APPROVER,
        )

        validate_error(response, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value, 403)

    def test_lane_check_surfaces_once_a_different_approver_records_the_cab_decision(
        self, api
    ):
        """"Submitting a lane the change's class does not require -- a ``CAB``
        decision on a ``MEDIUM`` change, for instance -- is refused with
        ``ERR_APPROVAL_KIND_NOT_REQUIRED``".

        Design: Difficulty/priority_pair_validation_conflict/self_approval_safety_beats_approval_kind_referential_check
        """
        built = scenario_medium_change_authored_by_dual_role_operator(api)

        response = api.create_approval(
            built["change"]["id"],
            make_approval_payload(kind=ApprovalKind.CAB),
            SECOND_CHANGE_APPROVER,
        )

        validate_error(response, ApiErrorId.ERR_APPROVAL_KIND_NOT_REQUIRED.value, 422)

    @pytest.mark.parametrize(
        "headers", [DUAL_ROLE_APPROVER, SECOND_CHANGE_APPROVER], ids=["author", "board"]
    )
    def test_neither_refused_approval_records_anything(self, api, headers):
        """The ladder "applies **no side effect whatsoever** -- no counter moves, no
        state changes, no timestamp is stamped".

        Design: Difficulty/priority_pair_validation_conflict/self_approval_safety_beats_approval_kind_referential_check
        """
        built = scenario_medium_change_authored_by_dual_role_operator(api)

        api.create_approval(
            built["change"]["id"], make_approval_payload(kind=ApprovalKind.CAB), headers
        )

        change = read_change(api, built["change"]["id"])
        assert change["state"] == ChangeState.RISK_CLASSIFIED
        assert change["risk_class"] == RiskClass.MEDIUM
        assert change["approval_cab_count"] == 0
        _, meta = validate_paginated(
            api.list_approvals(built["change"]["id"], COMPLIANCE_OFFICER)
        )
        assert meta["total_count"] == 0
