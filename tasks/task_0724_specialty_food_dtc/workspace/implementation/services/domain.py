"""Cross-entity domain logic: availability recompute, churn recompute, FEFO, cascades."""
from datetime import timedelta

from db import db, touch
from clock import clock, parse_iso
from services import calc


def lot_is_consumable(lot):
    """Released, not past expiry at current clock."""
    if lot["status"] != "RELEASED":
        return False
    exp = parse_iso(lot["expiry_iso"])
    if exp is None:
        return False
    return clock.now() < exp


def lot_is_expired(lot):
    """A lot is EXPIRED (§3.2) once the clock reaches or passes its expiry_iso.
    This is independent of status (RELEASED vs RECALLED): a recalled lot with a
    future expiry is NOT expired."""
    exp = parse_iso(lot["expiry_iso"])
    if exp is None:
        return False
    return clock.now() >= exp


def recompute_sku_availability(sku):
    """available_units = sum(remaining_units over RELEASED, non-expired lots) - reserved_units.
    Bumps version/updated_at as it is a mutation of a computed field."""
    total_remaining = 0
    for lot in db.lots.values():
        if lot["sku_id"] == sku["id"] and lot_is_consumable(lot):
            total_remaining += lot["remaining_units"]
    available = total_remaining - sku["reserved_units"]
    if available < 0:
        available = 0
    if available != sku["available_units"]:
        sku["available_units"] = available
        touch(sku)
    return available


def _window_count_events(customer_id, kind):
    """Count events of `kind` ('skip'|'fail') in trailing CHURN_WINDOW_DAYS for ACUTE variant."""
    cutoff = clock.now() - timedelta(days=calc.CHURN_WINDOW_DAYS)
    count = 0
    for ev in db.customers[customer_id].get("_events", []):
        if ev["kind"] == kind and ev["at"] >= cutoff:
            count += 1
    return count


def _days_since_last_order(customer):
    last = customer.get("last_order_at")
    if not last:
        # No order ever: treat recency at maximum (cap applies anyway).
        return calc.RECENCY_DIVISOR_DAYS
    last_dt = parse_iso(last)
    delta = (clock.now() - last_dt).total_seconds() / 86400.0
    if delta < 0:
        delta = 0
    return delta


def compute_churn(customer, variant="ACUTE"):
    """Return (score, band) for the given variant without persisting."""
    days = _days_since_last_order(customer)
    if variant == "CHRONIC":
        skips = customer["lifetime_skip_count"]
        fails = customer["lifetime_failed_payment_count"]
    else:
        skips = _window_count_events(customer["id"], "skip")
        fails = _window_count_events(customer["id"], "fail")
    score = calc.churn_score(days, skips, fails)
    band = calc.churn_band(score)
    return score, band


def recompute_customer_churn(customer):
    """Persist ACUTE churn score/band (mutation)."""
    score, band = compute_churn(customer, "ACUTE")
    if score != customer["churn_risk_score"] or band != customer["churn_band"]:
        customer["churn_risk_score"] = score
        customer["churn_band"] = band
        touch(customer)
    else:
        # Even when unchanged numerically the recompute is invoked; per PRD §2.4 a
        # recompute is a mutation. Bump to keep version semantics consistent.
        customer["churn_risk_score"] = score
        customer["churn_band"] = band
        touch(customer)
    update_winback_eligible(customer)


def update_winback_eligible(customer):
    has_active_offer = any(
        o["customer_id"] == customer["id"] and o["status"] == "OFFERED"
        for o in db.winback_offers.values()
    )
    eligible = (
        customer["status"] == "DORMANT"
        and customer["churn_band"] == "CHURN_IMMINENT"
        and not has_active_offer
    )
    customer["winback_eligible"] = eligible


def fefo_select(sku_id):
    """Pick the consumable lot with earliest expiry_iso, tie-break created_at (_seq) ASC.
    Returns the lot dict or None."""
    candidates = [
        lot for lot in db.lots.values()
        if lot["sku_id"] == sku_id and lot_is_consumable(lot)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (parse_iso(l["expiry_iso"]), l["_seq"]))
    return candidates[0]


def auto_pause_subscriptions_for_sku(sku_id):
    """Auto-pause every ACTIVE subscription whose selected sku is sku_id (cascade)."""
    for sub in db.subscriptions.values():
        if sub["sku_id"] == sku_id and sub["status"] == "ACTIVE":
            sub["status"] = "PAUSED"
            touch(sub)


def record_event(customer, kind):
    customer.setdefault("_events", []).append({"kind": kind, "at": clock.now()})
