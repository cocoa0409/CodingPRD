"""Gates on the post-certification side: the mandatory notice period that only two
change types carry, the terminality of an assessment, and the triage step an
investigation outcome may not skip.
"""

from test_helpers import (
    ApiErrorId,
    ChangeType,
    ComplaintOutcome,
    Decision,
    GlutenContainingOperations,
    ImpactLevel,
    IngredientSpec,
    OutcomeEvidence,
    RiskClass,
    SymptomSeverity,
    assess_change_notification,
    file_change_notification,
    file_complaint,
    make_admin_headers,
    make_applicant_contact_headers,
    make_reviewer_headers,
    read_applicant,
    read_certificate,
    read_change_notification,
    read_complaint,
    read_product,
    set_clock,
    setup_issued_certificate,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
AUDIT_OPENS = "2026-08-05T09:00:00Z"
AUDIT_CLOSES = "2026-08-05T17:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"
TWENTY_NINE_DAYS_OUT = "2026-09-04T00:00:00Z"
THIRTY_DAYS_OUT = "2026-09-05T00:00:00Z"
COMPLAINT_DAY = "2026-08-20T00:00:00Z"
EXPOSURE_DAY = "2026-08-18T00:00:00Z"

CLEAN_SITE = {
    "site_name": "Plant 9",
    "shared_equipment_present": False,
    "gluten_containing_operations": GlutenContainingOperations.NONE,
}
ONE_CLEAN_LINE = (
    IngredientSpec(
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=55,
        doc_expires_on=DOC_EXPIRES,
    ),
)


def _a_certified_product(api, *, issue_clock=ISSUE_DAY):
    """One STANDARD product certified on a site with no shared equipment and no gluten
    operations, so its certified threshold is the program's own 20 ppm.

    Nothing has gone wrong on this file, which keeps the applicant in
    `GOOD_STANDING` and leaves the notice-period and state gates as the only
    things that can refuse a later write.
    """
    context = setup_issued_certificate(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
        audit_start_clock=AUDIT_OPENS,
        audit_close_clock=AUDIT_CLOSES,
        issue_clock=issue_clock,
    )
    assert context.certificate["status"] == "ISSUED"
    return context


def test_the_exempt_change_type_records_lateness_while_the_bar_refuses_it(api):
    """A FORMULA_PCT_CHANGE 29 days out is accepted and merely flagged late, while an
    INGREDIENT_SUBSTITUTION on the identical date is refused and never becomes a row.

    PRD: "**Change notice long enough.** For change types `INGREDIENT_SUBSTITUTION` and
    `SUPPLIER_CHANGE`, `effective_on` is at least 30 days after the logical clock; a notice
    exactly 30 days ahead is accepted and 29 days ahead is not. A breach is
    `ERR_LATE_CHANGE_NOTIFICATION` (422). `FORMULA_PCT_CHANGE` and `FACILITY_LINE_CHANGE`
    are exempt from this rejection and only raise the lateness flag."
    PRD: "Filing computes `notified_days_before_effective` as the number of whole days from
    the logical clock to `effective_on`, discarding any fractional day, and the value may be
    negative when the notice is retroactive. `late_notification` is true exactly when
    `notified_days_before_effective` is below 30."

    Design: Corner/validations/change_notification_twenty_nine_days_ahead_is_rejected_as_late
    """
    context = _a_certified_product(api)

    exempt = file_change_notification(
        api,
        context.applicant_id,
        context.certificate_id,
        change_type=ChangeType.FORMULA_PCT_CHANGE,
        effective_on=TWENTY_NINE_DAYS_OUT,
        description="Rice flour share trimmed by two points",
    )
    assert exempt["notified_days_before_effective"] == 29
    assert exempt["late_notification"] is True
    assert exempt["status"] == "SUBMITTED"

    response = api.create_change_notification(
        make_applicant_contact_headers(context.applicant_id),
        certificate_id=context.certificate_id,
        change_type=ChangeType.INGREDIENT_SUBSTITUTION,
        effective_on=TWENTY_NINE_DAYS_OUT,
        description="Swap rice flour to a second mill",
    )
    validate_error(response, ApiErrorId.LATE_CHANGE_NOTIFICATION, 422)

    rows, meta = validate_paginated(
        api.list_change_notifications(
            make_admin_headers(), certificate_id=context.certificate_id
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == exempt["id"]

    assert read_certificate(api, context.certificate_id)["status"] == "ISSUED"
    assert read_applicant(api, context.applicant_id)["compliance_posture"] == "GOOD_STANDING"


def test_a_second_assessment_cannot_add_conditions_to_a_settled_notification(api):
    """The notification was assessed ACCEPT with no impact, so a later ACCEPT at LOW
    impact is refused and none of the LOW branch's side effects run.

    PRD: "**Change-notification state.** Assessment requires `SUBMITTED` — otherwise
    `ERR_INVALID_CHANGE_NOTIFICATION_STATE` (409)."
    PRD: "An `ACCEPT` with an `impact_level` of `LOW` moves it to
    `ACCEPTED_WITH_CONDITIONS`, sets `required_retest` to true — obliging a `FOR_CAUSE` lot
    test before the effective date — and makes the certificate's product recompute
    `threshold_ppm`, `sampling_lots_per_year` and `sampling_exclusion_days` from its current
    ingredient set, using exactly the arithmetic of §3.6."

    Design: Corner/validations/assessing_an_already_assessed_change_notification_is_rejected
    """
    context = _a_certified_product(api)
    before = read_product(api, context.product_id)
    assert before["threshold_ppm"] == 20

    notification = file_change_notification(
        api,
        context.applicant_id,
        context.certificate_id,
        change_type=ChangeType.SUPPLIER_CHANGE,
        effective_on=THIRTY_DAYS_OUT,
        description="Second mill added as an alternate source",
    )
    assert notification["notified_days_before_effective"] == 30
    assert notification["late_notification"] is False

    assessed = assess_change_notification(
        api,
        notification["id"],
        decision=Decision.ACCEPT,
        impact_level=ImpactLevel.NONE,
        reviewer_user_id="rev-2",
    )
    assert assessed["status"] == "ACCEPTED_NO_IMPACT"
    assert assessed["required_retest"] is False
    assert assessed["assessed_by_user_id"] == "rev-2"

    response = api.assess_change_notification(
        notification["id"],
        make_reviewer_headers("rev-3"),
        decision=Decision.ACCEPT,
        impact_level=ImpactLevel.LOW,
    )
    validate_error(response, ApiErrorId.INVALID_CHANGE_NOTIFICATION_STATE, 409)

    row = read_change_notification(api, notification["id"])
    assert row["status"] == "ACCEPTED_NO_IMPACT"
    assert row["impact_level"] == ImpactLevel.NONE
    assert row["required_retest"] is False
    assert row["assessed_by_user_id"] == "rev-2"

    after = read_product(api, context.product_id)
    assert after["threshold_ppm"] == before["threshold_ppm"]
    assert after["sampling_lots_per_year"] == before["sampling_lots_per_year"]
    assert read_certificate(api, context.certificate_id)["status"] == "ISSUED"


def test_an_outcome_filed_before_triage_writes_nothing_at_all(api):
    """The outcome branch reads the recall action that only triage computes, so an
    outcome filed from RECEIVED is refused and leaves no investigator, no finding and no
    suspension behind.

    PRD: "**Complaint state.** Triage requires `RECEIVED` and recording an investigation
    outcome requires `INVESTIGATING` — otherwise `ERR_INVALID_COMPLAINT_STATE` (409)."
    PRD: "A filed complaint opens with `status` of `RECEIVED`, `reported_on` set to the
    logical clock, `triage_priority` null, `recall_action` of `NONE`,
    `recall_scope_lot_codes` as an empty list, and `investigated_by_user_id`,
    `outcome_evidence` and `closed_on` null."

    Design: Corner/validations/recording_an_investigation_outcome_before_triage_is_rejected
    """
    context = _a_certified_product(api)

    set_clock(api, COMPLAINT_DAY)
    complaint = file_complaint(
        api,
        context.certificate_id,
        exposure_date=EXPOSURE_DAY,
        symptom_severity=SymptomSeverity.SEVERE,
        lot_code="RSL-L1",
    )
    assert complaint["status"] == "RECEIVED"
    assert complaint["triage_priority"] is None
    assert complaint["recall_action"] == "NONE"

    response = api.record_investigation_outcome(
        complaint["id"],
        make_reviewer_headers("rev-2"),
        outcome=ComplaintOutcome.SUBSTANTIATED,
        outcome_evidence=OutcomeEvidence.CROSS_CONTACT,
    )
    validate_error(response, ApiErrorId.INVALID_COMPLAINT_STATE, 409)

    row = read_complaint(api, complaint["id"])
    assert row["status"] == "RECEIVED"
    assert row["investigated_by_user_id"] is None
    assert row["outcome_evidence"] is None
    assert row["recall_scope_lot_codes"] == []

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "ISSUED"
    assert certificate["suspension_count"] == 0

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["substantiated_complaint_count_cycle"] == 0
    assert applicant["compliance_posture"] == "GOOD_STANDING"

    _rows, meta = validate_paginated(
        api.list_nonconformances(make_admin_headers(), complaint_id=complaint["id"])
    )
    assert meta["total_count"] == 0
