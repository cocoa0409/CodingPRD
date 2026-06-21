"""Calculation rules (PRD §3.4–§3.7). Integer cents only; explicit rounding."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import db

# winback_credit constants (PRD §3.7)
BASE_GRANT_PCT = Decimal("0.20")
TENURE_WEIGHT = Decimal("0.05")
TENURE_CAP = 6
MAX_GRANT_CENTS = 5000


def prepaid_total_paid(period_price_cents, term_periods, prepaid_discount_pct):
    """Prepaid charge with pinned order of operations (PRD §3.4).

    gross = period_price_cents * term_periods            (exact integer)
    discount = floor(gross * prepaid_discount_pct)       (floored once on whole gross)
    total = gross - discount
    """
    gross = period_price_cents * term_periods
    pct = Decimal(str(prepaid_discount_pct))
    discount = int((Decimal(gross) * pct).to_integral_value(rounding=ROUND_FLOOR))
    return gross - discount


def amortized_unit_value(prepaid_total_paid_cents, term_length):
    """Amortized per-period value = floor(total / term_length) (PRD §3.4/§3.6)."""
    if term_length <= 0:
        return 0
    return prepaid_total_paid_cents // term_length


def cancellation_refund(subscription):
    """Two-variant cancellation refund (PRD §3.5). Returns refund in integer cents.

    PERIOD variant (billing_status==CURRENT): sum of amount_charged_cents over
    every unshipped CURRENT-funded PAID billing cycle. A period is "shipped" iff
    it has a COMMITTED allocation; unshipped otherwise.

    AMORTIZED variant (billing_status==PREPAID):
    prepaid_periods_remaining * prepaid_unit_value_cents.
    """
    if subscription["billing_status"] == "PREPAID":
        return (subscription["prepaid_periods_remaining"]
                * subscription["prepaid_unit_value_cents"])

    # period_proration variant
    sub_id = subscription["id"]
    cycles = [c for c in db.billing_cycles.values()
              if c["subscription_id"] == sub_id and c["status"] == "PAID"]
    refund = 0
    for c in cycles:
        if c["funding_source"] != "CHARGE":
            continue
        if _cycle_shipped(c):
            continue
        refund += c["amount_charged_cents"]
    return refund


def _cycle_shipped(cycle):
    """A paid period is shipped iff a COMMITTED allocation exists for its box period."""
    sub_id = cycle["subscription_id"]
    period = cycle["period_index"]
    boxes = [b for b in db.box_selections.values()
             if b["subscription_id"] == sub_id and b["period_index"] == period]
    for b in boxes:
        alloc_id = b.get("allocation_id")
        if alloc_id:
            alloc = db.allocations.get(alloc_id)
            if alloc and alloc["status"] == "COMMITTED":
                return True
    return False


def winback_credit(subscriber_id, plan):
    """Win-back loyalty grant (PRD §3.7). round_half_up, cap applied AFTER rounding.

    committed = count of Shipment in {PACKED,DISPATCHED,DELIVERED} across all
    subscriptions owned by this subscriber.
    """
    sub_ids = {s["id"] for s in db.subscriptions.values()
               if s["subscriber_id"] == subscriber_id}
    committed = 0
    for sh in db.shipments.values():
        if sh["subscription_id"] in sub_ids and sh["status"] in (
                "PACKED", "DISPATCHED", "DELIVERED"):
            committed += 1

    base = plan["period_price_cents"]
    tenure_factor = Decimal(min(committed, TENURE_CAP)) * TENURE_WEIGHT
    raw = Decimal(base) * (BASE_GRANT_PCT + tenure_factor)
    grant = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    grant = min(grant, MAX_GRANT_CENTS)
    return grant


def recompute_wallet_balance(subscriber_id):
    """wallet_balance_cents = sum of all WalletEntry.amount_cents (PRD §3.2)."""
    total = sum(e["amount_cents"] for e in db.wallet_entries.values()
                if e["subscriber_id"] == subscriber_id)
    sub = db.subscribers.get(subscriber_id)
    if sub is not None:
        from common import touch
        sub["wallet_balance_cents"] = total
        touch(sub)
    return total
