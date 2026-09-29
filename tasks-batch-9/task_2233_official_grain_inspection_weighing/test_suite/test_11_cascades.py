"""Transitive cascades that reach across determinations, certificates, the
applicant ledger and inspector standing."""

from test_helpers import (
    ADMIN,
    CORN_NO_1_FACTORS_MOISTURE_12_8,
    CORN_NO_2_FACTORS,
    CORN_NO_3_FACTORS,
    INSPECTOR,
    ApiErrorId,
    api_client,
    assert_ledger,
    assert_performance_score,
    assert_portion_accounting,
    assert_vote_tally,
    assign_appeal_sample,
    cast_vote,
    create_active_inspector,
    create_active_schedule,
    create_applicant_account,
    create_certified_instrument,
    create_certified_sampling_device,
    create_designated_area,
    create_inspector_row,
    create_request,
    decide,
    draw_sample,
    file_appeal,
    file_check,
    issue_certificate,
    protein_analysis_payload,
    read_analysis,
    read_applicant,
    read_certificate,
    read_equipment,
    read_grading,
    read_inspector,
    read_request,
    read_sample,
    record_analysis,
    record_grading,
    set_clock,
    validate_error,
    BUSINESS_HOURS_CLOCK,
)


# --------------------------------------------------------------------------- #
# An office whose grading determination is about to be overturned on appeal
# --------------------------------------------------------------------------- #

def _appeal_cascade_office():
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area(fee_multiplier_bp=11500)
    create_active_schedule(
        area["id"],
        "GRADING",
        base_fee_cents=12000,
        per_thousand_bushel_rate_cents=3000,
        overtime_multiplier_bp=2500,
        minimum_fee_cents=15000,
    )
    create_active_schedule(area["id"], "APPEAL", base_fee_cents=25000)
    applicant = create_applicant_account()
    grader = create_active_inspector(area["id"], "L-4001", hours=40)
    panel = [
        create_active_inspector(area["id"], f"L-400{n}", hours=24) for n in range(2, 6)
    ]
    probe = create_certified_sampling_device(area["id"], "PROBE-G1")
    instrument = create_certified_instrument(area["id"], "NIR-G1")

    # Two proficiency deviations already counted against the original grader.
    file_check(instrument["id"], grader["id"], 35.00, 35.30)
    file_check(instrument["id"], grader["id"], 35.00, 35.30)

    return {
        "area": area,
        "applicant": applicant,
        "grader": grader,
        "regrader": panel[0],
        "voters": panel[1:],
        "probe": probe,
        "instrument": instrument,
    }


def _appeal_under_review(office):
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        commodity="CORN",
        lot_identifier="LOT-APPEAL",
        declared_quantity_bushels=3609.27,
        requested_services=["GRADING"],
    )
    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        office["grader"]["id"],
        portions_count=4,
        seal_number="SEAL-AP1",
    )
    grading = record_grading(
        request["id"], sample["id"], office["grader"]["id"], factors=CORN_NO_2_FACTORS
    )
    certificate = issue_certificate(request["id"], office["grader"]["id"], "GRADE")
    certificate = read_certificate(certificate["id"])
    appeal = file_appeal(
        certificate["id"], office["applicant"]["id"], certificate["version"], "APPEAL"
    )
    assign_appeal_sample(appeal["id"], sample["id"])
    regrade = record_grading(
        request["id"],
        sample["id"],
        office["regrader"]["id"],
        factors=CORN_NO_3_FACTORS,
        appeal_id=appeal["id"],
    )
    for inspector, vote in zip(office["voters"], ("REVISE", "REVISE", "UPHOLD")):
        cast_vote(appeal["id"], inspector["id"], vote)
    return {
        "request": request,
        "sample": sample,
        "grading": grading,
        "certificate": certificate,
        "appeal": appeal,
        "regrade": regrade,
    }


def test_appeal_revision_supersedes_the_grading_and_reissues_a_fee_free_certificate():
    """The outcome is `DECIDED_REVISED` when twice the `revise_votes_count`
    strictly exceeds `effective_votes_count` **and** the regrade's
    `assigned_grade` differs from the challenged certificate's
    `grade_snapshot`; in every other case the outcome is `DECIDED_UPHELD`.

    On `DECIDED_REVISED`: `refund_cents` is set to the full `deposit_cents` and
    credited to the applicant's `credits_total_cents`; the regrade becomes the
    `FINAL` determination while the previous `FINAL` becomes `SUPERSEDED` and
    is named by the new determination's `supersedes_grading_result_id`; the
    challenged certificate moves `UNDER_APPEAL → VOIDED` with
    `fee_settlement_status` `REVERSED` and its whole `fee_total_cents`
    credited; a fee-free `APPEAL_GRADE` certificate is issued in its place,
    carrying `superseded_certificate_id` pointing at the voided row,
    `appeal_id` naming the appeal, and a `fee_total_cents` of 0; the request's
    `grade_revision_count` increases by one; the inspector who produced the
    overturned determination has their `appeal_reversal_count` increased by one
    and their `performance_score` recomputed, which may auto-suspend them; and
    the retained sample portion is released as `portions_retained` decreases by
    one.

    Design: Difficulty/transitive_cascade/appeal_revision_cascades_certificate_void_regrade_ledger_and_inspector_suspension
    """
    office = _appeal_cascade_office()
    staged = _appeal_under_review(office)

    decided = decide(staged["appeal"]["id"])

    assert decided["status"] == "DECIDED_REVISED"
    assert decided["effective_votes_count"] == 3
    assert decided["revise_votes_count"] == 2
    assert decided["uphold_votes_count"] == 1
    assert decided["outcome_grade"] == "US_NO_3"
    assert decided["refund_cents"] == 25000
    assert_vote_tally(decided)

    voided = read_certificate(staged["certificate"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["fee_settlement_status"] == "REVERSED"
    assert voided["fee_total_cents"] == 27600

    listed = api_client.list_request_certificates(staged["request"]["id"], ADMIN)
    replacements = [
        row
        for row in listed.json()["data"]
        if row["certificate_type"] == "APPEAL_GRADE"
    ]
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["fee_total_cents"] == 0
    assert replacement["grade_snapshot"] == "US_NO_3"
    assert replacement["limiting_factor_snapshot"] == "TEST_WEIGHT"
    assert replacement["superseded_certificate_id"] == staged["certificate"]["id"]
    assert replacement["appeal_id"] == staged["appeal"]["id"]

    original = read_grading(staged["grading"]["id"])
    revised = read_grading(staged["regrade"]["id"])
    assert original["status"] == "SUPERSEDED"
    assert revised["status"] == "FINAL"
    assert revised["supersedes_grading_result_id"] == staged["grading"]["id"]

    request = read_request(staged["request"]["id"])
    assert request["grade_revision_count"] == 1
    assert request["grading_status"] == "GRADE_CERTIFIED"


def test_appeal_revision_releases_the_retained_portion_and_settles_the_ledger():
    """On `DECIDED_REVISED`: `refund_cents` is set to the full `deposit_cents`
    and credited to the applicant's `credits_total_cents`; the regrade becomes
    the `FINAL` determination while the previous `FINAL` becomes `SUPERSEDED`
    and is named by the new determination's `supersedes_grading_result_id`; the
    challenged certificate moves `UNDER_APPEAL → VOIDED` with
    `fee_settlement_status` `REVERSED` and its whole `fee_total_cents`
    credited; a fee-free `APPEAL_GRADE` certificate is issued in its place,
    carrying `superseded_certificate_id` pointing at the voided row,
    `appeal_id` naming the appeal, and a `fee_total_cents` of 0; the request's
    `grade_revision_count` increases by one; the inspector who produced the
    overturned determination has their `appeal_reversal_count` increased by one
    and their `performance_score` recomputed, which may auto-suspend them; and
    the retained sample portion is released as `portions_retained` decreases by
    one.

    Whenever a certificate leaves the trustworthy world — voided by an
    equipment cascade, voided by an appeal decided in the applicant's favour,
    or superseded by a re-issued certificate after a grade revision — its
    `fee_settlement_status` becomes `REVERSED` and its full `fee_total_cents`
    is credited to the applicant, regardless of how much of it had actually
    been paid.

    Because a full-deposit refund on revision, a half-deposit refund on
    dismissal and a fee reversal on voiding are all credit events and never
    edits, the conservation rule of §2.8 holds throughout: an applicant charged
    44850 for a combined certificate and 25000 for a deposit, whose appeal is
    then decided `DECIDED_REVISED`, ends with 69850 charged, 69850 credited and
    an `open_balance_cents` of 0, the free `APPEAL_GRADE` certificate adding
    nothing to either side.

    Design: Difficulty/transitive_cascade/appeal_revision_cascades_certificate_void_regrade_ledger_and_inspector_suspension
    """
    office = _appeal_cascade_office()
    staged = _appeal_under_review(office)

    decide(staged["appeal"]["id"])

    sample = read_sample(staged["sample"]["id"])
    assert sample["portions_retained"] == 0
    assert sample["portions_consumed"] == 2
    assert sample["portions_available"] == 2
    assert sample["integrity_status"] == "SEALED"
    assert_portion_accounting(sample)

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=52600,
        credits=52600,
        open_balance=0,
    )


def test_appeal_revision_auto_suspends_the_overturned_grader_and_closes_the_appeal():
    """On `DECIDED_REVISED`: `refund_cents` is set to the full `deposit_cents`
    and credited to the applicant's `credits_total_cents`; the regrade becomes
    the `FINAL` determination while the previous `FINAL` becomes `SUPERSEDED`
    and is named by the new determination's `supersedes_grading_result_id`; the
    challenged certificate moves `UNDER_APPEAL → VOIDED` with
    `fee_settlement_status` `REVERSED` and its whole `fee_total_cents`
    credited; a fee-free `APPEAL_GRADE` certificate is issued in its place,
    carrying `superseded_certificate_id` pointing at the voided row,
    `appeal_id` naming the appeal, and a `fee_total_cents` of 0; the request's
    `grade_revision_count` increases by one; the inspector who produced the
    overturned determination has their `appeal_reversal_count` increased by one
    and their `performance_score` recomputed, which may auto-suspend them; and
    the retained sample portion is released as `portions_retained` decreases by
    one.

    Automatic suspension is the threshold trigger: whenever a recomputation
    leaves an `ACTIVE` inspector with a `performance_score` strictly below 70,
    the licence moves `ACTIVE → SUSPENDED` on the spot with `suspension_reason`
    recorded as `AUTO_PERFORMANCE`, that inspector's `SCHEDULED` watches are
    aborted with the area's `open_watch_count` decremented accordingly, and any
    non-terminal appeal on which they are the sole panel member stays
    `UNDER_REVIEW` while their further votes are refused.

    The appeal must be `UNDER_REVIEW`, otherwise `ERR_APPEAL_STATE_INVALID`,
    and `effective_votes_count` must be at least `required_panel_size`,
    otherwise `ERR_APPEAL_QUORUM_NOT_MET` — which is why a panel of three that
    has produced two revise votes and one abstention cannot yet decide.

    Design: Difficulty/transitive_cascade/appeal_revision_cascades_certificate_void_regrade_ledger_and_inspector_suspension
    """
    office = _appeal_cascade_office()
    staged = _appeal_under_review(office)

    decide(staged["appeal"]["id"])

    overturned = read_inspector(office["grader"]["id"])
    assert overturned["appeal_reversal_count"] == 1
    assert overturned["check_sample_deviation_count"] == 2
    assert overturned["performance_score"] == 66
    assert_performance_score(overturned)
    assert overturned["license_status"] == "SUSPENDED"
    assert overturned["suspension_reason"] == "AUTO_PERFORMANCE"

    regrader = read_inspector(office["regrader"]["id"])
    assert regrader["license_status"] == "ACTIVE"
    assert regrader["performance_score"] == 100

    repeat = api_client.decide_appeal(staged["appeal"]["id"], ADMIN)
    validate_error(repeat, ApiErrorId.ERR_APPEAL_STATE_INVALID.value, 409)


# --------------------------------------------------------------------------- #
# An office whose protein instrument is about to fail its comparison check
# --------------------------------------------------------------------------- #

def _instrument_cascade_office():
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area(fee_multiplier_bp=11500)
    create_active_schedule(
        area["id"],
        "GRADING",
        base_fee_cents=12000,
        per_thousand_bushel_rate_cents=3000,
        minimum_fee_cents=15000,
    )
    create_active_schedule(area["id"], "PROTEIN", base_fee_cents=6000)
    applicant = create_applicant_account()
    inspector = create_active_inspector(area["id"], "L-5001")
    checked = create_inspector_row(area["id"], "L-5002")
    probe = create_certified_sampling_device(area["id"], "PROBE-N1")
    instrument = create_certified_instrument(area["id"], "NIR-N1")

    request = create_request(
        applicant["id"],
        area["id"],
        commodity="CORN",
        lot_identifier="LOT-NIR",
        declared_quantity_bushels=3609.27,
        requested_services=["GRADING", "PROTEIN"],
    )
    sample = draw_sample(
        request["id"],
        probe["id"],
        inspector["id"],
        portions_count=4,
        seal_number="SEAL-NIR",
    )
    analysis = record_analysis(
        request["id"],
        sample["id"],
        instrument["id"],
        inspector["id"],
        protein_pct_as_is=34.60,
        instrument_moisture_pct=12.80,
    )
    grading = record_grading(
        request["id"],
        sample["id"],
        inspector["id"],
        factors=CORN_NO_1_FACTORS_MOISTURE_12_8,
    )
    certificate = issue_certificate(request["id"], inspector["id"], "GRADE")
    return {
        "area": area,
        "applicant": applicant,
        "inspector": inspector,
        "checked": checked,
        "instrument": instrument,
        "request": request,
        "sample": sample,
        "analysis": analysis,
        "grading": grading,
        "certificate": certificate,
    }


def test_out_of_tolerance_check_rejects_the_analysis_and_releases_its_portion():
    """Every analysis on that instrument whose `status` is `ACCEPTED` or
    `RECOMPUTED` and which was created at or after the instrument's previous
    comparison check is set to `REJECTED_CALIBRATION`, processed in ascending
    order of `created_at` with `sequence_no` breaking ties.

    Each rejected analysis releases the sample portion it had consumed: the
    sample's `portions_consumed` decreases by one so that `portions_available`
    rises again, and a sample sitting in `CONSUMED` returns `CONSUMED → SEALED`.

    The instrument must be of kind `PROTEIN_INSTRUMENT`, must belong to the
    request's area, and — uniquely among equipment uses — may be either
    `APPROVED` or `DRIFT_WATCH` provided its `certified_until` is still in the
    future; anything else is `ERR_EQUIPMENT_NOT_APPROVED`.

    Design: Difficulty/transitive_cascade/instrument_out_of_tolerance_cascades_analysis_portion_and_certificate_reversal
    """
    office = _instrument_cascade_office()
    assert office["certificate"]["protein_reported_pct_snapshot"] == 34.52

    file_check(office["instrument"]["id"], office["checked"]["id"], 35.00, 35.65)

    instrument = read_equipment(office["instrument"]["id"])
    assert instrument["last_comparison_deviation_pct"] == 0.65
    assert instrument["rolling_bias_pct"] == 0.65
    assert instrument["approval_status"] == "OUT_OF_TOLERANCE"
    assert instrument["consecutive_out_of_tolerance_checks"] == 1

    analysis = read_analysis(office["analysis"]["id"])
    assert analysis["status"] == "REJECTED_CALIBRATION"
    assert analysis["protein_reported_pct"] == 34.52

    sample = read_sample(office["sample"]["id"])
    assert sample["portions_consumed"] == 1
    assert sample["portions_available"] == 3
    assert sample["integrity_status"] == "SEALED"

    checked = read_inspector(office["checked"]["id"])
    assert checked["check_sample_deviation_count"] == 1
    assert checked["performance_score"] == 90

    blocked = api_client.create_protein_analysis(
        protein_analysis_payload(
            office["request"]["id"],
            office["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
        ),
        INSPECTOR,
    )
    validate_error(blocked, ApiErrorId.ERR_EQUIPMENT_NOT_APPROVED.value, 409)


def test_out_of_tolerance_check_voids_the_certificate_that_carried_the_analysis():
    """Every certificate carrying a rejected analysis's
    `protein_reported_pct_snapshot` becomes `VOIDED` with its fee `REVERSED` and
    credited.

    `open_balance_cents` is always `charges_total_cents` minus
    `credits_total_cents`.

    Design: Difficulty/transitive_cascade/instrument_out_of_tolerance_cascades_analysis_portion_and_certificate_reversal
    """
    office = _instrument_cascade_office()
    assert office["certificate"]["fee_total_cents"] == 34500

    file_check(office["instrument"]["id"], office["checked"]["id"], 35.00, 35.65)

    certificate = read_certificate(office["certificate"]["id"])
    assert certificate["status"] == "VOIDED"
    assert certificate["fee_settlement_status"] == "REVERSED"

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=34500,
        credits=34500,
        open_balance=0,
    )

    # The grading determination is untouched by a calibration cascade.
    assert read_grading(office["grading"]["id"])["status"] == "FINAL"
