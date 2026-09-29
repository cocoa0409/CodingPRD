"""The audit's two compliance-score variants: the provisional on-site figure that
is frozen at close and selects the outcome branch, and the final adjudicated
figure that keeps moving as its findings do.
"""

from test_helpers import (
    NcCategory,
    NcSeverity,
    NcSourceType,
    NcStatus,
    close_audit,
    decide_corrective_action,
    raise_nonconformance,
    read_applicant,
    read_audit,
    read_nonconformance,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    start_audit,
    submit_corrective_action,
    verify_corrective_action,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ONSITE_START = "2026-08-10T08:00:00Z"
ONSITE_END = "2026-08-10T16:00:00Z"
DURING_VISIT = "2026-08-10T09:00:00Z"
AFTER_VISIT = "2026-08-10T17:00:00Z"


def _audit_with_two_onsite_findings(api):
    """An INITIAL audit closed with one MAJOR/SHARED_EQUIPMENT and one
    MINOR/DOCUMENTATION finding, both raised while the auditor was still on site.

    Deduction 8 x 1.5 + 2 x 1.0 == 14, so the provisional score is 86 and the
    audit forks to CLOSED_CONDITIONAL.
    """
    context = setup_applicant_with_facility(
        api, clock=SANITATION_DAY, sanitation_validated_on=SANITATION_DAY
    )
    audit = schedule_audit(
        api,
        context.facility_id,
        onsite_start_at=ONSITE_START,
        onsite_end_at=ONSITE_END,
    )
    set_clock(api, DURING_VISIT)
    start_audit(api, audit["id"])
    major = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.AUDIT,
        audit_id=audit["id"],
        category=NcCategory.SHARED_EQUIPMENT,
        severity=NcSeverity.MAJOR,
        description="Changeover wipe-down record incomplete on shared sheeter.",
    )
    minor = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.AUDIT,
        audit_id=audit["id"],
        category=NcCategory.DOCUMENTATION,
        severity=NcSeverity.MINOR,
        description="Training log missing two signatures.",
    )
    set_clock(api, AFTER_VISIT)
    closed = close_audit(api, audit["id"])
    return context, closed, major, minor


def test_final_score_halves_a_verified_finding_while_provisional_stays_frozen(api):
    """Verifying the MAJOR finding's corrective action lifts the adjudicated score
    from 86 to 92 while the frozen on-site figure and the outcome branch stand.

    PRD: "It counts every such nonconformance regardless of `created_at`, and it
    differs in two further ways: each finding whose `ca_verified` is true
    contributes only half of its severity-times-weight product, and after the
    summed products have been rounded half up and subtracted from 100, a further
    flat 10 points is deducted for each of those nonconformances whose `status` is
    `ESCALATED`."
    PRD: "It is written into `provisional_score` at close and **frozen there
    forever**."

    Design: Difficulty/dual_variant_calc/audit_score_provisional_frozen_vs_final_recomputed_after_ca_verification
    """
    context, closed, major, minor = _audit_with_two_onsite_findings(api)

    submit_corrective_action(
        api,
        context.applicant_id,
        major["id"],
        major["version"],
        plan_text="Dedicated sheeter changeover SOP plus verification swab per changeover.",
    )
    decide_corrective_action(api, major["id"], reviewer_user_id="rev-1")

    verify_corrective_action(api, major["id"], auditor_user_id="aud-1")

    audit = read_audit(api, closed["id"])
    assert audit["status"] == "CLOSED_CONDITIONAL"
    assert audit["provisional_score"] == 86
    assert audit["final_score"] == 92
    assert audit["finding_count"] == 2
    assert audit["critical_finding_count"] == 0

    assert read_nonconformance(api, major["id"])["status"] == NcStatus.CLOSED
    assert read_nonconformance(api, major["id"])["ca_verified"] is True
    assert read_nonconformance(api, minor["id"])["status"] == NcStatus.OPEN

    # Only the still-open MINOR finding keeps charging the applicant.
    assert read_applicant(api, context.applicant_id)["open_nc_penalty_points"] == 2


def test_provisional_and_final_agree_at_close_and_select_the_conditional_branch(api):
    """At close both figures read the same 86, computed from severity points times
    category weight over the findings raised on site.

    PRD: "Each finding contributes its severity points — 2 for `MINOR`, 8 for
    `MAJOR`, 25 for `CRITICAL` — multiplied by a category weight read off its
    `category`: 1.5 for `SHARED_EQUIPMENT`, 1.25 for `AIR_HANDLING`, 1.25 for
    `SANITATION`, 1.0 for `DOCUMENTATION`, 1.0 for `LABELING` and 1.5 for
    `THRESHOLD_EXCEEDANCE`."
    PRD: "**`CLOSED_CONDITIONAL`** is selected when the provisional score is at
    least 75 and below 90, with `critical_finding_count` still 0."

    Design: Difficulty/dual_variant_calc/audit_score_provisional_frozen_vs_final_recomputed_after_ca_verification
    """
    _context, closed, _major, _minor = _audit_with_two_onsite_findings(api)

    assert closed["status"] == "CLOSED_CONDITIONAL"
    assert closed["provisional_score"] == 86
    assert closed["final_score"] == 86
    assert closed["closed_by_user_id"] == "aud-1"
    assert closed["closed_on"] == AFTER_VISIT
    assert closed["finding_count"] == 2
    assert closed["critical_finding_count"] == 0


def test_a_submitted_corrective_action_alone_does_not_move_either_figure(api):
    """Submitting and accepting the plan leaves both scores at 86, because the
    adjudicated figure only halves a finding once its `ca_verified` is true.

    PRD: "The provisional figure deliberately ignores `ca_verified` altogether and
    applies no escalation penalty."

    Design: Difficulty/dual_variant_calc/audit_score_provisional_frozen_vs_final_recomputed_after_ca_verification
    """
    context, closed, major, _minor = _audit_with_two_onsite_findings(api)

    submit_corrective_action(
        api,
        context.applicant_id,
        major["id"],
        major["version"],
        plan_text="Dedicated sheeter changeover SOP plus verification swab per changeover.",
    )
    accepted = decide_corrective_action(api, major["id"], reviewer_user_id="rev-1")
    assert accepted["status"] == NcStatus.CA_ACCEPTED
    assert accepted["ca_verified"] is False

    audit = read_audit(api, closed["id"])
    assert audit["provisional_score"] == 86
    assert audit["final_score"] == 86
    assert audit["status"] == "CLOSED_CONDITIONAL"
