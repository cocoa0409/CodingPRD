"""Minimum-due dual paths, reimbursable cap, reimbursement reward accrual, reward
redemption, the OCC stale-version guard, and version increment on mutation.

Corner queue: calculations, cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiClient, ApiErrorId,
    setup_company_with_card, setup_submitted_reimbursement_claim,
    setup_paid_reimbursement_claim, setup_due_statement_with_settled_spend,
    capture_settled_transaction, set_clock, get_reward_account,
    create_company, get_open_statement, create_employee, create_spend_policy,
    create_card, create_cleared_repayment,
)
from test_helpers import factories as F
from test_helpers.test_users import make_finance_admin_headers

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Corner: calculations / minimum_due_credit_floor_applies
# ===========================================================================
def test_minimum_due_credit_floor_applies(api: ApiClient):
    """PRD §3.6: "otherwise the raw minimum is the closing balance multiplied by the
    company's minimum_payment_pct, rounded up to whole cents, and the minimum due is
    the greater of that raw figure and the minimum-payment floor."

    CREDIT, 10% pct, closing balance 20000: raw ceil(2000)=2000 but the $25 floor
    (2500) wins, so minimum_due_cents == 2500.

    Design: Corner/calculations/minimum_due_credit_floor_applies
    """
    base = setup_company_with_card(company_overrides={"billing_model": "CREDIT",
                                                      "minimum_payment_pct": 0.10})
    stmt = base["open_statement"]
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=20000,
                                amount_cents=20000)
    set_clock(base["company"]["id"], "2026-06-30T00:00:00Z")
    closed = validate_success(api.close_statement(stmt["id"], ADMIN))
    assert closed["closing_balance_cents"] == 20000
    assert closed["minimum_due_cents"] == 2500, (
        f"floor wins: minimum_due 2500, got {closed['minimum_due_cents']}")


# ===========================================================================
# Corner: calculations / minimum_due_credit_percentage_above_floor
# ===========================================================================
def test_minimum_due_credit_percentage_above_floor(api: ApiClient):
    """PRD §3.6: "otherwise the raw minimum is the closing balance multiplied by the
    company's minimum_payment_pct, rounded up to whole cents, and the minimum due is
    the greater of that raw figure and the minimum-payment floor."

    CREDIT, 10% pct, closing balance 100000: ceil(10000)=10000 > floor, so
    minimum_due_cents == 10000 (percentage path).

    Design: Corner/calculations/minimum_due_credit_percentage_above_floor
    """
    base = setup_company_with_card(company_overrides={"billing_model": "CREDIT",
                                                      "minimum_payment_pct": 0.10})
    stmt = base["open_statement"]
    capture_settled_transaction(base["card"]["id"], settled_amount_cents=100000,
                                amount_cents=100000)
    set_clock(base["company"]["id"], "2026-06-30T00:00:00Z")
    closed = validate_success(api.close_statement(stmt["id"], ADMIN))
    assert closed["minimum_due_cents"] == 10000, (
        f"percentage path: minimum_due 10000, got {closed['minimum_due_cents']}")


# ===========================================================================
# Corner: calculations / reimbursable_amount_receipt_caps_payout
# ===========================================================================
def test_reimbursable_capped_by_receipt_amount(api: ApiClient):
    """PRD §3.7: "On approval the payout reimbursable_cents is computed as the least of
    the claimed amount_cents, the receipt_amount_cents, and the per-claim reimbursement
    cap of two thousand dollars (200,000 cents)"

    Claim amount 15000, receipt 12000 (< cap): reimbursable_cents == 12000.

    Design: Corner/calculations/reimbursable_amount_receipt_caps_payout
    """
    s = setup_submitted_reimbursement_claim(amount_cents=15000, receipt_amount_cents=12000)
    approved = validate_success(api.approve_reimbursement_claim(
        s["claim"]["id"], s["approver_headers"]))
    assert approved["reimbursable_cents"] == 12000, (
        f"receipt caps payout to 12000, got {approved['reimbursable_cents']}")
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Corner: calculations / reimbursement_pay_accrues_reward
# ===========================================================================
def test_reimbursement_pay_accrues_reward(api: ApiClient):
    """PRD §3.7: "payment cascades a reward into the company's reward account,
    increasing both accrued_points_cents and balance_points_cents by the claim's
    reimbursable_cents multiplied by the company's reward_rate_default_bps, divided by
    ten thousand, rounded half up to whole cents."

    Paying a claim with reimbursable_cents 12000 at 100 bps accrues
    round_half_up(12000*100/10000)=120.

    Design: Corner/calculations/reimbursement_pay_accrues_reward
    """
    s = setup_paid_reimbursement_claim(amount_cents=12000, receipt_amount_cents=12000,
                                       reward_rate_default_bps=100)
    assert s["claim"]["status"] == "PAID"
    ra = validate_success(api.get_reward_account(s["reward_account"]["id"], ADMIN))
    assert ra["accrued_points_cents"] == 120, (
        f"reimbursement reward 120 accrued, got {ra['accrued_points_cents']}")


# ===========================================================================
# Corner: calculations / reward_redeem_decrements_balance
# ===========================================================================
def test_reward_redeem_decrements_balance(api: ApiClient):
    """PRD §3.8: "A FinanceAdmin redeems cashback by supplying an amount_cents to
    redeem (positive); the redemption increases redeemed_points_cents by that amount
    and recomputes balance_points_cents"
    PRD §3.8: "balance_points_cents is accrued_points_cents minus redeemed_points_cents."

    After 120 accrued, redeeming 50 sets redeemed_points_cents=50 and
    balance_points_cents=70.

    Design: Corner/calculations/reward_redeem_decrements_balance
    """
    s = setup_paid_reimbursement_claim(amount_cents=12000, receipt_amount_cents=12000,
                                       reward_rate_default_bps=100)
    redeemed = validate_success(api.redeem_reward(
        s["reward_account"]["id"], F.redeem_payload(50), ADMIN))
    assert redeemed["redeemed_points_cents"] == 50, (
        f"redeemed 50, got {redeemed['redeemed_points_cents']}")
    assert redeemed["balance_points_cents"] == 70, (
        f"balance 120-50=70, got {redeemed['balance_points_cents']}")


# ===========================================================================
# Corner: calculations / reward_redeem_over_balance_rejected
# ===========================================================================
def test_reward_redeem_over_balance_rejected(api: ApiClient):
    """PRD §3.8: "A redemption greater than the current balance_points_cents is rejected
    with ERR_INSUFFICIENT_REWARD_BALANCE."

    Redeeming 200 from a fresh RewardAccount (balance 0) is rejected.

    Design: Corner/calculations/reward_redeem_over_balance_rejected
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=1_000_000)
    ra = get_reward_account(company["id"])
    resp = api.redeem_reward(ra["id"], F.redeem_payload(200), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REWARD_BALANCE.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_repayment_create_stale_statement_version_rejected
# ===========================================================================
def test_repayment_create_with_stale_statement_version_rejected(api: ApiClient):
    """PRD §2.8: "A request to create a repayment must include
    expected_statement_version, carrying the version of the target statement that the
    client last observed. If that value does not equal the statement's current version
    ... the create is rejected with ERR_STALE_VERSION and HTTP status 412."

    After a first repayment clears (advancing the statement version), a second create
    still carrying the pre-advance version is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_repayment_create_stale_statement_version_rejected
    """
    s = setup_due_statement_with_settled_spend(settled_amount_cents=40000,
                                               billing_model="CHARGE")
    v0 = s["statement_version"]
    # First repayment with the correct version, then clear it (advances version).
    create_cleared_repayment(s["statement"]["id"], 10000, v0)
    # Second create still carrying the stale v0.
    resp = api.create_repayment(
        F.create_repayment_payload(s["statement"]["id"], 10000, v0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / version_increments_on_card_mutation
# ===========================================================================
def test_version_increments_on_card_freeze(api: ApiClient):
    """PRD §2.4: "version is an integer that begins at its initial value on creation and
    increments by exactly one on every mutation of the resource"
    PRD §3.2: "Freezing an ACTIVE card moves it ACTIVE -> FROZEN ... Each of these
    transitions increments the card's version."

    A freeze increments the card's version by exactly one (1 -> 2) and sets status FROZEN.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_card_mutation
    """
    base = setup_company_with_card()
    card = base["card"]
    assert card["version"] == 1, f"new card version 1, got {card['version']}"
    frozen = validate_success(api.freeze_card(card["id"], ADMIN))
    assert frozen["version"] == 2, f"version increments to 2, got {frozen['version']}"
    assert frozen["status"] == "FROZEN", f"status FROZEN, got {frozen['status']}"
