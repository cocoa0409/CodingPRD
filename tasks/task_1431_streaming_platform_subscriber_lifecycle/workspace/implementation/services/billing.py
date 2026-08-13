"""Billing event ledger + outstanding balance + payment method simulation."""
from datetime import timedelta
from decimal import Decimal

import db
from util import new_uuid, now_iso, format_ts, round_half_up_cents, whole_days

EVENT_TYPES = {
    "TRIAL_START", "CHARGE", "CHARGE_FAILED", "REFUND",
    "PRORATION_CREDIT", "PRICE_CHANGE_APPLIED", "RECOVERY",
}

DAYS_PER_PERIOD_NOMINAL = 30
DUNNING_RETRY_OFFSETS_HOURS = [24, 72, 120, 168, 240]
MAX_DUNNING_ATTEMPTS = 5
AUTO_RECONCILE_TOLERANCE_CENTS = 500


def post_event(account_id, subscription_id, event_type, amount_cents,
               external_reference=None, notes=None):
    ev = {
        "billing_event_id": new_uuid(),
        "account_id": account_id,
        "subscription_id": subscription_id,
        "event_type": event_type,
        "amount_cents": int(amount_cents),
        "occurred_at_utc": now_iso(),
        "external_reference": external_reference,
        "notes": notes,
        "created_at": now_iso(),
    }
    db.billing_events[ev["billing_event_id"]] = ev
    return ev


def recompute_outstanding_balance(account):
    """Sum of unsettled CHARGE_FAILED minus recovered amounts (PRD §2.7).
    A CHARGE_FAILED is settled when a RECOVERY event for the same subscription
    occurs after it."""
    events = [e for e in db.billing_events.values() if e["account_id"] == account["account_id"]]
    events.sort(key=lambda e: e["occurred_at_utc"])
    balance = 0
    for e in events:
        if e["event_type"] == "CHARGE_FAILED":
            balance += abs(e["amount_cents"])
        elif e["event_type"] == "RECOVERY":
            # recoveries settle outstanding CHARGE_FAILED amounts
            balance = max(0, balance - abs(e["amount_cents"]) if e["amount_cents"] != 0 else balance)
            # A RECOVERY event's amount covers the failed charges on the same subscription;
            # simplest model: zero out the balance accumulated on that subscription
            # when a recovery posts.
    return balance


def recompute_outstanding_balance_v2(account):
    """Alternative model: balance = sum(CHARGE_FAILED amounts) - sum(RECOVERY amounts)
    for the account, floored at zero. RECOVERY amount is expected to equal the
    recovered (previously failed) amount."""
    events = [e for e in db.billing_events.values() if e["account_id"] == account["account_id"]]
    failed = sum(abs(e["amount_cents"]) for e in events if e["event_type"] == "CHARGE_FAILED")
    recovered = sum(abs(e["amount_cents"]) for e in events if e["event_type"] == "RECOVERY")
    return max(0, failed - recovered)


def current_price_cents(subscription):
    """Current price: grandfathered when locked, else plan list price."""
    if subscription.get("grandfathered_price_cents") is not None:
        return subscription["grandfathered_price_cents"]
    plan = db.plans.get(subscription["plan_id"])
    return plan["monthly_price_cents"] if plan else 0


def payment_will_succeed(token_or_none):
    """Simulated payment gateway: a token equal to the string 'FAIL' (case-insensitive)
    or explicitly False fails; anything else succeeds. No token (None) means no
    payment method on file."""
    if token_or_none is None:
        return False
    if isinstance(token_or_none, str) and token_or_none.strip().upper() == "FAIL":
        return False
    return True


def proration_components(subscription, target_plan, now):
    """Upgrade proration per SCAFFOLD §1.3 proration_on_upgrade.
    Each component rounded half-up to whole cents BEFORE net subtraction."""
    period_start = parse_dt(subscription["period_start_utc"])
    period_end = parse_dt(subscription["period_end_utc"])
    days_remaining = whole_days(period_end, now)
    days_in_period = whole_days(period_end, period_start)
    if days_in_period <= 0:
        days_in_period = 1
    cur_price = current_price_cents(subscription)
    target_price = target_plan["monthly_price_cents"]
    unused_credit = round_half_up_cents(Decimal(cur_price) * days_remaining / days_in_period)
    prorated_charge = round_half_up_cents(Decimal(target_price) * days_remaining / days_in_period)
    net_charge = prorated_charge - unused_credit
    return {
        "net_charge_cents": net_charge,
        "unused_credit_cents": unused_credit,
        "prorated_charge_cents": prorated_charge,
    }


def pause_credit_cents(subscription, now):
    """PRORATION_CREDIT on pause (SCAFFOLD §1.3 proration_on_pause_credit)."""
    period_start = parse_dt(subscription["period_start_utc"])
    period_end = parse_dt(subscription["period_end_utc"])
    days_remaining = whole_days(period_end, now)
    days_in_period = whole_days(period_end, period_start)
    if days_in_period <= 0:
        days_in_period = 1
    cur_price = current_price_cents(subscription)
    return round_half_up_cents(Decimal(cur_price) * days_remaining / days_in_period)


def resume_charge_cents(subscription, now):
    """Prorated charge for the remaining period on resume."""
    period_start = parse_dt(subscription["period_start_utc"])
    period_end = parse_dt(subscription["period_end_utc"])
    days_remaining = whole_days(period_end, now)
    days_in_period = whole_days(period_end, period_start)
    if days_in_period <= 0:
        days_in_period = 1
    cur_price = current_price_cents(subscription)
    return round_half_up_cents(Decimal(cur_price) * days_remaining / days_in_period)


def parse_dt(s):
    from util import parse_iso
    return parse_iso(s)


def advance_period(subscription):
    """Move period forward by one nominal 30-day period; settle RECOVERED → CURRENT."""
    start = parse_dt(subscription["period_start_utc"])
    end = parse_dt(subscription["period_end_utc"])
    subscription["period_start_utc"] = format_ts(end)
    subscription["period_end_utc"] = format_ts(end + (end - start))
    if subscription["billing_state"] == "RECOVERED":
        subscription["billing_state"] = "CURRENT"
