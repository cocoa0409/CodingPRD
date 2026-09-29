"""Two strict-greater-than edges riding on the same decimal ppm result against an
integer threshold of 10: the PASS/FAIL edge and the MAJOR/CRITICAL edge.
"""

from test_helpers import (
    IngredientSpec,
    advance_and_sweep,
    LotTestType,
    RiskClass,
    make_admin_headers,
    make_lab_technician_headers,
    read_applicant,
    read_certificate,
    read_lot_test,
    read_product,
    record_lot_test,
    run_sweep,
    set_clock,
    setup_issued_certificate,
    validate_paginated,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
SAMPLE_DAY = "2026-08-12T00:00:00Z"

SOLE_LINE = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=40,
    doc_issued_on="2026-07-01T00:00:00Z",
    doc_expires_on="2028-07-01T00:00:00Z",
)


def _finding_for_lot(api, lot_test_id):
    rows, _meta = validate_paginated(
        api.list_nonconformances(make_admin_headers(), lot_test_id=lot_test_id)
    )
    assert len(rows) == 1, f"expected one finding for lot {lot_test_id}"
    return rows[0]


def _three_lots_around_both_edges(api):
    """A certified product with a 10 ppm threshold and three lots sampled on the same
    day: 10.0 SCHEDULED, 10.1 UNANNOUNCED and 20.0 FOR_CAUSE.

    Every sample is collected on the clock's own day, and only the first lot is
    SCHEDULED, so neither the future-sample rule nor the exclusion interval is in
    play and the verdict edges are observed in isolation.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
        issue_clock=ISSUE_DAY,
    )
    assert read_product(api, context.product_id)["threshold_ppm"] == 10

    set_clock(api, SAMPLE_DAY)
    at_threshold = record_lot_test(
        api,
        context.product_id,
        lot_code="L-1001",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=10.0,
    )
    just_over = record_lot_test(
        api,
        context.product_id,
        lot_code="L-1002",
        test_type=LotTestType.UNANNOUNCED,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=10.1,
    )
    at_double = record_lot_test(
        api,
        context.product_id,
        lot_code="L-1003",
        test_type=LotTestType.FOR_CAUSE,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=20.0,
    )
    return context, at_threshold, just_over, at_double


def test_a_result_exactly_at_the_threshold_passes_and_a_tenth_above_it_fails(api):
    """10.0 against a snapshot of 10 is a PASS that raises nothing, while 10.1 is a
    FAIL whose finding is MAJOR.

    PRD: "`verdict` is `FAIL` when `ppm_result` is strictly greater than
    `threshold_applied_ppm` and `PASS` otherwise, so a result exactly equal to the
    threshold passes."
    PRD: "Every recorded lot snapshots `threshold_applied_ppm` from the product's
    `threshold_ppm` at record time, and that snapshot — not the product's later value
    — is the bound the verdict is judged against."

    Design: Difficulty/boundary_precision_check/lot_verdict_and_critical_severity_strict_greater_than_boundaries
    """
    _context, at_threshold, just_over, _at_double = _three_lots_around_both_edges(api)

    assert at_threshold["threshold_applied_ppm"] == 10
    assert at_threshold["verdict"] == "PASS"
    assert at_threshold["nonconformance_created"] is False

    assert just_over["threshold_applied_ppm"] == 10
    assert just_over["verdict"] == "FAIL"
    assert just_over["nonconformance_created"] is True
    assert _finding_for_lot(api, just_over["id"])["severity"] == "MAJOR"


def test_exactly_twice_the_threshold_is_major_and_a_tenth_beyond_it_is_critical(api):
    """20.0 is still MAJOR because the critical edge is strict; the 20.1 lot recorded
    on top of it answers 201 with a CRITICAL finding.

    PRD: "a nonconformance is created with `source_type` of `LOT_TEST`, `category` of
    `THRESHOLD_EXCEEDANCE`, and a `severity` of `CRITICAL` when `ppm_result` is
    strictly more than twice `threshold_applied_ppm` and `MAJOR` otherwise — exactly
    twice the threshold is `MAJOR`, not `CRITICAL`."
    PRD: "A new lot's `status` is `RECORDED`, `nonconformance_created` is false and
    `in_recall_scope` is false."

    Design: Difficulty/boundary_precision_check/lot_verdict_and_critical_severity_strict_greater_than_boundaries
    """
    context, _at_threshold, _just_over, at_double = _three_lots_around_both_edges(api)

    assert at_double["verdict"] == "FAIL"
    assert _finding_for_lot(api, at_double["id"])["severity"] == "MAJOR"

    response = api.create_lot_test(
        make_lab_technician_headers(),
        product_id=context.product_id,
        lot_code="L-1004",
        test_type=LotTestType.FOR_CAUSE,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=20.1,
        lab_method="R5_ELISA",
    )
    assert response.status_code == 201, response.text
    beyond_double = response.json()["data"]

    assert beyond_double["verdict"] == "FAIL"
    assert beyond_double["threshold_applied_ppm"] == 10
    assert beyond_double["nonconformance_created"] is True
    assert beyond_double["status"] == "RECORDED"
    assert _finding_for_lot(api, beyond_double["id"])["severity"] == "CRITICAL"


def test_only_the_unannounced_failure_suspends_and_it_suspends_once(api):
    """Two later FOR_CAUSE failures do not add a second suspension, and the passing
    SCHEDULED lot is the one that dates the product's sampling record.

    PRD: "A failing `SCHEDULED` or `FOR_CAUSE` lot does **not** suspend on its own
    account; if it suspends anything it does so indirectly, through the
    critical-nonconformance cascade of §3.8."
    PRD: "Recording a `SCHEDULED` lot also refreshes the product's
    `last_scheduled_sample_on`, which is the greatest `sample_collected_on` among
    that product's `SCHEDULED` lots whose `status` is `RECORDED`."

    Design: Difficulty/boundary_precision_check/lot_verdict_and_critical_severity_strict_greater_than_boundaries
    """
    context, at_threshold, _just_over, _at_double = _three_lots_around_both_edges(api)

    record_lot_test(
        api,
        context.product_id,
        lot_code="L-1004",
        test_type=LotTestType.FOR_CAUSE,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=20.1,
    )

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_reason"] == "FAILED_UNANNOUNCED_TEST"
    assert certificate["suspension_count"] == 1

    product = read_product(api, context.product_id)
    assert product["label_status"] == "FROZEN"
    assert product["last_scheduled_sample_on"] == SAMPLE_DAY
    assert read_lot_test(api, at_threshold["id"])["verdict"] == "PASS"


def test_the_three_failing_lots_sum_to_forty_one_points_and_force_probation(api):
    """8 plus 8 plus 25 open points and the 5 for the suspended certificate leave the
    cycle score at 54, which is below the WATCH floor.

    PRD: "Start from 100 and subtract three terms: first, the sum of `penalty_points`
    over this applicant's nonconformances whose `status` is `OPEN`, `CA_SUBMITTED`,
    `CA_REJECTED` or `ESCALATED` **and** whose `created_at` falls inside the window
    running from 365 days before the logical clock up to the logical clock; second, 5
    points for each certificate counted in `suspended_certificate_count`; third, 15
    points for each complaint counted in `substantiated_complaint_count_rolling`."
    PRD: "`compliance_posture` is banded from `posture_score_cycle`: a score of at
    least 85 is `GOOD_STANDING`, a score from 60 up to but not including 85 is
    `WATCH`, and a score below 60 is `PROBATION`."

    Design: Difficulty/boundary_precision_check/lot_verdict_and_critical_severity_strict_greater_than_boundaries
    """
    context, _at_threshold, _just_over, _at_double = _three_lots_around_both_edges(api)

    record_lot_test(
        api,
        context.product_id,
        lot_code="L-1004",
        test_type=LotTestType.FOR_CAUSE,
        sample_collected_on=SAMPLE_DAY,
        ppm_result=20.1,
    )

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 41
    assert applicant["posture_score_cycle"] == 54
    assert applicant["compliance_posture"] == "PROBATION"


def _certificate_swept_to_each_surveillance_edge(api):
    """One certificate issued 2026-08-11 and swept at four instants: the day before
    it falls due, the exact due day, the last day of grace, and the day grace ends.

    No SURVEILLANCE audit is ever closed, so `surveillance_due_on` is never rebased
    and all four readings come from the same 2027-08-11 anchor.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
        issue_clock=ISSUE_DAY,
    )
    readings = {}
    for label, instant in (
        ("day_364", "2027-08-10T00:00:00Z"),
        ("day_365", "2027-08-11T00:00:00Z"),
        ("grace_last", "2027-10-09T00:00:00Z"),
    ):
        advance_and_sweep(api, instant)
        certificate = read_certificate(api, context.certificate_id)
        readings[label] = certificate
    set_clock(api, "2027-10-10T00:00:00Z")
    return context, readings


def test_the_due_edge_is_inclusive_and_the_grace_edge_is_exclusive(api):
    """The day before the anniversary still reads CURRENT, the anniversary itself
    already reads DUE, and the 59th day of grace is still DUE on an ISSUED row.

    PRD: "A certificate that was never observed during its `DUE` window jumps
    `CURRENT → OVERDUE` directly, with identical consequences; the window edges are
    inclusive on the left and exclusive on the right, so a certificate whose
    `surveillance_due_on` equals the clock exactly is already `DUE` rather than
    `CURRENT`."
    PRD: "Once the clock has reached `surveillance_due_on` but is still short of 60
    days past it, the certificate reads `DUE`, which is the program's signal that a
    `SURVEILLANCE` audit is now expected; reaching `DUE` changes nothing else."

    Design: Difficulty/boundary_precision_check/surveillance_due_and_grace_edges_on_exact_day_boundaries
    """
    _context, readings = _certificate_swept_to_each_surveillance_edge(api)

    assert readings["day_364"]["surveillance_due_on"] == "2027-08-11T00:00:00Z"
    assert readings["day_364"]["expires_on"] == "2029-08-10T00:00:00Z"
    assert readings["day_364"]["surveillance_status"] == "CURRENT"
    assert readings["day_365"]["surveillance_status"] == "DUE"
    assert readings["grace_last"]["surveillance_status"] == "DUE"
    assert readings["grace_last"]["status"] == "ISSUED"


def test_the_sweep_on_the_sixtieth_day_reports_one_overdue_and_one_suspension(api):
    """Exactly 60 days past the due date the sweep flips the certificate to OVERDUE
    and suspends it, while nothing has yet reached its expiry.

    PRD: "In one run it re-derives `surveillance_status` for every certificate whose
    `status` is `ISSUED` or `SUSPENDED` and suspends the newly `OVERDUE` `ISSUED`
    ones with `suspension_reason` of `SURVEILLANCE_OVERDUE`; moves every certificate
    whose `expires_on` has been reached to `EXPIRED`; moves every `VERIFIED` supplier
    document whose `expires_on` has been reached to `EXPIRED` and blocks every
    `APPROVED` ingredient whose required document set is thereby incomplete with
    `blocked_reason` of `DOCUMENT_EXPIRED`, cascading onward to products and
    certificates; moves every `VALIDATED` facility whose `sanitation_expires_on` has
    been reached to `EXPIRED`; cancels every `SCHEDULED` audit whose `onsite_end_at`
    has been reached; escalates every `OPEN` nonconformance whose `ca_due_on` has
    passed; and recomputes `open_nc_penalty_points`,
    `active_certified_product_count`, `suspended_certificate_count`, both posture
    scores and `compliance_posture` for every applicant."
    PRD: "The sweep answers with a summary of what it did: `run_at` carrying the
    logical instant of the run, and the counts `certificates_marked_due`,
    `certificates_marked_overdue`, `certificates_suspended`, `certificates_expired`,
    `documents_expired`, `ingredients_blocked`, `facility_validations_expired`,
    `audits_cancelled` and `nonconformances_escalated`."

    Design: Difficulty/boundary_precision_check/surveillance_due_and_grace_edges_on_exact_day_boundaries
    """
    _context, _readings = _certificate_swept_to_each_surveillance_edge(api)

    response = api.run_surveillance(make_admin_headers())
    assert response.status_code == 201, response.text
    summary = response.json()["data"]

    assert summary["run_at"] == "2027-10-10T00:00:00Z"
    assert summary["certificates_marked_overdue"] == 1
    assert summary["certificates_suspended"] == 1
    assert summary["certificates_expired"] == 0


def test_the_overdue_suspension_locks_the_mark_and_costs_five_posture_points(api):
    """The suspension carries SURVEILLANCE_OVERDUE, freezes the label and drops the
    applicant to one suspended certificate at a still-GOOD_STANDING 95.

    PRD: "Once the clock reaches 60 days past `surveillance_due_on` — exactly 60 days
    past is already `OVERDUE`, not `DUE` — the certificate reads `OVERDUE`, and that
    is not merely a label: if its `status` is `ISSUED` it is thereupon moved `ISSUED →
    SUSPENDED` with `suspension_reason` of `SURVEILLANCE_OVERDUE`, freezing the
    product's `label_status` to `FROZEN` and forcing an applicant posture recompute."

    Design: Difficulty/boundary_precision_check/surveillance_due_and_grace_edges_on_exact_day_boundaries
    """
    context, _readings = _certificate_swept_to_each_surveillance_edge(api)

    run_sweep(api)

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["surveillance_status"] == "OVERDUE"
    assert certificate["status"] == "SUSPENDED"
    assert certificate["suspension_reason"] == "SURVEILLANCE_OVERDUE"
    assert certificate["suspension_count"] == 1
    assert certificate["mark_usage_locked"] is True

    assert read_product(api, context.product_id)["label_status"] == "FROZEN"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 1
    assert applicant["posture_score_cycle"] == 95
    assert applicant["compliance_posture"] == "GOOD_STANDING"
