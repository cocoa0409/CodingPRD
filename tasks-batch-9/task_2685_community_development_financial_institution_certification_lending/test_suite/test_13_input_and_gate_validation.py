"""Rejections: uniqueness, fiscal ceilings, tiers, bounds, pages and gates.

Every case here drives a well-formed request into a rule that refuses it, and
checks that the refusal left nothing half-written behind.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_match_shortfall_invariant
from test_helpers.fixtures import (
    ADMINISTRATOR,
    ANALYST,
    COMMITTEE,
    REVIEWER,
    SECOND_REVIEWER,
    UNDERWRITER,
)


def test_a_second_registration_of_the_same_number_is_refused():
    """An employer identification number may sit on only one lender.

    PRD: "An `InstitutionOfficer` brings a candidate lender onto the platform by
    registering it with its registered `legal_name`, its `ein` — an employer
    identification number that must be exactly nine digits and must not already
    be on file for another institution, on pain of `ERR_DUPLICATE_EIN` — and its
    charter form in `entity_type`, which is one of `LOAN_FUND`, `CREDIT_UNION`,
    `BANK_HOLDING` or `VENTURE_FUND`."
    PRD: "**Business constraint**, in this order:
    employer-identification-number uniqueness on institution registration
    (`ERR_DUPLICATE_EIN`, HTTP 409)."

    Design: Corner/validations/duplicate_ein_on_a_second_institution_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    first = fixtures.create_institution(
        legal_name="Harborline Community Fund", ein="210000026"
    )

    duplicate = api_client.create_institution(
        factories.institution_payload(
            legal_name="Copycat Community Fund", ein="210000026"
        ),
        fixtures.make_institution_officer_headers(first["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_EIN)

    survivor = fixtures.read_institution(first["id"])
    assert survivor["legal_name"] == "Harborline Community Fund"
    assert survivor["ein"] == "210000026"
    assert survivor["version"] == 1

    _rows, meta = validate_paginated(api_client.list_institutions(ANALYST))
    assert meta["total_count"] == 1, "the duplicate never became a row"


def test_the_three_fiscal_ceilings_refuse_each_overrun_in_turn():
    """The cap bounds the approval, the approval the advance, the balance the payment.

    PRD: "**Fiscal**, in this order: the product cap on loan approval
    (`ERR_PRODUCT_CAP_EXCEEDED`, HTTP 422); the approved-principal ceiling on
    disbursement (`ERR_DISBURSEMENT_EXCEEDS_APPROVED`, HTTP 422); the
    outstanding-balance ceiling on payment (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`,
    HTTP 422); the zero-shortfall requirement on draw activation
    (`ERR_MATCH_SHORTFALL`, HTTP 422); and the federal-source exclusion on
    commitment verification (`ERR_FEDERAL_SOURCE_INELIGIBLE`, HTTP 422)."
    PRD: "The advance is refused with `ERR_DISBURSEMENT_EXCEEDS_APPROVED` when
    `principal_disbursed_cents` plus `amount_cents` would exceed
    `approved_principal_cents`."
    PRD: "A payment exceeding `principal_outstanding_cents` is refused with
    `ERR_PAYMENT_EXCEEDS_OUTSTANDING`."

    Design: Corner/validations/fiscal_ceilings_reject_approval_disbursement_and_payment_overruns
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution(
        product_overrides={
            "name": "Capped Small Business Loan",
            "product_cap_cents": 1_000_000,
        }
    )
    institution_id = scenario["institution"]["id"]
    officer = scenario["officer"]
    loan = fixtures.file_loan(
        institution_id, scenario["borrower"]["id"], scenario["product"]["id"],
        2_000_000,
    )
    priced = fixtures.underwrite_loan(loan["id"])
    assert float(priced["dti_pct"]) == 14.83
    assert priced["risk_grade"] == "A"

    over_the_cap = api_client.decide_loan(
        loan["id"],
        {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
        COMMITTEE,
    )
    validate_error(over_the_cap, ApiErrorId.ERR_PRODUCT_CAP_EXCEEDED)

    approved = fixtures.decide_loan(loan["id"], approved_principal_cents=1_000_000)
    assert approved["underwriting_state"] == "APPROVED"
    assert approved["approved_principal_cents"] == 1_000_000

    over_the_approval = api_client.disburse_loan(
        loan["id"], {"amount_cents": 1_200_000}, officer
    )
    validate_error(over_the_approval, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_APPROVED)

    fixtures.disburse_loan(institution_id, loan["id"], 1_000_000)

    over_the_balance = api_client.pay_loan(
        loan["id"], {"amount_cents": 1_000_001}, officer
    )
    validate_error(over_the_balance, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)

    final_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert final_loan["approved_principal_cents"] == 1_000_000
    assert final_loan["principal_disbursed_cents"] == 1_000_000
    assert final_loan["principal_outstanding_cents"] == 1_000_000
    assert final_loan["principal_repaid_cents"] == 0
    assert final_loan["servicing_state"] == "CURRENT"

    product = validate_success(
        api_client.get_loan_product(scenario["product"]["id"], ANALYST)
    )
    assert product["committed_principal_cents"] == 1_000_000, (
        "only the approval that succeeded was committed against the cap"
    )


def test_a_debt_ratio_over_the_product_ceiling_leaves_the_loan_unpriced():
    """The provisional installment is what pushes the ratio past the ceiling.

    PRD: "Before any tier is considered, `dti_pct` must be at or below the
    product's `max_dti_pct`; if it exceeds the ceiling, underwriting is refused
    with `ERR_UNDERWRITING_TIER_UNMET`."
    PRD: "`dti_pct` is then one hundred multiplied by the sum of
    `existing_monthly_debt_cents` and `provisional_monthly_payment_cents`,
    divided by `verified_monthly_income_cents`, rounded half up to two decimal
    places."

    Design: Corner/validations/underwriting_tier_unmet_when_the_provisional_payment_pushes_dti_over_the_ceiling
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution()
    loan = fixtures.file_loan(
        scenario["institution"]["id"], scenario["borrower"]["id"],
        scenario["product"]["id"], 1_000_000,
    )
    assert loan["underwriting_state"] == "SCREENING"

    response = api_client.underwrite_loan(
        loan["id"],
        factories.underwrite_payload(
            verified_monthly_income_cents=200_000,
            existing_monthly_debt_cents=100_000,
            credit_score_at_underwriting=740,
        ),
        UNDERWRITER,
    )
    validate_error(response, ApiErrorId.ERR_UNDERWRITING_TIER_UNMET)

    unchanged = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged["underwriting_state"] == "SCREENING"
    assert unchanged["dti_pct"] is None
    assert unchanged["risk_grade"] is None
    assert unchanged["provisional_monthly_payment_cents"] is None
    assert unchanged["version"] == 1


def test_bounds_ordering_is_checked_before_the_window_is_checked_against_the_clock():
    """A window that is both inverted and unfinished answers with the bounds error.

    PRD: "**Temporal**, in this order: window and slot bounds ordering
    (`ERR_PERIOD_BOUNDS_INVALID`, HTTP 422, guarding measurement creation,
    award-application creation and engagement booking); then the measurement
    window's upper bound against the logical clock
    (`ERR_PERIOD_END_IN_FUTURE`, HTTP 422, guarding measurement creation only)."
    PRD: "`period_end` must be strictly after `period_start`, or the cut is
    refused with `ERR_PERIOD_BOUNDS_INVALID`, and `period_end` must not be later
    than the current logical clock, or it is refused with
    `ERR_PERIOD_END_IN_FUTURE` — an institution cannot be measured over a period
    that has not finished."
    PRD: "`scheduled_end_at` must be strictly after `scheduled_start_at`, and a
    violation is reported as `ERR_PERIOD_BOUNDS_INVALID`."

    Design: Corner/validations/temporal_bounds_and_future_period_end_rejected_with_bounds_winning_when_both_fail
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    borrower = fixtures.create_borrower(institution_id)
    officer = fixtures.make_institution_officer_headers(institution_id)

    empty_window = api_client.create_compliance_measurement(
        institution_id,
        factories.compliance_measurement_payload(
            "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z"
        ),
        ANALYST,
    )
    validate_error(empty_window, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID)

    empty_slot = api_client.create_ta_engagement(
        institution_id,
        factories.ta_engagement_payload(
            borrower["id"], "2026-09-02T09:00:00Z", "2026-09-02T09:00:00Z", 1.00
        ),
        officer,
    )
    validate_error(empty_slot, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID)

    unfinished_window = api_client.create_compliance_measurement(
        institution_id,
        factories.compliance_measurement_payload(
            "2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        ANALYST,
    )
    validate_error(unfinished_window, ApiErrorId.ERR_PERIOD_END_IN_FUTURE)

    both_defects = api_client.create_compliance_measurement(
        institution_id,
        factories.compliance_measurement_payload(
            "2026-10-05T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        ANALYST,
    )
    validate_error(both_defects, ApiErrorId.ERR_PERIOD_BOUNDS_INVALID)

    _windows, window_meta = validate_paginated(
        api_client.list_institution_compliance_measurements(institution_id, ANALYST)
    )
    assert window_meta["total_count"] == 0
    _slots, slot_meta = validate_paginated(
        api_client.list_ta_engagements(ANALYST, {"institution_id": institution_id})
    )
    assert slot_meta["total_count"] == 0


def test_page_sizes_outside_the_accepted_range_are_refused():
    """Zero, one hundred and one, and a negative offset are all out of range.

    PRD: "`limit` controls page size; it defaults to 10 when omitted, and its
    accepted range is a minimum of 1 and a maximum of 100."
    PRD: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected
    with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_bounds_rejected_at_zero_and_above_one_hundred
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    fixtures.create_institution(
        legal_name="Harborline Community Fund", ein="210000027"
    )

    validate_error(
        api_client.list_institutions(ANALYST, {"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )
    validate_error(
        api_client.list_institutions(ANALYST, {"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )
    validate_error(
        api_client.list_institutions(ANALYST, {"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )

    rows, meta = validate_paginated(
        api_client.list_institutions(ANALYST, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert len(rows) == 1


def test_the_submission_ladder_walks_market_then_accountability_then_activity():
    """Each repair exposes the next gate, and the docket stays in draft throughout.

    PRD: "Three substantive gates stand in front of it, and they are evaluated
    in this order after the state check: the institution must have at least one
    target market in `state` `APPROVED`, or the submission fails with
    `ERR_TARGET_MARKET_NOT_APPROVED`; `accountability_satisfied` must be true, or
    it fails with `ERR_ACCOUNTABILITY_NOT_SATISFIED`; and
    `financing_activity_pct_claimed` must be at least 60.00, or it fails with
    `ERR_FINANCING_ACTIVITY_BELOW_MINIMUM`."
    PRD: "Submission moves the docket `DRAFT → SUBMITTED` and records the acting
    officer in `submitted_by_user_id`."

    Design: Corner/validations/submit_gate_ladder_walks_target_market_then_accountability_then_financing_activity
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)
    market = fixtures.create_target_market(
        institution_id, name="South Bronx Investment Area"
    )
    assert market["state"] == "DRAFT"
    application = fixtures.open_certification_application(
        institution_id, financing_activity_pct_claimed=59.99
    )

    validate_error(
        api_client.submit_certification_application(application["id"], officer),
        ApiErrorId.ERR_TARGET_MARKET_NOT_APPROVED,
    )

    validate_success(api_client.approve_target_market(market["id"], REVIEWER))
    validate_error(
        api_client.submit_certification_application(application["id"], officer),
        ApiErrorId.ERR_ACCOUNTABILITY_NOT_SATISFIED,
    )

    fixtures.seat_representing_governing_board(institution_id, market["id"])
    validate_error(
        api_client.submit_certification_application(application["id"], officer),
        ApiErrorId.ERR_FINANCING_ACTIVITY_BELOW_MINIMUM,
    )

    repaired = fixtures.read_institution(institution_id)
    assert float(repaired["accountability_score"]) == 1.0000
    assert repaired["accountability_satisfied"] is True

    docket = validate_success(
        api_client.get_certification_application(application["id"], ANALYST)
    )
    assert docket["state"] == "DRAFT"
    assert docket["submitted_by_user_id"] is None
    assert docket["version"] == 1, "three refusals wrote nothing to the docket"


def test_signing_a_docket_with_one_verdict_still_pending_is_refused():
    """Five settled verdicts are not enough; the sixth must be settled too.

    PRD: "The signing `CertificationReviewer` must present an `X-User-ID`
    different from `reviewed_by_user_id`, or the signature is refused with
    `ERR_SEGREGATION_OF_DUTIES`; the docket must be `UNDER_REVIEW`; and no
    verdict may still be `PENDING`, or the signature is refused with
    `ERR_TEST_VERDICT_PENDING`."
    PRD: "Recording a verdict writes the one matching field —
    `test_primary_mission_state`, `test_financing_entity_state`,
    `test_target_market_state`, `test_development_services_state`,
    `test_accountability_state` or `test_non_government_state` — and leaves the
    application's own `state` at `UNDER_REVIEW`; this is a self-loop that never
    changes state."

    Design: Corner/validations/decide_with_one_verdict_still_pending_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_application_under_review()
    application_id = scenario["application"]["id"]
    for test_code in (
        "PRIMARY_MISSION",
        "FINANCING_ENTITY",
        "TARGET_MARKET",
        "DEVELOPMENT_SERVICES",
        "ACCOUNTABILITY",
    ):
        fixtures.record_certification_verdict(application_id, test_code, "PASSED")

    response = api_client.decide_certification_application(
        application_id, SECOND_REVIEWER
    )
    validate_error(response, ApiErrorId.ERR_TEST_VERDICT_PENDING)

    docket = validate_success(
        api_client.get_certification_application(application_id, ANALYST)
    )
    assert docket["state"] == "UNDER_REVIEW"
    assert docket["test_accountability_state"] == "PASSED"
    assert docket["test_non_government_state"] == "PENDING"
    assert docket["decided_at"] is None

    institution = fixtures.read_institution(scenario["institution"]["id"])
    assert institution["certification_state"] == "UNCERTIFIED"
    assert institution["certified_at"] is None


def test_award_submission_needs_certification_first_and_then_a_pledge():
    """Two gates in order; a merely pledged source clears the second one.

    PRD: "Submission of an award application moves it `DRAFT → SUBMITTED` and is
    gated twice, in this order: the institution's `certification_state` must be
    `CERTIFIED`, failing with `ERR_INSTITUTION_NOT_CERTIFIED`, and the
    application must carry at least one matching-fund commitment of any status,
    failing with `ERR_NO_MATCH_COMMITMENTS`."
    PRD: "At creation, `required_match_cents` is computed as
    `requested_amount_cents` multiplied by `match_ratio_pct` divided by one
    hundred, rounded half up to whole cents; `match_eligible_cents` starts at 0
    and `match_shortfall_cents` therefore starts equal to
    `required_match_cents`."
    PRD: "A pledge is created with `status` `PLEDGED`, `eligible_cents` 0,
    `verified_by_user_id` null and `withdraw_reason` null."
    PRD: "Each commitment is rounded to whole cents on its own first, and only
    the already-rounded per-commitment figures are summed into the award's
    `match_eligible_cents`, which counts commitments in `status` `VERIFIED` only
    — `PLEDGED`, `HELD` and `WITHDRAWN` commitments contribute zero."

    Design: Corner/validations/award_submit_needs_certification_first_then_a_commitment_and_then_succeeds
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.create_accountable_institution()
    institution_id = scenario["institution"]["id"]
    award = fixtures.open_award_application(
        institution_id,
        program="CDFI_PROGRAM_FA",
        requested_amount_cents=1_000_000,
        match_ratio_pct=100.00,
        performance_goal_jobs=40,
        performance_goal_housing_units=12,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    assert award["state"] == "DRAFT"
    assert award["required_match_cents"] == 1_000_000
    assert award["match_eligible_cents"] == 0
    assert award["match_shortfall_cents"] == 1_000_000

    validate_error(
        api_client.submit_award_application(award["id"], ADMINISTRATOR),
        ApiErrorId.ERR_INSTITUTION_NOT_CERTIFIED,
    )

    application = fixtures.open_certification_application(institution_id)
    fixtures.submit_certification_application(institution_id, application["id"])
    fixtures.begin_certification_review(application["id"])
    fixtures.record_all_certification_verdicts(application["id"])
    validate_success(
        api_client.decide_certification_application(
            application["id"], SECOND_REVIEWER
        )
    )
    certified = fixtures.read_institution(institution_id)
    assert certified["certification_state"] == "CERTIFIED"
    assert certified["certified_at"] == "2026-09-01T00:00:00.000Z"

    validate_error(
        api_client.submit_award_application(award["id"], ADMINISTRATOR),
        ApiErrorId.ERR_NO_MATCH_COMMITMENTS,
    )

    commitment = fixtures.pledge_commitment(
        award["id"], source_name="Meridian Foundation",
        source_type="CASH_PRIVATE", amount_cents=1_000_000,
    )
    assert commitment["status"] == "PLEDGED"
    assert commitment["eligible_cents"] == 0
    assert commitment["verified_by_user_id"] is None

    submitted = validate_success(
        api_client.submit_award_application(award["id"], ADMINISTRATOR)
    )
    assert submitted["state"] == "SUBMITTED"
    assert submitted["required_match_cents"] == 1_000_000
    assert submitted["match_eligible_cents"] == 0, (
        "an unverified pledge opens the door without entering the ledger"
    )
    assert submitted["match_shortfall_cents"] == 1_000_000
    assert_match_shortfall_invariant(submitted)


def test_a_federal_source_can_never_be_verified_as_match():
    """The federal exclusion is absolute, not merely a zero factor.

    PRD: "Federal sources count at 0.00 and are in fact never verifiable at all:
    verification of a commitment whose `source_type` is `FEDERAL` is refused with
    `ERR_FEDERAL_SOURCE_INELIGIBLE`."
    PRD: "On success the commitment moves `PLEDGED → VERIFIED`,
    `verified_by_user_id` is recorded, and `eligible_cents` is set to the
    commitment's `amount_cents` multiplied by its source factor and rounded half
    up to whole cents."

    Design: Corner/validations/federal_source_cannot_be_verified_as_matching_funds
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    award = fixtures.open_award_application(
        institution["id"],
        program="CDFI_PROGRAM_TA",
        requested_amount_cents=1_000_000,
        match_ratio_pct=100.00,
        performance_goal_jobs=10,
        performance_goal_housing_units=0,
        period_start="2027-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    commitment = fixtures.pledge_commitment(
        award["id"], source_name="Federal Treasury Grant",
        source_type="FEDERAL", amount_cents=1_000_000,
    )
    assert commitment["eligible_cents"] == 0

    response = api_client.verify_matching_fund_commitment(
        commitment["id"], ADMINISTRATOR
    )
    validate_error(response, ApiErrorId.ERR_FEDERAL_SOURCE_INELIGIBLE)

    unchanged = validate_success(
        api_client.get_matching_fund_commitment(commitment["id"], ADMINISTRATOR)
    )
    assert unchanged["status"] == "PLEDGED"
    assert unchanged["verified_by_user_id"] is None
    assert unchanged["eligible_cents"] == 0

    ledger = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert ledger["match_eligible_cents"] == 0
    assert ledger["match_shortfall_cents"] == 1_000_000
    assert_match_shortfall_invariant(ledger)


def test_finalizing_a_window_with_no_disbursed_loans_is_refused():
    """An empty input set has no percentage to publish.

    PRD: "If the input set is empty, finalization is refused with
    `ERR_NO_MEASURABLE_LOANS`, and finalizing a measurement that is not `DRAFT`
    is refused with `ERR_MEASUREMENT_NOT_DRAFT`."
    PRD: "It comprises the loans of the measured institution that have ever been
    disbursed — that is, whose `first_disbursed_on` is not null — and whose
    `first_disbursed_on` falls at or after `period_start` and strictly before
    `period_end`."

    Design: Corner/validations/finalize_over_a_window_with_no_disbursed_loans_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    measurement = fixtures.open_measurement(
        institution["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )

    response = api_client.finalize_compliance_measurement(
        measurement["id"], ANALYST
    )
    validate_error(response, ApiErrorId.ERR_NO_MEASURABLE_LOANS)

    unchanged = validate_success(
        api_client.get_compliance_measurement(measurement["id"], ANALYST)
    )
    assert unchanged["state"] == "DRAFT"
    assert unchanged["verdict"] == "PENDING"
    assert unchanged["selected_pct"] is None
    assert unchanged["measured_loan_count"] == 0
    assert unchanged["target_market_loan_count"] == 0
    assert unchanged["finalized_at"] is None

    lender = fixtures.read_institution(institution["id"])
    assert float(lender["target_market_lending_pct"]) == 0.00


def test_the_coaching_prerequisite_needs_a_session_closed_with_competency():
    """Completed hours without an attestation do not unlock the approval.

    PRD: "Two further gates apply to approvals only, in this order: when the
    product's `requires_ta_completion` is true, a session must exist for the
    loan's borrower in `state` `COMPLETED` with `competency_verified` true, or
    the approval is refused with `ERR_TA_PREREQUISITE_UNMET`; and the product's
    `committed_principal_cents` plus the amount being approved must not exceed
    `product_cap_cents`, or the approval is refused with
    `ERR_PRODUCT_CAP_EXCEEDED`."
    PRD: "Only a session that is `COMPLETED` **and** carries
    `competency_verified` true satisfies a product's technical-assistance
    prerequisite; hours delivered under a session still `SCHEDULED`, or one
    closed as `NO_SHOW`, contribute nothing to `ta_hours_total` and nothing to
    the prerequisite."
    PRD: "`ta_discount_bps` is a step function on coaching already delivered at
    the moment of underwriting: 25 basis points when the borrower's
    `ta_hours_total` is at least 8.00 hours, and 0 otherwise."

    Design: Corner/validations/ta_prerequisite_blocks_approval_until_a_verified_engagement_exists
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution(
        product_overrides={
            "name": "Credit Builder With Coaching",
            "requires_ta_completion": True,
            "credit_building_features": ["REPORTS_TO_BUREAUS", "SAVINGS_MATCH"],
        }
    )
    institution_id = scenario["institution"]["id"]
    borrower_id = scenario["borrower"]["id"]
    loan = fixtures.file_loan(
        institution_id, borrower_id, scenario["product"]["id"], 1_000_000
    )
    priced = fixtures.underwrite_loan(loan["id"])
    assert float(priced["dti_pct"]) == 12.42
    assert priced["risk_grade"] == "A"
    assert priced["ta_discount_bps"] == 0

    approval = {"decision": "APPROVE", "approved_principal_cents": 1_000_000}
    validate_error(
        api_client.decide_loan(loan["id"], approval, COMMITTEE),
        ApiErrorId.ERR_TA_PREREQUISITE_UNMET,
    )

    unattested = fixtures.book_ta_engagement(
        institution_id, borrower_id,
        "2026-09-02T09:00:00Z", "2026-09-02T13:00:00Z", 4.00,
        topic="FINANCIAL_COACHING", loan_id=loan["id"],
    )
    fixtures.close_ta_engagement(
        institution_id, unattested["id"], outcome="COMPLETED",
        actual_hours=4.00, competency_verified=False,
    )
    validate_error(
        api_client.decide_loan(loan["id"], approval, COMMITTEE),
        ApiErrorId.ERR_TA_PREREQUISITE_UNMET,
    )

    attested = fixtures.book_ta_engagement(
        institution_id, borrower_id,
        "2026-09-03T09:00:00Z", "2026-09-03T13:00:00Z", 4.00,
        topic="CREDIT_BUILDING", loan_id=loan["id"],
    )
    fixtures.close_ta_engagement(
        institution_id, attested["id"], outcome="COMPLETED",
        actual_hours=4.00, competency_verified=True,
    )

    approved = validate_success(
        api_client.decide_loan(loan["id"], approval, COMMITTEE)
    )
    assert approved["underwriting_state"] == "APPROVED"
    assert approved["approved_principal_cents"] == 1_000_000

    coached = validate_success(api_client.get_borrower(borrower_id, ANALYST))
    assert float(coached["ta_hours_total"]) == 8.00, (
        "both completed sessions credit hours; only one of them attests competency"
    )

    final_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert float(final_loan["dti_pct"]) == 12.42
    assert final_loan["risk_grade"] == "A"
    assert final_loan["ta_discount_bps"] == 0, (
        "the discount was frozen at underwriting, before any coaching was delivered"
    )
    assert final_loan["final_rate_bps"] == 900
