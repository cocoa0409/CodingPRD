"""Servicing lifecycle and recapture: shared-appreciation recapture, the
provisional-vs-final assistance divergence, declining-balance sum-then-round
forgiveness, per-award principal conservation on servicing close, the parallel
payment/lifecycle dimensions, and the sale-before-open guard.

Difficulty:
  dual_variant_calc / recapture_shared_appreciation_on_servicing
  dual_variant_calc / assistance_provisional_vs_final_divergence
  combinatorial_formula / declining_balance_forgiveness_sum_then_round_mode_b
  compensating_invariant / assistance_principal_conserved_on_servicing_close
  non_linear_state_machine / servicing_parallel_payment_and_lifecycle
Corner:
  state_machines / report_sale_before_open_returns_error
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx

CASE_MANAGER = fx.CASE_MANAGER
SERVICER = fx.SERVICER


def _declining_balance_config():
    """DECLINING_BALANCE award, original_disbursed 3,650,000, opened_at
    2027-01-01. 50% AMI (tier 0), basis 20,000,000, first mortgage 16,350,000."""
    return dict(
        recapture_model="DECLINING_BALANCE",
        recapture_term_months=120,
        assistance_type="LOAN",
        annual_income_cents=5_000_000,
        purchase_price_cents=20_000_000,
        appraised_value_cents=20_000_000,
        first_mortgage_amount_cents=16_350_000,
        buyer_contribution_cents=0,
        alloc_amount=3_650_000,
        final_purchase_price_cents=20_000_000,
        final_first_mortgage_cents=16_350_000,
        complete_clock="2027-01-01T00:00:00Z",
    )


# --- dual_variant_calc / recapture_shared_appreciation_on_servicing ---------
def test_shared_appreciation_sale_event_figures(api):
    """PRD 3.7: "The recapture amount is the original disbursed principal plus
    the program's `appreciation_share_pct` percent of the appreciation (the
    share percentage divided by 100, multiplied by `appreciation_cents`, rounded
    half-up), and the forgiven amount is always zero."
    PRD 3.7: "The sale event's `appreciation_cents` is the sale price minus the
    award's captured `basis_value_cents`, floored at zero (never negative)."

    Design: Difficulty/dual_variant_calc/recapture_shared_appreciation_on_servicing
    """
    ctx = fx.setup_servicing_account(api)  # SHARED_APPRECIATION, basis 30,000,000, original 5,000,000
    sale = validate_success(
        api.report_sale(ctx["servicing_account"]["id"],
                        {"sale_price_cents": 35_000_000, "sale_date": "2029-01-01T00:00:00Z"}, SERVICER),
        201,
    )
    assert sale["appreciation_cents"] == 5_000_000
    assert sale["recapture_amount_cents"] == 6_500_000  # 5,000,000 + round(0.30 * 5,000,000)
    assert sale["forgiven_amount_cents"] == 0


def test_shared_appreciation_copied_onto_servicing_account(api):
    """PRD 3.7: "Reporting a sale creates a **Sale Event** ... computes the
    recapture figures, copies `recapture_amount_cents` and `forgiven_amount_cents`
    onto the servicing account, and advances `lifecycle_status` from `ACTIVE` to
    `IN_SALE`."

    Design: Difficulty/dual_variant_calc/recapture_shared_appreciation_on_servicing
    """
    ctx = fx.setup_servicing_account(api)
    validate_success(
        api.report_sale(ctx["servicing_account"]["id"],
                        {"sale_price_cents": 35_000_000, "sale_date": "2029-01-01T00:00:00Z"}, SERVICER),
        201,
    )
    account = validate_success(api.get_servicing_account(ctx["servicing_account"]["id"], SERVICER), 200)
    assert account["recapture_amount_cents"] == 6_500_000
    assert account["forgiven_amount_cents"] == 0
    assert account["lifecycle_status"] == "IN_SALE"


# --- dual_variant_calc / assistance_provisional_vs_final_divergence ---------
def test_provisional_assistance_estimate(api):
    """PRD 3.2: "On success the system computes the reporting `ami_pct` and the
    provisional `estimated_assistance_cents` (the provisional assistance
    calculation of Section 3.4) from the application's estimated inputs."
    PRD 3.4: "In the provisional computation performed at submit and at each
    resubmit, the basis is the property's `purchase_price_cents`, the
    first-mortgage amount is the application's `first_mortgage_amount_cents`, the
    stated contribution is `buyer_contribution_cents`, and `ami_pct` is the value
    recorded on the application; no appraised-value cap applies to the basis in
    the provisional variant."

    Design: Difficulty/dual_variant_calc/assistance_provisional_vs_final_divergence
    """
    # basis 30,000,000, first 24,000,000, tier 3% -> required 900,000, gap 5,100,000, cap 5,000,000.
    ctx = fx.setup_eligible_application(api, with_education=False)
    application = validate_success(api.get_application(ctx["application"]["id"], CASE_MANAGER), 200)
    assert application["estimated_assistance_cents"] == 5_000_000


def test_final_assistance_diverges_from_provisional_at_closing(api):
    """PRD 3.6: "The award's `assistance_amount_final_cents` is recomputed with
    the assistance calculation of Section 3.4 in its final variant. Here the
    basis is the smaller of the closing's `final_purchase_price_cents` and the
    property's `appraised_value_cents`; the first-mortgage amount is
    `final_first_mortgage_cents`; the stated contribution is the application's
    `buyer_contribution_cents`; and `ami_pct` is the value recorded on the
    application."
    PRD 3.6: "The award's `original_disbursed_cents` is set equal to
    `assistance_amount_final_cents`, the true total disbursed and the basis for
    recapture."

    Design: Difficulty/dual_variant_calc/assistance_provisional_vs_final_divergence
    """
    # Final first mortgage 25,000,000 (vs 24,000,000 estimate): gap 30M-25M-900k = 4,100,000.
    ctx = fx.setup_servicing_account(api, final_first_mortgage_cents=25_000_000)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert award["assistance_amount_final_cents"] == 4_100_000
    assert award["original_disbursed_cents"] == 4_100_000
    assert award["status"] == "SERVICING"


# --- combinatorial_formula / declining_balance_forgiveness_sum_then_round ---
def test_declining_balance_forgiveness_single_final_rounding(api):
    """PRD 3.7: "The forgiven amount is the original principal multiplied by the
    smaller of the months held and `recapture_term_months`, divided by
    `recapture_term_months`, with a single round-half-up applied to that whole
    product. This single final rounding is required: rounding a per-month figure
    and then summing across months would produce a different cents result and is
    not used."

    Design: Difficulty/combinatorial_formula/declining_balance_forgiveness_sum_then_round_mode_b
    """
    # round_half_up(3,650,000 * 7 / 120) = round(212916.67) = 212917.
    ctx = fx.setup_servicing_account(api, **_declining_balance_config())
    validate_success(
        api.report_sale(ctx["servicing_account"]["id"],
                        {"sale_price_cents": 25_000_000, "sale_date": "2027-08-01T00:00:00Z"}, SERVICER),
        201,
    )
    account = validate_success(api.get_servicing_account(ctx["servicing_account"]["id"], SERVICER), 200)
    assert account["forgiven_amount_cents"] == 212_917


def test_declining_balance_recapture_is_principal_minus_forgiven(api):
    """PRD 3.7: "The recapture amount is the original principal minus the
    forgiven amount, which lands somewhere between zero and the full original
    amount."

    Design: Difficulty/combinatorial_formula/declining_balance_forgiveness_sum_then_round_mode_b
    """
    ctx = fx.setup_servicing_account(api, **_declining_balance_config())
    validate_success(
        api.report_sale(ctx["servicing_account"]["id"],
                        {"sale_price_cents": 25_000_000, "sale_date": "2027-08-01T00:00:00Z"}, SERVICER),
        201,
    )
    account = validate_success(api.get_servicing_account(ctx["servicing_account"]["id"], SERVICER), 200)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert account["recapture_amount_cents"] == 3_437_083  # 3,650,000 - 212,917
    assert award["original_disbursed_cents"] == 3_650_000


# --- compensating_invariant / assistance_principal_conserved_on_servicing_close
def test_recapture_and_forgiven_sum_to_principal_on_close(api):
    """PRD 3.7: "Closing sets `principal_balance_cents` to zero, moves
    `lifecycle_status` to the terminal `CLOSED`".
    PRD 3.7: "The recapture amount is the original principal minus the forgiven
    amount, which lands somewhere between zero and the full original amount."

    Design: Difficulty/compensating_invariant/assistance_principal_conserved_on_servicing_close
    """
    ctx = fx.setup_servicing_account(api, **_declining_balance_config())
    sa_id = ctx["servicing_account"]["id"]
    validate_success(
        api.report_sale(sa_id, {"sale_price_cents": 25_000_000, "sale_date": "2027-08-01T00:00:00Z"}, SERVICER), 201
    )
    validate_success(api.close_servicing(sa_id, SERVICER), 200)
    account = validate_success(api.get_servicing_account(sa_id, SERVICER), 200)
    assert account["recapture_amount_cents"] + account["forgiven_amount_cents"] == 3_650_000
    assert account["lifecycle_status"] == "CLOSED"


def test_award_recaptured_after_servicing_close(api):
    """PRD 3.7: "drives the award out of `SERVICING` to its terminal outcome: if
    the account's `recapture_amount_cents` is greater than zero the award becomes
    `RECAPTURED`, and if it is exactly zero the award becomes `REPAID`."

    Design: Difficulty/compensating_invariant/assistance_principal_conserved_on_servicing_close
    """
    ctx = fx.setup_servicing_account(api, **_declining_balance_config())
    sa_id = ctx["servicing_account"]["id"]
    validate_success(
        api.report_sale(sa_id, {"sale_price_cents": 25_000_000, "sale_date": "2027-08-01T00:00:00Z"}, SERVICER), 201
    )
    validate_success(api.close_servicing(sa_id, SERVICER), 200)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert award["status"] == "RECAPTURED"


# --- non_linear_state_machine / servicing_parallel_payment_and_lifecycle ----
def test_payment_delinquent_leaves_lifecycle_active(api):
    """PRD 3.7: "The toggle is permitted as long as the account is not `CLOSED`,
    and it never alters `lifecycle_status` — the two dimensions move
    independently."

    Design: Difficulty/non_linear_state_machine/servicing_parallel_payment_and_lifecycle
    """
    ctx = fx.setup_servicing_account(api)
    account = validate_success(
        api.set_payment_status(ctx["servicing_account"]["id"], {"to": "DELINQUENT"}, SERVICER), 200
    )
    assert account["payment_status"] == "DELINQUENT"
    assert account["lifecycle_status"] == "ACTIVE"


def test_payment_status_persists_across_sale_report(api):
    """PRD 3.7: "A separate `payment_status` dimension runs between `CURRENT` and
    `DELINQUENT` and evolves independently of the lifecycle."
    PRD 3.7: "advances `lifecycle_status` from `ACTIVE` to `IN_SALE`."

    Design: Difficulty/non_linear_state_machine/servicing_parallel_payment_and_lifecycle
    """
    ctx = fx.setup_servicing_account(api)
    sa_id = ctx["servicing_account"]["id"]
    validate_success(api.set_payment_status(sa_id, {"to": "DELINQUENT"}, SERVICER), 200)
    validate_success(
        api.report_sale(sa_id, {"sale_price_cents": 35_000_000, "sale_date": "2029-01-01T00:00:00Z"}, SERVICER), 201
    )
    account = validate_success(api.get_servicing_account(sa_id, SERVICER), 200)
    assert account["payment_status"] == "DELINQUENT"
    assert account["lifecycle_status"] == "IN_SALE"


# --- Corner / report_sale_before_open_returns_error -------------------------
def test_report_sale_before_open_returns_error(api):
    """PRD 3.7: "The sale date must not precede the account's `opened_at`; a sale
    reported earlier than the account opened is rejected with
    `ERR_SALE_BEFORE_OPEN` (HTTP 422)."

    Design: Corner/state_machines/report_sale_before_open_returns_error
    """
    # opened_at is the completion-time clock (2026-07-02T13:00); sale_date precedes it.
    ctx = fx.setup_servicing_account(api)
    resp = api.report_sale(
        ctx["servicing_account"]["id"],
        {"sale_price_cents": 35_000_000, "sale_date": "2026-07-01T00:00:00Z"}, SERVICER,
    )
    validate_error(resp, ApiErrorId.ERR_SALE_BEFORE_OPEN.value)
