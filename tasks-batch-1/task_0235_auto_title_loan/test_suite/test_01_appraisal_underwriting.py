"""Appraisal valuation, the LTV ceiling, and underwriting gates.

Covers dual-variant / combinatorial appraisal calculations, the LTV boundary,
and the APR-cap / term-bounds gates at application submission.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_appraiser_headers,
    make_underwriter_headers,
    ensure_profile,
    create_borrower,
    create_vehicle,
    create_finalized_appraisal,
    setup_finalized_appraisal,
    set_clock,
    CLOCK_ORIGIN,
    CA_PROFILE,
    VA_PROFILE,
    create_application_payload,
    create_appraisal_payload,
    loan_for_application,
)

_UW = TEST_USERS["underwriter_headers"]
_APPR = TEST_USERS["appraiser_headers"]
_ADMIN = TEST_USERS["compliance_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Dual-variant: redemption vs reinstatement amounts diverge on the same loan
# (this instance reaches a delinquent loan; the payoff-quote pair is the trigger)
# ─────────────────────────────────────────────────────────────────────────
def _setup_ca_delinquent_loan_with_device():
    """Originate a CA loan (principal 600000, apr 3600, 3-month), install a device,
    advance the clock so seq1+seq2 are past due, and assess delinquency.
    Returns the loan id.
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile()
    borrower = create_borrower()
    vehicle = create_vehicle(borrower["id"])
    appraisal = create_finalized_appraisal(vehicle["id"], appraiser_id="appr-dvc")
    app = get_success_data(api_client.create_application(
        create_application_payload(borrower["id"], appraisal["id"]), _UW))
    # Approval returns the (APPROVED) application; the Loan is fetched by
    # reverse reference (Loans listable filtered by application_id, PRD §3.4).
    approved_app = get_success_data(api_client.approve_application(
        app["id"], make_underwriter_headers("uw-dvc")))
    loan = loan_for_application(approved_app["id"])
    get_success_data(api_client.create_device(
        {"vehicle_id": vehicle["id"], "serial_number": "SER-DVC-1"},
        TEST_USERS["loan_servicer_headers"]))
    set_clock("2026-03-15T00:00:00.000Z")
    get_success_data(api_client.assess_delinquency(loan["id"], TEST_USERS["loan_servicer_headers"]))
    return loan["id"]


def test_payoff_quote_redemption_and_reinstatement_diverge(api):
    """PRD §3.7: "The redemption amount is everything owed plus repossession cost
    recovery when a repossession has been opened: the sum of principal_balance_cents,
    accrued_interest_cents, and fees_balance_cents, plus a flat 25000-cent repossession
    recovery fee when the loan has a repossession order in ORDERED, ASSIGNED, or
    RECOVERED status (and excluding that fee when no active repossession order exists)."
    PRD §3.7: "The reinstatement amount is the cure amount only: the sum of past-due
    principal (the sum of principal_due_cents over installments whose status is
    PAST_DUE), past-due interest (the sum of interest_due_cents over those same
    PAST_DUE installments), the current fees_balance_cents, and — only when the loan's
    delinquency_status is DEFAULT — a flat repossession recovery fee of 25000 cents."

    Design: Difficulty/dual_variant_calc/loan_payoff_redemption_vs_reinstatement_diverge
    """
    loan_id = _setup_ca_delinquent_loan_with_device()
    quote = get_success_data(api.get_payoff_quote(loan_id, TEST_USERS["loan_servicer_headers"]))
    assert quote["redemption_amount_cents"] == 640176
    assert quote["reinstatement_amount_cents"] == 434236
    assert quote["redemption_amount_cents"] != quote["reinstatement_amount_cents"]


def test_payoff_quote_amounts_are_two_distinct_algorithms(api):
    """PRD §3.7: "It deliberately excludes principal that is not yet due."
    Redemption includes not-yet-due principal (the full balance) while reinstatement is
    arrears-only, so the two computed amounts must differ on a delinquent loan that still
    carries undue principal.

    Design: Difficulty/dual_variant_calc/loan_payoff_redemption_vs_reinstatement_diverge
    """
    loan_id = _setup_ca_delinquent_loan_with_device()
    quote = get_success_data(api.get_payoff_quote(loan_id, TEST_USERS["loan_servicer_headers"]))
    # Redemption (full balance) strictly exceeds reinstatement (arrears only).
    assert quote["redemption_amount_cents"] == 640176
    assert quote["reinstatement_amount_cents"] == 434236
    assert quote["redemption_amount_cents"] > quote["reinstatement_amount_cents"]


# ─────────────────────────────────────────────────────────────────────────
# Dual-variant: trade-in vs auction basis diverge for identical appraisal inputs
# ─────────────────────────────────────────────────────────────────────────
def test_appraisal_basis_trade_in_vs_auction_diverge(api):
    """PRD §3.2: "The system first selects the raw valuation according to the
    borrower's state valuation basis: if that state's profile names TRADE_IN, the raw
    value is trade_in_value_cents; if it names AUCTION, the raw value is
    auction_value_cents."
    PRD §3.2: "The basis value is the raw value multiplied by the quantity (10000 minus
    the haircut basis points), divided by 10000, with the result floored to whole cents."
    PRD §3.2: "It is the basis value multiplied by the borrower-state max_ltv_bps,
    divided by 10000, with the result floored to whole cents."

    Design: Difficulty/dual_variant_calc/appraisal_basis_trade_in_vs_auction_diverge
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile(VA_PROFILE)
    ensure_profile(CA_PROFILE)
    b_va = create_borrower(state_code="VA")
    b_ca = create_borrower(state_code="CA")
    veh_va = create_vehicle(b_va["id"])
    veh_ca = create_vehicle(b_ca["id"])
    appr_va = create_finalized_appraisal(veh_va["id"], appraiser_id="appr-va")
    appr_ca = create_finalized_appraisal(veh_ca["id"], appraiser_id="appr-ca")

    va = get_success_data(api.get_appraisal(appr_va["id"], _APPR))
    ca = get_success_data(api.get_appraisal(appr_ca["id"], _APPR))

    assert va["basis_value_cents"] == 1900000
    assert va["max_principal_cents"] == 950000
    assert ca["basis_value_cents"] == 1520000
    assert ca["max_principal_cents"] == 760000
    assert va["max_principal_cents"] != ca["max_principal_cents"]


def test_trade_in_basis_exceeds_auction_basis(api):
    """PRD §3.2: "Because the two states differ only in which raw value they select, a
    TRADE_IN state yields a larger basis — and therefore a larger LTV ceiling — than an
    AUCTION state would for the identical vehicle and condition, while an AUCTION state
    yields the smaller basis from the lower auction value."

    Design: Difficulty/dual_variant_calc/appraisal_basis_trade_in_vs_auction_diverge
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile(VA_PROFILE)
    ensure_profile(CA_PROFILE)
    b_va = create_borrower(state_code="VA")
    b_ca = create_borrower(state_code="CA")
    appr_va = create_finalized_appraisal(create_vehicle(b_va["id"])["id"], appraiser_id="appr-va2")
    appr_ca = create_finalized_appraisal(create_vehicle(b_ca["id"])["id"], appraiser_id="appr-ca2")
    va = get_success_data(api.get_appraisal(appr_va["id"], _APPR))
    ca = get_success_data(api.get_appraisal(appr_ca["id"], _APPR))
    assert va["basis_value_cents"] == 1900000
    assert ca["basis_value_cents"] == 1520000
    assert va["basis_value_cents"] > ca["basis_value_cents"]
    assert va["max_principal_cents"] > ca["max_principal_cents"]


# ─────────────────────────────────────────────────────────────────────────
# Combinatorial: nested haircut -> floor -> LTV multiply -> floor (AUCTION/GOOD)
# ─────────────────────────────────────────────────────────────────────────
def test_appraisal_finalize_computes_basis_and_max_principal_auction_good(api):
    """PRD §3.2: "a grade of EXCELLENT applies a haircut of 0 basis points, GOOD
    applies 500 basis points, FAIR applies 1500 basis points, and POOR applies 3000
    basis points. The basis value is the raw value multiplied by the quantity (10000
    minus the haircut basis points), divided by 10000, with the result floored to whole
    cents."
    PRD §3.2: "It is the basis value multiplied by the borrower-state max_ltv_bps,
    divided by 10000, with the result floored to whole cents."

    Design: Difficulty/combinatorial_formula/appraisal_basis_nested_haircut_ltv_mode_a
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile(CA_PROFILE)
    borrower = create_borrower()
    vehicle = create_vehicle(borrower["id"])
    appraisal = get_success_data(api.create_appraisal(
        create_appraisal_payload(vehicle["id"], trade_in_value_cents=2000000,
                                 auction_value_cents=1600000, condition_grade="GOOD"), _APPR))
    finalized = get_success_data(api.finalize_appraisal(
        appraisal["id"], make_appraiser_headers("appr-comb")))
    # AUCTION basis: 1600000 * (10000 - 500) / 10000 = 1520000; LTV 50% -> 760000.
    assert finalized["basis_value_cents"] == 1520000
    assert finalized["max_principal_cents"] == 760000


def test_appraisal_max_principal_depends_on_branch_and_tier(api):
    """PRD §3.2: "if it names `AUCTION`, the raw value is `auction_value_cents`."
    PRD §3.2: "`GOOD` applies 500 basis points".
    Selecting the AUCTION branch (1600000) then the GOOD tier (500 bps) then flooring
    then the 50% LTV multiply yields exactly 760000 — a non-linear chain, not a single
    linear term.

    Design: Difficulty/combinatorial_formula/appraisal_basis_nested_haircut_ltv_mode_a
    """
    set_clock(CLOCK_ORIGIN)
    ensure_profile(CA_PROFILE)
    borrower = create_borrower()
    appraisal = create_finalized_appraisal(
        create_vehicle(borrower["id"])["id"], appraiser_id="appr-comb2",
        trade_in_value_cents=2000000, auction_value_cents=1600000, condition_grade="GOOD")
    fetched = get_success_data(api.get_appraisal(appraisal["id"], _APPR))
    assert fetched["basis_value_cents"] == 1520000
    assert fetched["max_principal_cents"] == 760000


# ─────────────────────────────────────────────────────────────────────────
# Boundary precision: LTV ceiling (requested == max_principal allowed; +1 rejected)
# ─────────────────────────────────────────────────────────────────────────
def test_ltv_boundary_requested_equals_max_principal_allowed(api):
    """PRD §3.3: "It further enforces that requested_principal_cents does not exceed
    the appraisal's max_principal_cents — a requested principal exactly equal to the
    ceiling is allowed, and only a requested principal strictly greater than the ceiling
    is rejected, with ERR_LTV_EXCEEDED."

    Design: Difficulty/boundary_precision_check/ltv_boundary_requested_equals_max_principal_allowed
    """
    set_clock(CLOCK_ORIGIN)
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-ltv-eq")
    # max_principal_cents == 760000 for the canonical AUCTION/GOOD appraisal.
    res = api.create_application(
        create_application_payload(borrower["id"], appraisal["id"],
                                   requested_principal_cents=760000), _UW)
    app = validate_success(res, 201)
    assert app["status"] == "SUBMITTED"


def test_ltv_boundary_requested_one_over_max_principal_rejected(api):
    """PRD §3.3: "only a requested principal strictly greater than the ceiling is
    rejected, with ERR_LTV_EXCEEDED."

    Design: Difficulty/boundary_precision_check/ltv_boundary_requested_equals_max_principal_allowed
    """
    set_clock(CLOCK_ORIGIN)
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-ltv-over")
    res = api.create_application(
        create_application_payload(borrower["id"], appraisal["id"],
                                   requested_principal_cents=760001), _UW)
    validate_error(res, "ERR_LTV_EXCEEDED")


# ─────────────────────────────────────────────────────────────────────────
# Corner: APR cap and term bounds gates at submission
# ─────────────────────────────────────────────────────────────────────────
def test_apr_cap_exceeded_on_application_submit(api):
    """PRD §3.3: "the APR cap gate fires when `contract_apr_bps` is strictly greater
    than the borrower-state `max_apr_bps` — a contract rate exactly equal to the cap is
    allowed — and a violation is rejected with `ERR_APR_CAP_EXCEEDED`."

    Design: Corner/validations/apr_cap_exceeded_on_application_submit
    """
    set_clock(CLOCK_ORIGIN)
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-apr")
    res = api.create_application(
        create_application_payload(borrower["id"], appraisal["id"], contract_apr_bps=4000), _UW)
    validate_error(res, "ERR_APR_CAP_EXCEEDED")


def test_apr_cap_boundary_contract_equals_cap_allowed(api):
    """PRD §3.3: "a contract rate exactly equal to the cap is allowed".
    PRD §3.3: "At submission the system computes and stores the application's
    effective_apr_bps as the lesser of contract_apr_bps and the borrower-state
    max_apr_bps."

    Design: Corner/validations/apr_cap_boundary_contract_equals_cap_allowed
    """
    set_clock(CLOCK_ORIGIN)
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-aprb")
    res = api.create_application(
        create_application_payload(borrower["id"], appraisal["id"], contract_apr_bps=3600), _UW)
    app = validate_success(res, 201)
    assert app["status"] == "SUBMITTED"
    assert app["effective_apr_bps"] == 3600


def test_term_out_of_bounds_rejected(api):
    """PRD §3.3: "The same submission also enforces that the requested term lies within
    the borrower state's permitted window, that is, term_months is at least
    min_term_months and at most max_term_months; a term outside that window is rejected
    with ERR_TERM_OUT_OF_BOUNDS."

    Design: Corner/validations/term_out_of_bounds_rejected
    """
    set_clock(CLOCK_ORIGIN)
    _, borrower, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-term")
    res = api.create_application(
        create_application_payload(borrower["id"], appraisal["id"], term_months=36), _UW)
    validate_error(res, "ERR_TERM_OUT_OF_BOUNDS")
