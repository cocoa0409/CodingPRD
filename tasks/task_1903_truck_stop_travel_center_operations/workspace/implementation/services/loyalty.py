"""Loyalty points ledger (PRD 2.9; calc loyalty_points_accrual)."""
from datetime import timedelta

from db import db
from services.core import new_record, touch
from util import CLOCK, dec, fmt_dt, parse_dt, rhu_int

POINTS_EXPIRY_DAYS = 360

# Per-source accrual rates (points per dollar); each source rounds independently.
EARN_RATES = {
    "FUEL_SALE": dec("0.5"),
    "STORE_SALE": dec("1.0"),
    "SERVICE": dec("1.0"),
    "PARKING": dec("1.0"),
}


def member_lots(member_id):
    return [l for l in db["points_lots"].values() if l["loyalty_member_id"] == member_id]


def redeemable_balance(member_id, now=None):
    """Sum of remaining_points over lots whose expires_at is strictly after now."""
    now = now or CLOCK.now()
    total = 0
    for lot in member_lots(member_id):
        if lot["remaining_points"] <= 0:
            continue
        if parse_dt(lot["expires_at"]) <= now:
            continue  # expired: requires expires_at > now
        total += lot["remaining_points"]
    return total


def recompute_member_balance(member, bump=True):
    balance = redeemable_balance(member["id"])
    if member["points_balance"] != balance:
        member["points_balance"] = balance
        if bump:
            touch(member)
    return balance


def grant_lot(member_id, points, source_type, source_id):
    """Accrual: write a lot expiring 360 days out; recompute the member balance."""
    if not points:
        return None
    now = CLOCK.now()
    lot = new_record("points_lots", {
        "loyalty_member_id": member_id,
        "points": int(points),
        "remaining_points": int(points),
        "source_type": source_type,
        "source_id": source_id,
        "earned_at": fmt_dt(now),
        "expires_at": fmt_dt(now + timedelta(days=POINTS_EXPIRY_DAYS)),
    }, ledger=True)
    member = db["loyalty_members"].get(member_id)
    if member is not None:
        recompute_member_balance(member)
    return lot


def earn_points_for(member, amount_cents, source_type, source_id):
    """Per-source rounded earn. Suspended/closed members neither redeem nor earn."""
    if member is None or member["status"] != "ACTIVE":
        return 0
    rate = EARN_RATES[source_type]
    points = rhu_int(dec(amount_cents) / dec(100) * rate)
    if points > 0:
        grant_lot(member["id"], points, source_type, source_id)
    return points


def burn_fefo(member_id, count):
    """Redemption: consume lots first-expiring-first-out (earned_at ASC, ties by
    insertion order), skipping expired lots. Caller has checked the balance."""
    if count <= 0:
        return
    now = CLOCK.now()
    lots = [l for l in member_lots(member_id)
            if l["remaining_points"] > 0 and parse_dt(l["expires_at"]) > now]
    lots.sort(key=lambda l: (l["earned_at"], l["_seq"]))
    remaining = count
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["remaining_points"], remaining)
        lot["remaining_points"] -= take
        remaining -= take
    member = db["loyalty_members"].get(member_id)
    if member is not None:
        recompute_member_balance(member)


def clawback_newest(member_id, count, source_type="ADJUSTMENT", source_id=None):
    """Negative adjustment: decrement remaining_points newest-first, never below 0;
    the negative lot itself is recorded with remaining_points 0."""
    if count <= 0:
        return None
    lots = [l for l in member_lots(member_id) if l["remaining_points"] > 0]
    lots.sort(key=lambda l: (l["earned_at"], l["_seq"]), reverse=True)
    remaining = count
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["remaining_points"], remaining)
        lot["remaining_points"] -= take
        remaining -= take
    now = CLOCK.now()
    lot = new_record("points_lots", {
        "loyalty_member_id": member_id,
        "points": -int(count),
        "remaining_points": 0,
        "source_type": source_type,
        "source_id": source_id,
        "earned_at": fmt_dt(now),
        "expires_at": fmt_dt(now + timedelta(days=POINTS_EXPIRY_DAYS)),
    }, ledger=True)
    member = db["loyalty_members"].get(member_id)
    if member is not None:
        recompute_member_balance(member)
    return lot


def forfeit_all_points(member):
    """Member close: all remaining points forfeited; balance recomputed to 0."""
    changed = False
    for lot in member_lots(member["id"]):
        if lot["remaining_points"] != 0:
            lot["remaining_points"] = 0
            changed = True
    if member["points_balance"] != 0 or changed:
        member["points_balance"] = 0
