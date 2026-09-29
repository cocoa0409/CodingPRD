"""The corrective-action loop and its exit: the revision counter is incremented
first and only then decides whether the record cycles again or escalates.
"""

from test_helpers import (
    ApiErrorId,
    CaRejectionReason,
    NcCategory,
    NcSeverity,
    NcSourceType,
    NcStatus,
    decide_corrective_action,
    make_applicant_contact_headers,
    raise_nonconformance,
    read_applicant,
    read_audit,
    read_nonconformance,
    schedule_audit,
    setup_applicant_with_facility,
    submit_corrective_action,
    validate_error,
)

FINDING_DAY = "2026-08-03T00:00:00Z"
PLAN_2 = "Revision 2: retrain plus a per-changeover swab signed by the shift lead."


def _finding_escalated_after_two_rejected_plans(api):
    """A MAJOR/DOCUMENTATION finding against a still-SCHEDULED audit, taken through
    two full submit-and-reject rounds so it lands on ESCALATED.

    The reviewer who rejects is not the auditor who raised the finding, and the
    clock never advances past the 30-day corrective-action deadline.
    """
    context = setup_applicant_with_facility(api, clock=FINDING_DAY)
    audit = schedule_audit(api, context.facility_id)
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.AUDIT,
        audit_id=audit["id"],
        category=NcCategory.DOCUMENTATION,
        severity=NcSeverity.MAJOR,
        description="Allergen changeover records incomplete for three shifts.",
    )

    submitted = submit_corrective_action(
        api,
        context.applicant_id,
        finding["id"],
        finding["version"],
        plan_text="Revision 1: retrain the packaging crew.",
    )
    rejected_once = decide_corrective_action(
        api,
        finding["id"],
        decision="REJECT",
        reviewer_user_id="rev-1",
        ca_rejection_reason=CaRejectionReason.NO_VERIFICATION_EVIDENCE,
    )
    assert submitted["status"] == NcStatus.CA_SUBMITTED
    assert rejected_once["status"] == NcStatus.CA_REJECTED
    assert rejected_once["ca_revision_count"] == 1

    submit_corrective_action(
        api,
        context.applicant_id,
        finding["id"],
        rejected_once["version"],
        plan_text=PLAN_2,
    )
    escalated = decide_corrective_action(
        api,
        finding["id"],
        decision="REJECT",
        reviewer_user_id="rev-1",
        ca_rejection_reason=CaRejectionReason.TIMELINE_TOO_LONG,
    )
    return context, audit, finding, escalated


def test_a_third_plan_against_an_escalated_finding_is_refused(api):
    """ESCALATED is outside the plan-submission source set, so the third attempt is
    a 409 state refusal even though it carries the current version.

    PRD: "Submitting a corrective-action plan requires `OPEN` or `CA_REJECTED`;
    deciding a plan requires `CA_SUBMITTED`; verifying effectiveness requires
    `CA_ACCEPTED`."
    PRD: "Once the incremented count reaches 2 the record moves `CA_SUBMITTED →
    ESCALATED` instead of cycling again."

    Design: Difficulty/non_linear_state_machine/ca_cycle_bounded_by_revision_count_then_escalation_locks_the_loop
    """
    context, _audit, finding, escalated = _finding_escalated_after_two_rejected_plans(api)

    response = api.submit_corrective_action_plan(
        finding["id"],
        make_applicant_contact_headers(context.applicant_id),
        expected_nonconformance_version=escalated["version"],
        ca_plan_text="Revision 3: third attempt after escalation.",
    )
    validate_error(response, ApiErrorId.INVALID_NONCONFORMANCE_STATE, 409)

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == NcStatus.ESCALATED
    assert row["ca_revision_count"] == 2
    assert row["ca_plan_text"] == PLAN_2
    assert row["ca_verified"] is False
    assert row["penalty_points"] == 8


def test_escalation_deducts_its_flat_ten_points_from_the_open_audit(api):
    """The finding's own 8 points plus the flat 10-point escalation deduction take
    the still-SCHEDULED audit's adjudicated score to 82.

    PRD: "On reaching `ESCALATED` the record's `ca_revision_count` is increased and
    `updated_at` refreshed, the applicant's `open_nc_penalty_points` and posture
    fields are recomputed, the audit named by `audit_id` recomputes `final_score`
    with the additional flat 10-point escalation deduction, and — if the linked
    certificate's `status` is `ISSUED` — that certificate moves `ISSUED →
    SUSPENDED` with `suspension_reason` of `CRITICAL_NONCONFORMANCE`."

    Design: Difficulty/non_linear_state_machine/ca_cycle_bounded_by_revision_count_then_escalation_locks_the_loop
    """
    context, audit, _finding, _escalated = _finding_escalated_after_two_rejected_plans(api)

    audit_row = read_audit(api, audit["id"])
    assert audit_row["status"] == "SCHEDULED"
    assert audit_row["final_score"] == 82

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_cycle"] == 92
    assert applicant["compliance_posture"] == "GOOD_STANDING"


def test_the_first_rejection_cycles_the_loop_instead_of_escalating(api):
    """The first rejection takes the counter from 0 to 1, which is still below the
    bound, so the record returns to CA_REJECTED and a revised plan is accepted.

    PRD: "While the incremented count is still below 2 the record moves
    `CA_SUBMITTED → CA_REJECTED` with `ca_decided_by_user_id` recorded, and the
    applicant may submit a revised plan, re-entering `CA_SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/ca_cycle_bounded_by_revision_count_then_escalation_locks_the_loop
    """
    context = setup_applicant_with_facility(api, clock=FINDING_DAY)
    audit = schedule_audit(api, context.facility_id)
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.AUDIT,
        audit_id=audit["id"],
        category=NcCategory.DOCUMENTATION,
        severity=NcSeverity.MAJOR,
        description="Allergen changeover records incomplete for three shifts.",
    )

    submit_corrective_action(
        api,
        context.applicant_id,
        finding["id"],
        finding["version"],
        plan_text="Revision 1: retrain the packaging crew.",
    )
    rejected = decide_corrective_action(
        api,
        finding["id"],
        decision="REJECT",
        reviewer_user_id="rev-1",
        ca_rejection_reason=CaRejectionReason.NO_VERIFICATION_EVIDENCE,
    )
    assert rejected["status"] == NcStatus.CA_REJECTED
    assert rejected["ca_revision_count"] == 1
    assert rejected["ca_decided_by_user_id"] == "rev-1"

    resubmitted = submit_corrective_action(
        api,
        context.applicant_id,
        finding["id"],
        rejected["version"],
        plan_text=PLAN_2,
    )
    assert resubmitted["status"] == NcStatus.CA_SUBMITTED
    assert resubmitted["ca_plan_text"] == PLAN_2
    assert resubmitted["ca_revision_count"] == 1
