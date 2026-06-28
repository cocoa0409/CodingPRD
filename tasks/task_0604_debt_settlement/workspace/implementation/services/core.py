"""Core domain logic: computed fields, account standing, expiry, calculations, cascades."""
from decimal import Decimal
from datetime import timezone

from db import store, round_half_up, money, num
from clock import clock, parse_iso8601

# Constants
LITIGATION_SURCHARGE = Decimal("0.03")
SURCHARGE_CAP = Decimal("0.25")
TIER_1_CEIL = Decimal("10000")
TIER_2_CEIL = Decimal("30000")
REPORTABLE_FLOOR = Decimal("600")
MIN_OFFER_GAP_DAYS = 30
DEFAULT_TARGET_PCT = Decimal("0.50")

OPEN_FEE_TIER_STATUSES = {"ENROLLED", "IN_NEGOTIATION", "SETTLED", "LAWSUIT"}


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def program_debts(program_id):
    return [d for d in store.debts.values() if d["program_id"] == program_id]


def program_deposits(program_id):
    return [d for d in store.deposits.values() if d["program_id"] == program_id]


def program_settlements(program_id):
    return [s for s in store.settlements.values() if s["program_id"] == program_id]


def program_fees(program_id):
    return [f for f in store.fees.values() if f["program_id"] == program_id]


def program_offers(program_id):
    return [o for o in store.offers.values() if o["program_id"] == program_id]


def account_for_program(program_id):
    for a in store.accounts.values():
        if a["program_id"] == program_id:
            return a
    return None


def debt_offers(debt_id):
    return [o for o in store.offers.values() if o["debt_id"] == debt_id]


def debt_lawsuits(debt_id):
    return [lw for lw in store.lawsuits.values() if lw["debt_id"] == debt_id]


# ---------------------------------------------------------------------------
# Effective fee rate
# ---------------------------------------------------------------------------
def effective_rate(base_rate, debt_status):
    base = base_rate if isinstance(base_rate, Decimal) else Decimal(str(base_rate))
    if debt_status == "LAWSUIT":
        return min(base + LITIGATION_SURCHARGE, SURCHARGE_CAP)
    return base


# ---------------------------------------------------------------------------
# Fee tier snapshot (§1.3 fee_tier_snapshot)
# ---------------------------------------------------------------------------
def fee_tier_for_total(total):
    t = total if isinstance(total, Decimal) else Decimal(str(total))
    if t < TIER_1_CEIL:
        return Decimal("0.25")
    elif t < TIER_2_CEIL:
        return Decimal("0.22")
    else:
        return Decimal("0.18")


def total_enrolled_balance(program_id, extra=Decimal("0")):
    total = Decimal("0")
    for d in program_debts(program_id):
        if d["status"] in OPEN_FEE_TIER_STATUSES:
            total += Decimal(str(d["original_balance"]))
    return total + extra


# ---------------------------------------------------------------------------
# Account standing ladder (§2.9)
# ---------------------------------------------------------------------------
def missed_deposit_count(program_id):
    return sum(1 for d in program_deposits(program_id) if d["status"] == "MISSED")


def recompute_account_standing(program):
    count = missed_deposit_count(program["id"])
    if count >= 3:
        standing = "DEFAULTED"
    elif count >= 1:
        standing = "DELINQUENT"
    else:
        standing = "CURRENT"
    program["account_standing"] = standing
    return standing


# ---------------------------------------------------------------------------
# Account balance ledger (§2.8)
# ---------------------------------------------------------------------------
def account_balance(program_id):
    deposits_sum = sum(
        (Decimal(str(d["amount"])) for d in program_deposits(program_id) if d["status"] == "CLEARED"),
        Decimal("0"),
    )
    settle_sum = sum(
        (Decimal(str(s["funded_amount"])) for s in program_settlements(program_id) if s["status"] in ("FUNDED", "COMPLETED")),
        Decimal("0"),
    )
    fee_sum = sum(
        (Decimal(str(f["amount"])) for f in program_fees(program_id) if f["status"] == "PAID"),
        Decimal("0"),
    )
    acct = account_for_program(program_id)
    refunded = acct.get("_refunded", Decimal("0")) if acct else Decimal("0")
    return deposits_sum - settle_sum - fee_sum - refunded


def lifetime_deposited(program_id):
    return sum(
        (Decimal(str(d["amount"])) for d in program_deposits(program_id) if d["status"] == "CLEARED"),
        Decimal("0"),
    )


def lifetime_disbursed(program_id):
    settle_sum = sum(
        (Decimal(str(s["funded_amount"])) for s in program_settlements(program_id) if s["status"] in ("FUNDED", "COMPLETED")),
        Decimal("0"),
    )
    fee_sum = sum(
        (Decimal(str(f["amount"])) for f in program_fees(program_id) if f["status"] == "PAID"),
        Decimal("0"),
    )
    return settle_sum + fee_sum


# ---------------------------------------------------------------------------
# Offer expiry (lazy) — §3.5
# ---------------------------------------------------------------------------
def expire_offer_if_due(offer):
    if offer["status"] != "PENDING":
        return
    due = parse_iso8601(offer["due_date"])
    if due is not None and clock.get() > due:
        offer["status"] = "EXPIRED"
        from db import touch
        touch(offer)


def expire_program_offers(program_id):
    for o in program_offers(program_id):
        expire_offer_if_due(o)


# ---------------------------------------------------------------------------
# Portfolio savings (§3.12)
# ---------------------------------------------------------------------------
def estimated_total_savings(program):
    target = Decimal(str(program["target_settlement_pct"]))
    total = Decimal("0")
    for d in program_debts(program["id"]):
        if d["status"] not in ("ENROLLED", "IN_NEGOTIATION", "LAWSUIT"):
            continue
        orig = Decimal(str(d["original_balance"]))
        est_settlement = round_half_up(orig * target, 2)
        est_rate = effective_rate(Decimal(str(d["fee_rate_pct"])), d["status"])
        est_fee = round_half_up(est_settlement * est_rate, 2)
        total += (orig - est_settlement - est_fee)
    return total


def fee_amount_for_settlement(settlement_id):
    """Fee accrued on a settlement: PAID/OUTSTANDING amount; WAIVED contributes 0."""
    for f in store.fees.values():
        if f["settlement_id"] == settlement_id:
            if f["status"] == "WAIVED":
                return Decimal("0")
            return Decimal(str(f["amount"]))
    return Decimal("0")


def realized_total_savings(program):
    total = Decimal("0")
    for d in program_debts(program["id"]):
        if d["status"] != "SETTLED":
            continue
        orig = Decimal(str(d["original_balance"]))
        settled = Decimal(str(d["settled_amount"]))
        fee = Decimal("0")
        # find the settlement that settled this debt
        settle_id = None
        for s in store.settlements.values():
            if s["debt_id"] == d["id"] and s["status"] == "COMPLETED":
                settle_id = s["id"]
                break
        if settle_id is not None:
            fee = fee_amount_for_settlement(settle_id)
        total += (orig - settled - fee)
    return total


def completion_eligible(program):
    debts = program_debts(program["id"])
    for d in debts:
        if d["status"] not in ("SETTLED", "WITHDRAWN"):
            return False
    for f in program_fees(program["id"]):
        if f["status"] == "OUTSTANDING":
            return False
    return True
