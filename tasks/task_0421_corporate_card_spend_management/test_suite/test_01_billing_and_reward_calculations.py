"""Dual-variant billing, combinatorial reward accrual, and boundary precision.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
from test_helpers import (
    validate_success, get_success_data, api_client, ApiClient,
    capture_settled_transaction, capture_transaction, set_clock, get_reward_account,
    setup_company_with_card, create_company, create_employee, create_spend_policy,
    create_card,
)
from test_helpers import factories as F
from test_helpers.test_users import make_finance_admin_headers, make_cardholder_headers

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Difficulty: dual_variant_calc / dvc_statement_balance_accrual_vs_cash
# ===========================================================================
def test_statement_balance_accrual_sweeps_cleared_spend(api: ApiClient):
    """PRD §3.6: "Under the accrual variant, which applies when the company's
    billing_model is CHARGE, the closing balance is the sum of settled_amount_cents
    over every SETTLED transaction assigned to this statement, plus the sum of
    amount_cents over every transaction of the company that is CLEARED but not yet
    SETTLED at the moment of close"

    A SETTLED tx of 5000 plus a CLEARED-not-SETTLED tx of 3000 closes at 8000
    under CHARGE/accrual.

    Design: Difficulty/dual_variant_calc/dvc_statement_balance_accrual_vs_cash
    """
    base = setup_company_with_card(company_overrides={"billing_model": "CHARGE",
                                                      "credit_limit_cents": 1_000_000})
    stmt = base["open_statement"]
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=5000,
                                amount_cents=5000, merchant_name="M-A")
    # tx B: cleared but NOT settled.
    txb = capture_transaction(base["card"]["id"], amount_cents=3000, merchant_name="M-B")
    get_success_data(api.clear_transaction(txb["id"], ADMIN))
    set_clock(base["company"]["id"], "2026-06-30T00:00:00Z")

    closed = validate_success(api.close_statement(stmt["id"], ADMIN))
    assert closed["closing_balance_cents"] == 8000, (
        f"accrual sweeps cleared spend: expected 8000, got {closed['closing_balance_cents']}")
    assert closed["status"] == "CLOSED"


def test_statement_balance_cash_excludes_cleared_unsettled_spend(api: ApiClient):
    """PRD §3.6: "Under the cash variant, which applies when the billing_model is
    CREDIT, only SETTLED transactions assigned to this statement are included — the
    closing balance is the sum of their settled_amount_cents, and cleared-but-unsettled
    spend does not post this cycle."

    The same tx set (SETTLED 5000 + CLEARED-not-SETTLED 3000) closes at 5000 under
    CREDIT/cash.

    Design: Difficulty/dual_variant_calc/dvc_statement_balance_accrual_vs_cash
    """
    base = setup_company_with_card(company_overrides={"billing_model": "CREDIT",
                                                      "credit_limit_cents": 1_000_000})
    stmt = base["open_statement"]
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=5000,
                                amount_cents=5000, merchant_name="M-A")
    txb = capture_transaction(base["card"]["id"], amount_cents=3000, merchant_name="M-B")
    get_success_data(api.clear_transaction(txb["id"], ADMIN))
    set_clock(base["company"]["id"], "2026-06-30T00:00:00Z")

    closed = validate_success(api.close_statement(stmt["id"], ADMIN))
    assert closed["closing_balance_cents"] == 5000, (
        f"cash excludes cleared-unsettled: expected 5000, got {closed['closing_balance_cents']}")
    assert closed["status"] == "CLOSED"


# ===========================================================================
# Difficulty: dual_variant_calc / dvc_reward_accrual_net_vs_gross
# ===========================================================================
def test_reward_accrues_on_settled_amount_not_authorized(api: ApiClient):
    """PRD §3.4: "The reward (cashback) figure for a transaction is computed at
    settle and accrues on the net basis — that is, on settled_amount_cents, the
    amount that actually cleared, not on the authorized amount_cents, so a partial
    capture earns less than a full one would."

    Authorized 10000 but settled 6000 at 100 bps earns 60 (not the 100 the gross
    basis would give).

    Design: Difficulty/dual_variant_calc/dvc_reward_accrual_net_vs_gross
    """
    base = setup_company_with_card(company_overrides={"reward_rate_default_bps": 100})
    tx = capture_transaction(base["card"]["id"], amount_cents=10000)
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    settled = validate_success(api.settle_transaction(
        tx["id"], F.settle_payload(6000), ADMIN))
    assert settled["reward_points_cents"] == 60, (
        f"net basis on 6000 at 100bps = 60, got {settled['reward_points_cents']}")


def test_reward_account_accrues_settled_reward(api: ApiClient):
    """PRD §3.3: "the transaction's reward_points_cents is computed by the reward
    rule (§3.4) and that same amount is added to the reward account's
    accrued_points_cents and balance_points_cents"

    The 60-cent net reward flows into the RewardAccount's accrued and balance.

    Design: Difficulty/dual_variant_calc/dvc_reward_accrual_net_vs_gross
    """
    base = setup_company_with_card(company_overrides={"reward_rate_default_bps": 100})
    tx = capture_transaction(base["card"]["id"], amount_cents=10000)
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    get_success_data(api.settle_transaction(tx["id"], F.settle_payload(6000), ADMIN))
    ra = get_reward_account(base["company"]["id"])
    assert ra["accrued_points_cents"] == 60, f"accrued expected 60, got {ra['accrued_points_cents']}"
    assert ra["balance_points_cents"] == 60, f"balance expected 60, got {ra['balance_points_cents']}"


# ===========================================================================
# Difficulty: combinatorial_formula / cf_reward_accrual_tiered_rate_with_nested_cap
# ===========================================================================
def _setup_tiered_company():
    """CHARGE company default 100 bps; policy overrides MCC 5812 -> 500 bps; one card."""
    company = create_company(billing_model="CHARGE", credit_limit_cents=2_000_000,
                             reward_rate_default_bps=100)
    emp = create_employee(company["id"], "tier@acme.com", "H", "CARDHOLDER")
    pol = create_spend_policy(company["id"], name="Tier", per_transaction_limit_cents=500000,
                              approval_threshold_cents=1000000,
                              mcc_reward_overrides=[{"mcc_code": "5812", "reward_rate_bps": 500}])
    card = create_card(company["id"], emp["id"], pol["id"], card_limit_cents=500000)
    return company, card


def test_reward_mcc_override_rate_hits_per_txn_cap(api: ApiClient):
    """PRD §3.4: "if the transaction's mcc_code appears as an mcc_code key among the
    card's spend policy's mcc_reward_overrides, that override's reward_rate_bps is
    used"
    PRD §3.4: "The stored reward_points_cents is then the lesser of that rounded raw
    reward and the per-transaction cashback cap of fifty dollars (5,000 cents) — the
    cap is applied after rounding."

    MCC 5812 at 500 bps on a 100000 settle = raw 5000 = exactly the cap.

    Design: Difficulty/combinatorial_formula/cf_reward_accrual_tiered_rate_with_nested_cap
    """
    company, card = _setup_tiered_company()
    tx = capture_transaction(card["id"], amount_cents=100000, mcc_code="5812",
                             merchant_name="Dining")
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    settled = validate_success(api.settle_transaction(
        tx["id"], F.settle_payload(100000), ADMIN))
    assert settled["reward_points_cents"] == 5000, (
        f"500bps on 100000 capped at 5000, got {settled['reward_points_cents']}")


def test_reward_default_rate_when_no_mcc_override(api: ApiClient):
    """PRD §3.4: "otherwise the company's reward_rate_default_bps applies. The raw
    reward is the settled amount multiplied by the selected rate in basis points,
    divided by ten thousand, rounded half up to whole cents."

    MCC 5999 (no override) at the company default 100 bps on a 100000 settle = 1000
    (uncapped).

    Design: Difficulty/combinatorial_formula/cf_reward_accrual_tiered_rate_with_nested_cap
    """
    company, card = _setup_tiered_company()
    tx = capture_transaction(card["id"], amount_cents=100000, mcc_code="5999",
                             merchant_name="Misc")
    get_success_data(api.clear_transaction(tx["id"], ADMIN))
    settled = validate_success(api.settle_transaction(
        tx["id"], F.settle_payload(100000), ADMIN))
    assert settled["reward_points_cents"] == 1000, (
        f"100bps on 100000 = 1000, got {settled['reward_points_cents']}")


# ===========================================================================
# Difficulty: combinatorial_formula / cf_statement_cashback_round_per_line_then_sum
# ===========================================================================
def test_statement_cashback_rounds_per_line_then_sums(api: ApiClient):
    """PRD §3.4: "The order is fixed and matters: each transaction's reward was
    already rounded half up at settle, and the summary sums those already-rounded
    per-transaction values — it does not re-sum raw products and round once at the
    end."

    Three settles of 150 at 100 bps each round to 2 (round_half_up(1.5)=2), summing
    to 6 — not the 5 a sum-then-round would give.

    Design: Difficulty/combinatorial_formula/cf_statement_cashback_round_per_line_then_sum
    """
    base = setup_company_with_card(company_overrides={"reward_rate_default_bps": 100})
    stmt = base["open_statement"]
    for label in ("T1", "T2", "T3"):
        capture_settled_transaction(base["card"]["id"], settled_amount_cents=150,
                                    amount_cents=150, merchant_name=label)
    summary = validate_success(api.cashback_summary(stmt["id"], ADMIN))
    assert summary["statement_cashback_cents"] == 6, (
        f"round-per-line-then-sum = 6, got {summary['statement_cashback_cents']}")


def test_statement_cashback_counts_settled_transactions(api: ApiClient):
    """PRD §3.4: "A statement's cashback summary is a computed read returning the
    statement's statement_id, a statement_cashback_cents total, and a
    settled_transaction_count."
    PRD §3.4: "The total is the sum of reward_points_cents over the transactions
    whose statement_id is this statement and whose auth_status is SETTLED."

    Three SETTLED transactions assigned to the statement yield a count of 3.

    Design: Difficulty/combinatorial_formula/cf_statement_cashback_round_per_line_then_sum
    """
    base = setup_company_with_card(company_overrides={"reward_rate_default_bps": 100})
    stmt = base["open_statement"]
    for label in ("T1", "T2", "T3"):
        capture_settled_transaction(base["card"]["id"], settled_amount_cents=150,
                                    amount_cents=150, merchant_name=label)
    summary = validate_success(api.cashback_summary(stmt["id"], ADMIN))
    assert summary["settled_transaction_count"] == 3, (
        f"expected 3 settled txns, got {summary['settled_transaction_count']}")


# ===========================================================================
# Difficulty: boundary_precision_check / bpc_receipt_required_threshold_exact
# ===========================================================================
def test_receipt_threshold_at_boundary_stays_unreviewed(api: ApiClient):
    """PRD §3.3: "if amount_cents is greater than the receipt-required threshold of
    seventy-five dollars (7,500 cents), the transaction starts review_status
    NEEDS_RECEIPT; otherwise it starts UNREVIEWED."

    Exactly 7500 is not greater than the threshold, so review_status is UNREVIEWED.

    Design: Difficulty/boundary_precision_check/bpc_receipt_required_threshold_exact
    """
    base = setup_company_with_card()
    tx = validate_success(api.capture_transaction(
        base["card"]["id"], F.capture_transaction_payload(amount_cents=7500, merchant_name="Exact"),
        ADMIN), expected_status=201)
    assert tx["review_status"] == "UNREVIEWED", (
        f"7500 (== threshold) stays UNREVIEWED, got {tx['review_status']}")


def test_receipt_threshold_above_boundary_needs_receipt(api: ApiClient):
    """PRD §3.3: "if amount_cents is greater than the receipt-required threshold of
    seventy-five dollars (7,500 cents), the transaction starts review_status
    NEEDS_RECEIPT; otherwise it starts UNREVIEWED."

    7501 is greater than the threshold, so review_status is NEEDS_RECEIPT.

    Design: Difficulty/boundary_precision_check/bpc_receipt_required_threshold_exact
    """
    base = setup_company_with_card()
    tx = validate_success(api.capture_transaction(
        base["card"]["id"], F.capture_transaction_payload(amount_cents=7501, merchant_name="Over"),
        ADMIN), expected_status=201)
    assert tx["review_status"] == "NEEDS_RECEIPT", (
        f"7501 (> threshold) becomes NEEDS_RECEIPT, got {tx['review_status']}")


# ===========================================================================
# Difficulty: boundary_precision_check / bpc_receipt_match_tolerance_exact
# ===========================================================================
def test_receipt_match_at_tolerance_boundary_matches(api: ApiClient):
    """PRD §3.4: "The result is MATCH when the absolute difference between the
    receipt's amount_cents and the transaction's amount_cents is at most the match
    tolerance of one dollar (100 cents), and MISMATCH otherwise."

    A receipt off by exactly 100 from a 10000 tx MATCHes, advancing review to MATCHED.

    Design: Difficulty/boundary_precision_check/bpc_receipt_match_tolerance_exact
    """
    base = setup_company_with_card()
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=10000)
    rcpt = validate_success(api.upload_receipt(
        tx["id"], F.receipt_payload(10100, "Merchant"), ch), expected_status=201)
    assert rcpt["match_result"] == "MATCH", (
        f"off-by-exactly-100 is MATCH, got {rcpt['match_result']}")
    after = validate_success(api.get_transaction(tx["id"], ADMIN))
    assert after["review_status"] == "MATCHED", (
        f"MATCH advances review to MATCHED, got {after['review_status']}")


def test_receipt_match_above_tolerance_mismatches(api: ApiClient):
    """PRD §3.4: "On a MISMATCH, the receipt is still recorded with match_result
    MISMATCH, but the transaction's review_status is left unchanged."
    PRD §3.4: "The result is MATCH when the absolute difference between the receipt's
    amount_cents and the transaction's amount_cents is at most the match tolerance of
    one dollar (100 cents), and MISMATCH otherwise."

    A receipt off by 101 from a 10000 tx MISMATCHes; review stays NEEDS_RECEIPT.

    Design: Difficulty/boundary_precision_check/bpc_receipt_match_tolerance_exact
    """
    base = setup_company_with_card()
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=10000)
    rcpt = validate_success(api.upload_receipt(
        tx["id"], F.receipt_payload(10101, "Merchant"), ch), expected_status=201)
    assert rcpt["match_result"] == "MISMATCH", (
        f"off-by-101 is MISMATCH, got {rcpt['match_result']}")
    after = validate_success(api.get_transaction(tx["id"], ADMIN))
    assert after["review_status"] == "NEEDS_RECEIPT", (
        f"MISMATCH leaves review unchanged, got {after['review_status']}")
