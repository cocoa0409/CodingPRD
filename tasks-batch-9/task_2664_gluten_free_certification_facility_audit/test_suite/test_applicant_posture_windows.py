"""The applicant's two posture figures: the published rolling-12-month score and
the certification-cycle score that is the one the issuance gate reads.
"""

from test_helpers import (
    IngredientSpec,
    NcCategory,
    NcSeverity,
    NcSourceType,
    NcStatus,
    decide_corrective_action,
    make_admin_headers,
    file_complaint,
    raise_nonconformance,
    read_applicant,
    read_certificate,
    read_complaint,
    read_nonconformance,
    run_sweep,
    set_clock,
    setup_issued_certificate,
    submit_corrective_action,
    triage_complaint,
    record_investigation_outcome,
    validate_paginated,
    verify_corrective_action,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
INCIDENT_DAY = "2026-09-05T00:00:00Z"
OBSERVATION_DAY = "2027-10-01T00:00:00Z"


def _cycle_with_a_forgotten_incident(api):
    """The canonical certified product, then one substantiated MILD complaint and
    one open MAJOR audit finding both dated 2026-09-05, observed from 2027-10-01.

    By the observation instant the rolling 12-month window has moved past both,
    while the certification cycle that opened at issuance still contains them.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(IngredientSpec(doc_expires_on="2028-07-01T00:00:00Z"),),
        issue_clock=ISSUE_DAY,
    )

    set_clock(api, INCIDENT_DAY)
    complaint = file_complaint(
        api,
        context.certificate_id,
        exposure_date="2026-09-01T00:00:00Z",
        symptom_severity="MILD",
    )
    triage_complaint(api, complaint["id"])
    record_investigation_outcome(
        api, complaint["id"], outcome="SUBSTANTIATED", outcome_evidence="CROSS_CONTACT"
    )

    rows, _meta = validate_paginated(
        api.list_nonconformances(make_admin_headers(), complaint_id=complaint["id"])
    )
    assert len(rows) == 1, "a substantiated complaint raises exactly one finding"
    complaint_finding = rows[0]

    # Carry the complaint's finding all the way to CLOSED so it charges nothing.
    submit_corrective_action(
        api,
        context.applicant_id,
        complaint_finding["id"],
        complaint_finding["version"],
        plan_text="Segregate the packaging line and retrain on allergen changeover.",
    )
    decide_corrective_action(api, complaint_finding["id"], reviewer_user_id="rev-2")
    verify_corrective_action(api, complaint_finding["id"], auditor_user_id="aud-1")

    open_finding = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.AUDIT,
        audit_id=context.audit_id,
        category=NcCategory.SANITATION,
        severity=NcSeverity.MAJOR,
        description="Post-sanitation swab records not retained for two shifts.",
    )

    set_clock(api, OBSERVATION_DAY)
    return context, complaint, open_finding


def test_rolling_score_forgets_what_the_cycle_score_still_counts(api):
    """At 2027-10-01 the published rolling figure reads a perfect 100 while the
    cycle figure reads 77, and the band follows the cycle figure to WATCH.

    PRD: "The cycle figure, `posture_score_cycle`, applies identical arithmetic
    over the window running from `current_cycle_started_on` up to the logical
    clock — or from the applicant's own `created_at` up to the logical clock when
    `current_cycle_started_on` is null — and takes its complaint term from
    `substantiated_complaint_count_cycle` instead."
    PRD: "**The gate reads only the cycle score.**"

    Design: Difficulty/dual_variant_calc/applicant_posture_rolling_window_vs_certification_cycle_window
    """
    context, _complaint, _open_finding = _cycle_with_a_forgotten_incident(api)

    run_sweep(api)

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["posture_score_rolling_12m"] == 100
    assert applicant["posture_score_cycle"] == 77
    assert applicant["compliance_posture"] == "WATCH"
    assert applicant["current_cycle_started_on"] == ISSUE_DAY


def test_the_two_windows_disagree_on_both_the_finding_and_the_complaint_term(api):
    """The same sweep leaves the rolling complaint counter at 0 and the cycle
    counter at 1, and the escalated finding keeps charging its 8 points.

    PRD: "`substantiated_complaint_count_cycle` counts exactly the same population
    over the window from `current_cycle_started_on` to the logical clock, and is 0
    whenever `current_cycle_started_on` is null."
    PRD: "A record can also escalate without any reviewer involvement at all: when
    a surveillance sweep finds a nonconformance still `OPEN` whose `ca_due_on` has
    passed, it moves `OPEN → ESCALATED` with precisely the same set of
    consequences."

    Design: Difficulty/dual_variant_calc/applicant_posture_rolling_window_vs_certification_cycle_window
    """
    context, complaint, open_finding = _cycle_with_a_forgotten_incident(api)

    run_sweep(api)

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["substantiated_complaint_count_rolling"] == 0
    assert applicant["substantiated_complaint_count_cycle"] == 1
    assert applicant["open_nc_penalty_points"] == 8

    assert read_nonconformance(api, open_finding["id"])["status"] == NcStatus.ESCALATED
    # The complaint closed when its own finding was verified as effective.
    assert read_complaint(api, complaint["id"])["status"] == "CLOSED"

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "ISSUED"
    assert certificate["surveillance_status"] == "DUE"
