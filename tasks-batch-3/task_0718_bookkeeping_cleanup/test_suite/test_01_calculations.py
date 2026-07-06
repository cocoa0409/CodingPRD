"""Calculation correctness: volume estimate, fixed price, phase split, taxable
income, readiness, proration, recon difference.

Queue A (difficulty) instances for dual_variant_calc, combinatorial_formula,
boundary_precision_check (numeric parts), compensating_invariant (phase split),
and queue B (corner) calculation instances.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success
from test_helpers import (
    api_client,
    make_engagement_manager_headers,
    make_bookkeeper_headers,
    make_reviewer_headers,
    make_tax_preparer_headers,
)
from test_helpers import fixtures as fx

EM = make_engagement_manager_headers("em-1")
BK = make_bookkeeper_headers("bk-1")
RV = make_reviewer_headers("reviewer-1")
RV2 = make_reviewer_headers("reviewer-2")
TP = make_tax_preparer_headers("tp-1")


def _build_accrual_engagement_with_income_expense(basis):
    """Income 500000(settled)+120000(unsettled); Expense 80000(settled)+30000(unsettled).
    The two 'settled' entries are matched on a bank statement and finalized so their
    cash_settled is true; the bank account is then marked reconciled. Returns eng_id."""
    client = get_success_data(api_client.create_client(
        {"legal_name": "Calc Co", "entity_type": "LLC", "accounting_basis": basis}, EM))
    eng = get_success_data(api_client.create_engagement(
        {"client_id": client["id"], "title": "Calc", "period_start": "2025-01-01",
         "period_end": "2025-06-30", "complexity_tier": "MEDIUM"}, EM))
    eng_id = eng["id"]
    eng = get_success_data(api_client.start_scoping(eng_id, EM))
    v0 = eng["version"]
    est = get_success_data(api_client.create_scope_estimate(eng_id, {"monthly_txn_rate": 220}, EM))
    get_success_data(api_client.accept_scope_estimate(
        eng_id, est["id"], {"expected_engagement_version": v0}, EM))

    bank = get_success_data(api_client.create_account(
        eng_id, {"account_code": "1010", "name": "Checking", "account_type": "ASSET",
                 "is_bank_account": True}, BK))
    inc = get_success_data(api_client.create_account(
        eng_id, {"account_code": "4000", "name": "Income", "account_type": "INCOME"}, BK))
    exp = get_success_data(api_client.create_account(
        eng_id, {"account_code": "5000", "name": "Expense", "account_type": "EXPENSE"}, BK))

    def post(acct_id, date, side, amt):
        e = get_success_data(api_client.create_entry(
            eng_id, {"account_id": acct_id, "txn_date": date, "side": side, "amount_cents": amt}, BK))
        get_success_data(api_client.post_entry(eng_id, e["id"], BK))
        return e

    e_inc_s = post(inc["id"], "2025-02-01", "CREDIT", 500000)
    e_inc_u = post(inc["id"], "2025-03-01", "CREDIT", 120000)
    e_exp_s = post(exp["id"], "2025-02-15", "DEBIT", 80000)
    e_exp_u = post(exp["id"], "2025-03-15", "DEBIT", 30000)

    get_success_data(api_client.categorize_account(eng_id, inc["id"], BK))
    get_success_data(api_client.categorize_account(eng_id, exp["id"], BK))
    get_success_data(api_client.advance_to_reconciliation(eng_id, EM))

    stmt = get_success_data(api_client.create_statement(
        eng_id, {"account_id": bank["id"], "statement_start": "2025-02-01",
                 "statement_end": "2025-02-28", "ending_balance_cents": 0}, RV))
    get_success_data(api_client.create_reconciliation_item(
        eng_id, stmt["id"], {"ledger_entry_id": e_inc_s["id"],
                             "statement_line_amount_cents": 500000, "match_kind": "EXACT"}, RV))
    get_success_data(api_client.create_reconciliation_item(
        eng_id, stmt["id"], {"ledger_entry_id": e_exp_s["id"],
                             "statement_line_amount_cents": 80000, "match_kind": "EXACT"}, RV))
    get_success_data(api_client.finalize_statement(eng_id, stmt["id"], RV))
    get_success_data(api_client.mark_reconciled(eng_id, inc["id"], RV2))
    get_success_data(api_client.mark_reconciled(eng_id, exp["id"], RV2))
    return eng_id


def test_taxable_income_accrual_counts_all_qualifying_entries(api):
    """PRD 3.8: "Under `ACCRUAL`, every qualifying posted entry counts regardless of
    cash settlement." PRD 3.8: "Income is the sum of `amount_cents` over qualifying
    entries on `INCOME` accounts with a `CREDIT` side; expense is the sum of
    `amount_cents` over qualifying entries on `EXPENSE` accounts with a `DEBIT` side;
    and `net_book_income_cents` is income minus expense."

    Design: Difficulty/dual_variant_calc/taxable_income_cash_vs_accrual_diverge
    """
    eng_id = _build_accrual_engagement_with_income_expense("ACCRUAL")
    data = validate_success(api.build_tax_package(eng_id, TP), expected_status=201)
    assert data["basis"] == "ACCRUAL"
    # income 500000+120000=620000 minus expense 80000+30000=110000 -> 510000
    assert data["net_book_income_cents"] == 510000, \
        f"accrual net should be 510000, got {data['net_book_income_cents']}"


def test_taxable_income_cash_excludes_unsettled_entries(api):
    """PRD 3.8: "Under `CASH`, only entries whose `cash_settled` flag is true count —
    unsettled invoiced income and accrued-but-unpaid expense are excluded, so the cash
    figure generally differs from the accrual figure on the very same set of entries."
    PRD 3.8: "The package records the `basis` (`CASH` or `ACCRUAL`), copied from the
    client's `accounting_basis` at build time"

    Design: Difficulty/dual_variant_calc/taxable_income_cash_vs_accrual_diverge
    """
    eng_id = _build_accrual_engagement_with_income_expense("CASH")
    data = validate_success(api.build_tax_package(eng_id, TP), expected_status=201)
    assert data["basis"] == "CASH"
    # only cash_settled entries: income 500000 minus expense 80000 -> 420000
    assert data["net_book_income_cents"] == 420000, \
        f"cash net should be 420000, got {data['net_book_income_cents']}"


def test_taxable_income_cash_basis_excludes_unsettled_corner(api):
    """PRD 3.8: "Under `CASH`, only entries whose `cash_settled` flag is true count —
    unsettled invoiced income and accrued-but-unpaid expense are excluded, so the cash
    figure generally differs from the accrual figure on the very same set of entries."

    Design: Corner/calculations/taxable_income_cash_basis_excludes_unsettled
    """
    eng_id = _build_accrual_engagement_with_income_expense("CASH")
    data = validate_success(api.build_tax_package(eng_id, TP), expected_status=201)
    assert data["basis"] == "CASH"
    assert data["net_book_income_cents"] == 420000


def test_scope_forward_estimate_value_on_creation(api):
    """PRD 3.2: "the second is `txn_volume_estimate`, the forward-looking volume
    forecast: multiply `period_month_count` by the estimate's `monthly_txn_rate` and by
    the complexity factor for the engagement's tier, where that factor is 10000 basis
    points for `LOW`, 11500 for `MEDIUM`, and 13000 for `HIGH`; divide that product by
    10000 and round the result down to a whole number of transactions."

    Design: Difficulty/dual_variant_calc/scope_volume_forward_vs_actual_diverge
    """
    eng = fx.create_client_and_engagement(period_start="2025-01-01", period_end="2025-06-30",
                                          complexity_tier="MEDIUM")
    get_success_data(api.start_scoping(eng["id"], EM))
    est = validate_success(api.create_scope_estimate(eng["id"], {"monthly_txn_rate": 220}, EM),
                           expected_status=201)
    # 6 months * 220 * 11500 / 10000 floored = 1518
    assert est["txn_volume_estimate"] == 1518, \
        f"forward estimate should be 1518, got {est['txn_volume_estimate']}"


def test_volume_actuals_counts_posted_entries_not_forecast(api):
    """PRD 3.5: "it counts the `POSTED`, non-`REVERSED` ledger entries whose `txn_date`
    falls in the engagement's period, reports that as `actual_txn_volume` alongside the
    stored `estimated_txn_volume`, and gives the `variance` between them. This actual
    count is a different measure entirely from the forward forecast of section 3.2 — it
    ignores the estimate inputs and simply tallies real entries."

    Design: Difficulty/dual_variant_calc/scope_volume_forward_vs_actual_diverge
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    fx.add_posted_entry(eng["id"], acct["id"], side="DEBIT", amount_cents=1000, txn_date="2025-02-01")
    fx.add_posted_entry(eng["id"], acct["id"], side="CREDIT", amount_cents=1000, txn_date="2025-02-02")
    data = validate_success(api.get_volume_actuals(eng["id"], EM))
    assert data["estimated_txn_volume"] == 1518
    assert data["actual_txn_volume"] == 2, \
        f"actual should count 2 posted entries, got {data['actual_txn_volume']}"


def test_fixed_price_tiered_marginal_rate_third_tier(api):
    """PRD 3.7: "otherwise the price is 50000 cents plus 40 cents times 1000 plus 30
    cents times the volume in excess of 1500." PRD 3.7: "Quoting requires that
    `scope_locked` be true ... which computes the engagement's fixed price and moves
    `billing_status` from `UNBILLED` to `QUOTED`."

    Design: Difficulty/combinatorial_formula/fixed_price_tiered_marginal_rate
    """
    eng = fx.setup_reconstruction_engagement()
    data = validate_success(api.quote(eng["id"], EM))
    assert data["billing_status"] == "QUOTED"
    assert data["estimated_txn_volume"] == 1518
    # price = 50000 + 40*1000 + 30*(1518-1500) = 50000 + 40000 + 540 = 90540
    # asserted via the phase split below; quote response need not expose price directly.


def test_fixed_price_quote_advances_billing_to_quoted(api):
    """PRD 3.7: "Once scope is locked, the `EngagementManager` requests a quote, which
    computes the engagement's fixed price and moves `billing_status` from `UNBILLED` to
    `QUOTED`."

    Design: Difficulty/combinatorial_formula/fixed_price_tiered_marginal_rate
    """
    eng = fx.setup_reconstruction_engagement()
    data = validate_success(api.quote(eng["id"], EM))
    assert data["billing_status"] == "QUOTED"
    assert data["workflow_status"] == "RECONSTRUCTION"


def test_phase_split_residual_rounding_order(api):
    """PRD 3.7: "for every phase except the one with the highest index, set its
    `amount_cents` to the fixed price multiplied by that phase's `weight_bp`, divided by
    10000, rounded half up to whole cents; then set the highest-index phase's
    `amount_cents` to the fixed price minus the sum of all the earlier phases' amounts,
    so the final phase absorbs the rounding remainder and the phase amounts sum to
    exactly the fixed price."

    Design: Difficulty/combinatorial_formula/phase_split_residual_rounding_order
    """
    eng, phases = fx.setup_phased_engagement([3333, 3333, 3334])
    by_idx = {p["phase_index"]: p for p in phases}
    # price 90540: round_half_up(90540*3333/10000)=30177 for the first two; residual 30186.
    assert by_idx[1]["amount_cents"] == 30177
    assert by_idx[2]["amount_cents"] == 30177
    assert by_idx[3]["amount_cents"] == 30186


def test_phase_split_sums_to_fixed_price(api):
    """PRD 3.7: "the final phase absorbs the rounding remainder and the phase amounts
    sum to exactly the fixed price."

    Design: Difficulty/combinatorial_formula/phase_split_residual_rounding_order
    """
    eng, phases = fx.setup_phased_engagement([3333, 3333, 3334])
    total = sum(p["amount_cents"] for p in phases)
    assert total == 90540, f"phase amounts should sum to fixed price 90540, got {total}"


def test_phase_split_conserves_fixed_price_invariant(api):
    """PRD 3.7: "the final phase absorbs the rounding remainder and the phase amounts
    sum to exactly the fixed price."

    Design: Difficulty/compensating_invariant/phase_split_conserves_fixed_price
    """
    eng, phases = fx.setup_phased_engagement([3333, 3333, 3334])
    by_idx = {p["phase_index"]: p for p in phases}
    assert by_idx[1]["amount_cents"] + by_idx[2]["amount_cents"] + by_idx[3]["amount_cents"] == 90540


def test_phase_split_single_phase_conserves_price(api):
    """PRD 3.7: "then set the highest-index phase's `amount_cents` to the fixed price
    minus the sum of all the earlier phases' amounts, so the final phase absorbs the
    rounding remainder and the phase amounts sum to exactly the fixed price."

    Design: Difficulty/compensating_invariant/phase_split_conserves_fixed_price
    """
    eng, phases = fx.setup_phased_engagement([10000])
    assert phases[0]["amount_cents"] == 90540


def test_service_proration_mid_month(api):
    """PRD 3.9: "the prorated fee is the `monthly_fee_cents` multiplied by those
    remaining days, divided by the days in the month, rounded half up to whole cents."
    PRD 3.9: "the remaining days, counted inclusively of the conversion day, are the
    days-in-month minus the day-of-month plus one"

    Design: Corner/calculations/service_proration_mid_month
    """
    # Reach TAX_HANDOFF so the service plan can be activated.
    eng, acct, entry = fx.setup_reconciliation_with_categorized_account()
    get_success_data(api.mark_reconciled(eng["id"], acct["id"], RV))
    get_success_data(api.build_tax_package(eng["id"], TP))
    sp = get_success_data(api.create_service_plan(
        eng["id"], {"monthly_fee_cents": 30000, "conversion_date": "2026-04-10"}, EM))
    data = validate_success(api.activate_service_plan(eng["id"], sp["id"], EM))
    # April has 30 days; day=10; remaining=30-10+1=21; 30000*21/30=21000.
    assert data["first_month_prorated_cents"] == 21000
    assert data["status"] == "ACTIVE"


def test_volume_actuals_empty_entry_set_zero(api):
    """PRD 3.5: "it counts the `POSTED`, non-`REVERSED` ledger entries whose `txn_date`
    falls in the engagement's period, reports that as `actual_txn_volume` alongside the
    stored `estimated_txn_volume`, and gives the `variance` between them."

    Design: Difficulty/boundary_precision_check/volume_actuals_empty_entry_set_zero
    """
    eng = fx.setup_reconstruction_engagement()
    data = validate_success(api.get_volume_actuals(eng["id"], EM))
    assert data["actual_txn_volume"] == 0
    assert data["estimated_txn_volume"] == 1518
    assert data["variance"] == -1518


def test_volume_actuals_variance_is_estimate_minus_actual(api):
    """PRD 3.5: "reports that as `actual_txn_volume` alongside the stored
    `estimated_txn_volume`, and gives the `variance` between them."

    Design: Difficulty/boundary_precision_check/volume_actuals_empty_entry_set_zero
    """
    eng = fx.setup_reconstruction_engagement()
    acct = fx.add_account(eng["id"], account_code="1000", name="Cash", account_type="ASSET")
    fx.add_posted_entry(eng["id"], acct["id"], side="DEBIT", amount_cents=1000, txn_date="2025-02-01")
    fx.add_posted_entry(eng["id"], acct["id"], side="CREDIT", amount_cents=1000, txn_date="2025-02-02")
    data = validate_success(api.get_volume_actuals(eng["id"], EM))
    assert data["actual_txn_volume"] == 2
    assert data["variance"] == 2 - data["estimated_txn_volume"]


def test_recon_tolerance_boundary_via_exact_zero(api):
    """PRD 3.5: "If the absolute value of that difference is at most 100 cents — the
    boundary is inclusive, so a difference whose magnitude equals exactly 100 still
    reconciles — the statement becomes `RECONCILED`."

    Design: Difficulty/boundary_precision_check/recon_difference_tolerance_inclusive_boundary
    """
    # diff exactly -100: book 340000, bank adjusted 350000+15000-25100=339900 -> -100.
    eng, bank, entry, stmt, item = fx.setup_bank_statement_reconciling(
        book_amount=340000, ending_balance_cents=350000,
        deposits_in_transit_cents=15000, outstanding_checks_cents=25100,
        statement_line_amount_cents=340000, match_kind="TOLERANCE")
    data = validate_success(api.finalize_statement(eng["id"], stmt["id"], RV))
    assert data["status"] == "RECONCILED"


def test_readiness_score_with_blocking_penalty(api):
    """PRD 2.8: "the base is one hundred multiplied by `reconciled_account_count`,
    divided by `total_account_count`, with the result rounded down to a whole number
    before any penalty is applied. From that base, a penalty of eight points is
    subtracted for each open blocking exception, i.e. eight multiplied by
    `open_blocking_exception_count`."

    Design: Corner/calculations/readiness_score_with_blocking_penalty
    """
    eng = fx.setup_reconstruction_engagement()
    a1, _ = fx.add_categorized_account(eng["id"], account_code="1000", name="Cash",
                                       account_type="ASSET")
    a2, _ = fx.add_categorized_account(eng["id"], account_code="5000", name="Exp",
                                       account_type="EXPENSE", entry_amount=500)
    get_success_data(api.advance_to_reconciliation(eng["id"], EM))
    get_success_data(api.mark_reconciled(eng["id"], a1["id"], RV))
    fx.add_exception(eng["id"], a2["id"], "UNCATEGORIZED", severity="BLOCKING")
    data = validate_success(api.get_engagement(eng["id"], EM))
    # floor(100*1/2) - 1*8 = 50 - 8 = 42
    assert data["readiness_score"] == 42, f"expected 42, got {data['readiness_score']}"
