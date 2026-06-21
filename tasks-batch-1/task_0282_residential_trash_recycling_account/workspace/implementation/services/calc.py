"""Calculation rules (SCAFFOLD §1.3, PRD §3.8-§3.11).

All monetary values are integer cents. No rounding, no floats anywhere.
"""
from datetime import timedelta

import db
from util import parse_dt

# Constants from SCAFFOLD §1.3
PROVISIONED_CART_COUNT = 2
FREE_BULK_ALLOWANCE = 2
STREAM_CREDIT = {"TRASH": 300, "RECYCLING": 200}
REPEAT_THRESHOLD = 2
REPEAT_BONUS_CENTS = 150
MINOR_FEE_CENTS = 1500
MAJOR_MULTIPLIER = 2


# --------------------------------------------------------------------------
# account_balance (§1.3 account_balance / PRD §3.2)
# --------------------------------------------------------------------------
def credit_balance_cents(account_id):
    """Sum of MissedPickupCredit.amount_cents for ISSUED credits on this account."""
    total = 0
    for c in db.missed_pickup_credits.values():
        if c["account_id"] == account_id and c["status"] == "ISSUED":
            total += c["amount_cents"]
    return total


def account_balance_cents(account_id):
    """Sum of Invoice.amount_due_cents for invoices in {OPEN, PAST_DUE}.

    Credit is NOT subtracted again here — it is consumed at invoice generation.
    """
    total = 0
    for inv in db.invoices.values():
        if inv["account_id"] == account_id and inv["status"] in ("OPEN", "PAST_DUE"):
            total += inv["amount_due_cents"]
    return total


# --------------------------------------------------------------------------
# extra_pickup_charge (§1.3 / PRD §3.10)
# --------------------------------------------------------------------------
def extra_pickup_charge(plan, bulk_item_count):
    base = plan["extra_pickup_base_cents"]
    if bulk_item_count == 0:
        return base
    if bulk_item_count <= FREE_BULK_ALLOWANCE:
        return base
    billable = bulk_item_count - FREE_BULK_ALLOWANCE
    return base + billable * plan["bulk_item_cents"]


# --------------------------------------------------------------------------
# missed_credit (§1.3 / PRD §3.8)
# --------------------------------------------------------------------------
def missed_credit_amount(account_id, stream, clock_now):
    """Per-stream credit with repeat-victim escalation in a rolling 90-day window.

    prior_misses = count of MissedPickupCredit on this account in {ISSUED, APPLIED}
    whose originating PickupEvent.reported_at within (clock - 90d, clock].
    If prior_misses > 2 -> base + 150, else base.
    """
    window_start = clock_now - timedelta(days=90)  # exclusive lower
    prior = 0
    for c in db.missed_pickup_credits.values():
        if c["account_id"] != account_id:
            continue
        if c["status"] not in ("ISSUED", "APPLIED"):
            continue
        ev = db.pickup_events.get(c["pickup_event_id"])
        if not ev:
            continue
        reported = parse_dt(ev["reported_at"])
        if reported is None:
            continue
        if window_start < reported <= clock_now:
            prior += 1
    base = STREAM_CREDIT[stream]
    if prior > REPEAT_THRESHOLD:
        return base + REPEAT_BONUS_CENTS
    return base


# --------------------------------------------------------------------------
# contamination_fee (§1.3 / PRD §3.9)
# --------------------------------------------------------------------------
def contamination_fee(account_id, severity, this_seq):
    """First notice ever on the account is a free warning (0); else MINOR=1500,
    MAJOR=3000. prior count = notices on the account in
    {OPEN, ACKNOWLEDGED, WAIVED} created strictly before this one.
    """
    prior = 0
    for n in db.contamination_notices.values():
        if n["account_id"] != account_id:
            continue
        if n.get("_seq") == this_seq:
            continue
        if n["status"] not in ("OPEN", "ACKNOWLEDGED", "WAIVED"):
            continue
        if n["_seq"] < this_seq:
            prior += 1
    if prior == 0:
        return 0
    if severity == "MINOR":
        return MINOR_FEE_CENTS
    return MINOR_FEE_CENTS * MAJOR_MULTIPLIER


# --------------------------------------------------------------------------
# invoice_gross (§1.3 / PRD §3.11)
# --------------------------------------------------------------------------
def invoice_gross(account, plan, period_start, period_end):
    """Forward-looking period bill. Evaluation order PINNED:
      base + extra_cart + extras + contam.
    Returns gross_amount_cents (credit applied is computed separately).
    """
    account_id = account["id"]

    # 1) base
    base = plan["monthly_base_cents"]

    # 2) extra-cart surcharge
    active_cart_count = sum(
        1 for c in db.cart_assignments.values()
        if c["account_id"] == account_id and c["status"] == "ACTIVE"
    )
    extra_cart_units = max(0, active_cart_count - PROVISIONED_CART_COUNT)
    extra_cart = extra_cart_units * plan["extra_cart_monthly_cents"]

    # 3) extra-pickup charges in [period_start, period_end)
    extras = 0
    for r in db.extra_pickup_requests.values():
        if r["account_id"] != account_id:
            continue
        if r["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        rd = parse_dt(r["requested_date"])
        if rd is None:
            continue
        if period_start <= rd < period_end:
            extras += r["charge_cents"]

    # 4) contamination fees in [period_start, period_end), traced via event->schedule
    contam = 0
    for n in db.contamination_notices.values():
        if n["account_id"] != account_id:
            continue
        if n["status"] not in ("OPEN", "ACKNOWLEDGED"):
            continue
        ev = db.pickup_events.get(n["pickup_event_id"])
        if not ev:
            continue
        sched = db.pickup_schedules.get(ev["schedule_id"])
        if not sched:
            continue
        sd = parse_dt(sched["service_date"])
        if sd is None:
            continue
        if period_start <= sd < period_end:
            contam += n["fee_cents"]

    return base + extra_cart + extras + contam


def apply_credits(account_id, gross, invoice_id):
    """credit_applied_cents = min(gross, credit_balance) (frozen formula, §1.3).

    Consume ISSUED credits oldest-first (created_at ASC; tie -> smaller
    amount_cents first), marking each consumed credit APPLIED with
    applied_invoice_id set, until the consumed total reaches the computed
    target. Each consumed credit's version/updated_at is bumped (touch).
    Returns the frozen credit_applied_cents = target.
    """
    from services.common import touch

    target = min(gross, credit_balance_cents(account_id))
    if target <= 0:
        return 0

    issued = [
        c for c in db.missed_pickup_credits.values()
        if c["account_id"] == account_id and c["status"] == "ISSUED"
    ]
    issued.sort(key=lambda c: (c["created_at"], c["amount_cents"], c["_seq"]))

    consumed = 0
    for c in issued:
        if consumed >= target:
            break
        c["status"] = "APPLIED"
        c["applied_invoice_id"] = invoice_id
        touch(c)
        consumed += c["amount_cents"]
    return target
