"""Calculation rules (SCAFFOLD §1.3, PRD §2.5/§3.4/§3.6)."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import (
    MIN_PAYMENT_FLOOR_CENTS,
    MAX_REWARD_PER_TXN_CENTS,
    REIMBURSEMENT_CAP_CENTS,
)


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reward_for_amount(base_amount_cents, rate_bps):
    """raw = round_half_up(base * rate_bps / 10000), then cap (PRD §3.4)."""
    raw = round_half_up(Decimal(base_amount_cents) * Decimal(rate_bps) / Decimal(10000))
    return min(raw, MAX_REWARD_PER_TXN_CENTS)


def select_reward_rate(policy, mcc_code, company):
    """MCC override on the card's SpendPolicy wins; else company default."""
    if policy is not None:
        for ovr in policy.get("mcc_reward_overrides", []) or []:
            if str(ovr.get("mcc_code")) == str(mcc_code):
                return ovr.get("reward_rate_bps")
    return company["reward_rate_default_bps"]


def compute_transaction_reward(tx, policy, company):
    """reward_points_cents on settle: net basis on settled_amount_cents."""
    base = tx["settled_amount_cents"]
    rate_bps = select_reward_rate(policy, tx["mcc_code"], company)
    return reward_for_amount(base, rate_bps)


def compute_statement_balance(stmt, company):
    """Dual-variant closing balance (PRD §3.6 / SCAFFOLD statement_balance).

    Returns (closing_balance_cents, swept_cleared_tx_ids).
    For accrual variant, the swept CLEARED-not-SETTLED transactions are returned
    so the caller can assign their statement_id to this statement.
    """
    cid = company["id"]
    billing = company["billing_model"]
    total = 0
    swept = []

    # SETTLED transactions assigned to this statement (both variants).
    for tx in db.transactions.values():
        if (tx["company_id"] == cid
                and tx.get("statement_id") == stmt["id"]
                and tx["auth_status"] == "SETTLED"):
            total += tx["settled_amount_cents"]

    if billing == "CHARGE":
        # accrual: also sweep company's CLEARED-not-SETTLED tx at authorized amount.
        for tx in db.transactions.values():
            if tx["company_id"] == cid and tx["auth_status"] == "CLEARED":
                total += tx["amount_cents"]
                swept.append(tx["id"])

    return total, swept


def compute_minimum_due(closing_balance_cents, company):
    """minimum_due (PRD §3.6 / SCAFFOLD minimum_due)."""
    if company["billing_model"] == "CHARGE":
        return closing_balance_cents
    # CREDIT
    if closing_balance_cents == 0:
        return 0
    if closing_balance_cents <= MIN_PAYMENT_FLOOR_CENTS:
        return closing_balance_cents
    # raw = ceil(closing_balance * minimum_payment_pct) (round UP to whole cents)
    pct = Decimal(str(company["minimum_payment_pct"]))
    raw = int(math.ceil(Decimal(closing_balance_cents) * pct))
    return max(raw, MIN_PAYMENT_FLOOR_CENTS)


def compute_reimbursable(claim):
    """min(amount_cents, receipt_amount_cents, REIMBURSEMENT_CAP_CENTS)."""
    return min(
        claim["amount_cents"],
        claim["receipt_amount_cents"],
        REIMBURSEMENT_CAP_CENTS,
    )


def statement_cashback_total(stmt):
    """Sum already-rounded per-transaction reward over SETTLED tx in this statement."""
    total = 0
    count = 0
    for tx in db.transactions.values():
        if tx.get("statement_id") == stmt["id"] and tx["auth_status"] == "SETTLED":
            total += tx["reward_points_cents"]
            count += 1
    return total, count
