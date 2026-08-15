"""Working-capital covenant evaluation: exact cross-multiplication, display
ratio, breach-count conservation through void/waive, and segregation of duties
(PRD section 3.7).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, get_borrower, get_success_data,
    make_committee_headers, record_evaluation, setup_active_loan,
    validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]  # opaque id "officer-1"


def test_covenant_ratio_exact_threshold_compliant_one_cent_liabilities_breach(api):
    """PRD section 3.7: "`required_ratio_milli` tiers off the loan's
    `approved_commitment_cents`: a commitment at or below 25,000,000 cents
    ($250,000) requires 1100 — a current ratio of 1.100 — at or below 100,000,000
    cents ($1,000,000) requires 1250, and anything larger requires 1400." PRD
    section 3.7: "And the `outcome` is decided by exact integer
    cross-multiplication with no rounding of the ratio: when the liabilities are
    zero, the evaluation is `COMPLIANT` if assets are positive and `BREACH` if
    assets are also zero; otherwise the evaluation is `COMPLIANT` exactly when the
    assets times one thousand are at least the `required_ratio_milli` times the
    liabilities, and `BREACH` otherwise." PRD section 3.7: "A display ratio
    `current_ratio_milli` — the floor of the assets times one thousand divided by
    the liabilities, defined as 0 when both are zero and 999999999 when liabilities
    are zero with positive assets — is computed independently and never feeds the
    outcome."

    Design: Difficulty/boundary_precision_check/covenant_ratio_exact_threshold_compliant_one_cent_liabilities_breach
    """
    ctx = setup_active_loan()  # commitment 50,000,000 -> required ratio 1250 milli

    ev1 = validate_success(api.create_covenant_evaluation(
        {"loan_account_id": ctx["loan"]["id"], "as_of_date": "2026-03-15T00:00:00Z",
         "current_assets_cents": 125_000, "current_liabilities_cents": 100_000},
        OFFICER), 201)
    assert ev1["required_ratio_milli"] == 1250
    assert ev1["working_capital_cents"] == 25_000
    assert ev1["outcome"] == "COMPLIANT", \
        "125,000 x 1000 >= 1250 x 100,000 (equality complies)"
    assert ev1["current_ratio_milli"] == 1250

    ev2 = validate_success(api.create_covenant_evaluation(
        {"loan_account_id": ctx["loan"]["id"], "as_of_date": "2026-03-16T00:00:00Z",
         "current_assets_cents": 125_000, "current_liabilities_cents": 100_001},
        OFFICER), 201)
    assert ev2["outcome"] == "BREACH", \
        "125,000 x 1000 = 125,000,000 < 1250 x 100,001 = 125,001,250"
    assert ev2["current_ratio_milli"] == 1249, \
        "the display ratio floors 1249.9875 to 1249 while the outcome used exact math"
    assert get_borrower(ctx["bor"]["id"])["active_covenant_breach_count"] == 1, \
        "exactly one RECORDED breach on the borrower"


def test_covenant_zero_liabilities_legs(api):
    """PRD section 3.7: "And the `outcome` is decided by exact integer
    cross-multiplication with no rounding of the ratio: when the liabilities are
    zero, the evaluation is `COMPLIANT` if assets are positive and `BREACH` if
    assets are also zero". PRD section 3.7: "A display ratio `current_ratio_milli`
    — the floor of the assets times one thousand divided by the liabilities,
    defined as 0 when both are zero and 999999999 when liabilities are zero with
    positive assets — is computed independently and never feeds the outcome."

    Design: Difficulty/boundary_precision_check/covenant_ratio_exact_threshold_compliant_one_cent_liabilities_breach
    """
    ctx = setup_active_loan()

    ev1 = record_evaluation(ctx, 1, 0, as_of_date="2026-03-15T00:00:00Z")
    assert ev1["outcome"] == "COMPLIANT", "positive assets with zero liabilities"
    assert ev1["current_ratio_milli"] == 999_999_999

    ev2 = record_evaluation(ctx, 0, 0, as_of_date="2026-03-16T00:00:00Z")
    assert ev2["outcome"] == "BREACH", "zero assets with zero liabilities breaches"
    assert ev2["current_ratio_milli"] == 0
    assert get_borrower(ctx["bor"]["id"])["active_covenant_breach_count"] == 1


def test_covenant_record_then_void_conserves_breach_count(api):
    """PRD section 3.7: "A `RECORDED` evaluation with outcome `BREACH` increments
    the borrower's `active_covenant_breach_count` by one and re-evaluates borrower
    standing". PRD section 3.7: "A `LoanOfficer` voids a mis-recorded evaluation,
    moving `RECORDED` → `VOIDED` (terminal). Both exits share one side effect with
    equal force: if the evaluation's outcome was `BREACH`, the borrower's
    `active_covenant_breach_count` decrements by one and borrower standing is
    re-evaluated; a `COMPLIANT` evaluation's waiver or voiding touches nothing."

    Design: Difficulty/compensating_invariant/covenant_record_then_void_conserves_breach_count
    """
    ctx = setup_active_loan()
    bor_id = ctx["bor"]["id"]
    assert get_borrower(bor_id)["active_covenant_breach_count"] == 0

    ev = record_evaluation(ctx, 100_000, 100_000)  # ratio 1000 < 1250 -> BREACH
    assert ev["outcome"] == "BREACH"
    bor = get_borrower(bor_id)
    assert bor["active_covenant_breach_count"] == 1
    assert bor["status"] == "ACTIVE", "one breach is below the two-breach suspension rule"

    data = validate_success(api.void_covenant_evaluation(ev["id"], OFFICER), 200)
    assert data["status"] == "VOIDED"
    bor = get_borrower(bor_id)
    assert bor["active_covenant_breach_count"] == 0, \
        "the record/void pair conserves the breach count"
    assert bor["status"] == "ACTIVE"


def test_covenant_record_then_waive_conserves_breach_count(api):
    """PRD section 3.7: "The `CreditCommittee` waives a `RECORDED` evaluation,
    moving it to `WAIVED` (terminal)". PRD section 3.7: "Both exits share one side
    effect with equal force: if the evaluation's outcome was `BREACH`, the
    borrower's `active_covenant_breach_count` decrements by one and borrower
    standing is re-evaluated; a `COMPLIANT` evaluation's waiver or voiding touches
    nothing."

    Design: Difficulty/compensating_invariant/covenant_record_then_void_conserves_breach_count
    """
    ctx = setup_active_loan()
    bor_id = ctx["bor"]["id"]
    ev = record_evaluation(ctx, 100_000, 100_000)  # BREACH -> count 1
    assert get_borrower(bor_id)["active_covenant_breach_count"] == 1

    data = validate_success(api.waive_covenant_evaluation(
        ev["id"], make_committee_headers("committee-9")), 200)  # not the recorder
    assert data["status"] == "WAIVED"
    bor = get_borrower(bor_id)
    assert bor["active_covenant_breach_count"] == 0, \
        "the record/waive pair conserves the breach count"
    assert bor["status"] == "ACTIVE"


def test_covenant_waive_by_recorder_segregation_rejected(api):
    """PRD section 3.7: "The `CreditCommittee` waives a `RECORDED` evaluation,
    moving it to `WAIVED` (terminal) — but segregation of duties forbids the
    committee member whose `X-User-ID` equals the evaluation's
    `recorded_by_user_id` from waiving it, and such an attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/covenant_waive_by_recorder_segregation_rejected
    """
    ctx = setup_active_loan()
    ev = record_evaluation(ctx, 100_000, 100_000)  # recorded by officer-1; BREACH
    assert ev["recorded_by_user_id"] == "officer-1"

    resp = api.waive_covenant_evaluation(
        ev["id"], make_committee_headers("officer-1"))  # committee role, recorder's id
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    data = validate_success(api.waive_covenant_evaluation(
        ev["id"], make_committee_headers("committee-9")), 200)
    assert data["status"] == "WAIVED", "a different committee user may waive"
    assert get_borrower(ctx["bor"]["id"])["active_covenant_breach_count"] == 0
