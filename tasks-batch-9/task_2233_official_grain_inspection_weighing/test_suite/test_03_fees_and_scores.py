"""Arithmetic contracts: the performance score, the fee input set, the payment
waterfall, the credit ceiling and the appeal tally."""

from test_helpers import (
    ADMIN,
    BUSINESS_HOURS_CLOCK,
    CORN_NO_2_FACTORS,
    INSPECTOR,
    ApiErrorId,
    activate_schedule,
    api_client,
    assert_ledger,
    cast_vote,
    certificate_payload,
    create_active_inspector,
    create_certified_instrument,
    create_designated_area,
    draft_schedule,
    file_check,
    file_training_hours,
    issue_certificate,
    make_applicant_headers,
    payment_payload,
    read_appeal,
    read_applicant,
    read_certificate,
    read_equipment,
    read_inspector,
    read_request,
    read_sample,
    set_clock,
    setup_appeal_under_review,
    setup_certificated_request,
    setup_graded_and_weighed_request,
    setup_graded_request,
    setup_office,
    validate_error,
    validate_paginated,
    validate_success,
)


GRADING_SCHEDULE = {
    "service_class": "GRADING",
    "base_fee_cents": 8000,
    "per_thousand_bushel_rate_cents": 2000,
    "minimum_fee_cents": 10000,
}

APPEAL_SCHEDULE = {"service_class": "APPEAL", "base_fee_cents": 20000}


def test_four_proficiency_deviations_walk_the_score_below_the_suspension_floor():
    """The score is a weighted deduction from a perfect 100: subtract 18 for each
    appeal reversed against the inspector, subtract 10 for each proficiency
    deviation counted against them, subtract 3 for each late certificate, then add
    a training credit equal to the whole number of complete ten-hour blocks of
    `training_hours_completed`, capped at 12.

    Automatic suspension is the threshold trigger: whenever a recomputation leaves
    an `ACTIVE` inspector with a `performance_score` strictly below 70, the licence
    moves `ACTIVE → SUSPENDED` on the spot with `suspension_reason` recorded as
    `AUTO_PERFORMANCE`, that inspector's `SCHEDULED` watches are aborted with the
    area's `open_watch_count` decremented accordingly, and any non-terminal appeal
    on which they are the sole panel member stays `UNDER_REVIEW` while their
    further votes are refused. A score of exactly 70 does not trigger it.

    Note also that a deviation of 0.30 counts against the inspector's
    `check_sample_deviation_count`, because that counter's bar is 0.25, while
    leaving the instrument merely on drift watch.

    Reinstatement moves `SUSPENDED → ACTIVE`, requires a `performance_score` of at
    least 80 (`ERR_INSPECTOR_NOT_QUALIFIED` otherwise) and a `license_expires_at`
    still in the future, and clears `suspension_reason`.

    Design: Corner/calculations/performance_score_penalties_accumulate_until_the_auto_suspension_threshold
    """
    set_clock(BUSINESS_HOURS_CLOCK)
    area = create_designated_area()
    instrument = create_certified_instrument(area["id"], "NIR-S1")
    inspector = create_active_inspector(
        area["id"], "L-4101", endorsements=["GRADING", "PROTEIN"], hours=24
    )
    assert inspector["performance_score"] == 100
    assert inspector["license_status"] == "ACTIVE"

    expected_scores = [92, 82, 72]
    for index, expected in enumerate(expected_scores, start=1):
        file_check(instrument["id"], inspector["id"], 12.00, 12.30)
        walked = read_inspector(inspector["id"])
        assert walked["check_sample_deviation_count"] == index
        assert walked["performance_score"] == expected
        assert walked["license_status"] == "ACTIVE"
        drifting = read_equipment(instrument["id"])
        assert drifting["approval_status"] == "DRIFT_WATCH"
        assert drifting["rolling_bias_pct"] == 0.30

    file_check(instrument["id"], inspector["id"], 12.00, 12.30)
    suspended = read_inspector(inspector["id"])
    assert suspended["check_sample_deviation_count"] == 4
    assert suspended["performance_score"] == 62
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "AUTO_PERFORMANCE"

    # The calibration ladder never left drift watch, so nothing else touched the score.
    settled = read_equipment(instrument["id"])
    assert settled["approval_status"] == "DRIFT_WATCH"
    assert settled["rolling_bias_pct"] == 0.30

    trained = file_training_hours(inspector["id"], 120)
    assert trained["training_hours_completed"] == 144
    assert trained["performance_score"] == 72
    assert trained["license_status"] == "SUSPENDED"

    unqualified = api_client.reinstate_inspector(inspector["id"], ADMIN)
    validate_error(unqualified, ApiErrorId.ERR_INSPECTOR_NOT_QUALIFIED.value, 422)
    assert read_inspector(inspector["id"])["license_status"] == "SUSPENDED"


def test_a_draft_and_a_closed_window_schedule_are_both_outside_the_fee_input_set():
    """For each applicable class the system takes the `ACTIVE` fee schedule of the
    request's area whose window covers the logical clock — `effective_from` at or
    before now and either a null `effective_to` or an `effective_to` strictly after
    now — ignoring `DRAFT` and `SUPERSEDED` schedules and any schedule outside its
    window. If a class has no such schedule, issuance fails with
    `ERR_NO_ACTIVE_FEE_SCHEDULE`.

    The service charge is the sum of `base_fee_cents` over the applicable schedules
    plus the billed thousands multiplied by the sum of
    `per_thousand_bushel_rate_cents` over the same schedules.

    Design: Corner/calculations/fee_input_set_excludes_draft_and_window_closed_schedules
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(
            GRADING_SCHEDULE,
            {
                "service_class": "WEIGHING",
                "base_fee_cents": 40000,
                "per_thousand_bushel_rate_cents": 8000,
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2026-07-01T00:00:00Z",
            },
        ),
    )
    draft_schedule(
        office["area"]["id"],
        "WEIGHING",
        base_fee_cents=50000,
        per_thousand_bushel_rate_cents=9000,
    )
    staged = setup_graded_and_weighed_request(office, lot_identifier="LOT-FEE-1")
    priced = read_request(staged["request"]["id"])
    assert priced["certified_quantity_bushels"] == 3609.27

    unpriceable = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "COMBINED"
        ),
        INSPECTOR,
    )
    validate_error(unpriceable, ApiErrorId.ERR_NO_ACTIVE_FEE_SCHEDULE.value, 422)

    unmoved = read_request(staged["request"]["id"])
    assert unmoved["grading_status"] == "GRADED"
    assert unmoved["weighing_status"] == "WEIGHED"
    assert read_applicant(office["applicant"]["id"])["charges_total_cents"] == 0

    # The failure is class-specific: only the WEIGHING class is unpriceable.
    grade_only = setup_graded_and_weighed_request(office, lot_identifier="LOT-FEE-2")
    priced_grade = issue_certificate(
        grade_only["request"]["id"], office["inspector"]["id"], "GRADE"
    )
    assert priced_grade["fee_total_cents"] == 16000

    replacement = draft_schedule(
        office["area"]["id"],
        "WEIGHING",
        base_fee_cents=9000,
        per_thousand_bushel_rate_cents=1500,
        minimum_fee_cents=12000,
        effective_from="2026-07-01T00:00:00Z",
    )
    activate_schedule(replacement["id"])

    accepted = api_client.create_certificate(
        certificate_payload(
            staged["request"]["id"], office["inspector"]["id"], "COMBINED"
        ),
        INSPECTOR,
    )
    combined = validate_success(accepted, 201)
    assert combined["fee_total_cents"] == 31000
    assert combined["overtime_applied"] is False


def test_a_payment_fills_the_older_certificate_before_touching_the_newer():
    """Settlement runs as a waterfall. The allocatable total is the sum, over that
    pool, of `fee_total_cents` less `fee_paid_cents`.

    Otherwise the pool is walked oldest first, ordered by `issued_at` ascending
    with `sequence_no` ascending breaking ties at the same instant, and each
    certificate is filled to its full fee before the next is touched: the amount
    taken is the smaller of what remains of the payment and what remains
    outstanding on that certificate, it is added to that certificate's
    `fee_paid_cents`, and the certificate's `fee_settlement_status` becomes `PAID`
    the moment `fee_paid_cents` equals `fee_total_cents`.

    The walk stops when the payment is exhausted, and the whole `amount_cents` is
    added to the applicant's `credits_total_cents`.

    Design: Corner/calculations/payment_waterfall_fills_the_oldest_certificate_before_the_next
    """
    office = setup_office(
        "DELEGATED",
        fee_schedules=(GRADING_SCHEDULE,),
        applicant_overrides={"credit_limit_cents": 900000},
    )
    applicant_id = office["applicant"]["id"]
    as_applicant = make_applicant_headers(applicant_id)

    first = setup_certificated_request(
        office,
        "GRADE",
        declared_quantity_bushels=500,
        portions_count=1,
        lot_identifier="LOT-PW1",
        seal_number="SEAL-PW1",
    )
    second = setup_certificated_request(
        office,
        "GRADE",
        declared_quantity_bushels=500,
        portions_count=1,
        lot_identifier="LOT-PW2",
        seal_number="SEAL-PW2",
    )
    older = first["certificate"]
    newer = second["certificate"]

    assert older["fee_total_cents"] == 10000
    assert newer["fee_total_cents"] == 10000
    assert older["issued_at"] == newer["issued_at"]
    assert older["sequence_no"] < newer["sequence_no"]

    validate_success(
        api_client.record_payment(applicant_id, payment_payload(12000), as_applicant),
        200,
    )

    filled = read_certificate(older["id"])
    assert filled["fee_paid_cents"] == 10000
    assert filled["fee_settlement_status"] == "PAID"

    partial = read_certificate(newer["id"])
    assert partial["fee_paid_cents"] == 2000
    assert partial["fee_settlement_status"] == "UNPAID"

    assert_ledger(
        read_applicant(applicant_id), charges=20000, credits=12000, open_balance=8000
    )

    overshoot = api_client.record_payment(
        applicant_id, payment_payload(8001), as_applicant
    )
    validate_error(overshoot, ApiErrorId.ERR_PAYMENT_EXCEEDS_ALLOCATABLE.value, 422)
    assert read_certificate(newer["id"])["fee_paid_cents"] == 2000
    assert_ledger(
        read_applicant(applicant_id), charges=20000, credits=12000, open_balance=8000
    )

    validate_success(
        api_client.record_payment(applicant_id, payment_payload(8000), as_applicant),
        200,
    )
    settled = read_certificate(newer["id"])
    assert settled["fee_paid_cents"] == 10000
    assert settled["fee_settlement_status"] == "PAID"
    assert_ledger(
        read_applicant(applicant_id), charges=20000, credits=20000, open_balance=0
    )

    nothing_left = api_client.record_payment(
        applicant_id, payment_payload(1), as_applicant
    )
    validate_error(nothing_left, ApiErrorId.ERR_PAYMENT_EXCEEDS_ALLOCATABLE.value, 422)


def test_a_certificate_landing_exactly_on_the_credit_limit_is_still_issued():
    """The credit check is the last gate of all, because it needs the finished
    number: the applicant's `open_balance_cents` plus the newly computed
    `fee_total_cents` may not exceed their `credit_limit_cents`, otherwise the whole
    issuance is refused with `ERR_CREDIT_LIMIT_EXCEEDED` and nothing is written.

    The assessed fee is charged before the certificate is returned: it is added to
    the applicant's `charges_total_cents`, `open_balance_cents` is recomputed, and
    the certificate begins with `fee_paid_cents` 0 and `fee_settlement_status`
    `UNPAID`.

    Design: Corner/calculations/credit_limit_admits_the_exact_limit_and_refuses_the_next_charge
    """
    office = setup_office(
        "DELEGATED",
        fee_schedules=(GRADING_SCHEDULE,),
        applicant_overrides={"credit_limit_cents": 20000},
    )
    applicant_id = office["applicant"]["id"]
    staged = [
        setup_graded_request(
            office,
            declared_quantity_bushels=500,
            portions_count=1,
            lot_identifier=f"LOT-CL{index}",
            seal_number=f"SEAL-CL{index}",
        )
        for index in (1, 2, 3)
    ]

    first = issue_certificate(
        staged[0]["request"]["id"], office["inspector"]["id"], "GRADE"
    )
    assert first["fee_total_cents"] == 10000
    assert first["fee_paid_cents"] == 0
    assert first["fee_settlement_status"] == "UNPAID"
    assert read_applicant(applicant_id)["open_balance_cents"] == 10000

    second = issue_certificate(
        staged[1]["request"]["id"], office["inspector"]["id"], "GRADE"
    )
    assert second["fee_total_cents"] == 10000
    at_the_limit = read_applicant(applicant_id)
    assert at_the_limit["open_balance_cents"] == 20000
    assert at_the_limit["open_balance_cents"] == at_the_limit["credit_limit_cents"]

    over_the_limit = api_client.create_certificate(
        certificate_payload(
            staged[2]["request"]["id"], office["inspector"]["id"], "GRADE"
        ),
        INSPECTOR,
    )
    validate_error(over_the_limit, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 422)

    assert read_request(staged[2]["request"]["id"])["grading_status"] == "GRADED"
    _rows, meta = validate_paginated(
        api_client.list_request_certificates(staged[2]["request"]["id"], ADMIN)
    )
    assert meta["total_count"] == 0
    assert_ledger(
        read_applicant(applicant_id), charges=20000, credits=0, open_balance=20000
    )

    validate_success(
        api_client.record_payment(applicant_id, payment_payload(20000), ADMIN), 200
    )
    assert read_applicant(applicant_id)["open_balance_cents"] == 0

    retried = api_client.create_certificate(
        certificate_payload(
            staged[2]["request"]["id"], office["inspector"]["id"], "GRADE"
        ),
        INSPECTOR,
    )
    third = validate_success(retried, 201)
    assert third["fee_total_cents"] == 10000
    assert read_applicant(applicant_id)["open_balance_cents"] == 10000


def test_an_abstention_is_excluded_from_quorum_and_from_the_revise_majority():
    """Each accepted vote increments `votes_cast_count` and the counter for its own
    value, recomputes `effective_votes_count` as `revise_votes_count` plus
    `uphold_votes_count` — abstentions count toward neither side and are excluded
    from the denominator — and advances the appeal's `version`.

    The appeal must be `UNDER_REVIEW`, otherwise `ERR_APPEAL_STATE_INVALID`, and
    `effective_votes_count` must be at least `required_panel_size`, otherwise
    `ERR_APPEAL_QUORUM_NOT_MET` — which is why a panel of three that has produced
    two revise votes and one abstention cannot yet decide.

    The outcome is `DECIDED_REVISED` when twice the `revise_votes_count` strictly
    exceeds `effective_votes_count` **and** the regrade's `assigned_grade` differs
    from the challenged certificate's `grade_snapshot`; in every other case the
    outcome is `DECIDED_UPHELD`.

    On `DECIDED_UPHELD`: `refund_cents` stays 0, the challenged certificate returns
    `UNDER_APPEAL → ISSUED`, and the retained sample portion is likewise released as
    `portions_retained` decreases by one.

    Design: Corner/calculations/appeal_quorum_counts_effective_votes_only_and_upholds_without_a_majority
    """
    office = setup_office(
        "DELEGATED",
        fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE),
        applicant_overrides={"credit_limit_cents": 900000},
    )
    staged = setup_appeal_under_review(
        office,
        appeal_type="APPEAL",
        regrade_factors=CORN_NO_2_FACTORS,
        panel_size=4,
        portions_count=6,
        declared_quantity_bushels=500,
        lot_identifier="LOT-QUO",
        seal_number="SEAL-QUO",
    )
    appeal_id = staged["appeal"]["id"]
    certificate_id = staged["certificate"]["id"]
    original_grader = office["inspector"]

    assert staged["appeal"]["required_panel_size"] == 3
    assert staged["appeal"]["deposit_cents"] == 20000
    assert staged["certificate"]["grade_snapshot"] == "US_NO_1"
    assert staged["regrade"]["assigned_grade"] == "US_NO_2"
    assert staged["regrade"]["limiting_factor"] == "TEST_WEIGHT"

    cast_vote(appeal_id, staged["voters"][0]["id"], "REVISE")
    cast_vote(appeal_id, staged["voters"][1]["id"], "UPHOLD")
    cast_vote(appeal_id, staged["voters"][2]["id"], "ABSTAIN")

    short = read_appeal(appeal_id)
    assert short["votes_cast_count"] == 3
    assert short["effective_votes_count"] == 2

    premature = api_client.decide_appeal(appeal_id, ADMIN)
    validate_error(premature, ApiErrorId.ERR_APPEAL_QUORUM_NOT_MET.value, 422)

    waiting = read_appeal(appeal_id)
    assert waiting["status"] == "UNDER_REVIEW"
    assert waiting["decided_at"] is None
    assert waiting["refund_cents"] == 0
    assert read_certificate(certificate_id)["status"] == "UNDER_APPEAL"

    cast_vote(appeal_id, staged["voters"][3]["id"], "UPHOLD")
    quorate = read_appeal(appeal_id)
    assert quorate["effective_votes_count"] == 3
    assert quorate["revise_votes_count"] == 1
    assert quorate["uphold_votes_count"] == 2
    assert quorate["abstain_votes_count"] == 1

    decided = validate_success(api_client.decide_appeal(appeal_id, ADMIN), 200)
    assert decided["status"] == "DECIDED_UPHELD"
    assert decided["outcome_grade"] == "US_NO_2"
    assert decided["refund_cents"] == 0

    assert read_certificate(certificate_id)["status"] == "ISSUED"
    restored = read_request(staged["request"]["id"])
    assert restored["grading_status"] == "GRADE_CERTIFIED"
    assert restored["grade_revision_count"] == 0
    assert read_sample(staged["sample"]["id"])["portions_retained"] == 0

    untouched = read_inspector(original_grader["id"])
    assert untouched["appeal_reversal_count"] == 0
    assert untouched["performance_score"] == 100

    assert_ledger(
        read_applicant(office["applicant"]["id"]),
        charges=30000,
        credits=0,
        open_balance=30000,
    )
