"""Fee calculations: the discount-then-sum-then-round excess-claims rule,
the discount-only filing/issue fee schedule, the per-month extension fee
table, the entity-size multipliers, and the fee-amount-mismatch rejection.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, create_applicant, create_application,
    setup_applicant_and_application,
    setup_application_in_awaiting_examination,
    setup_application_with_outstanding_oa,
    pay_filing_fee,
    create_fee_payment_payload,
    create_office_action_response_payload,
    filing_fee_cents, issue_fee_cents, extension_fee_cents,
    excess_claims_fee_cents,
)


# =============================================================================
# Difficulty / combinatorial_formula / excess_claims_fee_rounding_order_pinned
# =============================================================================

def test_excess_claims_small_entity_exact_amount_posts(api):
    """For a SMALL UTILITY filing with 21 total claims and 4 independent
    claims, the expected excess-claims fee = (1*10000*0.5) + (1*48000*0.5)
    = 5000 + 24000 = 29000 cents. Paying exactly 29000 must POST.

    PRD §3.3: "The expected excess fee is computed as follows: count the
    excess total claims as `claim_count` minus 20 (or zero, whichever is
    greater), count the excess independent claims as `independent_claim_count`
    minus 3 (or zero, whichever is greater), multiply the excess-total count
    by `EXCESS_CLAIM_BASE_CENTS` of 10,000 cents per claim, multiply the
    excess-independent count by `EXCESS_INDEP_BASE_CENTS` of 48,000 cents per
    claim, apply the entity-size multiplier to each of those two products
    individually, add the two scaled products together, and finally round
    the sum to the nearest cent using round-half-up."

    Design: Difficulty/combinatorial_formula/excess_claims_fee_rounding_order_pinned
    """
    set_clock("2026-05-27T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="SMALL", application_type="UTILITY",
        title="Excess claims widget", claim_count=21, independent_claim_count=4,
    )
    pay_filing_fee(applicant, application)  # 16000 SMALL UTILITY

    expected = excess_claims_fee_cents(21, 4, "SMALL")
    assert expected == 29000  # pin the value for the test reader

    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="EXCESS_CLAIMS",
            amount_cents=expected,
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(res, 201)
    assert fee_payment["payment_status"] == "POSTED"

    app_after = validate_success(
        api.get_application(application["id"], make_applicant_headers(applicant["id"])),
        200,
    )
    assert app_after["total_fees_paid_cents"] == 16000 + 29000


def test_excess_claims_amount_off_by_one_rejected(api):
    """The fee-amount-exactness rule is unforgiving: 29001 (one cent over)
    is rejected with ERR_FEE_AMOUNT_MISMATCH.

    PRD §2.6: "Every calculated fee follows the same procedure: take the
    base amount in cents from the calculation's constant table, multiply by
    the applicant's entity-size multiplier (1.00 for `LARGE`, 0.50 for
    `SMALL`, 0.20 for `MICRO`), round the product to the nearest integer
    using round-half-up, and compare the result for exact equality against
    the applicant's submitted `amount_cents`. Greater is rejected just as
    firmly as less."

    Design: Difficulty/combinatorial_formula/excess_claims_fee_rounding_order_pinned
    """
    set_clock("2026-05-27T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="SMALL", application_type="UTILITY",
        title="Excess claims widget", claim_count=21, independent_claim_count=4,
    )
    pay_filing_fee(applicant, application)

    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="EXCESS_CLAIMS",
            amount_cents=29001,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# =============================================================================
# Corner / calculations / filing_fee_micro_design_amount_exact
# =============================================================================

def test_micro_design_filing_fee_at_exact_amount_posts(api):
    """MICRO DESIGN filing fee = round_half_up(22000 * 0.20) = 4400 cents.

    PRD §3.3: "The base filing fee in cents depends on the application type:
    32,000 cents for `UTILITY`, 22,000 cents for `DESIGN`, 30,000 cents for
    `PROVISIONAL`, and 32,000 cents for `PCT_NATIONAL`. That base is
    multiplied by the entity multiplier — 1.00, 0.50, or 0.20 for `LARGE`,
    `SMALL`, and `MICRO` respectively — and the product is rounded to the
    nearest cent using round-half-up to yield the expected payment."

    Design: Corner/calculations/filing_fee_micro_design_amount_exact
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant = create_applicant(
        legal_name="Micro Designer", entity_size="MICRO",
        prior_applications_filed=0, micro_qualifying_year=2025,
        gross_income_prior_year_cents=5000000,
    )
    application = create_application(
        applicant, application_type="DESIGN",
        title="Stylish widget", claim_count=10, independent_claim_count=2,
    )
    expected = filing_fee_cents("DESIGN", "MICRO")
    assert expected == 4400

    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="FILING",
            amount_cents=4400,
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(res, 201)
    assert fee_payment["payment_status"] == "POSTED"
    app_after = validate_success(
        api.get_application(application["id"], make_applicant_headers(applicant["id"])),
        200,
    )
    assert app_after["total_fees_paid_cents"] == 4400


# =============================================================================
# Corner / calculations / extension_fee_two_months_small_amount_exact
# =============================================================================

def test_two_month_extension_small_entity_exact_amount(api):
    """SMALL 2-month extension = round_half_up(64000 * 0.5) = 32000 cents.
    Response with 2 months of extension and a posted EXTENSION fee of 32000
    yields an OAR whose extension_fee_cents == 32000.

    PRD §3.5: "Otherwise, the expected base in cents is read from a small
    table indexed by month count — 22,000 cents for a 1-month extension,
    64,000 cents cumulative for a 2-month extension, and 148,000 cents
    cumulative for a 3-month extension — multiplied by the same entity-size
    multiplier, and rounded to the nearest cent with round-half-up. The
    result is recorded on the response as `extension_fee_cents`."

    Design: Corner/calculations/extension_fee_two_months_small_amount_exact
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="SMALL", action_type="NON_FINAL",
    )
    set_clock("2026-04-30T00:00:00.000Z")
    expected_ext = extension_fee_cents(2, "SMALL")
    assert expected_ext == 32000

    # File the OAR first so the EXTENSION amount can be matched against the
    # response's extension_months_requested per PRD §3.5.
    res = api.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=oa["id"],
            extension_months_requested=2, claim_amendment_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )
    oar = validate_success(res, 201)
    assert oar["response_status"] == "ACCEPTED"
    assert oar["extension_fee_cents"] == 32000

    # Post EXTENSION fee payment in the same transaction-window
    pay = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="EXTENSION",
            amount_cents=expected_ext,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_success(pay, 201)


# =============================================================================
# Corner / calculations / filing_fee_amount_mismatch_rejected
# =============================================================================

def test_filing_fee_amount_mismatch_rejected(api):
    """LARGE UTILITY filing fee = 32000; submitting 31000 (under) returns
    ERR_FEE_AMOUNT_MISMATCH.

    PRD §3.3: "A submitted amount that is greater or less than this expected
    value is rejected with `ERR_FEE_AMOUNT_MISMATCH`."

    Design: Corner/calculations/filing_fee_amount_mismatch_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
    )
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="FILING",
            amount_cents=31000,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# =============================================================================
# Difficulty / boundary_precision_check / excess_claims_at_20_boundary_zero_fee
# =============================================================================

def test_at_claim_boundary_no_excess_claims_fee_required(api, examiner_headers):
    """At exactly claim_count=20 and independent_claim_count=3 (both at the
    included-without-fee thresholds), no EXCESS_CLAIMS payment is required —
    only FILING — and the application can still be docketed.

    PRD §3.3: "A second category, `EXCESS_CLAIMS`, covers the per-claim
    surcharge that applies whenever an application files more than 20 total
    claims or more than 3 independent claims."

    Design: Difficulty/boundary_precision_check/excess_claims_at_20_boundary_zero_fee
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
        title="Boundary widget", claim_count=20, independent_claim_count=3,
    )
    pay_filing_fee(applicant, application)  # 32000 LARGE UTILITY

    docket_res = api.docket_application(application["id"], examiner_headers)
    docketed = validate_success(docket_res, 200)
    assert docketed["status"] == "AWAITING_EXAMINATION"
    assert docketed["total_fees_paid_cents"] == 32000


def test_one_claim_above_boundary_requires_excess_fee(api):
    """At claim_count=21 and independent_claim_count=3, the excess-total
    surcharge alone applies (1*10000*1.00 = 10000 cents LARGE), and that
    payment posts at exactly the expected amount.

    PRD §3.3: "A second category, `EXCESS_CLAIMS`, covers the per-claim
    surcharge that applies whenever an application files more than 20 total
    claims or more than 3 independent claims."

    Design: Difficulty/boundary_precision_check/excess_claims_at_20_boundary_zero_fee
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_applicant_and_application(
        entity_size="LARGE", application_type="UTILITY",
        title="Just-above widget", claim_count=21, independent_claim_count=3,
    )
    pay_filing_fee(applicant, application)
    expected = excess_claims_fee_cents(21, 3, "LARGE")
    assert expected == 10000

    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="EXCESS_CLAIMS",
            amount_cents=10000,
        ),
        make_applicant_headers(applicant["id"]),
    )
    fee_payment = validate_success(res, 201)
    assert fee_payment["payment_status"] == "POSTED"
