"""Three derivations read at their sharpest point: the recall-scope selector's
four-part policy, the threshold ladder's step order, and the status filter on the
open-penalty aggregate.
"""

from test_helpers import (
    AirHandlingClass,
    AssayMethod,
    Decision,
    DocType,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    MarkTier,
    NcCategory,
    NcSeverity,
    RiskClass,
    SymptomSeverity,
    activate_testing_plan,
    add_supplier_document,
    create_ingredient,
    create_product,
    create_supplier,
    decide_corrective_action,
    file_complaint,
    link_ingredient,
    raise_nonconformance,
    read_applicant,
    read_audit,
    read_certificate,
    read_lot_test,
    read_nonconformance,
    read_product,
    record_lot_test,
    review_formula,
    review_ingredient,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    setup_issued_certificate,
    start_audit,
    submit_corrective_action,
    submit_ingredient,
    triage_complaint,
    verify_corrective_action,
)

CLOCK_START = "2026-08-01T00:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"
INELIGIBLE_DAY = "2026-08-16T00:00:00Z"
EDGE_DAY = "2026-08-17T00:00:00Z"
EXPOSURE_DAY = "2026-11-15T00:00:00Z"
COMPLAINT_DAY = "2026-11-16T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"

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


def _five_lots_and_a_severe_complaint(api):
    """One certified product at a 20 ppm threshold with five lots, then a SEVERE
    complaint whose exposure_date is 2026-11-15.

    The lots are laid out so that all four elements of the selector are in play at
    once: RSL-L1 is the only failing lot and is collected 91 days before exposure,
    RSL-L2 sits exactly on the 90-day edge, RSL-L5 is five days before exposure, and
    RSL-L3 and RSL-L4 share the exposure date itself with RSL-L3 recorded first.
    """
    context = setup_issued_certificate(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        onsite_start_at="2026-08-05T09:00:00Z",
        onsite_end_at="2026-08-05T17:00:00Z",
        audit_start_clock="2026-08-05T09:00:00Z",
        audit_close_clock="2026-08-05T17:00:00Z",
        issue_clock=ISSUE_DAY,
    )
    assert read_product(api, context.product_id)["threshold_ppm"] == 20
    assert context.certificate["total_fee_cents"] == 124800

    lots = {}
    set_clock(api, INELIGIBLE_DAY)
    lots["L1"] = record_lot_test(
        api,
        context.product_id,
        lot_code="RSL-L1",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=INELIGIBLE_DAY,
        ppm_result=25.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    set_clock(api, EDGE_DAY)
    lots["L2"] = record_lot_test(
        api,
        context.product_id,
        lot_code="RSL-L2",
        test_type=LotTestType.UNANNOUNCED,
        sample_collected_on=EDGE_DAY,
        ppm_result=6.0,
        lab_method=AssayMethod.G12_ELISA,
    )
    set_clock(api, EXPOSURE_DAY)
    for key, code, collected, ppm in (
        ("L5", "RSL-L5", "2026-11-10T00:00:00Z", 9.0),
        ("L3", "RSL-L3", EXPOSURE_DAY, 7.0),
        ("L4", "RSL-L4", EXPOSURE_DAY, 8.0),
    ):
        lots[key] = record_lot_test(
            api,
            context.product_id,
            lot_code=code,
            test_type=LotTestType.FOR_CAUSE,
            sample_collected_on=collected,
            ppm_result=ppm,
            lab_method=AssayMethod.G12_ELISA,
        )

    set_clock(api, COMPLAINT_DAY)
    complaint = file_complaint(
        api,
        context.certificate_id,
        exposure_date=EXPOSURE_DAY,
        symptom_severity=SymptomSeverity.SEVERE,
        lot_code="RSL-L3",
    )
    return context, lots, complaint


def test_triage_takes_the_top_three_candidates_in_selection_order(api):
    """The 91-day-old lot is out of the look-back and the 90-day-old one is eligible
    but ranks fourth, so the scope reads RSL-L3, RSL-L4, RSL-L5 in that order.

    PRD: "**Eligibility:** a lot test of the complaint's certified product is a
    candidate only if its `status` is `RECORDED` — a lot superseded by a retest is never
    a candidate — and its `sample_collected_on` falls inside the closed interval running
    from 90 days before `exposure_date` through `exposure_date` itself, so a lot
    collected exactly 90 days before exposure is eligible, one collected 91 days before
    is not, and one collected exactly on `exposure_date` is eligible."
    PRD: "**Take:** the first 3 candidates in that order are selected, and if fewer than
    3 candidates exist all of them are selected."

    Design: Corner/calculations/recall_scope_selector_ranks_takes_three_and_leaves_the_ineligible_fail_out
    """
    _context, lots, complaint = _five_lots_and_a_severe_complaint(api)

    assert complaint["status"] == "RECEIVED"
    assert complaint["triage_priority"] is None
    assert complaint["recall_action"] == "NONE"
    assert complaint["recall_scope_lot_codes"] == []

    triaged = triage_complaint(api, complaint["id"], reviewer_user_id="rev-2")
    assert triaged["id"] == complaint["id"]
    assert triaged["status"] == "INVESTIGATING"
    assert triaged["triage_priority"] == "P1"
    assert triaged["recall_scope_lot_codes"] == ["RSL-L3", "RSL-L4", "RSL-L5"]

    assert read_lot_test(api, lots["L3"]["id"])["in_recall_scope"] is True
    assert read_lot_test(api, lots["L4"]["id"])["in_recall_scope"] is True
    assert read_lot_test(api, lots["L5"]["id"])["in_recall_scope"] is True


def test_a_failing_lot_outside_the_selection_does_not_upgrade_the_action(api):
    """The only FAIL in the register is the ineligible lot, so the action settles on
    VOLUNTARY_RECALL and the certificate is left alone.

    PRD: "When at least one **selected** lot test has a `verdict` of `FAIL`,
    `recall_action` is `MANDATORY_RECALL_SUPPORT`. Otherwise `recall_action` is
    `VOLUNTARY_RECALL`. A failing lot that was eligible but ranked fourth or lower does
    not upgrade the action — only the selected three can."
    PRD: "The applicant's live penalty balance, `open_nc_penalty_points`, is the sum of
    the severity points of every nonconformance charged to that applicant whose `status`
    is `OPEN`, `CA_SUBMITTED`, `CA_REJECTED` or `ESCALATED`, with no time window at all."

    Design: Corner/calculations/recall_scope_selector_ranks_takes_three_and_leaves_the_ineligible_fail_out
    """
    context, lots, complaint = _five_lots_and_a_severe_complaint(api)

    triaged = triage_complaint(api, complaint["id"], reviewer_user_id="rev-2")
    assert triaged["recall_action"] == "VOLUNTARY_RECALL"

    assert lots["L1"]["verdict"] == "FAIL"
    assert read_lot_test(api, lots["L1"]["id"])["in_recall_scope"] is False
    assert read_lot_test(api, lots["L2"]["id"])["in_recall_scope"] is False

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "ISSUED"
    assert certificate["suspension_count"] == 0

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_cycle"] == 92
    assert applicant["compliance_posture"] == "GOOD_STANDING"
    assert applicant["substantiated_complaint_count_rolling"] == 0


def _an_elite_product_on_a_same_line_site_with_high_risk_grain(api):
    """An ELITE-tier product with one HIGH_RISK_GRAIN line at 60 pct inclusion, made on
    a SAME_LINE site with shared equipment present, formula CLEARED and no plan yet.

    All five ceilings are pushed away from the program's 20 at once — 5 from the tier, 10
    from the risk class, 10 from the shared equipment and 5 from the operations — and the
    COA claims exactly the 5 ppm cap so the document set verifies cleanly.
    """
    context = setup_applicant_with_facility(
        api,
        clock=CLOCK_START,
        facility_overrides={
            "site_name": "Plant 7",
            "air_handling_class": AirHandlingClass.OPEN_PLENUM,
            "shared_equipment_present": True,
            "gluten_containing_operations": GlutenContainingOperations.SAME_LINE,
        },
    )
    supplier = create_supplier(
        api, name="Prairie Mills", country_code="CA", gluten_handling_disclosed=True
    )
    ingredient = create_ingredient(
        api,
        context.applicant_id,
        supplier["id"],
        name="Purity Protocol Oats",
        risk_class=RiskClass.HIGH_RISK_GRAIN,
    )
    for doc_type in (DocType.ALLERGEN_STATEMENT, DocType.PROCESS_FLOW):
        add_supplier_document(
            api,
            context.applicant_id,
            supplier["id"],
            ingredient["id"],
            doc_type=doc_type,
            expires_on=DOC_EXPIRES,
        )
    add_supplier_document(
        api,
        context.applicant_id,
        supplier["id"],
        ingredient["id"],
        doc_type=DocType.COA,
        expires_on=DOC_EXPIRES,
        lab_ppm_claim=5,
    )
    submit_ingredient(api, context.applicant_id, ingredient["id"])
    approved = review_ingredient(api, ingredient["id"])
    assert approved["status"] == "APPROVED"

    product = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Elite Oat Granola",
        sku="EOG-001",
        requested_mark_tier=MarkTier.ELITE,
    )
    link_ingredient(api, context.applicant_id, product["id"], ingredient["id"], 60)
    cleared = review_formula(api, product["id"], decision=Decision.CLEAR)
    assert cleared["testing_plan_status"] == "NONE"
    return context, product, cleared


def test_the_floor_catches_the_penalised_minimum_at_five_ppm(api):
    """The five ceilings bottom out at 5, the co-location penalty takes the working
    value to 3, and the floor lifts the certified threshold back to 5.

    PRD: "Second, take the smallest of those five ceilings as a working value. Third,
    apply the co-location penalty **to that smallest value and to no individual
    ceiling**: when the facility's `gluten_containing_operations` is `SAME_LINE` and at
    least one formula line of the product references an ingredient whose `risk_class` is
    `HIGH_RISK_GRAIN`, subtract 2 ppm from the working value. Fourth, `threshold_ppm` is
    the larger of 5 ppm and the working value."
    PRD: "Activation computes `threshold_ppm`, then `sampling_lots_per_year` and
    `sampling_exclusion_days` from it, sets `testing_plan_status` to `ACTIVE`, increases
    `testing_plan_revision` by 1 — so the counter records how many plans this product has
    had, each superseding the last — and increases the product's `version` by 1."

    Design: Corner/calculations/threshold_penalty_is_subtracted_after_the_minimum_and_then_floored_at_five
    """
    _context, product, cleared = _an_elite_product_on_a_same_line_site_with_high_risk_grain(api)

    planned = activate_testing_plan(api, product["id"], cleared["version"])

    assert planned["id"] == product["id"]
    assert planned["threshold_ppm"] == 5
    assert planned["testing_plan_status"] == "ACTIVE"
    assert planned["testing_plan_revision"] == 1
    assert planned["formula_status"] == "CLEARED"
    assert planned["label_status"] == "NOT_SUBMITTED"


def test_the_tightest_threshold_selects_the_two_point_zero_multiplier(api):
    """A 5 ppm threshold buys the 2.0 multiplier, which on one HIGH_RISK_GRAIN line at
    60 pct gives 8 lots a year and a 45-day exclusion span.

    PRD: "One threshold multiplier is shared by every line and is read off the freshly
    computed `threshold_ppm`: 2.0 when the threshold is at most 5 ppm, 1.5 when it is
    above 5 ppm and at most 10 ppm, and 1.0 when it is above 10 ppm."
    PRD: "`sampling_exclusion_days` follows immediately: divide the 365 days of a year by
    `sampling_lots_per_year`, discard any fractional part, and take the larger of that
    quotient and 7 days."

    Design: Corner/calculations/threshold_penalty_is_subtracted_after_the_minimum_and_then_floored_at_five
    """
    _context, product, cleared = _an_elite_product_on_a_same_line_site_with_high_risk_grain(api)

    planned = activate_testing_plan(api, product["id"], cleared["version"])

    assert planned["sampling_lots_per_year"] == 8
    assert planned["sampling_exclusion_days"] == 45


NC_DAY = "2026-08-10T00:00:00Z"
CA_DUE = "2026-09-09T00:00:00Z"


def _a_major_finding_walked_to_ca_accepted(api):
    """One MAJOR SHARED_EQUIPMENT finding raised by aud-1 against an IN_PROGRESS audit
    at 2026-08-10, answered by the applicant and accepted by rev-1.

    The chain walks three different actors — aud-1 raises, rev-1 decides, aud-2 will
    verify — so no segregation rule is ever the reason a step is refused, and the
    applicant holds no certificate, which keeps the posture arithmetic to the finding.
    """
    context = setup_applicant_with_facility(api, clock=NC_DAY)
    audit = schedule_audit(
        api,
        context.facility_id,
        onsite_start_at=NC_DAY,
        onsite_end_at="2026-08-10T17:00:00Z",
    )
    start_audit(api, audit["id"])

    finding = raise_nonconformance(
        api,
        context.applicant_id,
        raiser_user_id="aud-1",
        category=NcCategory.SHARED_EQUIPMENT,
        severity=NcSeverity.MAJOR,
        description="Shared line changeover log incomplete",
        audit_id=audit["id"],
    )
    while_open = read_applicant(api, context.applicant_id)

    submitted = submit_corrective_action(
        api, context.applicant_id, finding["id"], finding["version"]
    )
    accepted = decide_corrective_action(
        api, finding["id"], decision=Decision.ACCEPT, reviewer_user_id="rev-1"
    )
    return context, audit, finding, while_open, submitted, accepted


def test_the_open_major_finding_charges_eight_points_and_a_thirty_day_deadline(api):
    """Creation fixes 8 penalty points and a corrective-action deadline 30 days out,
    and the applicant reads 92 while the record is open.

    PRD: "`penalty_points` is fixed at creation from `severity` — 2 for `MINOR`, 8 for
    `MAJOR`, 25 for `CRITICAL`. `ca_due_on`, the deadline for the applicant's
    corrective-action plan, is set to the record's `created_at` plus a severity-dependent
    window: 15 days for a `CRITICAL` finding, 30 days for a `MAJOR` one and 90 days for a
    `MINOR` one, because a critical exceedance cannot be left to drift for a quarter."
    PRD: "A successful submission records `ca_plan_text`, replacing any previous text on a
    resubmission, moves the record to `CA_SUBMITTED`, refreshes `updated_at` to the
    logical clock, increases `version` by 1, and recomputes the adjudicated score of the
    audit named by `audit_id` if there is one."

    Design: Corner/calculations/closed_nonconformance_drops_out_of_the_open_penalty_aggregate
    """
    _context, _audit, finding, while_open, submitted, accepted = _a_major_finding_walked_to_ca_accepted(api)

    assert finding["penalty_points"] == 8
    assert finding["ca_due_on"] == CA_DUE
    assert finding["version"] == 1
    assert submitted["status"] == "CA_SUBMITTED"
    assert submitted["version"] == 2
    assert accepted["status"] == "CA_ACCEPTED"

    assert while_open["open_nc_penalty_points"] == 8
    assert while_open["posture_score_cycle"] == 92


def test_verified_effectiveness_closes_the_finding_and_clears_both_windows(api):
    """The record keeps its 8 points forever but contributes nothing once CLOSED, so
    both posture scores return to exactly 100.

    PRD: "When it is true the record moves `CA_ACCEPTED → CLOSED`, sets `ca_verified` to
    true and `closed_on` to the logical clock, drops out of the applicant's penalty
    balance and triggers a posture recompute, and causes the audit named by `audit_id` to
    recompute `final_score` so that this finding's deduction is halved rather than
    removed."
    PRD: "Findings whose `status` is `CA_ACCEPTED` or `CLOSED` contribute nothing."

    Design: Corner/calculations/closed_nonconformance_drops_out_of_the_open_penalty_aggregate
    """
    context, audit, finding, _while_open, _submitted, _accepted = _a_major_finding_walked_to_ca_accepted(api)

    closed = verify_corrective_action(
        api, finding["id"], effectiveness_confirmed=True, auditor_user_id="aud-2"
    )
    assert closed["id"] == finding["id"]
    assert closed["status"] == "CLOSED"
    assert closed["ca_verified"] is True
    assert closed["closed_on"] == NC_DAY
    assert closed["penalty_points"] == 8
    assert closed["ca_revision_count"] == 0

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 0
    assert applicant["posture_score_rolling_12m"] == 100
    assert applicant["posture_score_cycle"] == 100
    assert applicant["compliance_posture"] == "GOOD_STANDING"

    row = read_audit(api, audit["id"])
    assert row["finding_count"] == 1
    assert row["critical_finding_count"] == 0
    assert read_nonconformance(api, finding["id"])["status"] == "CLOSED"
