"""Claims: the medical and vision adjudication fork, appeals, corrections and gates."""

from test_helpers import (
    ApiErrorId,
    assert_claim_dollar_identity,
    assert_money,
    assert_vision_allowance_identity,
    coverage_version,
    create_claim_payload,
    deliver_session,
    get_success_data,
    make_billing_specialist_headers,
    new_coverage,
    new_vision_payer,
    open_claim,
    read_authorization,
    read_coverage,
    read_session,
    set_clock,
    setup_active_plan,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scenario_with_both_coverages():
    """One patient carrying a medical and a vision coverage, plus two billable sessions."""
    scn = setup_active_plan()
    vision_payer = new_vision_payer()
    vision_coverage = new_coverage(
        scn["pt"],
        vision_payer["id"],
        member_number="V-2002",
        deductible_total=0.00,
        deductible_met=0.00,
        vision_allowance_total=250.00,
    )
    scn["payer_vis"] = vision_payer["id"]
    scn["cov_vis"] = vision_coverage["id"]

    first = deliver_session(
        scn,
        scheduled_start_at="2026-06-02T09:00:00Z",
        scheduled_end_at="2026-06-02T10:00:00Z",
        performed_at="2026-06-02T09:55:00Z",
        timed_minutes=45,
    )
    second = deliver_session(
        scn,
        scheduled_start_at="2026-06-03T09:00:00Z",
        scheduled_end_at="2026-06-03T10:00:00Z",
        performed_at="2026-06-03T09:55:00Z",
        timed_minutes=45,
    )
    return scn, first, second


def test_the_medical_arm_splits_the_encounter_across_deductible_and_coinsurance(api):
    """PRD §3.10: "Step one, `allowed_amount` is the claim's `units` multiplied by
    that per-unit figure. Step two, `contractual_adjustment_amount` is `billed_amount`
    less `allowed_amount`, floored at `0.00`. Step three,
    `deductible_applied_amount` is the smaller of `allowed_amount` and the coverage's
    remaining deductible — its `deductible_total` less its `deductible_met` — floored
    at `0.00`. Step four, the post-deductible balance is `allowed_amount` less
    `deductible_applied_amount`. Step five, `coinsurance_amount` is that balance
    multiplied by the payer's `coinsurance_rate`. Step six, `plan_paid_amount` is that
    balance less `coinsurance_amount`. Step seven, `patient_responsibility_amount` is
    `deductible_applied_amount` plus `coinsurance_amount`."
    PRD §3.10: "Worked through: three timed units billed at 126.00 against a 34.00
    per-unit allowed figure, with 50.00 of deductible left and a coinsurance rate of
    0.20, yields a plan payment of 41.60 and a patient responsibility of 60.40."
    PRD §3.10: "Under the medical arm, the coverage's `deductible_met` rises by the
    `deductible_applied_amount` just applied."
    PRD §3.10: "And when the claim names a `session_id`, that session's billing axis
    moves `CLAIMED → SETTLED`, bumping the session's `version`."

    Design: Difficulty/dual_variant_calc/claim_money_medical_versus_vision_same_encounter
    """
    scn, first, _second = _scenario_with_both_coverages()
    claim = open_claim(scn, service_date="2026-06-02", session_id=first["id"])
    assert_money(claim["billed_amount"], 126.00, "billed_amount")
    submit_claim(scn, claim["id"])
    get_success_data(api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"]))

    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, scn["hdr_biller"]), 200
    )

    assert paid["adjudication_variant"] == "MEDICAL"
    assert_money(paid["deductible_applied_amount"], 50.00, "deductible_applied_amount")
    assert_money(paid["coinsurance_amount"], 10.40, "coinsurance_amount")
    assert_money(paid["plan_paid_amount"], 41.60, "plan_paid_amount")
    assert_money(paid["patient_responsibility_amount"], 60.40, "patient_responsibility_amount")
    assert_money(paid["contractual_adjustment_amount"], 24.00, "contractual_adjustment_amount")
    assert_claim_dollar_identity(paid)

    assert_money(read_coverage(scn["cov_med"])["deductible_met"], 200.00, "deductible_met")
    assert read_session(first["id"])["billing_status"] == "SETTLED"


def test_the_vision_arm_pays_the_whole_encounter_out_of_the_allowance(api):
    """PRD §3.10: "Step one, `allowed_amount` is the smaller of the claim's
    `billed_amount` and the coverage's `vision_allowance_remaining`. Step two,
    `contractual_adjustment_amount` is `0.00`. Step three,
    `deductible_applied_amount` is `0.00`. Step four, the post-deductible balance is
    simply `allowed_amount`. Step five, `coinsurance_amount` is `0.00`. Step six,
    `plan_paid_amount` is `allowed_amount`. Step seven,
    `patient_responsibility_amount` is the claim's `billed_amount` less
    `allowed_amount` — every dollar above the remaining allowance falls on the
    patient."
    PRD §3.10: "The same 126.00 encounter against a remaining allowance of 250.00
    yields a plan payment of 126.00 and a patient responsibility of 0.00."
    PRD §3.10: "Under the vision arm, the coverage's `vision_allowance_used` rises by
    `plan_paid_amount`, `vision_allowance_remaining` falls by the same figure, and the
    last-paid date matching the claim's `service_class` —
    `last_paid_service_date_therapy` or `last_paid_service_date_evaluation` — is set
    to the claim's `service_date`."

    Design: Difficulty/dual_variant_calc/claim_money_medical_versus_vision_same_encounter
    """
    scn, _first, second = _scenario_with_both_coverages()
    claim = open_claim(
        scn,
        service_date="2026-06-03",
        coverage_id=scn["cov_vis"],
        session_id=second["id"],
    )
    assert_money(claim["billed_amount"], 126.00, "billed_amount")
    submit_claim(scn, claim["id"])
    get_success_data(api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"]))

    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, scn["hdr_biller"]), 200
    )

    assert paid["adjudication_variant"] == "VISION"
    assert_money(paid["plan_paid_amount"], 126.00, "plan_paid_amount")
    assert_money(paid["patient_responsibility_amount"], 0.00, "patient_responsibility_amount")
    assert_money(paid["contractual_adjustment_amount"], 0.00, "contractual_adjustment_amount")
    assert_claim_dollar_identity(paid)

    coverage = read_coverage(scn["cov_vis"])
    assert_money(coverage["vision_allowance_used"], 126.00, "vision_allowance_used")
    assert_money(coverage["vision_allowance_remaining"], 124.00, "vision_allowance_remaining")
    assert coverage["last_paid_service_date_therapy"] == "2026-06-03"
    assert_vision_allowance_identity(coverage)
    assert read_session(second["id"])["billing_status"] == "SETTLED"


def _denied_medical_claim(api, scn, session_id):
    claim = open_claim(scn, service_date="2026-06-10", session_id=session_id)
    submit_claim(scn, claim["id"])
    get_success_data(api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"]))
    return get_success_data(
        api.adjudicate_claim(
            claim["id"],
            {"outcome": "DENIED", "denial_reason": "Medical necessity"},
            scn["hdr_biller"],
        )
    )


def test_a_denied_claim_can_be_appealed_twice_back_into_submitted(api):
    """PRD §3.10: "If `appeal_count` is still below 2, the appeal proceeds:
    `appeal_count` increments by 1 and the claim moves `DENIED → SUBMITTED` for a
    second look."
    PRD §3.10: "From `SUBMITTED`, an outcome of `ACCEPTED` moves the claim to
    `ACCEPTED` and an outcome of `REJECTED` moves it to `REJECTED`, recording
    `denial_reason`; neither computes money. From `ACCEPTED`, an outcome of `PAID` or
    `DENIED` runs the money waterfall and moves the claim to `PAID` or `DENIED`
    respectively."

    Design: Difficulty/non_linear_state_machine/claim_capped_appeal_cycle_denied_to_submitted_to_denied
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    denied = _denied_medical_claim(api, scn, session["id"])
    assert denied["status"] == "DENIED"

    first_appeal = validate_success(
        api.appeal_claim(denied["id"], scn["hdr_biller"], {"appeal_reason": "Chart notes attached"}),
        200,
    )
    assert first_appeal["status"] == "SUBMITTED"
    assert first_appeal["appeal_count"] == 1

    get_success_data(api.adjudicate_claim(denied["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"]))
    get_success_data(
        api.adjudicate_claim(
            denied["id"],
            {"outcome": "DENIED", "denial_reason": "Medical necessity"},
            scn["hdr_biller"],
        )
    )

    second_appeal = validate_success(
        api.appeal_claim(denied["id"], scn["hdr_biller"], {"appeal_reason": "Chart notes attached"}),
        200,
    )
    assert second_appeal["status"] == "SUBMITTED"
    assert second_appeal["appeal_count"] == 2


def test_the_third_appeal_is_refused_but_its_attempt_is_still_recorded(api):
    """PRD §3.10: "Every appeal call, successful or not, first increments
    `appeal_attempt_log_count` by 1, stamps `last_appeal_attempt_at` with the clock
    and bumps the claim's `version`; those three writes are committed before the cap
    is evaluated."
    PRD §3.10: "If `appeal_count` has already reached 2, the call fails with
    `ERR_APPEAL_LIMIT_REACHED` — and the three bookkeeping writes still stand, so a
    refused appeal is durably recorded."

    Design: Difficulty/non_linear_state_machine/claim_capped_appeal_cycle_denied_to_submitted_to_denied
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    claim = _denied_medical_claim(api, scn, session["id"])

    for _ in range(2):
        get_success_data(
            api.appeal_claim(claim["id"], scn["hdr_biller"], {"appeal_reason": "Chart notes attached"})
        )
        get_success_data(
            api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"])
        )
        get_success_data(
            api.adjudicate_claim(
                claim["id"],
                {"outcome": "DENIED", "denial_reason": "Medical necessity"},
                scn["hdr_biller"],
            )
        )

    response = api.appeal_claim(claim["id"], scn["hdr_biller"], {"appeal_reason": "Third try"})

    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)
    stored = validate_success(api.get_claim(claim["id"], scn["hdr_biller"]), 200)
    assert stored["appeal_count"] == 2
    assert stored["appeal_attempt_log_count"] == 3
    assert stored["last_appeal_attempt_at"] is not None
    assert stored["status"] == "DENIED"


def test_moving_the_clock_past_the_end_dates_terminates_and_expires(api):
    """PRD §2.5: "First, every `Authorization` whose `window_end_date` now lies
    strictly in the past and whose `status` is `ACTIVE` or `EXHAUSTED` moves to
    `EXPIRED`, bumping that authorization's `version`. Second, every `Coverage` whose
    `effective_end_date` now lies strictly in the past and whose `status` is `ACTIVE`
    moves to `TERMINATED`."
    PRD §2.5: "Both comparisons are on the calendar date, and both windows are
    inclusive of their end date: a clock sitting exactly on `window_end_date` has not
    passed it and expires nothing."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_terminated_coverage
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    open_claim(scn, service_date="2026-06-10", session_id=session["id"])

    set_clock("2027-01-05T00:00:00Z")

    assert read_coverage(scn["cov_med"])["status"] == "TERMINATED"
    assert read_authorization(scn["auth"])["status"] == "EXPIRED"


def test_submitting_a_claim_against_a_terminated_coverage_is_refused(api):
    """PRD §3.10: "Submission moves the claim `DRAFT → SUBMITTED` and stamps
    `submitted_by_user_id` with the acting `X-User-ID`. The coverage behind the claim
    must be in `status` `ACTIVE` at that moment, or the submission is refused with
    `ERR_INVALID_STATE` — a coverage the clock has already terminated cannot be billed
    against."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_blocked_by_terminated_coverage
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    claim = open_claim(scn, service_date="2026-06-10", session_id=session["id"])
    set_clock("2027-01-05T00:00:00Z")

    response = api.submit_claim(claim["id"], scn["hdr_biller"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(api.get_claim(claim["id"], scn["hdr_biller"]), 200)
    assert stored["status"] == "DRAFT"
    assert stored["submitted_by_user_id"] is None


def test_an_untouched_deductible_absorbs_the_whole_allowed_amount(api):
    """PRD §3.10: "Step three, `deductible_applied_amount` is the smaller of
    `allowed_amount` and the coverage's remaining deductible — its `deductible_total`
    less its `deductible_met` — floored at `0.00`."
    PRD §3.10: "Step six, `plan_paid_amount` is that balance less
    `coinsurance_amount`. Step seven, `patient_responsibility_amount` is
    `deductible_applied_amount` plus `coinsurance_amount`."
    PRD §2.10: "On every adjudicated `Claim` row, `billed_amount` equals
    `plan_paid_amount` plus `patient_responsibility_amount` plus
    `contractual_adjustment_amount` plus `denied_amount`."

    Design: Corner/calculations/medical_claim_with_untouched_deductible_absorbs_the_whole_allowed_amount
    """
    scn = setup_active_plan(
        coverage_overrides={
            "member_number": "M-1001",
            "deductible_total": 200.00,
            "deductible_met": 0.00,
        }
    )
    session = deliver_session(scn)
    claim = open_claim(scn, service_date="2026-06-10", session_id=session["id"])
    assert_money(claim["billed_amount"], 126.00, "billed_amount")
    submit_claim(scn, claim["id"])
    get_success_data(api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, scn["hdr_biller"]))

    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, scn["hdr_biller"]), 200
    )

    assert_money(paid["allowed_amount"], 102.00, "allowed_amount")
    assert_money(paid["deductible_applied_amount"], 102.00, "deductible_applied_amount")
    assert_money(paid["coinsurance_amount"], 0.00, "coinsurance_amount")
    assert_money(paid["plan_paid_amount"], 0.00, "plan_paid_amount")
    assert_money(paid["patient_responsibility_amount"], 102.00, "patient_responsibility_amount")
    assert_money(paid["contractual_adjustment_amount"], 24.00, "contractual_adjustment_amount")
    assert_money(paid["denied_amount"], 0.00, "denied_amount")
    assert_claim_dollar_identity(paid)
    assert_money(read_coverage(scn["cov_med"])["deductible_met"], 102.00, "deductible_met")


def test_a_claim_may_not_be_corrected_by_the_operator_who_submitted_it(api):
    """PRD §3.10: "The operator correcting the claim must not be the operator who
    submitted it: when `X-User-ID` equals the claim's `submitted_by_user_id` the
    correction is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.10: "When the correction supplies `corrected_units`, the claim's `units` is
    overwritten with that figure and `billed_amount` is recomputed as the new `units`
    multiplied by the same clinic rate for the claim's `procedure_code`, rounded
    half-up to two decimals; when it does not, both are left alone."
    PRD §3.10: "A claim in `REJECTED` or `DENIED` may be corrected back to `DRAFT`,
    optionally recording a `correction_reason`, and `correction_count` increments by
    1."

    Design: Corner/validations/claim_correction_requires_a_different_operator_than_the_submitter
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    submitter = make_billing_specialist_headers("biller-1")
    adjudicator = make_billing_specialist_headers("biller-9")
    corrector = make_billing_specialist_headers("biller-2")

    claim = open_claim(
        scn, service_date="2026-06-10", session_id=session["id"], headers=submitter
    )
    submitted = get_success_data(api.submit_claim(claim["id"], submitter))
    assert submitted["submitted_by_user_id"] == "biller-1"
    get_success_data(api.adjudicate_claim(claim["id"], {"outcome": "ACCEPTED"}, adjudicator))
    get_success_data(
        api.adjudicate_claim(
            claim["id"], {"outcome": "DENIED", "denial_reason": "Documentation"}, adjudicator
        )
    )

    self_correction = api.correct_claim(
        claim["id"], {"correction_reason": "Wrong unit count"}, submitter
    )
    validate_error(self_correction, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    corrected = validate_success(
        api.correct_claim(
            claim["id"],
            {"correction_reason": "Wrong unit count", "corrected_units": 2},
            corrector,
        ),
        200,
    )
    assert corrected["status"] == "DRAFT"
    assert corrected["correction_count"] == 1
    assert corrected["units"] == 2
    assert_money(corrected["billed_amount"], 84.00, "billed_amount")


def test_a_vision_claim_inside_the_frequency_interval_is_refused(api):
    """PRD §3.10: "And when the coverage's payer is of `payer_type` `VISION` and the
    stored last-paid date for this class — `last_paid_service_date_therapy` for a
    `THERAPY_SESSION` claim, `last_paid_service_date_evaluation` for an `EVALUATION`
    claim — is not null, the whole months from that date to the claim's `service_date`
    must be at least the payer's `frequency_limit_months`, or the claim is refused
    with `ERR_VISION_FREQUENCY_LIMIT`."
    PRD §3.3: "a `frequency_limit_months` giving the minimum whole months a vision
    plan requires between two paid services of the same class."

    Design: Corner/validations/vision_frequency_limit_blocks_a_claim_inside_the_interval
    """
    scn = setup_active_plan()
    vision_payer = new_vision_payer()
    vision_coverage = new_coverage(
        scn["pt"],
        vision_payer["id"],
        member_number="V-1",
        vision_allowance_total=250.00,
        last_paid_service_date_therapy="2026-03-01",
    )
    session = deliver_session(scn)

    response = api.create_claim(
        create_claim_payload(
            scn["pt"],
            vision_coverage["id"],
            "THERAPY_SESSION",
            "2026-06-10",
            coverage_version(vision_coverage["id"]),
            session_id=session["id"],
        ),
        scn["hdr_biller"],
    )

    validate_error(response, ApiErrorId.ERR_VISION_FREQUENCY_LIMIT.value, 422)
    assert read_session(session["id"])["billing_status"] == "BILLABLE"
    coverage = read_coverage(vision_coverage["id"])
    assert_money(coverage["vision_allowance_remaining"], 250.00, "vision_allowance_remaining")


def test_a_second_claim_on_the_same_session_is_refused_as_a_duplicate(api):
    """PRD §2.7 rung 29: "**Claim uniqueness.** At most one claim exists per
    `session_id` and at most one per `assessment_id`, regardless of the existing
    claim's status. Otherwise `ERR_DUPLICATE_CLAIM`, HTTP 409. Applies to claim
    creation."
    PRD §3.10: "At most one claim may exist for any given `session_id`, and at most
    one for any given `assessment_id`, regardless of what state the existing claim is
    in — a second attempt is `ERR_DUPLICATE_CLAIM`."

    Design: Corner/validations/second_claim_on_the_same_session_rejected_as_duplicate
    """
    scn = setup_active_plan()
    session = deliver_session(scn)
    open_claim(scn, service_date="2026-06-10", session_id=session["id"])

    response = api.create_claim(
        create_claim_payload(
            scn["pt"],
            scn["cov_med"],
            "THERAPY_SESSION",
            "2026-06-10",
            coverage_version(scn["cov_med"]),
            session_id=session["id"],
        ),
        scn["hdr_biller"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)
    rows, meta = validate_paginated(
        api.list_claims(scn["hdr_biller"], {"session_id": session["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1 and len(rows) == 1
