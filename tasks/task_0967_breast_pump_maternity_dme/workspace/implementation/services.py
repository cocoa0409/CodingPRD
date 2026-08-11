from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, next_seq, now_iso

BUNDLE_THRESHOLD_CENTS = 20000
BUNDLE_DISCOUNT_PCT = Decimal("0.10")
MAX_WARRANTY_REPLACEMENTS = 2
MAX_REOPENS = 2


def rhu(dec):
    """Round half up to integer cents."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(ent):
    ent["updated_at"] = now_iso()


def bump(ent):
    ent["version"] += 1
    touch(ent)


def create_entity(collection, fields):
    ent = dict(fields)
    ent["id"] = new_id()
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    collection[ent["id"]] = ent
    return ent


def order_lines(order_id):
    return [l for l in store.order_lines.values() if l["order_id"] == order_id]


def primary_line(order_id):
    for l in store.order_lines.values():
        if l["order_id"] == order_id and l["line_type"] == "PUMP_PRIMARY":
            return l
    return None


def recompute_pricing(order):
    """order_line_pricing then bundle_discount, in the pinned evaluation order."""
    lines = order_lines(order["id"])
    subtotal = 0
    for l in lines:
        l["line_total_cents"] = rhu(Decimal(l["quantity"]) * Decimal(l["unit_price_cents"]))
        subtotal += l["line_total_cents"]
    if subtotal >= BUNDLE_THRESHOLD_CENTS:
        for l in lines:
            if l["line_type"] == "ADDON_GARMENT":
                l["discount_cents"] = rhu(Decimal(l["line_total_cents"]) * BUNDLE_DISCOUNT_PCT)
            else:
                l["discount_cents"] = 0
    else:
        for l in lines:
            l["discount_cents"] = 0
    order["merchandise_subtotal_cents"] = subtotal
    order["discount_total_cents"] = sum(l["discount_cents"] for l in lines)
    order["order_total_cents"] = subtotal - order["discount_total_cents"]


def garment_qty(order):
    return sum(
        l["quantity"]
        for l in order_lines(order["id"])
        if l["line_type"] == "ADDON_GARMENT"
    )


def _iso(d):
    return d.isoformat()


def compute_next_eligible(sched):
    anchor = date.fromisoformat(sched["anchor_date"])
    freq = sched["frequency_days"]
    last = sched["last_fulfilled_date"]
    if last is None:
        return _iso(anchor + timedelta(days=freq))
    last_d = date.fromisoformat(last)
    if sched["schedule_mode"] == "ROLLING":
        return _iso(last_d + timedelta(days=freq))
    # CALENDAR_ANCHORED: smallest anchor + k*freq strictly greater than last
    diff = (last_d - anchor).days
    k = diff // freq + 1
    if k < 1:
        k = 1
    return _iso(anchor + timedelta(days=k * freq))


def recompute_member_aggregates(member):
    actives = [
        s
        for s in store.schedules.values()
        if s["member_id"] == member["id"] and s["status"] == "ACTIVE"
    ]
    count = len(actives)
    nrd = min((s["next_eligible_date"] for s in actives), default=None)
    if member["active_schedule_count"] != count or member["next_resupply_date"] != nrd:
        member["active_schedule_count"] = count
        member["next_resupply_date"] = nrd
        bump(member)


def add_months(d, months):
    idx = d.month - 1 + months
    y = d.year + idx // 12
    m = idx % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def adjudication_waterfall(policy, member, allowed):
    ded_remaining = max(0, policy["deductible_cents"] - policy["deductible_met_cents"])
    ded_applied = min(allowed, ded_remaining)
    remainder = allowed - ded_applied
    coins = rhu(Decimal(remainder) * Decimal(str(policy["coinsurance_pct"])))
    pre_cap = ded_applied + coins
    if policy["oop_max_cents"] > 0:
        headroom = max(0, policy["oop_max_cents"] - member["oop_accumulated_cents"])
        patient = min(pre_cap, headroom)
    else:
        patient = pre_cap
    return ded_applied, patient
