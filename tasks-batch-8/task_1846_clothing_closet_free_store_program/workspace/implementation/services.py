"""Business logic: lazy status advancement, calculations, serializers."""
from datetime import timedelta
from decimal import Decimal

import db
from db import store, touch
from util import fmt_dt, month_key, next_month, quantize, round_half_up_int, trunc_second

# --- visit_item_allowance constants ---
BASE_ITEMS = 8
PER_MEMBER_ITEMS = 2
HOUSEHOLD_CAP = 16
HARDSHIP_MULTIPLIER = Decimal("1.5")
HARD_VISIT_CAP = 24

# --- visit_frequency_gate / rolling caps ---
COOLDOWN_DAYS = 14
MAX_VISITS_PER_30D = 3
MAX_ITEMS_PER_30D = 30

# --- category_line_cap (general lines only) ---
CATEGORY_CAPS = {"COATS": 2, "INTERVIEW_ATTIRE": 1}

# --- voucher_quota_carryover ---
MAX_CARRYOVER = 5

# --- recycling_credit ---
EST_WEIGHT_KG = {
    "ADULT_TOPS": Decimal("0.40"),
    "ADULT_BOTTOMS": Decimal("0.60"),
    "CHILDRENS": Decimal("0.30"),
    "COATS": Decimal("1.50"),
    "INTERVIEW_ATTIRE": Decimal("0.80"),
    "ACCESSORIES": Decimal("0.20"),
}
RATE_CENTS_PER_KG = {
    "ADULT_TOPS": 45,
    "ADULT_BOTTOMS": 45,
    "CHILDRENS": 38,
    "COATS": 52,
    "INTERVIEW_ATTIRE": 60,
    "ACCESSORIES": 30,
}
TIER1_MAX_KG = Decimal("100")
TIER2_MAX_KG = Decimal("500")
TIER1_RATE = 40
TIER2_RATE = 44
TIER3_RATE = 50

CATEGORIES = set(EST_WEIGHT_KG)
SEASONS = {"WINTER", "SUMMER", "ALL_SEASON"}
GRADES = {"NEW_WITH_TAGS", "GOOD", "FAIR", "REJECT"}


# ---------------------------------------------------------------------------
# Lazy status advancement (PRD 2.4).
# ---------------------------------------------------------------------------

def refresh_voucher(v):
    """ISSUED -> EXPIRED once the clock reaches expires_at."""
    if v["status"] == "ISSUED" and db.now() >= v["expires_at"]:
        v["status"] = "EXPIRED"
        touch(v)


def refresh_drive(d):
    """UPCOMING -> ACTIVE inside [start_at, end_at]; -> CLOSED past end_at."""
    if d["status"] == "CLOSED":
        return
    now = db.now()
    if now > d["end_at"]:
        d["status"] = "CLOSED"
        touch(d)
    elif d["start_at"] <= now <= d["end_at"] and d["status"] == "UPCOMING":
        d["status"] = "ACTIVE"
        touch(d)


def refresh_all_drives():
    for d in store.drives.values():
        refresh_drive(d)


# ---------------------------------------------------------------------------
# visit_window_stats: half-open window (now-30d, now]; a checkout exactly
# 30*24h ago is EXCLUDED. Second precision on timestamp comparisons.
# ---------------------------------------------------------------------------

def visit_window_stats(client_id):
    now = trunc_second(db.now())
    window_start = now - timedelta(days=30)
    visit_ids = set()
    visits = 0
    for v in store.visits.values():
        if v["client_id"] != client_id:
            continue
        if v["status"] != "CHECKED_OUT" or v["checked_out_at"] is None:
            continue
        co = trunc_second(v["checked_out_at"])
        if window_start < co <= now:
            visits += 1
            visit_ids.add(v["id"])
    items = sum(
        1 for ln in store.lines.values()
        if ln["visit_id"] in visit_ids and ln["status"] == "DISTRIBUTED"
    )
    return visits, items


# ---------------------------------------------------------------------------
# visit_item_allowance.
# ---------------------------------------------------------------------------

def compute_allowance(client, voucher):
    base = min(
        HOUSEHOLD_CAP,
        BASE_ITEMS + PER_MEMBER_ITEMS * max(0, client["household_size"] - 1),
    )
    if client["eligibility_tier"] == "HARDSHIP":
        base = round_half_up_int(Decimal(base) * HARDSHIP_MULTIPLIER)
    bonus = voucher["bonus_items"] if voucher else 0
    general = min(HARD_VISIT_CAP, base + bonus)
    return general, bonus


def cooldown_ok(client, voucher):
    """14-day cooldown; inclusive boundary; waives_frequency overrides it."""
    if voucher is not None and voucher.get("waives_frequency"):
        return True
    last = client["last_checkout_at"]
    if last is None:
        return True
    now = trunc_second(db.now())
    return now >= trunc_second(last) + timedelta(days=COOLDOWN_DAYS)


# ---------------------------------------------------------------------------
# zone_posture: FULL when current_stock >= capacity (inclusive);
# NEAR_FULL at ceil(0.8 * capacity); else AVAILABLE.
# ---------------------------------------------------------------------------

def zone_posture(zone):
    stock = zone["current_stock"]
    cap = zone["capacity_items"]
    if stock >= cap:
        return "FULL"
    if stock >= -(-8 * cap // 10):  # ceil(0.8 * capacity) in integer math
        return "NEAR_FULL"
    return "AVAILABLE"


def season_compatible(item_season, zone_policy):
    return (
        item_season == "ALL_SEASON"
        or zone_policy == "ALL_SEASON"
        or item_season == zone_policy
    )


# ---------------------------------------------------------------------------
# voucher_quota_carryover: walk months ascending from the anchor month.
# ---------------------------------------------------------------------------

def vouchers_issued_in_month(partner_id, mk):
    return sum(
        1 for v in store.vouchers.values()
        if v["partner_id"] == partner_id and v["issued_month_key"] == mk
    )


def partner_current_month_quota(partner):
    base = partner["base_voucher_quota"]
    anchor = partner["activated_month_key"]
    cur = month_key(db.now())
    quota = base  # carryover into the anchor month is 0
    m = anchor
    while m < cur:
        issued_m = vouchers_issued_in_month(partner["id"], m)
        carry = min(MAX_CARRYOVER, max(0, quota - issued_m))
        quota = base + carry
        m = next_month(m)
    return quota


# ---------------------------------------------------------------------------
# recycling_credit.
# ---------------------------------------------------------------------------

def recycling_items(batch_id):
    return [i for i in store.items.values() if i["recycling_batch_id"] == batch_id]


def est_weight_of(item):
    return EST_WEIGHT_KG[item["category"]]


def provisional_credit_cents(items):
    """Per-item rounding, then sum (pinned order)."""
    total = 0
    for item in items:
        total += round_half_up_int(
            est_weight_of(item) * RATE_CENTS_PER_KG[item["category"]]
        )
    return total


def est_weight_total(items):
    total = sum((est_weight_of(i) for i in items), Decimal("0"))
    return quantize(total, "0.01")


def final_credit_cents(actual_weight_kg):
    """Single blended tier rate on the actual scale weight; inclusive upward."""
    w = Decimal(actual_weight_kg)
    if w < TIER1_MAX_KG:
        rate = TIER1_RATE
    elif w < TIER2_MAX_KG:
        rate = TIER2_RATE
    else:
        rate = TIER3_RATE
    return round_half_up_int(w * rate)


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved at read time).
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_client(c):
    visits, items = visit_window_stats(c["id"])
    out = {
        "id": c["id"],
        "full_name": c["full_name"],
        "household_size": c["household_size"],
        "eligibility_tier": c["eligibility_tier"],
        "status": c["status"],
        "last_checkout_at": fmt_dt(c["last_checkout_at"]),
        "visits_in_30d": visits,
        "items_in_30d": items,
    }
    out.update(_common(c))
    return out


def serialize_visit(v):
    out = {
        "id": v["id"],
        "client_id": v["client_id"],
        "voucher_id": v["voucher_id"],
        "status": v["status"],
        "checked_in_at": fmt_dt(v["checked_in_at"]),
        "checked_out_at": fmt_dt(v["checked_out_at"]),
        "general_allowance": v["general_allowance"],
        "voucher_bonus_applied": v["voucher_bonus_applied"],
    }
    out.update(_common(v))
    return out


def serialize_line(ln):
    out = {
        "id": ln["id"],
        "visit_id": ln["visit_id"],
        "item_id": ln["item_id"],
        "category_snapshot": ln["category_snapshot"],
        "is_drive_line": ln["is_drive_line"],
        "drive_id": ln["drive_id"],
        "status": ln["status"],
    }
    out.update(_common(ln))
    return out


def batch_items_created_count(batch_id):
    return sum(1 for i in store.items.values() if i["donation_batch_id"] == batch_id)


def serialize_batch(b):
    out = {
        "id": b["id"],
        "donor_name": b["donor_name"],
        "donor_email": b["donor_email"],
        "item_count_declared": b["item_count_declared"],
        "items_created_count": batch_items_created_count(b["id"]),
        "status": b["status"],
        "sorted_by_user_id": b["sorted_by_user_id"],
        "closed_by_user_id": b["closed_by_user_id"],
    }
    out.update(_common(b))
    return out


def serialize_item(i):
    out = {
        "id": i["id"],
        "donation_batch_id": i["donation_batch_id"],
        "category": i["category"],
        "season": i["season"],
        "quality_grade": i["quality_grade"],
        "drive_id": i["drive_id"],
        "status": i["status"],
        "storage_zone_id": i["storage_zone_id"],
        "reserved_visit_id": i["reserved_visit_id"],
        "recycling_batch_id": i["recycling_batch_id"],
        "graded_by_user_id": i["graded_by_user_id"],
        "stocked_at": fmt_dt(i["stocked_at"]),
        "distributed_at": fmt_dt(i["distributed_at"]),
        "distributed_from_zone_id": i["distributed_from_zone_id"],
    }
    out.update(_common(i))
    return out


def serialize_zone(z):
    out = {
        "id": z["id"],
        "zone_code": z["zone_code"],
        "season_policy": z["season_policy"],
        "capacity_items": z["capacity_items"],
        "current_stock": z["current_stock"],
        "posture": zone_posture(z),
    }
    out.update(_common(z))
    return out


def serialize_volunteer(v):
    out = {
        "id": v["id"],
        "full_name": v["full_name"],
        "is_lead": v["is_lead"],
        "status": v["status"],
    }
    out.update(_common(v))
    return out


def shift_active_signup_count(shift_id):
    return sum(
        1 for s in store.signups.values()
        if s["shift_id"] == shift_id and s["status"] in ("SIGNED_UP", "CHECKED_IN")
    )


def serialize_shift(s):
    out = {
        "id": s["id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "role_type": s["role_type"],
        "capacity_volunteers": s["capacity_volunteers"],
        "active_signup_count": shift_active_signup_count(s["id"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def serialize_signup(s):
    out = {
        "id": s["id"],
        "shift_id": s["shift_id"],
        "volunteer_id": s["volunteer_id"],
        "status": s["status"],
        "checked_in_at": fmt_dt(s["checked_in_at"]),
    }
    out.update(_common(s))
    return out


def serialize_partner(p):
    cur = month_key(db.now())
    out = {
        "id": p["id"],
        "name": p["name"],
        "base_voucher_quota": p["base_voucher_quota"],
        "status": p["status"],
        "activated_month_key": p["activated_month_key"],
        "vouchers_issued_current_month": vouchers_issued_in_month(p["id"], cur),
        "current_month_quota": partner_current_month_quota(p),
    }
    out.update(_common(p))
    return out


def serialize_voucher(v):
    out = {
        "id": v["id"],
        "code": v["code"],
        "partner_id": v["partner_id"],
        "client_id": v["client_id"],
        "bonus_items": v["bonus_items"],
        "waives_frequency": v["waives_frequency"],
        "expires_at": fmt_dt(v["expires_at"]),
        "status": v["status"],
        "issued_month_key": v["issued_month_key"],
        "redeemed_at": fmt_dt(v["redeemed_at"]),
    }
    out.update(_common(v))
    return out


def serialize_drive(d):
    out = {
        "id": d["id"],
        "drive_type": d["drive_type"],
        "target_category": d["target_category"],
        "start_at": fmt_dt(d["start_at"]),
        "end_at": fmt_dt(d["end_at"]),
        "bonus_items_per_client": d["bonus_items_per_client"],
        "status": d["status"],
    }
    out.update(_common(d))
    return out


def serialize_rotation(r):
    out = {
        "id": r["id"],
        "target_season": r["target_season"],
        "window_start": fmt_dt(r["window_start"]),
        "window_end": fmt_dt(r["window_end"]),
        "status": r["status"],
        "executed_at": fmt_dt(r["executed_at"]),
        "moved_out_count": r["moved_out_count"],
        "moved_in_count": r["moved_in_count"],
    }
    out.update(_common(r))
    return out


def serialize_recycling(b):
    items = recycling_items(b["id"])
    out = {
        "id": b["id"],
        "recycler_name": b["recycler_name"],
        "capacity_kg": float(b["capacity_kg"]),
        "status": b["status"],
        "item_count": len(items),
        "est_weight_kg": float(est_weight_total(items)),
        "provisional_credit_cents": b["provisional_credit_cents"],
        "actual_weight_kg": (
            float(b["actual_weight_kg"]) if b["actual_weight_kg"] is not None else None
        ),
        "final_credit_cents": b["final_credit_cents"],
        "sealed_by_user_id": b["sealed_by_user_id"],
        "picked_up_by_user_id": b["picked_up_by_user_id"],
    }
    out.update(_common(b))
    return out
