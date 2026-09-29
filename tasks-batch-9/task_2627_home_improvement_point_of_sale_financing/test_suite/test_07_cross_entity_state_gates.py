"""Writes whose legality is decided by a different entity's state.

Three entity pairs are pinned here.  A `FundingDraw` write is gated on the
`Merchant`'s `enrollment_status`, a `Merchant` enrollment approval is gated on a
`MerchantLicense`'s `verification_status`, and both a `Payment` and a
`FundingDraw` are gated on the `LoanAccount`'s `balance_status`.  In every case
the payload never names the gating entity, so the same request body flips
between accepted and refused with nothing about the request itself changing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_empty, assert_fields, bps_of
from test_helpers.test_users import ADMIN_HEADERS, AGENT_HEADERS, UNDERWRITER_HEADERS
from test_helpers.test_users import UNDERWRITER_ID

#: 3500000 contract * 3000 bps of verified release share = the whole headroom.
DRAW_AMOUNT_CENTS = 1050000

#: 3500000 * 7000 bps of verified release (milestones 1 and 2) less draw 1.
SECOND_DRAW_AMOUNT_CENTS = 1400000


def _verified_milestone_scenario(api, releases=(3000,), verify=(0,)):
    """Program, APPROVED merchant, ACTIVE enrollment, loan, project, verified milestones."""
    return S.project_with_milestones(api, releases=releases, verify=verify)


def _draw_body(scenario, loan_version, amount_cents=DRAW_AMOUNT_CENTS,
               milestone_index=0):
    """The draw request body; identical across the refused and the permitted arm."""
    return F.funding_draw_payload(
        scenario.loan_id,
        scenario.milestone_id(milestone_index),
        amount_cents,
        loan_version,
        "STANDARD_3DAY",
    )


def _pending_review_merchant_with_unverified_covering_license(api):
    """A ROOFING/TX merchant at PENDING_REVIEW whose only VERIFIED licence is CA."""
    scenario = S.program(api)
    scenario.merchant = S.register_merchant(api)
    tx_license = S.file_license(api, scenario.merchant_id)
    ca_license = S.file_license(
        api, scenario.merchant_id, license_number="CA-RCF-40011", state_code="CA"
    )
    S.verify_license(api, scenario.merchant_id, ca_license["id"])
    scenario.merchant = S.submit_enrollment(api, scenario.merchant_id)
    scenario.license = tx_license
    return scenario, tx_license, ca_license


def _settled_first_draw_scenario(api):
    """Two verified milestones and draw 1 of 1050000 SETTLED, so principal is 1050000."""
    scenario = _verified_milestone_scenario(api, releases=(3000, 4000), verify=(0, 1))
    S.request_draw(api, scenario, DRAW_AMOUNT_CENTS, 0)
    S.settle_draw(api, scenario)
    return scenario


def test_draw_creation_refused_while_the_merchant_stands_suspended(api):
    """A draw request that is faultless in itself is refused because the merchant is SUSPENDED.

    PRD: "Merchant enrollment posture: the merchant's `enrollment_status` must admit the requested transition or dependent write — submission only from `DRAFT` or `DOCS_REQUIRED`, an enrollment decision only from `PENDING_REVIEW`, suspension or termination only from `APPROVED` or `SUSPENDED`, reinstatement only from `SUSPENDED`, and `APPROVED` for every funding-side write."

    Design: Difficulty/cross_entity_state_dependency/draw_creation_gated_on_merchant_enrollment_state
    """
    scenario = _verified_milestone_scenario(api)
    loan_version = S.loan_version(api, scenario.loan_id)
    # The draw asks for exactly the headroom the verified milestone supports, so
    # nothing about the request itself is defective.
    project = S.read_project(api, scenario.project_id)
    assert project["max_fundable_now_cents"] == DRAW_AMOUNT_CENTS

    S.program_action(api, scenario.merchant_id, "SUSPEND", reason_code="ANALYST_ACTION")
    response = api.create_funding_draw(
        _draw_body(scenario, loan_version), scenario.as_merchant
    )

    validate_error(response, E.ERR_INVALID_MERCHANT_STATE)


def test_the_refused_draw_leaves_no_trace_on_either_entity(api):
    """The refused draw writes no FundingDraw row and does not mark the milestone funded.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Difficulty/cross_entity_state_dependency/draw_creation_gated_on_merchant_enrollment_state
    """
    scenario = _verified_milestone_scenario(api)
    loan_version = S.loan_version(api, scenario.loan_id)
    S.program_action(api, scenario.merchant_id, "SUSPEND", reason_code="ANALYST_ACTION")

    validate_error(
        api.create_funding_draw(_draw_body(scenario, loan_version), scenario.as_merchant),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert draws == []
    assert meta["total_count"] == 0
    milestones = S.read_milestones(api, scenario.project_id)
    assert_fields(milestones[0], status="VERIFIED", is_funded=False)


def test_suspension_and_reinstatement_carry_the_promotion_enrollment_with_them(api):
    """The gating merchant state drags its ACTIVE enrollment to SUSPENDED and back again.

    PRD: "Reinstatement clears `suspension_reason_code`, returns every `SUSPENDED` promotion enrollment of that merchant to `ACTIVE`, and increments `version`."

    Design: Difficulty/cross_entity_state_dependency/draw_creation_gated_on_merchant_enrollment_state
    """
    scenario = _verified_milestone_scenario(api)

    suspended = S.program_action(
        api, scenario.merchant_id, "SUSPEND", reason_code="ANALYST_ACTION"
    )
    assert_fields(
        suspended, enrollment_status="SUSPENDED", suspension_reason_code="ANALYST_ACTION"
    )
    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, UNDERWRITER_HEADERS)
    )
    assert_fields(enrollments[0], id=scenario.enrollment["id"], status="SUSPENDED")

    reinstated = S.program_action(api, scenario.merchant_id, "REINSTATE")

    assert_fields(reinstated, enrollment_status="APPROVED")
    assert_empty(reinstated, "suspension_reason_code")
    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, UNDERWRITER_HEADERS)
    )
    assert_fields(enrollments[0], id=scenario.enrollment["id"], status="ACTIVE")


def test_the_identical_draw_body_is_accepted_once_the_merchant_is_reinstated(api):
    """The byte-identical request refused under SUSPENDED is created once the merchant is APPROVED again.

    PRD: "The provisional view deliberately uses only plan-level and trade-level rates: `provisional_discount_cents` is `funded_amount_cents` multiplied by the promotion plan's `merchant_discount_bps`, divided by ten thousand and rounded half up; `provisional_holdback_cents` is `funded_amount_cents` multiplied by the trade rule's `holdback_pct_bps`, divided by ten thousand and rounded half up; and `provisional_net_settlement_cents` is `funded_amount_cents` reduced by `provisional_discount_cents` and reduced again by `provisional_holdback_cents`."

    Design: Difficulty/cross_entity_state_dependency/draw_creation_gated_on_merchant_enrollment_state
    """
    scenario = _verified_milestone_scenario(api)
    body = _draw_body(scenario, S.loan_version(api, scenario.loan_id))
    S.program_action(api, scenario.merchant_id, "SUSPEND", reason_code="ANALYST_ACTION")
    validate_error(
        api.create_funding_draw(body, scenario.as_merchant), E.ERR_INVALID_MERCHANT_STATE
    )
    S.program_action(api, scenario.merchant_id, "REINSTATE")

    draw = validate_success(api.create_funding_draw(body, scenario.as_merchant), 201)

    # 525 bps plan discount and 500 bps trade holdback on 1050000 cents.
    assert_fields(
        draw,
        status="REQUESTED",
        funded_amount_cents=DRAW_AMOUNT_CENTS,
        provisional_discount_cents=bps_of(DRAW_AMOUNT_CENTS, 525),
        provisional_holdback_cents=bps_of(DRAW_AMOUNT_CENTS, 500),
        provisional_net_settlement_cents=DRAW_AMOUNT_CENTS
        - bps_of(DRAW_AMOUNT_CENTS, 525)
        - bps_of(DRAW_AMOUNT_CENTS, 500),
    )
    assert draw["provisional_net_settlement_cents"] == 942375


def test_enrollment_approval_refused_while_the_covering_license_is_unverified(api):
    """Approval is refused because the ROOFING/TX licence is still UNVERIFIED, even though a CA licence is VERIFIED.

    PRD: "Enrollment approval requires at least one licence whose `verification_status` is `VERIFIED`, whose `trade_type` equals the merchant's `trade_type` and whose `state_code` equals the merchant's `state_code`; absent such a licence the approval fails with `ERR_LICENSE_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_approval_gated_on_license_verification_state
    """
    scenario, _tx_license, _ca_license = (
        _pending_review_merchant_with_unverified_covering_license(api)
    )

    response = api.decide_enrollment(
        scenario.merchant_id,
        F.enrollment_decision_payload("APPROVE", decision_note="First attempt"),
        UNDERWRITER_HEADERS,
    )

    validate_error(response, E.ERR_LICENSE_NOT_VERIFIED)
    # Registration wrote version 1, submission version 2; the refusal wrote nothing.
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        enrollment_status="PENDING_REVIEW",
        version=2,
    )
    assert_empty(S.read_merchant(api, scenario.merchant_id), "approved_by_user_id")


def test_enrollment_approval_still_refused_when_the_covering_license_is_rejected(api):
    """A REJECTED covering licence leaves the coverage gate unsatisfied just as an UNVERIFIED one does.

    PRD: "The `UNVERIFIED → VERIFIED` outcome makes the licence count toward enrollment coverage and increments the licence record's `version`; the `UNVERIFIED → REJECTED` outcome is terminal and removes the licence from the coverage check entirely."

    Design: Difficulty/cross_entity_state_dependency/enrollment_approval_gated_on_license_verification_state
    """
    scenario, tx_license, _ = (
        _pending_review_merchant_with_unverified_covering_license(api)
    )

    decided = validate_success(
        api.verify_license(
            scenario.merchant_id,
            tx_license["id"],
            F.license_verification_payload(
                "REJECTED", verification_note="Licence number not on the state board record"
            ),
            UNDERWRITER_HEADERS,
        )
    )
    assert_fields(
        decided, verification_status="REJECTED", verified_by_user_id=UNDERWRITER_ID
    )
    assert decided["verified_on"].startswith(C.DEFAULT_CLOCK_DATE)

    response = api.decide_enrollment(
        scenario.merchant_id,
        F.enrollment_decision_payload("APPROVE", decision_note="Second attempt"),
        UNDERWRITER_HEADERS,
    )

    validate_error(response, E.ERR_LICENSE_NOT_VERIFIED)
    assert_fields(
        S.read_merchant(api, scenario.merchant_id), enrollment_status="PENDING_REVIEW"
    )


def test_a_rejected_license_releases_its_coverage_interval_for_refiling(api):
    """Because REJECTED leaves the overlap set, the identical ROOFING/TX interval may be filed again.

    PRD: "Licence coverage may not overlap for the same combination of merchant, `trade_type` and `state_code` among licences whose `verification_status` is `UNVERIFIED` or `VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_approval_gated_on_license_verification_state
    """
    scenario, tx_license, _ = (
        _pending_review_merchant_with_unverified_covering_license(api)
    )
    S.verify_license(api, scenario.merchant_id, tx_license["id"], "REJECTED")

    replacement = validate_success(
        api.file_license(
            scenario.merchant_id,
            F.license_payload(license_number="TX-RCF-88120-R2"),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert_fields(
        replacement,
        trade_type="ROOFING",
        state_code="TX",
        effective_from=C.CANONICAL_LICENSE["effective_from"],
        expires_on=C.CANONICAL_LICENSE["expires_on"],
        verification_status="UNVERIFIED",
    )


def test_enrollment_approval_succeeds_once_a_matching_license_is_verified(api):
    """Flipping the licence to VERIFIED is the only change that turns the refused approval into an approval.

    PRD: "Enrollment approval requires at least one licence whose `verification_status` is `VERIFIED`, whose `trade_type` equals the merchant's `trade_type` and whose `state_code` equals the merchant's `state_code`; absent such a licence the approval fails with `ERR_LICENSE_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_approval_gated_on_license_verification_state
    """
    scenario, tx_license, _ = (
        _pending_review_merchant_with_unverified_covering_license(api)
    )
    S.verify_license(api, scenario.merchant_id, tx_license["id"], "REJECTED")
    replacement = S.file_license(
        api, scenario.merchant_id, license_number="TX-RCF-88120-R2"
    )
    S.verify_license(api, scenario.merchant_id, replacement["id"], "VERIFIED")

    approved = validate_success(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE", decision_note="Licence verified"),
            UNDERWRITER_HEADERS,
        )
    )

    assert_fields(
        approved,
        enrollment_status="APPROVED",
        approved_by_user_id=UNDERWRITER_ID,
        risk_tier="STANDARD",
        portfolio_grade="A",
        reserve_coverage_bps=10000,
        version=3,
    )
    assert approved["approved_on"].startswith(C.DEFAULT_CLOCK_DATE)


def test_a_payment_of_the_whole_principal_allocates_entirely_to_principal(api):
    """With no capitalized interest to take, the first bucket is zero and the second takes the whole payment.

    PRD: "The second bucket, `applied_to_principal_cents`, takes whatever remains of `amount_cents` after the first bucket."

    Design: Difficulty/cross_entity_state_dependency/payment_and_draw_gated_on_loan_account_balance_state
    """
    scenario = _settled_first_draw_scenario(api)
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=DRAW_AMOUNT_CENTS,
        capitalized_interest_cents=0,
        balance_status="CURRENT",
    )

    payment = validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, DRAW_AMOUNT_CENTS), scenario.as_consumer
        ),
        201,
    )

    assert_fields(
        payment,
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=DRAW_AMOUNT_CENTS,
        resulting_principal_balance_cents=0,
        posted_on=C.DEFAULT_CLOCK_DATE,
        source_role="CONSUMER",
    )


def test_the_payoff_closes_both_loan_dimensions_at_once(api):
    """The payment that zeroes principal before promo expiry satisfies the promotion and pays the account off.

    PRD: "If the payment brings `principal_balance_cents` to zero on or before `promo_expires_on` — the boundary being inclusive, so a payment posted on the expiration date itself still wins the wager — the promotional dimension moves `PROMO_ACTIVE → PROMO_SATISFIED`: `waived_interest_cents` is written with the accrual standing at that instant, `accrued_deferred_interest_cents` and `deferred_interest_at_risk_cents` both drop to zero, `capitalized_interest_cents` stays at zero, and the repayment dimension moves `CURRENT → PAID_OFF`, with the consumer's `existing_program_debt_cents` and `active_loan_count` recomputed."

    Design: Difficulty/cross_entity_state_dependency/payment_and_draw_gated_on_loan_account_balance_state
    """
    scenario = _settled_first_draw_scenario(api)

    validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, DRAW_AMOUNT_CENTS), scenario.as_consumer
        ),
        201,
    )

    # The payment posts on 2026-08-01, the same day funding began, so nothing accrued.
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        promo_status="PROMO_SATISFIED",
        balance_status="PAID_OFF",
        principal_balance_cents=0,
        waived_interest_cents=0,
        accrued_deferred_interest_cents=0,
        deferred_interest_at_risk_cents=0,
        promo_payoff_cents=0,
        standard_payoff_cents=0,
        last_payment_on=C.DEFAULT_CLOCK_DATE,
    )
    assert_fields(
        validate_success(api.get_consumer(scenario.consumer_id, ADMIN_HEADERS)),
        existing_program_debt_cents=0,
        active_loan_count=0,
    )


def test_a_second_identical_payment_is_refused_as_loan_closed(api):
    """Once the account is PAID_OFF the closed-account gate pre-empts the overpayment gate.

    PRD: "Loan-account openness: the account's `balance_status` must be neither `PAID_OFF` nor `CHARGED_OFF` for money to move, otherwise `ERR_LOAN_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/payment_and_draw_gated_on_loan_account_balance_state
    """
    scenario = _settled_first_draw_scenario(api)
    body = F.payment_payload(scenario.loan_id, DRAW_AMOUNT_CENTS)
    validate_success(api.create_payment(body, scenario.as_consumer), 201)

    response = api.create_payment(body, scenario.as_consumer)

    # Priority 23 wins over priority 54: the payoff is now zero, so an
    # ERR_PAYMENT_EXCEEDS_PAYOFF condition also holds, and is not the reported one.
    validate_error(response, E.ERR_LOAN_CLOSED)
    _payments, meta = validate_paginated(
        api.list_payments(scenario.loan_id, AGENT_HEADERS)
    )
    assert meta["total_count"] == 1


def test_a_draw_within_headroom_is_refused_once_the_account_is_paid_off(api):
    """A draw for exactly the remaining headroom is refused because the loan account, not the draw, is closed.

    PRD: "Loan-account openness: the account's `balance_status` must be neither `PAID_OFF` nor `CHARGED_OFF` for money to move, otherwise `ERR_LOAN_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/payment_and_draw_gated_on_loan_account_balance_state
    """
    scenario = _settled_first_draw_scenario(api)
    validate_success(
        api.create_payment(
            F.payment_payload(scenario.loan_id, DRAW_AMOUNT_CENTS), scenario.as_consumer
        ),
        201,
    )
    # 3500000 * 7000 bps of verified release, less the 1050000 already settled.
    assert (
        S.read_project(api, scenario.project_id)["max_fundable_now_cents"]
        == SECOND_DRAW_AMOUNT_CENTS
    )

    response = api.create_funding_draw(
        _draw_body(
            scenario,
            S.loan_version(api, scenario.loan_id),
            amount_cents=SECOND_DRAW_AMOUNT_CENTS,
            milestone_index=1,
        ),
        scenario.as_merchant,
    )

    validate_error(response, E.ERR_LOAN_CLOSED)
    _draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 1
    assert S.read_project(api, scenario.project_id)["settled_funded_cents"] == DRAW_AMOUNT_CENTS
