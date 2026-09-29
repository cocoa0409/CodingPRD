"""Compensations that must restore an invariant exactly: the two-sided applicant
ledger and the sample's portion accounting."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    ApiErrorId,
    BUSINESS_HOURS_CLOCK,
    CORN_NO_1_FACTORS_MOISTURE_12_8,
    CORN_NO_2_FACTORS,
    CORN_NO_3_FACTORS,
    SINGLE_CORN_DRAFT_500_BU,
    api_client,
    assert_ledger,
    assert_portion_accounting,
    assign_appeal_sample,
    cast_vote,
    certify,
    create_active_inspector,
    create_active_schedule,
    create_applicant_account,
    create_certified_instrument,
    create_certified_sampling_device,
    create_certified_scale,
    create_delegated_area,
    create_designated_area,
    create_request,
    decide,
    draw_sample,
    file_appeal,
    file_check,
    issue_certificate,
    pay,
    payment_payload,
    protein_analysis_payload,
    read_analysis,
    read_applicant,
    read_certificate,
    read_equipment,
    read_sample,
    record_analysis,
    record_grading,
    record_weighing,
    set_clock,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------- #
# A billed office with two certificates outstanding
# --------------------------------------------------------------------------- #

def _ledger_office():
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_delegated_area()
    create_active_schedule(
        area["id"],
        "GRADING",
        base_fee_cents=8000,
        per_thousand_bushel_rate_cents=2000,
        overtime_multiplier_bp=2000,
        minimum_fee_cents=10000,
    )
    create_active_schedule(
        area["id"],
        "WEIGHING",
        base_fee_cents=6000,
        per_thousand_bushel_rate_cents=1000,
        overtime_multiplier_bp=2000,
        minimum_fee_cents=8000,
    )
    create_active_schedule(area["id"], "APPEAL", base_fee_cents=20000)
    return {
        "area": area,
        "applicant": create_applicant_account(credit_limit_cents=900000),
        "inspector": create_active_inspector(area["id"], "L-9301"),
        "reviewer": create_active_inspector(area["id"], "L-9302"),
        "probe": create_certified_sampling_device(area["id"], "PROBE-L1"),
        "scale": create_certified_scale(area["id"], "SCALE-L1"),
    }


def _two_outstanding_certificates(office):
    weighed_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-W500",
        declared_quantity_bushels=500,
        requested_services=["GRADING", "WEIGHING"],
    )
    record_weighing(
        weighed_request["id"],
        office["scale"]["id"],
        office["inspector"]["id"],
        SINGLE_CORN_DRAFT_500_BU,
        dockage_pct=0,
    )
    cert_a = issue_certificate(
        weighed_request["id"], office["inspector"]["id"], "WEIGHT"
    )

    graded_request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier="LOT-G20500",
        declared_quantity_bushels=20500,
        requested_services=["GRADING"],
    )
    sample = draw_sample(
        graded_request["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=4,
        seal_number="SEAL-LED",
    )
    record_grading(
        graded_request["id"],
        sample["id"],
        office["inspector"]["id"],
        factors=CORN_NO_2_FACTORS,
    )
    cert_b = issue_certificate(
        graded_request["id"], office["inspector"]["id"], "GRADE"
    )
    return {
        "graded_request": graded_request,
        "sample": sample,
        "cert_a": cert_a,
        "cert_b": cert_b,
    }


def _appeal_under_review(office, staged):
    challenged = read_certificate(staged["cert_b"]["id"])
    appeal = file_appeal(
        challenged["id"],
        office["applicant"]["id"],
        challenged["version"],
        "REINSPECTION",
    )
    assign_appeal_sample(appeal["id"], staged["sample"]["id"])
    record_grading(
        staged["graded_request"]["id"],
        staged["sample"]["id"],
        office["reviewer"]["id"],
        factors=CORN_NO_3_FACTORS,
        appeal_id=appeal["id"],
    )
    cast_vote(appeal["id"], office["reviewer"]["id"], "REVISE")
    return appeal


def test_the_waterfall_fills_the_oldest_certificate_before_touching_the_second():
    """Otherwise the pool is walked oldest first, ordered by `issued_at`
    ascending with `sequence_no` ascending breaking ties at the same instant,
    and each certificate is filled to its full fee before the next is touched:
    the amount taken is the smaller of what remains of the payment and what
    remains outstanding on that certificate, it is added to that certificate's
    `fee_paid_cents`, and the certificate's `fee_settlement_status` becomes
    `PAID` the moment `fee_paid_cents` equals `fee_total_cents`.

    Issuance stamps `issued_at` from the logical clock, assigns a `sequence_no`
    that is monotonically increasing per applicant starting at 1, and freezes
    the state of the request into snapshots: `grade_snapshot` and
    `limiting_factor_snapshot` copy the `assigned_grade` and `limiting_factor`
    of the request's `FINAL` determination and are null on a `WEIGHT`
    certificate; `net_lbs_snapshot` and `net_bushels_snapshot` copy the
    operative weighing record's `net_lbs` and `net_bushels` and are null when
    no weighing is certified; `protein_reported_pct_snapshot` copies the
    operative analysis's `protein_reported_pct` and is null when protein was
    not ordered; and `certified_quantity_bushels` copies the request's own
    `certified_quantity_bushels`, which is what the fee is assessed on.

    Design: Difficulty/compensating_invariant/payment_waterfall_then_appeal_reversal_conserves_the_applicant_ledger_into_credit
    """
    office = _ledger_office()
    staged = _two_outstanding_certificates(office)

    assert staged["cert_a"]["sequence_no"] == 1
    assert staged["cert_a"]["fee_total_cents"] == 8000
    assert staged["cert_b"]["sequence_no"] == 2
    assert staged["cert_b"]["fee_total_cents"] == 47500
    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=55500,
        credits=0,
        open_balance=55500,
    )

    pay(office["applicant"]["id"], 20000)

    first = read_certificate(staged["cert_a"]["id"])
    assert first["fee_paid_cents"] == 8000
    assert first["fee_settlement_status"] == "PAID"

    second = read_certificate(staged["cert_b"]["id"])
    assert second["fee_paid_cents"] == 12000
    assert second["fee_settlement_status"] == "UNPAID"

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=55500,
        credits=20000,
        open_balance=35500,
    )


def test_a_payment_larger_than_the_allocatable_total_mutates_nothing():
    """The allocatable total is the sum, over that pool, of `fee_total_cents` less
    `fee_paid_cents`. A payment larger than the allocatable total is refused
    outright with `ERR_PAYMENT_EXCEEDS_ALLOCATABLE` and nothing is mutated — a
    payment is never partially applied.

    `open_balance_cents` is always `charges_total_cents` minus
    `credits_total_cents`.

    Design: Difficulty/compensating_invariant/payment_waterfall_then_appeal_reversal_conserves_the_applicant_ledger_into_credit
    """
    office = _ledger_office()
    staged = _two_outstanding_certificates(office)
    pay(office["applicant"]["id"], 20000)

    response = api_client.record_payment(
        office["applicant"]["id"], payment_payload(35501), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_ALLOCATABLE.value, 422)

    assert read_certificate(staged["cert_a"]["id"])["fee_paid_cents"] == 8000
    assert read_certificate(staged["cert_b"]["id"])["fee_paid_cents"] == 12000
    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=55500,
        credits=20000,
        open_balance=35500,
    )

    exactly_allocatable = api_client.record_payment(
        office["applicant"]["id"], payment_payload(35500), ADMIN
    )
    validate_success(exactly_allocatable, 200)
    assert read_certificate(staged["cert_b"]["id"])["fee_settlement_status"] == "PAID"


def test_a_revised_appeal_credits_the_deposit_and_the_partly_paid_fee():
    """No event ever edits an earlier event, which means the balance may
    legitimately go negative when a certificate that was already paid is later
    reversed.

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

    Design: Difficulty/compensating_invariant/payment_waterfall_then_appeal_reversal_conserves_the_applicant_ledger_into_credit
    """
    office = _ledger_office()
    staged = _two_outstanding_certificates(office)
    pay(office["applicant"]["id"], 20000)
    appeal = _appeal_under_review(office, staged)

    assert appeal["deposit_cents"] == 20000
    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=75500,
        credits=20000,
        open_balance=55500,
    )

    decided = decide(appeal["id"])
    assert decided["status"] == "DECIDED_REVISED"
    assert decided["required_panel_size"] == 1
    assert decided["effective_votes_count"] == 1
    assert decided["revise_votes_count"] == 1
    assert decided["refund_cents"] == 20000

    voided = read_certificate(staged["cert_b"]["id"])
    assert voided["status"] == "VOIDED"
    assert voided["fee_settlement_status"] == "REVERSED"
    assert voided["fee_total_cents"] == 47500
    assert voided["fee_paid_cents"] == 12000

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=75500,
        credits=87500,
        open_balance=-12000,
    )


def test_a_second_decision_is_refused_and_never_compensates_twice():
    """The appeal must be `UNDER_REVIEW`, otherwise `ERR_APPEAL_STATE_INVALID`,
    and `effective_votes_count` must be at least `required_panel_size`,
    otherwise `ERR_APPEAL_QUORUM_NOT_MET` — which is why a panel of three that
    has produced two revise votes and one abstention cannot yet decide.

    A payment of `amount_cents` — which must be positive — is allocated across
    the applicant's certificates whose `fee_settlement_status` is `UNPAID` and
    whose `status` is `ISSUED` or `UNDER_APPEAL`; `REVERSED` settlements and
    `VOIDED` or `SUPERSEDED` certificates are excluded from the pool entirely.

    Design: Difficulty/compensating_invariant/payment_waterfall_then_appeal_reversal_conserves_the_applicant_ledger_into_credit
    """
    office = _ledger_office()
    staged = _two_outstanding_certificates(office)
    pay(office["applicant"]["id"], 20000)
    appeal = _appeal_under_review(office, staged)
    decide(appeal["id"])

    repeat = api_client.decide_appeal(appeal["id"], ADMIN)
    validate_error(repeat, ApiErrorId.ERR_APPEAL_STATE_INVALID.value, 409)

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=75500,
        credits=87500,
        open_balance=-12000,
    )

    # Nothing is left in the allocatable pool: the paid weight certificate is out,
    # the voided grade certificate is out, and the replacement is fee-free.
    unallocatable = api_client.record_payment(
        office["applicant"]["id"], payment_payload(1), ADMIN
    )
    validate_error(unallocatable, ApiErrorId.ERR_PAYMENT_EXCEEDS_ALLOCATABLE.value, 422)

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=75500,
        credits=87500,
        open_balance=-12000,
    )


# --------------------------------------------------------------------------- #
# A fully consumed sample whose analysis is about to be invalidated
# --------------------------------------------------------------------------- #

def _calibration_office():
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    applicant = create_applicant_account()
    inspector = create_active_inspector(area["id"], "L-9401")
    probe = create_certified_sampling_device(area["id"], "PROBE-C1")
    instrument = create_certified_instrument(area["id"], "NIR-C1")

    request = create_request(
        applicant["id"],
        area["id"],
        lot_identifier="LOT-CAL",
        declared_quantity_bushels=4000,
        requested_services=["GRADING", "PROTEIN"],
    )
    sample = draw_sample(
        request["id"],
        probe["id"],
        inspector["id"],
        portions_count=2,
        seal_number="SEAL-CAL",
    )
    record_grading(
        request["id"],
        sample["id"],
        inspector["id"],
        factors=CORN_NO_1_FACTORS_MOISTURE_12_8,
    )
    analysis = record_analysis(
        request["id"],
        sample["id"],
        instrument["id"],
        inspector["id"],
        protein_pct_as_is=34.60,
        instrument_moisture_pct=12.80,
    )
    return {
        "area": area,
        "applicant": applicant,
        "inspector": inspector,
        "instrument": instrument,
        "request": request,
        "sample": sample,
        "analysis": analysis,
    }


def _fresh_analysis(office):
    return api_client.create_protein_analysis(
        protein_analysis_payload(
            office["request"]["id"],
            office["sample"]["id"],
            office["instrument"]["id"],
            office["inspector"]["id"],
            34.60,
            12.80,
        ),
        INSPECTOR,
    )


def test_an_out_of_tolerance_check_releases_exactly_one_consumed_portion():
    """Each rejected analysis releases the sample portion it had consumed: the
    sample's `portions_consumed` decreases by one so that `portions_available`
    rises again, and a sample sitting in `CONSUMED` returns `CONSUMED → SEALED`.

    The check resolves to `OUT_OF_TOLERANCE` when the absolute deviation of this
    single check exceeds 0.50 percentage points **or** the absolute
    `rolling_bias_pct` exceeds 0.30.

    Design: Difficulty/compensating_invariant/calibration_rejection_releases_exactly_one_sample_portion_and_never_twice
    """
    office = _calibration_office()
    assert office["analysis"]["protein_reported_pct"] == 34.52
    assert office["analysis"]["basis_source"] == "OFFICIAL_MOISTURE"

    before = read_sample(office["sample"]["id"])
    assert before["portions_count"] == 2
    assert before["portions_consumed"] == 2
    assert before["portions_retained"] == 0
    assert before["portions_available"] == 0
    assert before["integrity_status"] == "CONSUMED"

    file_check(office["instrument"]["id"], office["inspector"]["id"], 35.00, 35.65)

    instrument = read_equipment(office["instrument"]["id"])
    assert instrument["approval_status"] == "OUT_OF_TOLERANCE"
    assert instrument["last_comparison_deviation_pct"] == 0.65
    assert instrument["consecutive_out_of_tolerance_checks"] == 1

    assert read_analysis(office["analysis"]["id"])["status"] == "REJECTED_CALIBRATION"

    after = read_sample(office["sample"]["id"])
    assert after["portions_consumed"] == 1
    assert after["portions_retained"] == 0
    assert after["portions_available"] == 1
    assert after["integrity_status"] == "SEALED"
    assert_portion_accounting(after)


def test_recalibration_clears_the_bias_window_without_releasing_a_second_portion():
    """On a pass, the row moves `PENDING_APPROVAL → APPROVED` (or recovers
    `EXPIRED → APPROVED`, or `OUT_OF_TOLERANCE → APPROVED` provided
    `consecutive_out_of_tolerance_checks` is still below 3), `certified_until`
    is stored, `consecutive_out_of_tolerance_checks` is reset to 0, and for a
    scale `last_certification_error_lbs` records the observed error.

    Recalibrating a protein instrument out of `OUT_OF_TOLERANCE` additionally
    empties `recent_deviations_pct` and returns `rolling_bias_pct` to null, so
    the comparison window starts fresh.

    Design: Difficulty/compensating_invariant/calibration_rejection_releases_exactly_one_sample_portion_and_never_twice
    """
    office = _calibration_office()
    file_check(office["instrument"]["id"], office["inspector"]["id"], 35.00, 35.65)

    recovered = certify(office["instrument"]["id"])

    assert recovered["approval_status"] == "APPROVED"
    assert recovered["rolling_bias_pct"] is None
    assert recovered["recent_deviations_pct"] == []
    assert recovered["consecutive_out_of_tolerance_checks"] == 0

    # The compensation is not applied a second time by the recovery.
    sample = read_sample(office["sample"]["id"])
    assert sample["portions_consumed"] == 1
    assert sample["portions_available"] == 1
    assert sample["integrity_status"] == "SEALED"
    assert_portion_accounting(sample)

    assert read_analysis(office["analysis"]["id"])["status"] == "REJECTED_CALIBRATION"


def test_the_released_portion_is_reusable_once_and_then_exhausted():
    """When a consumption drives `portions_available` to 0 the sample moves
    `SEALED → CONSUMED`; the compensating release described in §3.3 moves it
    back `CONSUMED → SEALED`.

    Any of those three operations attempted when `portions_available` is 0 is
    refused with `ERR_SAMPLE_PORTIONS_EXHAUSTED`.

    Design: Difficulty/compensating_invariant/calibration_rejection_releases_exactly_one_sample_portion_and_never_twice
    """
    office = _calibration_office()
    file_check(office["instrument"]["id"], office["inspector"]["id"], 35.00, 35.65)
    certify(office["instrument"]["id"])

    replacement = validate_success(_fresh_analysis(office), 201)
    assert replacement["protein_reported_pct"] == 34.52

    sample = read_sample(office["sample"]["id"])
    assert sample["portions_consumed"] == 2
    assert sample["portions_available"] == 0
    assert sample["integrity_status"] == "CONSUMED"
    assert_portion_accounting(sample)

    exhausted = _fresh_analysis(office)
    validate_error(exhausted, ApiErrorId.ERR_SAMPLE_PORTIONS_EXHAUSTED.value, 422)
