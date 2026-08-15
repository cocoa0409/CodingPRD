"""Case intake, eligibility gating, the marketing period, creditable days, and
the withdrawal cascade (PRD §2.4, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_marketing_listing,
    assert_same_instant,
    assert_workout_case,
    board_loan,
    create_listing_payload,
    get_case,
    get_listing,
    get_loan,
    open_workout_case,
    register_borrower,
    set_clock,
    setup_case_at_agreement_active,
    setup_case_at_marketing_period,
    setup_case_at_terms_negotiation,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_case_born_in_intake(api, specialist_headers):
    """A newly opened case is INTAKE and freezes the creator's X-User-ID.

    PRD §3.2: "The case is born in `INTAKE`, with the creating specialist's `X-User-ID` frozen into the immutable `assigned_specialist_id`."

    Design: Corner/state_machines/case_starts_in_intake
    """
    loan = board_loan("LN-S1", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    borrower = register_borrower(full_name="S. One", email="s1@x.com", hardship_type="NONE",
                                 self_reported_condition_grade="A")
    case = validate_success(
        api.create_case(
            {"loan_id": loan["id"], "borrower_id": borrower["id"], "program_type": "DEED_IN_LIEU"},
            specialist_headers,
        ),
        201,
    )
    assert_workout_case(case)
    assert case["status"] == "INTAKE"
    assert case["assigned_specialist_id"] == "spec_1"
    assert case["loan_id"] == loan["id"] and case["borrower_id"] == borrower["id"]


def test_certify_title_from_marketing_period_rejected(api, specialist_headers):
    """certify-title requires TITLE_REVIEW; from MARKETING_PERIOD it is a state error.

    PRD §3.4: "Certifying title moves the case from `TITLE_REVIEW` to `TERMS_NEGOTIATION` and increments the case's `version`."
    PRD §3.2: "Any case action attempted from the wrong state is refused with `ERR_CASE_INVALID_STATE`."

    Design: Corner/state_machines/certify_title_from_marketing_period_rejected
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-S2", with_listing=False)
    case_id = bundle["case"]["id"]
    assert bundle["case"]["status"] == "MARKETING_PERIOD"

    resp = api.certify_title(case_id, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)
    assert get_case(case_id)["status"] == "MARKETING_PERIOD"


def test_declined_case_terminal_lockdown(api, specialist_headers):
    """A FAIL decision declines the case (terminal), returns the loan, and any
    further action is refused.

    PRD §3.2: "A failing one moves the case to `DECLINED` and returns the loan from `WORKOUT_IN_PROGRESS` to `ACTIVE_DELINQUENT`, again incrementing both versions."
    PRD §3.2: "of which `COMPLETED`, `DECLINED`, `WITHDRAWN`, and `CLOSED_EVICTED` are terminal and reject every further action with `ERR_CASE_INVALID_STATE`."

    Design: Corner/state_machines/declined_case_terminal_lockdown_rejected
    """
    loan = board_loan("LN-S3", accrued_interest_cents=0, escrow_advances_cents=0,
                      foreclosure_fees_cents=0, delinquency_days=10)
    borrower = register_borrower(full_name="S. Three", email="s3@x.com", hardship_type="NONE",
                                 self_reported_condition_grade="C")
    case = open_workout_case(loan["id"], borrower["id"], "DEED_IN_LIEU")
    validate_success(api.submit_case(case["id"], specialist_headers))
    declined = validate_success(
        api.evaluate_eligibility(case["id"], {"decision": "FAIL"}, specialist_headers)
    )
    assert declined["status"] == "DECLINED"
    assert get_loan(loan["id"])["status"] == "ACTIVE_DELINQUENT"

    resp = api.submit_case(case["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)
    assert get_case(case["id"])["status"] == "DECLINED"


def test_eligibility_gate_delinquency_30_vs_31(api, specialist_headers):
    """PASS requires at least 31 days delinquent: 30 fails the gate, 31 passes.

    PRD §3.2: "A `PASS` decision is gated on the loan's posture: the loan must be at least 31 days delinquent, and its foreclosure referral must not be `ACTIVE`; a `PASS` attempted against those gates fails with `ERR_ELIGIBILITY_CRITERIA_NOT_MET`."

    Design: Corner/validations/eligibility_gate_delinquency_30_vs_31
    """
    loan_30 = board_loan("LN-V1", accrued_interest_cents=0, escrow_advances_cents=0,
                         foreclosure_fees_cents=0, delinquency_days=30)
    loan_31 = board_loan("LN-V2", accrued_interest_cents=0, escrow_advances_cents=0,
                         foreclosure_fees_cents=0, delinquency_days=31)
    bor_1 = register_borrower(full_name="V. One", email="v1@x.com", hardship_type="NONE",
                              self_reported_condition_grade="A")
    bor_2 = register_borrower(full_name="V. Two", email="v2@x.com", hardship_type="NONE",
                              self_reported_condition_grade="A")
    case_30 = open_workout_case(loan_30["id"], bor_1["id"], "DEED_IN_LIEU")
    case_31 = open_workout_case(loan_31["id"], bor_2["id"], "DEED_IN_LIEU")
    validate_success(api.submit_case(case_30["id"], specialist_headers))
    validate_success(api.submit_case(case_31["id"], specialist_headers))

    resp = api.evaluate_eligibility(case_30["id"], {"decision": "PASS"}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_CRITERIA_NOT_MET.value)
    assert get_case(case_30["id"])["status"] == "ELIGIBILITY_REVIEW"

    passed = validate_success(api.evaluate_eligibility(case_31["id"], {"decision": "PASS"}, specialist_headers))
    assert passed["status"] == "MARKETING_PERIOD"


def test_marketing_certification_89_days_rejected(api, specialist_headers):
    """At 89 creditable days the marketing minimum (90) is not yet met.

    PRD §3.3: "Then the marketing minimum applies: the most recently created listing must show at least 90 creditable days, unless a marketing exception has been granted on the case; failing both alternatives yields `ERR_MARKETING_PERIOD_NOT_MET`."

    Design: Difficulty/boundary_precision_check/marketing_days_89_vs_90
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-BP1")
    case_id = bundle["case"]["id"]
    set_clock("2026-07-29T00:00:00Z")  # 89 whole days after the 2026-05-01 list_date

    resp = api.certify_marketing(case_id, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_MARKETING_PERIOD_NOT_MET.value)
    assert get_case(case_id)["status"] == "MARKETING_PERIOD"


def test_marketing_certification_exactly_90_days_passes(api, specialist_headers):
    """At exactly 90 creditable days the gate admits the case to TITLE_REVIEW.

    PRD §3.3: "Then the marketing minimum applies: the most recently created listing must show at least 90 creditable days, unless a marketing exception has been granted on the case; failing both alternatives yields `ERR_MARKETING_PERIOD_NOT_MET`."
    PRD §3.3: "A successful certification advances the case to `TITLE_REVIEW` and increments its `version`."

    Design: Difficulty/boundary_precision_check/marketing_days_89_vs_90
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-BP1")
    case_id = bundle["case"]["id"]
    set_clock("2026-07-30T00:00:00Z")  # exactly 90 whole days after 2026-05-01

    listing = validate_success(api.get_listing(bundle["listing"]["id"], specialist_headers))
    assert listing["creditable_days"] == 90, (
        f"span 2026-05-01..2026-07-30 must be 90 creditable days, got {listing['creditable_days']}"
    )
    certified = validate_success(api.certify_marketing(case_id, specialist_headers))
    assert certified["status"] == "TITLE_REVIEW"


def test_marketing_exception_overrides_days(api, specialist_headers, workout_manager_headers):
    """The 90-day minimum is conditional: a WorkoutManager exception waives it.

    PRD §3.3: "Then the marketing minimum applies: the most recently created listing must show at least 90 creditable days, unless a marketing exception has been granted on the case; failing both alternatives yields `ERR_MARKETING_PERIOD_NOT_MET`."
    PRD §3.2: "During the marketing stage a `WorkoutManager` may grant a marketing-period exception, supplying a `reason`; the grant sets `marketing_exception_granted` to true and preserves the reason in `marketing_exception_reason`, incrementing the case's `version`."

    Design: Corner/validations/marketing_exception_overrides_days
    """
    bundle = setup_case_at_marketing_period(
        loan_number="LN-V3", program_type="CASH_FOR_KEYS",
        borrower_overrides={"full_name": "V. Three", "email": "v3@x.com", "hardship_type": "NONE",
                            "self_reported_condition_grade": "A"},
    )
    case_id = bundle["case"]["id"]
    set_clock("2026-05-21T00:00:00Z")  # only 20 creditable days

    resp = api.certify_marketing(case_id, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_MARKETING_PERIOD_NOT_MET.value)

    granted = validate_success(
        api.grant_marketing_exception(
            case_id, {"reason": "property not legally listable during probate hold"}, workout_manager_headers
        )
    )
    assert granted["marketing_exception_granted"] is True
    assert granted["marketing_exception_reason"] == "property not legally listable during probate hold"

    certified = validate_success(api.certify_marketing(case_id, specialist_headers))
    assert certified["status"] == "TITLE_REVIEW"


def test_active_listing_exists_rejected(api, specialist_headers):
    """A second listing while one is ACTIVE violates the one-open-listing rule.

    PRD §3.3: "Only one non-`CLOSED` listing may exist per case — attempting to create a second while one is `ACTIVE` or `SUSPENDED` is rejected with `ERR_ACTIVE_LISTING_EXISTS`."

    Design: Corner/validations/active_listing_exists_rejected
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-V9")
    resp = api.create_listing(
        create_listing_payload(bundle["case"]["id"], list_price_cents=18500000), specialist_headers
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_LISTING_EXISTS.value)
    listings = validate_paginated(api.list_case_listings(bundle["case"]["id"], specialist_headers))[0]
    assert len(listings) == 1


def test_clock_default_listing_creditable_days(api, specialist_headers):
    """Without any clock adjustment the logical clock reads 2026-08-01: a listing
    dated that day shows zero creditable days and a future list_date is malformed.

    PRD §2.4: "Before any explicit adjustment the clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time."
    PRD §3.3: "the payload carries the `case_id`, the `list_date` (which must not lie in the future relative to the logical clock), and the `list_price_cents` (strictly greater than zero)."
    PRD §3.3: "First, the raw span is the number of whole days from `list_date` to the evaluation date, floored at zero."

    Design: Corner/cross_cutting_layers/clock_default_is_fixed
    """
    # NB: no set_clock call anywhere in this test — the default clock holds.
    loan = board_loan("LN-L4", accrued_interest_cents=0, escrow_advances_cents=0, foreclosure_fees_cents=0)
    borrower = register_borrower(full_name="L. Four", email="l4@x.com", hardship_type="NONE",
                                 self_reported_condition_grade="A")
    case = open_workout_case(loan["id"], borrower["id"], "DEED_IN_LIEU")
    validate_success(api.submit_case(case["id"], specialist_headers))
    validate_success(api.evaluate_eligibility(case["id"], {"decision": "PASS"}, specialist_headers))

    listing = validate_success(
        api.create_listing(create_listing_payload(case["id"], list_date="2026-08-01"), specialist_headers), 201
    )
    assert_marketing_listing(listing)
    assert listing["creditable_days"] == 0, (
        f"list_date equal to the default clock date must yield 0 creditable days, got {listing['creditable_days']}"
    )

    resp = api.create_listing(create_listing_payload(case["id"], list_date="2026-08-02"), specialist_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_open_suspension_clamped_at_evaluation(api, specialist_headers):
    """An open suspension counts through the evaluation date: span 92 minus the
    clamped 61 suspended days leaves 31 creditable days.

    PRD §3.3: "Second, every suspension interval is clamped to the window from `list_date` to the evaluation date, and an open suspension — one whose `ended_at` is still null — is treated as ending on the evaluation date."
    PRD §3.3: "Finally, `creditable_days` is the span minus the suspended days, floored at zero."

    Design: Difficulty/resource_temporal_overlap/listing_open_suspension_clamped_at_eval
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-OV1")
    listing_id = bundle["listing"]["id"]
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.suspend_listing(listing_id, {"reason": "title objection"}, specialist_headers))
    set_clock("2026-08-01T00:00:00Z")

    listing = validate_success(api.get_listing(listing_id, specialist_headers))
    assert listing["status"] == "SUSPENDED"
    assert listing["creditable_days"] == 31, (
        f"span 92 minus open suspension clamped to 61 must give 31, got {listing['creditable_days']}"
    )
    suspensions = validate_paginated(api.list_listing_suspensions(listing_id, specialist_headers))[0]
    assert len(suspensions) == 1
    assert suspensions[0]["ended_at"] is None, "suspension is still open yet its days count through eval"


def test_open_suspension_blocks_marketing_certification(api, specialist_headers):
    """With the open suspension clamped, 31 creditable days fails the 90-day gate.

    PRD §3.3: "Second, every suspension interval is clamped to the window from `list_date` to the evaluation date, and an open suspension — one whose `ended_at` is still null — is treated as ending on the evaluation date."
    PRD §3.3: "Then the marketing minimum applies: the most recently created listing must show at least 90 creditable days, unless a marketing exception has been granted on the case; failing both alternatives yields `ERR_MARKETING_PERIOD_NOT_MET`."

    Design: Difficulty/resource_temporal_overlap/listing_open_suspension_clamped_at_eval
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-OV1")
    listing_id = bundle["listing"]["id"]
    case_id = bundle["case"]["id"]
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.suspend_listing(listing_id, {"reason": "title objection"}, specialist_headers))
    set_clock("2026-08-01T00:00:00Z")

    resp = api.certify_marketing(case_id, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_MARKETING_PERIOD_NOT_MET.value)
    assert get_case(case_id)["status"] == "MARKETING_PERIOD"


def test_listing_close_closes_suspension_and_freezes(api, specialist_headers):
    """Closing a SUSPENDED listing stamps the open suspension's ended_at and
    freezes creditable_days (31) against later clock movement.

    PRD §3.3: "Closing — whether from `ACTIVE` or from `SUSPENDED` — moves the listing to `CLOSED`, closes any open suspension the same way, and freezes `creditable_days` at its closing value."
    PRD §3.3: "for a `CLOSED` listing the evaluation date is the closing date, so the value stays frozen."

    Design: Corner/state_machines/listing_close_closes_open_suspension
    """
    bundle = setup_case_at_marketing_period(loan_number="LN-S6")
    listing_id = bundle["listing"]["id"]
    set_clock("2026-06-01T00:00:00Z")
    validate_success(api.suspend_listing(listing_id, {"reason": "title objection"}, specialist_headers))
    set_clock("2026-06-11T00:00:00Z")

    closed = validate_success(api.close_listing(listing_id, specialist_headers))
    assert closed["status"] == "CLOSED"
    assert closed["creditable_days"] == 31, (
        f"span 41 minus 10 suspended days must freeze at 31, got {closed['creditable_days']}"
    )

    set_clock("2026-08-01T00:00:00Z")
    reread = validate_success(api.get_listing(listing_id, specialist_headers))
    assert reread["creditable_days"] == 31, "CLOSED listing must keep its frozen closing value"

    suspensions = validate_paginated(api.list_listing_suspensions(listing_id, specialist_headers))[0]
    assert len(suspensions) == 1
    assert_same_instant(suspensions[0]["ended_at"], "2026-06-11T00:00:00Z", "suspension ended_at")


def test_withdraw_from_agreement_active_cascades(api, specialist_headers):
    """Withdrawal resolves every dependent resource into its terminal state.

    PRD §3.2: "Withdrawal is a deep cascade: any agreement of the case in `DRAFT`, `OFFERED`, `COUNTERED`, or `ACCEPTED` moves to `TERMINATED`; any listing in `ACTIVE` or `SUSPENDED` moves to `CLOSED`; any disbursement in `PENDING` or `APPROVED` moves to `VOIDED`; the loan falls back from `WORKOUT_IN_PROGRESS` to `ACTIVE_DELINQUENT`; and when the case had been in `HOLDOVER_ESCALATED`, any eviction case still `ESCALATED` is dismissed with `dismissal_reason` `OTHER`."

    Design: Corner/state_machines/withdraw_cascades_to_children
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-S7")
    case_id = bundle["case"]["id"]
    assert bundle["case"]["status"] == "AGREEMENT_ACTIVE"

    withdrawn = validate_success(api.withdraw_case(case_id, specialist_headers))
    assert withdrawn["status"] == "WITHDRAWN"
    agreement = validate_success(api.get_agreement(bundle["agreement"]["id"], specialist_headers))
    assert agreement["status"] == "TERMINATED"
    listing = validate_success(api.get_listing(bundle["listing"]["id"], specialist_headers))
    assert listing["status"] == "CLOSED"
    assert get_loan(bundle["loan"]["id"])["status"] == "ACTIVE_DELINQUENT"
