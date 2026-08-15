"""Shared service helpers: serializers, pagination, derived fields, calculations.

All monetary math uses integer cents with round-half-up at exactly the steps the
PRD pins. Per-line values are rounded before summation; multi-step formulas
evaluate in the exact written order.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, fmt_ts
from errors import ApiError

# ---------------------------------------------------------------------------
# Pricing constants (PRD §3.9 / sale_price)
# ---------------------------------------------------------------------------
BASE_PRICE = {"KIDS": 4000, "BMX": 6000, "HYBRID": 9000, "ROAD": 12000, "MTB": 12000, "CARGO": 18000}
GRADE_MULT = {"A": Decimal("1.00"), "B": Decimal("0.80"), "C": Decimal("0.40")}
SURCHARGE_CAP = 3000
PRICE_FLOOR = 2000
ROUNDUP_STEP = 500

# Donation receipt (PRD §3.14 / donation_receipt_value)
FLAT_SCHEDULE_VALUE = {"A": 15000, "B": 9000, "C": 4000, "D": 1000}
FMV_FACTOR = Decimal("0.60")
GRADE_D_FACTOR = Decimal("0.10")

# Scrap payout (PRD §3.13 / scrap_payout)
SCRAP_RATE = {"STEEL": 15, "ALUMINUM": 85, "MIXED": 10}

# Hours accrual (PRD §3.7 / hours_accrual)
YOUTH_REQUIRED_HOURS = 8
ADULT_REQUIRED_HOURS = 12
DAILY_CAP_HOURS = 6

# Membership billing (PRD §3.12 / membership_billing)
PER_SESSION_CENTS = 400
PER_SESSION_MONTHLY_CAP = 3000
FLAT_MONTHLY_CENTS = 2500

# Giveaway quota (PRD §3.10 / giveaway_quota)
MONTHLY_GIVEAWAY_CAP = 4

# Promotion thresholds (PRD §3.5 / promotion_eligibility)
PROMOTION = {
    "TRAINEE": ("APPRENTICE", {"training_hours": 8, "sessions_attended": 2}),
    "APPRENTICE": ("JOURNEYMAN", {"training_hours": 24, "sessions_attended": 5}),
    "JOURNEYMAN": ("LEAD_MECHANIC", {"training_hours": 60, "sessions_attended": 12, "inspections_conducted": 10}),
}

NO_SHOW_LIMIT = 3
MAX_SHIFT_MINUTES = 480

SKILL_ORDER = ["TRAINEE", "APPRENTICE", "JOURNEYMAN", "LEAD_MECHANIC"]


def round_half_up(value):
    """Round a Decimal to whole integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 (lifecycle entities only)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] += 1


def make_common():
    """Common system fields for lifecycle-bearing entities."""
    ts = db.now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def make_event():
    """Event-style entities (PartHarvest, PartUsage, SafetyInspection,
    HelmetDistribution) carry only id + created_at."""
    return {"id": new_id(), "created_at": db.now_iso()}


def month_of(dt):
    return (dt.year, dt.month)


def month_str(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


def parse_month_param(raw):
    """Parse YYYY-MM -> (year, month); ERR_VALIDATION on bad shape."""
    try:
        y, m = raw.split("-")
        y, m = int(y), int(m)
        if not (1 <= m <= 12):
            raise ValueError
        return y, m
    except (ValueError, AttributeError):
        raise ApiError("ERR_VALIDATION", "month must be YYYY-MM")


def paginate(items):
    """Offset pagination per PRD §2.3: limit default 10, min 1, max 100; offset default 0.
    Results are pre-sorted by the caller (created_at ascending)."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + limit) < total}


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# Derived-field reconciliation (PRD §2.8) — recomputed on every input mutation
# ---------------------------------------------------------------------------

def recompute_donor(donor):
    bikes = [b for b in db.bikes.values() if b["donor_id"] == donor["id"]]
    donor["donated_bike_count"] = len(bikes)
    graded = [b for b in bikes if b["condition_grade"] is not None]
    if donor["receipt_method"] == "FLAT_SCHEDULE":
        donor["lifetime_receipt_value_cents"] = sum(FLAT_SCHEDULE_VALUE[b["condition_grade"]] for b in graded)
    else:
        donor["lifetime_receipt_value_cents"] = sum(fmv_bike_value(b) for b in graded)


def fmv_bike_value(bike):
    base = BASE_PRICE[bike["bike_type"]]
    grade = bike["condition_grade"]
    if grade in ("A", "B", "C"):
        return round_half_up(Decimal(base) * GRADE_MULT[grade] * FMV_FACTOR)
    return round_half_up(Decimal(base) * GRADE_D_FACTOR)


def recompute_bike_parts_cost(bike):
    """parts_cost_rollup: sum over COMMITTED PartUsage of quantity * snapshot unit_cost_cents."""
    total = 0
    for u in db.part_usages.values():
        if u["bike_id"] == bike["id"] and u["status"] == "COMMITTED":
            total += u["quantity"] * u["unit_cost_cents"]
    bike["parts_cost_cents"] = total


def recompute_part_low_stock(part):
    part["low_stock"] = part["quantity_on_hand"] <= part["reorder_threshold"]


def recompute_volunteer(vol):
    vol["training_hours"] = sum(
        db.training_sessions[a["session_id"]]["credit_hours"]
        for a in db.attendances.values()
        if a["volunteer_id"] == vol["id"] and a["status"] == "ATTENDED"
    )
    vol["sessions_attended"] = sum(
        1 for a in db.attendances.values()
        if a["volunteer_id"] == vol["id"] and a["status"] == "ATTENDED"
    )
    vol["inspections_conducted"] = sum(
        1 for i in db.inspections.values() if i["inspector_volunteer_id"] == vol["id"]
    )
    vol["shift_minutes"] = sum(
        s["credited_minutes"] or 0
        for s in db.shifts.values()
        if s["volunteer_id"] == vol["id"] and s["status"] == "COMPLETED"
    )


def recompute_session_enrolled(session):
    session["enrolled_count"] = sum(
        1 for a in db.attendances.values()
        if a["session_id"] == session["id"] and a["status"] == "ENROLLED"
    )


def participant_hours_earned(participant):
    return sum(
        h["hours"] for h in db.hour_logs.values()
        if h["participant_id"] == participant["id"] and h["status"] == "APPROVED"
    )


def release_reserved_bike(participant):
    """Cascade: participant leaving/losing HOURS_MET releases their reserved bike."""
    bike_id = participant.get("reserved_bike_id")
    if bike_id:
        bike = db.bikes.get(bike_id)
        if bike is not None and bike["status"] == "RESERVED_FOR_GRADUATE":
            bike["status"] = "READY_FOR_DISPOSITION"
            touch(bike)
        participant["reserved_bike_id"] = None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def sale_price(bike, membership_id):
    """sale_price ladder (PRD §3.9), pinned order:
    grade tier -> surcharge cap -> member discount -> floor."""
    step1 = round_half_up(Decimal(BASE_PRICE[bike["bike_type"]]) * GRADE_MULT[bike["condition_grade"]])
    surcharge = min(round_half_up(Decimal(bike["parts_cost_cents"]) * Decimal("0.5")), SURCHARGE_CAP)
    step2 = step1 + surcharge
    discount = 0
    if membership_id:
        membership = db.memberships.get(membership_id)
        if membership is not None and membership["status"] == "ACTIVE":
            discount = round_half_up(Decimal(step2) * Decimal("0.10"))
    step3 = step2 - discount
    return max(step3, PRICE_FLOOR)


def scrap_payout(material, weight_kg):
    return round_half_up(Decimal(str(weight_kg)) * SCRAP_RATE[material])


def giveaway_month_count(year, month):
    return sum(
        1 for g in db.giveaways.values()
        if g["status"] in ("APPROVED", "FULFILLED")
        and g["decided_at"] is not None
        and month_of(_parse_dt(g["decided_at"])) == (year, month)
    )


def _parse_dt(s):
    from db import _parse_iso
    return _parse_iso(s)
