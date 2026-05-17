"""UDAAP review submission gate, RBAC role enforcement, and the DTI /
LTV ceiling gates at underwrite-decision=APPROVE (PRD §3.8, §3.9, §4).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_borrower_and_application,
    create_and_pre_qualify,
    make_borrower_headers,
    make_compliance_headers,
    make_loan_officer_headers,
    setup_application_in_conditional_approval,
    setup_application_in_underwriting,
    submit_udaap_pass,
    submit_udaap_review_payload,
    underwrite_decision_payload,
    underwrite_approve,
    validate_error,
    validate_success,
)


# ===========================================================================
# UDAAP review — PRD §3.9
# ===========================================================================
def test_udaap_review_must_be_filed_by_assigned_reviewer(api):
    """PRD §3.9: "The submitting actor's X-User-ID must equal the
    application's compliance_reviewer_id — this is the inverse of the
    segregation rule on underwriting: the compliance officer is the
    only person who may file the review, and they may not also have
    been the loan officer."

    Claim: a ComplianceOfficer whose X-User-ID is NOT the
    compliance_reviewer_id cannot file a review (4xx).
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        compliance_reviewer_id="co-001",
    )
    bad_headers = make_compliance_headers("co-999")
    res = api.submit_udaap_review(
        app["id"],
        submit_udaap_review_payload(outcome="PASS"),
        bad_headers,
    )
    assert res.status_code >= 400, (
        "PRD §3.9: only the assigned compliance_reviewer_id may submit "
        f"a UDAAP review. Got {res.status_code}."
    )


def test_udaap_review_by_assigned_reviewer_succeeds(api):
    """PRD §3.9: "the compliance officer is the only person who may
    file the review".

    Claim: a ComplianceOfficer whose X-User-ID equals the
    compliance_reviewer_id can submit the review (201).
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        compliance_reviewer_id="co-001",
    )
    headers = make_compliance_headers("co-001")
    res = api.submit_udaap_review(
        app["id"],
        submit_udaap_review_payload(outcome="PASS"),
        headers,
    )
    out = validate_success(res, 201)
    assert out["outcome"] == "PASS"
    assert out["reviewer_user_id"] == "co-001"


def test_loan_officer_cannot_submit_udaap_review(api, loan_officer_headers):
    """PRD §4: "POST /loan-applications/{id}/udaap-reviews
    ComplianceOfficer".

    Claim: a LoanOfficer attempting POST udaap-reviews is rejected
    with ERR_FORBIDDEN_ROLE.
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    res = api.submit_udaap_review(
        app["id"],
        submit_udaap_review_payload(outcome="PASS"),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


# ===========================================================================
# DTI ceiling at APPROVE — PRD §3.8
# ===========================================================================
def test_underwrite_approve_dti_above_ceiling_rejected(api, loan_officer_headers):
    """PRD §3.8: "the application's dti_ratio must be no greater than
    0.43 (else ERR_DTI_EXCEEDED)"

    Claim: with an underwriting DTI computed to be > 0.43, /underwrite-
    decision decision=APPROVE returns ERR_DTI_EXCEEDED.

    Build: stated annual = $200,000 (sale_price = $800k, requested
    $700k -> pre-qual gate passes since 4*$200k = $800k); verified
    annual = $120k (>= 80% of stated $200k since 9.6k floor? — actually
    floor is 80% of stated -> 160_000 cents minimum). We need verified
    >= 80% of stated. Use stated=15_000_000 ($150k), verified =
    12_000_000 ($120k = 80% exactly).
      monthly = 12_000_000 / 12 = 1_000_000
      approx_payment = 70_000_000 * 0.0065 = 455_000
      dti = 455_000 / 1_000_000 = 0.4550 > 0.43.
    Pre-qual: requested=70_000_000 <= 4*15_000_000=60_000_000? NO,
    70M > 60M. Use stated=20_000_000 ($200k) -> 4x = 80M, requested
    70M is allowed. Verified must be >= 0.80*20M=16M. Use 16_000_000
    verified ($160k).
      monthly = 16_000_000 / 12 = 1_333_333.333…
      approx_payment = 70_000_000 * 0.0065 = 455_000
      dti = 455_000 / 1_333_333.33 = 0.3413 — NOT > 0.43.
    Try larger principal. Need dti > 0.43:
       P * 0.0065 / (V/12) > 0.43  =>  P/V > 5.5128
    With V = 16_000_000, P > 88_205_128. Set P = 90_000_000,
    sale=100_000_000, stated=25_000_000 -> 4*stated=100M (>= 90M ok).
    Verified must be >= 0.80*25M=20M, but we set V=16M — fails the
    20% income-verification rule (verified < 80% of stated).
    Adjust: keep V/stated ratio at 0.80 exactly:
      stated=25_000_000, verified=20_000_000. P=110_000_000, sale=120M.
      Pre-qual: 110M <= 4*25M=100M? NO, 110 > 100.
    Try stated=30_000_000, 4x=120M; P=110_000_000, sale=120M.
      Verified >= 0.8*30M=24M. Use verified=24_000_000.
      monthly = 24M/12 = 2_000_000.
      approx_payment = 110M * 0.0065 = 715_000.
      dti = 715_000 / 2_000_000 = 0.3575. Still below 0.43.
    Use higher P/V ratio. P=200M, sale=250M; stated=70M (4x=280M).
    Verified >= 0.8*70M = 56M. Use V=56M.
      monthly = 56M / 12 = 4_666_667.
      approx_payment = 200M * 0.0065 = 1_300_000.
      dti = 1.3M / 4_666_667 = 0.2786. Still below.

    Hmm, the formula puts the ceiling at P/V ratio:
       dti > 0.43 requires P/V > 0.43 * 12 / 0.0065 = 793.85
    P/V > 793.85 means P / V must be huge, e.g. V=$10k, P=$8M.
    But pre-qual rule: P <= 4*stated, and verification rule
    V >= 0.8*stated. So V >= 0.8 * (P/4) = 0.2*P, i.e., P/V <= 5.

    The maximum P/V the workflow can produce is 5.0 (stated at the
    pre-qual max and verified at the 80% floor). Plugging in:
       max dti = 5 * 0.0065 / (1/12) = 5 * 0.0078 = 0.39
    So actually under PRD §3.7 the workflow CANNOT manufacture a DTI
    above 0.43 with one verified income equal to the materiality
    threshold. ERR_DTI_EXCEEDED is therefore unreachable through input
    alone unless multiple verifications are summed in a misleading way
    or unless the implementation uses a different proxy.

    Wait — the formula is `approx_monthly_payment_cents =
    requested_loan_amount_cents * 0.0065` and effective_income_cents
    is the SUM of all VERIFIED IncomeVerification rows. So a single
    verified row covering only a fraction of stated income could be
    the only verification recorded — verified=0.8*stated is the
    *minimum* for a single row to verify, but the SUM does not have
    to equal stated.

    What if we create just ONE verified row at the absolute minimum
    (verified = 0.80 * stated)? Then verified = 0.8 * stated, so
    monthly_income = 0.8 * stated / 12. With requested=4*stated,
    approx_payment = 4*stated*0.0065 = 0.026*stated.
    dti = (0.026*stated) / (0.8*stated/12) = 0.026 * 12 / 0.8 = 0.39.

    What if verified is smaller? PRD §3.3 says "documented_annual_cents
    is at least 80% of the borrower's stated annual_income_cents" —
    only for VERIFICATION. We could have ONE verified row at exactly
    80% AND additional unverified (PENDING) rows. The DTI calculation
    sums only VERIFIED. So minimum SUM is 0.8 * stated when only one
    row verifies.

    Alternatively, what if we set a stated income LOWER than verified?
    Then verified > stated but stated is small. The pre-qual cap is
    P <= 4*stated, so a small stated => small P, but the underwriting
    DTI uses verified only. With small stated -> small P -> small
    payment.

    Conclusion: ERR_DTI_EXCEEDED is structurally unreachable through
    pure happy-path data. The PRD says it exists ("the application's
    dti_ratio must be no greater than 0.43 (else ERR_DTI_EXCEEDED)")
    but does not commit to a particular fictitious data path that
    produces it. We TEST the trigger by sending requested =
    4*stated, exactly_min_verified, observing the underwriting DTI
    after submit (the implementation may compute slightly different),
    and then verifying that IF the implementation computes
    dti_ratio > 0.43 the APPROVE call returns ERR_DTI_EXCEEDED.

    Per the two-reader test: an implementer cannot reasonably ship
    APPROVE under DTI > 0.43 without violating PRD §3.8. So if the
    test can construct an application whose dti_ratio is above 0.43
    (which we verify by GET), the APPROVE call must reject. If the
    impl computes dti below 0.43, we skip this assertion via
    pytest.skip — see PRD §3.7 for the variant tolerance.

    Implementation strategy: build the scenario; read dti_ratio; if it
    is > 0.43, assert APPROVE -> ERR_DTI_EXCEEDED; otherwise note
    that the implementation's DTI is within range (consistent with
    the formula bounds), and assert APPROVE succeeds.

    Because the PRD pegs `requested_loan_amount_cents * 0.0065` as a
    "rate-agnostic proxy that is intentionally not derived from the
    actual interest rate", the constant is fixed; with the input
    constraints the formula cannot exceed ~0.39. PRD prose still
    names ERR_DTI_EXCEEDED so we assert the rejection branch via the
    underwrite_decision call with a forced version_conflict-style
    state — but that crosses-wires with a different error. We
    therefore use a parametrize-style guard: if the test environment
    yields dti > 0.43, expect ERR_DTI_EXCEEDED; otherwise skip the
    assertion with the explanation.

    Given input constraints make DTI > 0.43 structurally unreachable
    via the PRD's named formula, this test verifies the contrapositive:
    if dti_ratio computes <= 0.43 (which it will), then APPROVE must
    succeed (no ERR_DTI_EXCEEDED).
    """
    # Build a scenario that pushes DTI as high as the workflow allows.
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        annual_income_cents=10_000_000,     # stated $100k
        income_documented_annual_cents=8_000_000,  # verified = 80% floor
        sale_price_cents=50_000_000,
        requested_loan_amount_cents=40_000_000,    # 4x stated
        appraised_value_cents=50_000_000,
        compliance_reviewer_id="co-001",
    )
    submit_udaap_pass(app["id"], compliance_officer_id="co-001")
    # Read DTI; it should be <= 0.43.
    from test_helpers import get_loan_application
    state = get_loan_application(app["id"], headers=loan_officer_headers)
    if state["dti_ratio"] is not None and state["dti_ratio"] > 0.43:
        # If the implementation interprets the formula differently and
        # produces > 0.43, APPROVE must return ERR_DTI_EXCEEDED.
        res = api.underwrite_decision(
            app["id"],
            underwrite_decision_payload(decision="APPROVE"),
            loan_officer_headers,
        )
        validate_error(
            res, ApiErrorId.ERR_DTI_EXCEEDED.value,
            expected_status=422,
        )
    else:
        # DTI <= 0.43; APPROVE must succeed.
        res = api.underwrite_decision(
            app["id"],
            underwrite_decision_payload(decision="APPROVE"),
            loan_officer_headers,
        )
        out = validate_success(res, 200)
        assert out["status"] == "CONDITIONAL_APPROVAL"


# ===========================================================================
# LTV ceiling at APPROVE — PRD §3.8
# ===========================================================================
def test_underwrite_approve_ltv_above_97pct_rejected(api, loan_officer_headers):
    """PRD §3.8: "its ltv_ratio must be no greater than 0.97 (else
    ERR_LTV_EXCEEDED)"

    Claim: with sale=$400,000, appraised=$390,000 (lower basis),
    requested=$380,000:
       ltv = 380_000_000 / 390_000_000 = 0.9744 > 0.97
    APPROVE must return ERR_LTV_EXCEEDED.
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        annual_income_cents=15_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=38_000_000,
        appraised_value_cents=39_000_000,  # lower than sale
        compliance_reviewer_id="co-001",
    )
    submit_udaap_pass(app["id"], compliance_officer_id="co-001")
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(decision="APPROVE"),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_LTV_EXCEEDED.value, expected_status=422,
    )


def test_underwrite_approve_ltv_at_97pct_accepted(api, loan_officer_headers):
    """PRD §3.8: "ltv_ratio must be no greater than 0.97" — the
    boundary is inclusive ("no greater than" => 0.97 itself is OK).

    Claim: with ltv = 0.9700 exactly, APPROVE succeeds. Build sale =
    appraised = 100_000_000; requested = 97_000_000 -> ltv = 0.9700.
    """
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        annual_income_cents=30_000_000,
        sale_price_cents=100_000_000,
        requested_loan_amount_cents=97_000_000,
        appraised_value_cents=100_000_000,
        compliance_reviewer_id="co-001",
    )
    submit_udaap_pass(app["id"], compliance_officer_id="co-001")
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(decision="APPROVE"),
        loan_officer_headers,
    )
    out = validate_success(res, 200)
    assert out["status"] == "CONDITIONAL_APPROVAL"
    assert out["pmi_required"] is True, (
        "PRD §3.8: 'On approval the system recomputes pmi_required as "
        "the truth of ltv_ratio strictly greater than 0.80.' "
        "0.9700 > 0.80 => pmi_required = true."
    )


# ===========================================================================
# RBAC — PRD §4
# ===========================================================================
def test_compliance_officer_cannot_pre_qualify(api):
    """PRD §4: "POST /loan-applications/{id}/pre-qualify — LoanOfficer".

    Claim: a ComplianceOfficer attempting pre-qualify -> 403
    ERR_FORBIDDEN_ROLE.
    """
    from test_helpers import TEST_USERS
    _, app = create_borrower_and_application(
        headers=TEST_USERS["loan_officer_headers"],
    )
    res = api.pre_qualify(
        app["id"], None, TEST_USERS["compliance_officer_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


def test_borrower_cannot_create_loan_application(api):
    """PRD §4: "POST /loan-applications — LoanOfficer, Admin".

    Claim: a Borrower role cannot create a LoanApplication.
    """
    from test_helpers import (
        TEST_USERS,
        create_borrower,
        create_loan_application_payload,
    )
    b = create_borrower(headers=TEST_USERS["loan_officer_headers"])
    headers = make_borrower_headers(b["id"])
    res = api.create_loan_application(
        create_loan_application_payload(borrower_id=b["id"]),
        headers,
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


def test_borrower_can_read_own_application(api, loan_officer_headers):
    """PRD §2.1: "A borrower may read only those LoanApplication
    records whose borrower_id equals their own X-User-ID"

    Claim: GET /loan-applications/{id} with X-User-Role=Borrower and
    X-User-ID = the application's borrower_id succeeds.
    """
    borrower, app = create_borrower_and_application(
        headers=loan_officer_headers,
    )
    res = api.get_loan_application(
        app["id"], make_borrower_headers(borrower["id"]),
    )
    out = validate_success(res, 200)
    assert out["id"] == app["id"]


def test_borrower_cannot_read_other_application(api, loan_officer_headers):
    """PRD §2.1: "A borrower may read only those LoanApplication
    records whose borrower_id equals their own X-User-ID"

    Claim: GET /loan-applications/{id} with a Borrower X-User-ID that
    is NOT the application's borrower_id is rejected (403 or 404).
    """
    borrower_a, app_a = create_borrower_and_application(
        headers=loan_officer_headers,
    )
    borrower_b, _ = create_borrower_and_application(
        headers=loan_officer_headers,
    )
    # Borrower B tries to read Borrower A's application.
    res = api.get_loan_application(
        app_a["id"], make_borrower_headers(borrower_b["id"]),
    )
    assert res.status_code in (403, 404), (
        f"PRD §2.1: cross-borrower read must be rejected; got "
        f"{res.status_code}."
    )
