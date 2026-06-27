"""Core domain services: common-field management, derived-field recomputation,
calculations, scheduling geometry, serialization, and shared validation helpers.

All numeric/monetary rules follow PRD §2.7 (integer cents, floor truncation) and
the §1.3 calculation table. Decimal is used for exact arithmetic; floats are never
used for money.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
from errors import err
from db import db, new_id, iso_millis, clock_now

# --- Constants (SCAFFOLD §1.3) ---
SERVICE_FEE_PCT = Decimal("0.15")
BILLING_INCREMENT_HOURS = Decimal("0.25")
TRAVEL_BUFFER_MIN = 30
MAX_RESCHEDULES = 3
FREE_THRESHOLD_HOURS = Decimal("24")
LATE_THRESHOLD_HOURS = Decimal("2")
LATE_PCT = Decimal("0.25")
LAST_MINUTE_PCT = Decimal("0.50")
PENALTY = {"LOW": 5, "MEDIUM": 15, "HIGH": 35}


# =============================================================================
# Common system fields (PRD §2.4)
# =============================================================================
def stamp_create(record, with_version=True):
    """Set id, created_at, updated_at, version on a new record. Adds a hidden
    _seq for deterministic created_at tie-breaking."""
    now = clock_now()
    record.setdefault("id", new_id())
    record["created_at"] = iso_millis(now)
    if with_version:
        record["updated_at"] = iso_millis(now)
        record["version"] = 1
    record["_seq"] = db.next_seq()
    record["_created_dt"] = now
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.5)."""
    record["updated_at"] = iso_millis(clock_now())
    record["version"] = record.get("version", 1) + 1


# =============================================================================
# Money helpers (PRD §2.7 — floor truncation)
# =============================================================================
def floor_cents(value):
    """Floor a Decimal monetary value down to a whole number of cents."""
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


def dec(value):
    return Decimal(str(value))


# =============================================================================
# Pricing calculations (§1.3 quote_estimate / final_settlement)
# =============================================================================
def quote_estimate(booking, category):
    """Pin estimate at OFFER time. Uses category default rate (no tasker yet)."""
    if category["pricing_model"] == "HOURLY":
        rate = dec(category["default_hourly_rate_cents"])
        hours = dec(booking["estimated_hours"])
        labor = floor_cents(rate * hours)
    else:  # FIXED
        labor = int(category["fixed_price_cents"])
    fee = floor_cents(dec(labor) * SERVICE_FEE_PCT)
    booking["estimated_labor_cents"] = labor
    booking["estimated_service_fee_cents"] = fee
    booking["estimated_total_cents"] = labor + fee


def final_settlement_amounts(booking, category, tasker):
    """Final variant: claimed tasker's personal rate, actual_hours rounded UP to
    the next quarter hour, THEN multiply, THEN floor (§1.3 final_settlement mode b)."""
    if category["pricing_model"] == "HOURLY":
        actual = dec(booking.get("actual_hours") or 0)
        # ceil(actual / 0.25) * 0.25
        quarters = (actual / BILLING_INCREMENT_HOURS).to_integral_value(rounding="ROUND_CEILING")
        billed_hours = quarters * BILLING_INCREMENT_HOURS
        labor = floor_cents(dec(tasker["hourly_rate_cents"]) * billed_hours)
    else:  # FIXED
        labor = int(category["fixed_price_cents"])
    fee = floor_cents(dec(labor) * SERVICE_FEE_PCT)
    tip = int(booking.get("tip_cents") or 0)
    total = labor + fee + tip
    payout = labor + tip
    return {
        "final_labor_cents": labor,
        "final_service_fee_cents": fee,
        "tip_cents": tip,
        "total_charged_cents": total,
        "tasker_payout_cents": payout,
    }


def cancellation_fee(booking):
    """§1.3 cancellation_fee — tier by lead time (>= boundaries), fee off labor estimate."""
    delta = booking["_scheduled_start_dt"] - clock_now()
    hours_before = dec(delta.total_seconds()) / dec(3600)
    if hours_before >= FREE_THRESHOLD_HOURS:
        tier, pct = "FREE", Decimal("0.00")
    elif hours_before >= LATE_THRESHOLD_HOURS:
        tier, pct = "LATE", LATE_PCT
    else:
        tier, pct = "LAST_MINUTE", LAST_MINUTE_PCT
    base = dec(booking["estimated_labor_cents"])
    fee = floor_cents(base * pct)
    # hours_before_start surfaced as a number (PRD): keep it as a float for the body.
    return {
        "hours_before_start": float(hours_before),
        "fee_tier": tier,
        "cancellation_fee_cents": fee,
    }


# =============================================================================
# Schedule window (§1.3 schedule_window)
# =============================================================================
def schedule_window_end(start_dt, booking, category):
    if category["pricing_model"] == "HOURLY":
        minutes = dec(booking["estimated_hours"]) * dec(60)
        minutes = float(minutes)
    else:
        minutes = float(category["default_duration_minutes"])
    return start_dt + timedelta(minutes=minutes)


# =============================================================================
# Scheduling geometry (§1.3 window_containment / booking_overlap)
# =============================================================================
def window_contained(tasker_id, start_dt, end_dt):
    """Closed containment in at least one OPEN AvailabilityWindow, no buffer."""
    for w in db.availability_windows.values():
        if w["tasker_id"] != tasker_id or w["status"] != "OPEN":
            continue
        if w["_window_start_dt"] <= start_dt and end_dt <= w["_window_end_dt"]:
            return True
    return False


def has_overlap(tasker_id, start_dt, end_dt, exclude_booking_id):
    """Buffered half-open overlap against the tasker's CLAIMED/EN_ROUTE/IN_PROGRESS
    bookings (excluding the one under evaluation), scanned by created_at ASC."""
    buffer = timedelta(minutes=TRAVEL_BUFFER_MIN)
    candidates = [
        b for b in db.bookings.values()
        if b.get("tasker_id") == tasker_id
        and b["status"] in ("CLAIMED", "EN_ROUTE", "IN_PROGRESS")
        and b["id"] != exclude_booking_id
    ]
    candidates.sort(key=lambda b: b["_seq"])
    for other in candidates:
        o_start = other["_scheduled_start_dt"]
        o_end = other["_scheduled_end_dt"]
        # conflict <=> new.start < other.end + BUF AND other.start < new.end + BUF
        if start_dt < (o_end + buffer) and o_start < (end_dt + buffer):
            return True
    return False


# =============================================================================
# Tasker derived fields & trust gate (§1.3 trust_score / trust_gate / avg_rating,
# PRD §2.5, §3.7)
# =============================================================================
def recompute_tasker(tasker, bump_version=False):
    """Recompute all derived fields of a tasker and re-derive its status gate."""
    tk_id = tasker["id"]

    # incident_penalty_total / trust_score
    penalty_total = 0
    for ti in db.trust_incidents.values():
        if ti["tasker_id"] == tk_id and ti["status"] in ("OPEN", "UPHELD"):
            penalty_total += ti["penalty_points"]
    tasker["incident_penalty_total"] = penalty_total
    trust_score = max(100 - penalty_total, 0)
    tasker["trust_score"] = trust_score

    # trust gate
    if trust_score < 40:
        tasker["status"] = "SUSPENDED"
    elif trust_score <= 69:
        tasker["status"] = "RESTRICTED"
    else:
        tasker["status"] = "ACTIVE"

    # booking counts
    active = 0
    completed = 0
    for b in db.bookings.values():
        if b.get("tasker_id") != tk_id:
            continue
        if b["status"] in ("CLAIMED", "EN_ROUTE", "IN_PROGRESS"):
            active += 1
        elif b["status"] == "COMPLETED":
            completed += 1
    tasker["active_booking_count"] = active
    tasker["completed_booking_count"] = completed

    # rating aggregates (PUBLISHED only)
    published = [
        r["rating_value"] for r in db.reviews.values()
        if r["tasker_id"] == tk_id and r["status"] == "PUBLISHED"
    ]
    tasker["rating_count"] = len(published)
    if not published:
        tasker["avg_rating"] = 0.0
    else:
        avg = (dec(sum(published)) / dec(len(published))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        tasker["avg_rating"] = float(avg)

    if bump_version:
        touch(tasker)


# =============================================================================
# Serialization — strip private fields and surface the public schema per entity
# =============================================================================
_PRIVATE_PREFIX = "_"


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith(_PRIVATE_PREFIX)}


def serialize_tasker(tasker):
    # taskers are recomputed lazily before being returned (PRD §2.5)
    recompute_tasker(tasker)
    return _public(tasker)


def serialize(record):
    return _public(record)


# =============================================================================
# Existence lookups (typed not-found, PRD §2.8)
# =============================================================================
def get_category_or_404(cid):
    c = db.task_categories.get(cid)
    if c is None:
        raise err(errors.ERR_CATEGORY_NOT_FOUND, "Category not found")
    return c


def get_tasker_or_404(tid):
    t = db.taskers.get(tid)
    if t is None:
        raise err(errors.ERR_TASKER_NOT_FOUND, "Tasker not found")
    return t


def get_client_or_404(cid):
    c = db.clients.get(cid)
    if c is None:
        raise err(errors.ERR_CLIENT_NOT_FOUND, "Client not found")
    return c


def get_skill_or_404(sid):
    s = db.tasker_skills.get(sid)
    if s is None:
        raise err(errors.ERR_SKILL_NOT_FOUND, "Skill not found")
    return s


def get_window_or_404(wid):
    w = db.availability_windows.get(wid)
    if w is None:
        raise err(errors.ERR_WINDOW_NOT_FOUND, "Window not found")
    return w


def get_series_or_404(sid):
    s = db.recurring_series.get(sid)
    if s is None:
        raise err(errors.ERR_SERIES_NOT_FOUND, "Series not found")
    return s


def get_review_or_404(rid):
    r = db.reviews.get(rid)
    if r is None:
        raise err(errors.ERR_REVIEW_NOT_FOUND, "Review not found")
    return r


def get_incident_or_404(iid):
    i = db.trust_incidents.get(iid)
    if i is None:
        raise err(errors.ERR_INCIDENT_NOT_FOUND, "Incident not found")
    return i


def get_booking_or_404(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise err(errors.ERR_BOOKING_NOT_FOUND, "Booking not found")
    lazy_expire(b)
    return b


# =============================================================================
# Lazy expiry of stale OFFERED bookings (PRD §2.4, §3.3)
# =============================================================================
def lazy_expire(booking):
    if booking["status"] == "OFFERED" and clock_now() >= booking["_scheduled_start_dt"]:
        booking["status"] = "EXPIRED"
        touch(booking)


def lazy_expire_all():
    for b in db.bookings.values():
        lazy_expire(b)


# =============================================================================
# Pagination (PRD §2.3)
# =============================================================================
def parse_pagination(args):
    """Parse limit/offset query params. Returns (limit, offset).
    limit default 10, min 1, max 100; offset default 0. Invalid -> ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_REQUEST, "Invalid limit")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_REQUEST, "Invalid offset")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (via _seq), slice, and build the pagination meta."""
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, meta
