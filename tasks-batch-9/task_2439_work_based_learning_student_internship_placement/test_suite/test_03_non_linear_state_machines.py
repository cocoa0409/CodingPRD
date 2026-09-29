"""Neither of this service's two-dimensional state machines advances in a straight
line. A placement's compliance dimension can be flagged and cleared repeatedly
while its lifecycle never moves, and a training plan can be pushed back to the
employer and resubmitted before it is finally approved.
"""

from test_helpers import (
    APPROVER,
    COORDINATOR,
    OFFICER,
    api_client,
    compliance_decision,
    draft_plan_with_objectives,
    issue_work_permit,
    read_permit,
    read_placement,
    read_plan,
    request_changes_payload,
    request_work_permit,
    revoke_work_permit,
    setup_active_placement,
    setup_proposed_placement,
    validate_success,
)

HARBOR_POINT = {
    "legal_name": "Harbor Point Clinic",
    "naics_code": "621111",
    "industry_sector": "HEALTHCARE",
}
LENA_ORTIZ = {"full_name": "Lena Ortiz", "birth_date": "2009-11-02"}
ALDER_STREET = {
    "legal_name": "Alder Street Bakery",
    "naics_code": "311811",
    "industry_sector": "HOSPITALITY",
}
OWEN_MARSH = {"full_name": "Owen Marsh", "email": "owen.marsh@alderstreet.example"}
KAI_BISHOP = {"full_name": "Kai Bishop", "birth_date": "2009-08-30"}

ONE_CYCLE_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1500,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "PUBLIC_TRANSIT",
    "commute_round_trip_miles": 0.00,
}


def _active_placement_whose_permit_gets_revoked():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="HSC-210",
        credit_hours_target=60.00,
        partner_overrides=HARBOR_POINT,
        student_overrides=LENA_ORTIZ,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    revoke_work_permit(scenario.permit_id, "Permit issued against the wrong school year")
    return scenario


def _plan_returned_once_then_resubmitted():
    scenario = setup_proposed_placement(
        clock="2026-09-07T08:00:00Z",
        partner_overrides=ALDER_STREET,
        supervisor_overrides=OWEN_MARSH,
        student_overrides=KAI_BISHOP,
        permit_class="MINOR_16_17",
        placement_overrides={**ONE_CYCLE_PLACEMENT, "scheduled_weekly_hours": 10.00},
    )
    draft_plan_with_objectives(
        scenario, course_code="FCS-120", credit_hours_target=60.00, objective_count=3
    )
    validate_success(api_client.submit_training_plan(scenario.plan_id, {}, COORDINATOR))
    validate_success(
        api_client.request_training_plan_changes(
            scenario.plan_id,
            request_changes_payload("Objective FCS-2 needs an assessment rubric reference"),
            OFFICER,
        )
    )
    validate_success(api_client.submit_training_plan(scenario.plan_id, {}, COORDINATOR))
    return scenario


class TestComplianceDimensionCyclesIndependently:
    def test_permit_revocation_flags_the_placement_without_touching_its_lifecycle(self):
        """Revocation flags but does not block: every `Placement` of that student whose
        `lifecycle_status` is `PROPOSED` or `ACTIVE` and whose `compliance_status` is
        `PENDING_REVIEW` or `CLEARED` moves to `FLAGGED`. `compliance_status` starts at
        `PENDING_REVIEW` and tracks its clearance to operate; the two dimensions evolve
        independently, and an `ACTIVE` placement can be `FLAGGED` without ceasing to be
        `ACTIVE`.

        Design: Difficulty/non_linear_state_machine/placement_compliance_dimension_cycles_back_to_cleared_while_lifecycle_stays_active
        """
        scenario = _active_placement_whose_permit_gets_revoked()

        placement = read_placement(scenario.placement_id)
        assert placement["compliance_status"] == "FLAGGED"
        assert placement["lifecycle_status"] == "ACTIVE"

        assert read_permit(scenario.student_id, scenario.permit_id)["status"] == "REVOKED"

    def test_clearing_against_a_replacement_permit_returns_the_dimension_to_cleared(self):
        """A decision of `CLEAR` moves the compliance dimension `FLAGGED → CLEARED`, and
        additionally requires that the student hold a work permit whose `status` is
        `ISSUED` and whose `permit_class` equals the placement's `permit_class_at_start`,
        failing with `ERR_WORK_PERMIT_INVALID` otherwise. The compliance dimension may
        therefore cycle between `FLAGGED` and `CLEARED` any number of times without the
        placement's lifecycle changing.

        Design: Difficulty/non_linear_state_machine/placement_compliance_dimension_cycles_back_to_cleared_while_lifecycle_stays_active
        """
        scenario = _active_placement_whose_permit_gets_revoked()
        assert read_placement(scenario.placement_id)["compliance_status"] == "FLAGGED"

        replacement = request_work_permit(scenario.student_id, permit_class="MINOR_16_17")
        replacement = issue_work_permit(replacement["id"], "2027-06-30")

        cleared = compliance_decision(
            scenario.placement_id, "CLEAR", "Replacement permit verified"
        )

        assert cleared["compliance_status"] == "CLEARED"
        assert cleared["lifecycle_status"] == "ACTIVE"
        assert read_permit(scenario.student_id, scenario.permit_id)["status"] == "REVOKED"
        assert read_permit(scenario.student_id, replacement["id"])["status"] == "ISSUED"


class TestTrainingPlanRevisionLoop:
    def test_a_returned_plan_goes_back_to_submitted_carrying_its_revision_round(self):
        """Requesting changes moves the plan `SUBMITTED → CHANGES_REQUESTED`, stores the
        supplied `change_request_note`, and increments `revision_round` by 1; like the
        agreement negotiation loop it is permitted only while `revision_round` is below 3,
        and the fourth request is refused with `ERR_NEGOTIATION_ROUND_LIMIT`. Submission
        moves the plan `DRAFT → SUBMITTED`, and the same operation moves a returned plan
        `CHANGES_REQUESTED → SUBMITTED`; either way `submitted_at` is set or refreshed to
        the clock timestamp.

        Design: Difficulty/non_linear_state_machine/training_plan_revision_loop_returns_to_submitted_before_approval
        """
        scenario = _plan_returned_once_then_resubmitted()

        plan = read_plan(scenario.plan_id)
        assert plan["status"] == "SUBMITTED"
        assert plan["revision_round"] == 1
        assert (
            plan["change_request_note"]
            == "Objective FCS-2 needs an assessment rubric reference"
        )

        # The loop has not touched the placement, which is still awaiting approval.
        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "PROPOSED"

    def test_approval_after_the_loop_activates_the_placement(self):
        """Approval moves the plan `SUBMITTED → APPROVED` and is the single most
        consequential operation in the system, because it fires a three-hop cascade.
        Approval increments the placement's `version` by 1.

        Design: Difficulty/non_linear_state_machine/training_plan_revision_loop_returns_to_submitted_before_approval
        """
        scenario = _plan_returned_once_then_resubmitted()

        approved = validate_success(
            api_client.approve_training_plan(scenario.plan_id, {}, APPROVER)
        )

        assert approved["status"] == "APPROVED"
        assert approved["revision_round"] == 1

        placement = read_placement(scenario.placement_id)
        assert placement["lifecycle_status"] == "ACTIVE"
        assert placement["compliance_status"] == "CLEARED"
