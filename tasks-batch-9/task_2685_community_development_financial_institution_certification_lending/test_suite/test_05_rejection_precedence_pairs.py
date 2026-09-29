"""Requests that break two rules at once, and which error the contract names.

A state guard outranks a referential guard on the review surface; a business
safety guard outranks a fiscal guard on the credit surface.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, REVIEWER


def test_evaluating_a_test_on_a_draft_docket_reports_the_state_guard():
    """A docket in draft with no approved market reports the state failure.

    PRD: "When a single request violates more than one rule, the response must
    carry the error belonging to the earliest band below, and within a band the
    earliest listed check."
    PRD: "Then the specific state guards, all HTTP 409, in this order: the
    application is `UNDER_REVIEW` (`ERR_APPLICATION_NOT_UNDER_REVIEW`, guarding
    test evaluation, information requests and the certification decision)."
    PRD: "**Business referential**, in this order: an approved target market
    exists (`ERR_TARGET_MARKET_NOT_APPROVED`, HTTP 422, guarding both
    application submission and test evaluation)."

    Design: Difficulty/priority_pair_validation_conflict/evaluate_test_state_error_outranks_target_market_referential_error
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    application = fixtures.open_certification_application(institution["id"])

    response = api_client.evaluate_certification_test(
        application["id"],
        {"test_code": "TARGET_MARKET", "verdict": "PASSED"},
        REVIEWER,
    )

    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW)

    unchanged = validate_success(
        api_client.get_certification_application(application["id"], ANALYST)
    )
    assert unchanged["state"] == "DRAFT"
    assert unchanged["test_target_market_state"] == "PENDING"


def test_the_subordinated_market_guard_is_live_on_the_same_docket():
    """With the state rung satisfied, the referential rung is what refuses.

    PRD: "**Business referential**, in this order: an approved target market
    exists (`ERR_TARGET_MARKET_NOT_APPROVED`, HTTP 422, guarding both
    application submission and test evaluation)."

    Design: Difficulty/priority_pair_validation_conflict/evaluate_test_state_error_outranks_target_market_referential_error
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    application = fixtures.open_certification_application(institution["id"])

    response = api_client.submit_certification_application(
        application["id"],
        fixtures.make_institution_officer_headers(institution["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TARGET_MARKET_NOT_APPROVED)


def _capped_ta_gated_loan(deliver_coaching):
    """An underwritten 2,000,000 loan under a product capped at 1,000,000.

    The product demands completed coaching. When ``deliver_coaching`` is false
    the borrower's only session was closed as a no-show, so the prerequisite is
    unmet at the same time as the cap is breached.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    institution_id = institution["id"]
    product = fixtures.create_loan_product(
        institution_id, name="TA-Gated Microloan",
        requires_ta_completion=True, product_cap_cents=1_000_000,
    )
    borrower = fixtures.create_geocoded_borrower(institution_id)
    engagement = fixtures.book_ta_engagement(
        institution_id, borrower["id"],
        "2026-09-02T14:00:00Z", "2026-09-02T16:00:00Z", 2.00,
    )
    if deliver_coaching:
        fixtures.close_ta_engagement(
            institution_id, engagement["id"], outcome="COMPLETED",
            actual_hours=2.00, competency_verified=True,
        )
    else:
        fixtures.close_ta_engagement(
            institution_id, engagement["id"], outcome="NO_SHOW"
        )
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 2_000_000
    )
    fixtures.underwrite_loan(loan["id"])
    return institution, product, loan


def test_a_missing_coaching_prerequisite_outranks_the_breached_product_cap():
    """Both approval gates fail; the safety gate is the one reported.

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

    Design: Difficulty/priority_pair_validation_conflict/loan_decision_ta_safety_error_outranks_product_cap_fiscal_error
    """
    _, product, loan = _capped_ta_gated_loan(deliver_coaching=False)

    response = api_client.decide_loan(
        loan["id"],
        {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
        COMMITTEE,
    )

    validate_error(response, ApiErrorId.ERR_TA_PREREQUISITE_UNMET)

    unchanged_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged_loan["underwriting_state"] == "UNDERWRITING"
    assert unchanged_loan["approved_principal_cents"] is None

    unchanged_product = validate_success(
        api_client.get_loan_product(product["id"], ANALYST)
    )
    assert unchanged_product["committed_principal_cents"] == 0


def test_the_subordinated_product_cap_is_live_once_the_coaching_is_delivered():
    """Satisfying the safety gate exposes the fiscal gate underneath it.

    PRD: "**Fiscal**, in this order: the product cap on loan approval
    (`ERR_PRODUCT_CAP_EXCEEDED`, HTTP 422)."
    PRD: "A successful approval moves the loan `UNDERWRITING → APPROVED`,
    records `approved_principal_cents` and `decided_by_user_id`, and adds the
    approved amount to the product's `committed_principal_cents`."

    Design: Difficulty/priority_pair_validation_conflict/loan_decision_ta_safety_error_outranks_product_cap_fiscal_error
    """
    _, product, loan = _capped_ta_gated_loan(deliver_coaching=True)

    response = api_client.decide_loan(
        loan["id"],
        {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
        COMMITTEE,
    )

    validate_error(response, ApiErrorId.ERR_PRODUCT_CAP_EXCEEDED)

    unchanged_loan = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert unchanged_loan["underwriting_state"] == "UNDERWRITING"

    unchanged_product = validate_success(
        api_client.get_loan_product(product["id"], ANALYST)
    )
    assert unchanged_product["committed_principal_cents"] == 0
