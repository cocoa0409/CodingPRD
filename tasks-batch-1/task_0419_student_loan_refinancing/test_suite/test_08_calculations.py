"""Calculation correctness: soft pull, estimated APR, locked APR constants, DTI
precision, pool best-fit selection, eligibility filtering, waterfall edge.

Corner queue B: section calculations (non-stub instances only; the dti and
estimated-vs-locked variant instances are owned by §1.8 difficulty instances).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_borrower_headers,
    make_disbursement_officer_headers,
    setup_prequalified_application,
    setup_approved_application,
    setup_funded_loan,
    set_clock,
    post_payment,
    get_loan,
    get_abs_pool,
    api_client,
)


def test_soft_pull_subprime_moves_up_to_near_prime(api):
    """PRD 3.2: "A borrower at position zero or one is moved up one position (so
    SUBPRIME becomes NEAR_PRIME and NEAR_PRIME becomes PRIME)"

    Design: Corner/calculations/soft_pull_subprime_moves_up_to_near_prime
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "SUBPRIME",
                        "base_apr_bps": 900, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 20_000_000, "fico_band": "SUBPRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    assert bundle["application"]["soft_pull_fico_band"] == "NEAR_PRIME", (
        f"SUBPRIME should move up to NEAR_PRIME, got {bundle['application']['soft_pull_fico_band']}"
    )


def test_estimated_apr_variable_adds_index_and_band_surcharge(api):
    """PRD 3.2: "Each offer's estimated_apr_bps is computed as the prequal
    estimate: the grid cell's base_apr_bps, plus the cell's index_apr_bps if the
    offer's rate type is VARIABLE (otherwise zero), plus a band surcharge keyed on
    the application's soft_pull_fico_band. The band surcharge is 300 basis points
    for SUBPRIME, 150 for NEAR_PRIME, 50 for PRIME, and 0 for SUPER_PRIME."

    base 500 + index 120 + NEAR_PRIME surcharge 150 = 770.

    Design: Corner/calculations/estimated_apr_variable_adds_index_and_band_surcharge
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "VARIABLE", "term_months": 84, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 500, "index_apr_bps": 120},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "SUBPRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 84, "requested_rate_type": "VARIABLE"},
    )
    offer = bundle["offers"][0]
    assert offer["estimated_apr_bps"] == 770, (
        f"estimated should be 770 (500+120+150), got {offer['estimated_apr_bps']}"
    )
    assert offer["rate_type"] == "VARIABLE"


def test_locked_apr_member_tier_discount_after_autopay(api):
    """PRD 3.4: "first subtract the autopay discount of 25 basis points if and
    only if autopay_elected is true, then from that running value subtract the
    member-tier discount keyed on the borrower's member_tier — 0 basis points for
    NONE, 10 for SILVER, 25 for GOLD, and 50 for PLATINUM."

    estimated 800, autopay on, member NONE -> 800 - 25 - 0 = 775.

    Design: Corner/calculations/locked_apr_member_tier_discount_after_autopay
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    offer = bundle["offers"][0]
    assert offer["estimated_apr_bps"] == 800
    borrower = bundle["borrower"]
    app = bundle["application"]
    locked = validate_success(api.lock_offer(
        offer["id"], {"expected_application_version": app["version"], "autopay_elected": True},
        make_borrower_headers(borrower["id"])))
    assert locked["locked_apr_bps"] == 775, (
        f"locked should be 775 (800 - 25 autopay - 0 member), got {locked['locked_apr_bps']}"
    )


def test_dti_computation_borrower_only_precision_four_decimals(api):
    """PRD 3.2: "The amortization factor is 0.0188 for a 60-month term"
    PRD 3.2: "The ratio is the annual debt service divided by the combined income,
    rounded half up to four decimal places."

    principal 8,000,000 * 0.0188 = 150,400; * 12 = 1,804,800; / 4,000,000 = 0.4512.

    Design: Corner/calculations/dti_computation_borrower_only_precision_four_decimals
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 8_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    assert bundle["application"]["dti_ratio"] == pytest.approx(0.4512, abs=1e-9), (
        f"dti should be 0.4512, got {bundle['application']['dti_ratio']}"
    )


def test_pool_capacity_best_fit_selection_tightest_pool(api):
    """PRD 3.7: "the pool is chosen by best fit: the candidate with the smallest
    remaining capacity wins, where remaining capacity is max_principal_cents minus
    committed_principal_cents (tightest fit first)."

    Two eligible pools: TIGHT (max 6,000,000) and ROOMY (max 20,000,000); the
    application requesting 5,000,000 is tagged to TIGHT.

    Design: Corner/calculations/pool_capacity_best_fit_selection_tightest_pool
    """
    from test_helpers import create_abs_pool
    tight = create_abs_pool(pool_code="CORNER-POOL-TIGHT", max_principal_cents=6_000_000,
                            min_fico_band="SUBPRIME", allowed_rate_type="ANY")
    roomy = create_abs_pool(pool_code="CORNER-POOL-ROOMY", max_principal_cents=20_000_000,
                            min_fico_band="SUBPRIME", allowed_rate_type="ANY")
    bundle = setup_approved_application(
        autopay_elected=False,
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = validate_success(api.fund_application(
        bundle["application"]["id"], make_disbursement_officer_headers("do-corner-7")), 201)
    assert loan["abs_pool_id"] == tight["id"], (
        f"best-fit should pick TIGHT pool, got {loan['abs_pool_id']}"
    )
    assert get_abs_pool(tight["id"])["committed_principal_cents"] == 5_000_000
    assert get_abs_pool(roomy["id"])["committed_principal_cents"] == 0


def test_pool_eligibility_filters_rate_type_mismatch(api):
    """PRD 3.7: "whose allowed_rate_type is either ANY or equal to the locked
    offer's rate_type"
    PRD 3.7: "If that candidate set is empty, funding is rejected with
    ERR_NO_ELIGIBLE_POOL (HTTP 422) and no loan is created."

    Only pool allows FIXED; a VARIABLE loan finds no candidate -> ERR_NO_ELIGIBLE_POOL.

    Design: Corner/calculations/pool_eligibility_filters_rate_type_mismatch
    """
    from test_helpers import create_abs_pool
    fixedonly = create_abs_pool(pool_code="CORNER-POOL-FIXEDONLY", max_principal_cents=20_000_000,
                                min_fico_band="SUBPRIME", allowed_rate_type="FIXED")
    bundle = setup_approved_application(
        autopay_elected=False,
        grid_overrides={"rate_type": "VARIABLE", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 500, "index_apr_bps": 100},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "VARIABLE"},
    )
    resp = api.fund_application(bundle["application"]["id"], make_disbursement_officer_headers("do-corner-8"))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_POOL.value, 422)
    assert get_abs_pool(fixedonly["id"])["committed_principal_cents"] == 0


def test_payment_waterfall_principal_only_when_no_interest(api):
    """PRD 3.9: "The number of days is the count of whole UTC days between those
    two instants, taking the floor."
    PRD 3.9: "The principal_portion_cents is the smaller of that remainder and the
    loan's principal_balance_cents."

    Payment posted the same day as funding -> 0 days accrue -> interest_portion 0,
    principal_portion is the whole payment.

    Design: Corner/calculations/payment_waterfall_principal_only_when_no_interest
    """
    bundle = setup_funded_loan(
        clock_at="2026-06-01T00:00:00Z",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-WF", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    payment = post_payment(loan, 100_000, "2026-06-01T00:00:00Z", paid_at="2026-06-01T00:00:00Z")
    assert payment["interest_portion_cents"] == 0, (
        f"0 days accrued -> interest 0, got {payment['interest_portion_cents']}"
    )
    assert payment["principal_portion_cents"] == 100_000
    assert get_loan(loan["id"])["principal_balance_cents"] == 4_900_000
