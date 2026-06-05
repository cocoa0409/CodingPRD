"""Application decision state machine: the counter-revision loop, merchant-status
dependency, decline reasons, withdraw, and invalid-state lockdown.

Covers queue A non_linear_state_machine (revision loop) and
cross_entity_state_dependency (Application depends on Merchant.status), plus queue B
corner instances on declines, withdraw, and invalid-state transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_merchant,
    create_borrower,
    create_application,
    decide_application,
    suspend_merchant,
    make_servicer_headers,
    make_borrower_headers,
    revise_payload,
    decision_payload,
)

SERVICER = make_servicer_headers()


def test_application_revision_loop_countered_to_submitted_to_approved(api):
    """PRD §3.3: "A successful revision writes the new requested down payment and returns
    the application from COUNTERED back to SUBMITTED for a fresh decision."
    PRD §3.3: "the application is approved: it moves from SUBMITTED to APPROVED, and
    approved_down_payment_cents is fixed equal to requested_down_payment_cents."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_countered_to_submitted
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="bc@x.com", full_name="BC",
                               soft_credit_score=620, annual_income_cents=2_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=50_001, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    countered = decide_application(application["id"], "COUNTER")
    assert countered["status"] == "COUNTERED"
    assert countered["approved_down_payment_cents"] == 1

    # Revise: new requested down payment >= countered approved (1) -> back to SUBMITTED.
    revised = validate_success(
        api.revise_application(application["id"], revise_payload(1),
                               make_borrower_headers(borrower["id"])),
        200,
    )
    assert revised["status"] == "SUBMITTED"

    approved = decide_application(application["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["financed_principal_cents"] == 50_000


def test_revise_updates_requested_down_payment_back_to_submitted(api):
    """PRD §3.3: "The owning Borrower revises a COUNTERED application by submitting a new
    requested_down_payment_cents; this is legal only while the application is in COUNTERED
    status, and the new value must be at least the countered approved_down_payment_cents.
    A successful revision writes the new requested down payment and returns the
    application from COUNTERED back to SUBMITTED for a fresh decision."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_countered_to_submitted
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="bc@x.com", full_name="BC",
                               soft_credit_score=620, annual_income_cents=2_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=50_001, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    decide_application(application["id"], "COUNTER")  # approved_down 1

    # Revise to a larger down payment (10) >= countered minimum (1) -> back to SUBMITTED.
    revised = validate_success(
        api.revise_application(application["id"], revise_payload(10),
                               make_borrower_headers(borrower["id"])),
        200,
    )
    assert revised["status"] == "SUBMITTED"
    assert revised["requested_down_payment_cents"] == 10


def test_application_declined_when_merchant_suspended(api):
    """PRD §3.3: "When the merchant on the application has status SUSPENDED, the decision
    takes the decline branch with decline_reason set to MERCHANT_SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_merchant_status
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")  # high limit, ample credit
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    suspend_merchant(merchant["id"])

    declined = decide_application(application["id"], "DECLINE")
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "MERCHANT_SUSPENDED"


def test_suspended_merchant_decline_takes_precedence_over_credit(api):
    """PRD §3.3: "When the merchant on the application has status SUSPENDED, the decision
    takes the decline branch with decline_reason set to MERCHANT_SUSPENDED. Otherwise,
    when the borrower's available credit is exactly 0, the application is declined with
    decline_reason INSUFFICIENT_CREDIT."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_merchant_status
    """
    merchant = create_merchant(mdr_bps=600)
    # High-limit borrower: credit would otherwise allow approval. Merchant.status decides.
    borrower = create_borrower(email="ba@x.com", soft_credit_score=760,
                               annual_income_cents=8_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    suspend_merchant(merchant["id"])
    declined = decide_application(application["id"], "DECLINE")
    assert declined["decline_reason"] == "MERCHANT_SUSPENDED", (
        "merchant suspension reason fires despite ample borrower credit"
    )


def test_decline_reason_insufficient_credit_on_zero_limit_borrower(api):
    """PRD §3.3: "when the borrower's available credit is exactly 0, the application is
    declined with decline_reason INSUFFICIENT_CREDIT."

    Design: Corner/state_machines/decline_reason_insufficient_credit_on_zero_limit_borrower
    """
    merchant = create_merchant(mdr_bps=600)
    # score 500 -> base limit 0 -> eligible 0 -> available 0.
    borrower = create_borrower(email="bd@x.com", full_name="BD",
                               soft_credit_score=500, annual_income_cents=9_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    declined = decide_application(application["id"], "DECLINE")
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "INSUFFICIENT_CREDIT"


def test_decide_already_declined_application_returns_invalid_state(api):
    """PRD §3.3: "the application must be in SUBMITTED status for any decision to be
    legal, and an illegal-state attempt is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/decline_application_already_declined_returns_invalid_state
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="bd@x.com", full_name="BD",
                               soft_credit_score=500, annual_income_cents=9_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    decide_application(application["id"], "DECLINE")  # now DECLINED (terminal)

    resp = api.decide_application(application["id"], decision_payload("APPROVE"), SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_withdraw_submitted_application(api):
    """PRD §3.3: "A Borrower may instead withdraw an application that is in either
    SUBMITTED or COUNTERED status, which moves it to the terminal WITHDRAWN state".

    Design: Corner/state_machines/withdraw_application_from_submitted
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    withdrawn = validate_success(
        api.withdraw_application(application["id"], make_borrower_headers(borrower["id"])),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    fetched = validate_success(api.get_application(application["id"], SERVICER), 200)
    assert fetched["status"] == "WITHDRAWN"
