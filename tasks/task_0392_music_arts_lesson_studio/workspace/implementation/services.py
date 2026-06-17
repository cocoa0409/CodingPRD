"""Business logic: calculations, derived counts, overlap tests, cascades.

All numbers per PRD §3 and SCAFFOLD §1.3.
"""
from decimal import Decimal

import db
import helpers

SESSIONS_PER_MONTH = 4
DECAY_BASE = Decimal("0.95")
MS_PER_DAY = 86400000

# ----------------------------------------------------------------------------
# Family-scoped derived counts and discount (PRD §3.4)
# ----------------------------------------------------------------------------

def active_enrollment_count(family_id):
    return sum(
        1 for e in db.enrollments.values()
        if e["family_id"] == family_id and e["lifecycle_status"] == "ACTIVE"
    )


def select_discount_pct(studio, n):
    """Greatest tier whose min_active_enrollments <= n; else 0.0 (PRD §3.4)."""
    eligible = [t for t in studio["family_discount_tiers"] if t["min_active_enrollments"] <= n]
    if not eligible:
        return 0.0
    best = max(eligible, key=lambda t: t["min_active_enrollments"])
    return best["discount_pct"]


def recompute_family_discount(studio, family):
    """Recompute active_enrollment_count and family_discount_pct on a family.
    This is a derived mutation: bump version + updated_at (PRD §2.9)."""
    n = active_enrollment_count(family["id"])
    family["active_enrollment_count"] = n
    family["family_discount_pct"] = select_discount_pct(studio, n)
    db.touch(family)


# ----------------------------------------------------------------------------
# Wallet balance (conserved quantity, PRD §2.8). We maintain wallet_balance_cents
# directly on the family as events occur, so no recompute needed here.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Makeup credits (PRD §3.6)
# ----------------------------------------------------------------------------

def lazy_expire_credit(credit, current_ms):
    """A credit past its expires_utc is treated EXPIRED on next read/use."""
    if credit["status"] == "OUTSTANDING":
        exp_ms = helpers.parse_iso_ms(credit["expires_utc"])
        if current_ms > exp_ms:
            credit["status"] = "EXPIRED"
            db.touch(credit)


def outstanding_credit_count(enrollment_id, current_ms):
    """Count OUTSTANDING credits still within validity window (PRD §3.6).
    Lazily expires any that have passed expires_utc."""
    count = 0
    for c in db.makeup_credits.values():
        if c["enrollment_id"] != enrollment_id:
            continue
        lazy_expire_credit(c, current_ms)
        if c["status"] == "OUTSTANDING":
            count += 1
    return count


def mint_credit(enrollment, studio, origin_occurrence_id):
    issued_ms = helpers.parse_iso_ms(studio["current_utc"])
    expires_ms = issued_ms + studio["makeup_credit_valid_days"] * MS_PER_DAY
    credit = db.init_record({
        "enrollment_id": enrollment["id"],
        "origin_occurrence_id": origin_occurrence_id,
        "issued_utc": studio["current_utc"],
        "expires_utc": helpers.ms_to_iso(expires_ms),
        "status": "OUTSTANDING",
    })
    db.makeup_credits[credit["id"]] = credit
    return credit


# ----------------------------------------------------------------------------
# Tuition (PRD §3.3)
# ----------------------------------------------------------------------------

def compute_monthly_tuition(instructor, duration_min):
    """round_half_up(hourly_rate_cents * duration_min / 60 * SESSIONS_PER_MONTH)."""
    rate = Decimal(instructor["hourly_rate_cents"])
    val = rate * Decimal(duration_min) / Decimal(60) * Decimal(SESSIONS_PER_MONTH)
    return helpers.round_half_up(val)


def billing_period_range_ms(billing_period):
    """Return (start_ms, end_ms) half-open for a 'YYYY-MM' billing period.
    end_ms is the first instant of the NEXT month."""
    year, month = billing_period.split("-")
    y = int(year)
    m = int(month)
    start = helpers.parse_iso_ms("%04d-%02d-01T00:00:00.000Z" % (y, m))
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    end = helpers.parse_iso_ms("%04d-%02d-01T00:00:00.000Z" % (ny, nm))
    return start, end


def compute_provisional(enrollment, family, billing_period, current_ms):
    """Forward-looking: count SCHEDULED occurrences in period at/after clock.
    prorate-then-round, then discount-then-round (PRD §3.3)."""
    start_ms, end_ms = billing_period_range_ms(billing_period)
    remaining = 0
    for occ in db.lesson_occurrences.values():
        if occ["enrollment_id"] != enrollment["id"]:
            continue
        if occ["status"] != "SCHEDULED":
            continue
        occ_ms = helpers.parse_iso_ms(occ["scheduled_start_utc"])
        if start_ms <= occ_ms < end_ms and occ_ms >= current_ms:
            remaining += 1
    base = helpers.round_half_up(
        Decimal(enrollment["monthly_tuition_cents"]) * Decimal(remaining) / Decimal(SESSIONS_PER_MONTH)
    )
    disc = Decimal(str(family["family_discount_pct"]))
    provisional = helpers.round_half_up(Decimal(base) * (Decimal(1) - disc))
    return provisional


def compute_finalized(enrollment, family, billing_period):
    """Backward-looking: per-session rate rounded, times billable count, then
    discount-then-round (PRD §3.3). billable = COMPLETED or CANCELLED_LATE in period."""
    start_ms, end_ms = billing_period_range_ms(billing_period)
    per_session = helpers.round_half_up(
        Decimal(enrollment["monthly_tuition_cents"]) / Decimal(SESSIONS_PER_MONTH)
    )
    billable = 0
    for occ in db.lesson_occurrences.values():
        if occ["enrollment_id"] != enrollment["id"]:
            continue
        if occ["status"] not in ("COMPLETED", "CANCELLED_LATE"):
            continue
        occ_ms = helpers.parse_iso_ms(occ["scheduled_start_utc"])
        if start_ms <= occ_ms < end_ms:
            billable += 1
    gross = per_session * billable
    disc = Decimal(str(family["family_discount_pct"]))
    finalized = helpers.round_half_up(Decimal(gross) * (Decimal(1) - disc))
    return finalized


def compute_rental_surcharge(family_id, billing_period):
    """Sum period_fee_cents over ACTIVE rentals attributed to family + period.
    'attributed to this invoice's family+period': rental window intersects period
    and rental is ACTIVE (PRD §3.3/§3.8)."""
    start_ms, end_ms = billing_period_range_ms(billing_period)
    total = 0
    for r in db.instrument_rentals.values():
        if r["family_id"] != family_id:
            continue
        if r["status"] != "ACTIVE":
            continue
        r_start = helpers.parse_iso_ms(r["rental_start_utc"])
        r_end = helpers.parse_iso_ms(r["rental_end_utc"])
        # window intersects the billing period (closed-on-period start, open end)
        if r_start < end_ms and r_end >= start_ms:
            total += r["period_fee_cents"]
    return total


# ----------------------------------------------------------------------------
# Student practice (PRD §3.7)
# ----------------------------------------------------------------------------

def recompute_practice(student, studio):
    logs = [l for l in db.practice_logs.values() if l["student_id"] == student["id"]]
    # chronological replay: logged_utc ASC then created_at ASC
    logs.sort(key=lambda l: (helpers.parse_iso_ms(l["logged_utc"]), l["created_at"], l["_seq"]))
    total = sum(l["minutes"] for l in logs)
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    score = Decimal(0)
    for l in logs:
        logged_ms = helpers.parse_iso_ms(l["logged_utc"])
        age_days = (current_ms - logged_ms) // MS_PER_DAY
        if age_days < 0:
            age_days = 0  # future logs: floor of negative not specified; clamp not decaying
        weight = DECAY_BASE ** int(age_days)
        score += Decimal(l["minutes"]) * weight
    weighted = helpers.round_half_up_dp(score / Decimal(60), 2)
    student["total_practice_minutes"] = total
    student["weighted_progress_score"] = float(weighted)
    db.touch(student)


# ----------------------------------------------------------------------------
# Overlap tests (PRD §3.2 / §3.5 / §3.8, SCAFFOLD §1.3)
# ----------------------------------------------------------------------------

def recurring_overlap(a_start, a_end, b_start, b_end):
    """Half-open minute windows overlap (no buffer)."""
    return a_start < b_end and b_start < a_end


def instructor_recurring_conflict(studio_id, enrollment):
    """Another ACTIVE enrollment, same instructor, same weekday, half-open overlap, no buffer."""
    s = enrollment["start_min"]
    e = enrollment["start_min"] + enrollment["duration_min"]
    for other in db.enrollments.values():
        if other["id"] == enrollment["id"]:
            continue
        if other["studio_id"] != studio_id:
            continue
        if other["lifecycle_status"] != "ACTIVE":
            continue
        if other["instructor_id"] != enrollment["instructor_id"]:
            continue
        if other["weekday"] != enrollment["weekday"]:
            continue
        os = other["start_min"]
        oe = other["start_min"] + other["duration_min"]
        if recurring_overlap(s, e, os, oe):
            return True
    return False


def room_recurring_conflict(studio_id, enrollment, room):
    """Another ACTIVE enrollment, same room, same weekday, windows expanded by
    room.turnover_buffer_min before testing overlap (PRD §3.2)."""
    buf = room["turnover_buffer_min"]
    s = enrollment["start_min"]
    e = enrollment["start_min"] + enrollment["duration_min"] + buf
    for other in db.enrollments.values():
        if other["id"] == enrollment["id"]:
            continue
        if other["studio_id"] != studio_id:
            continue
        if other["lifecycle_status"] != "ACTIVE":
            continue
        if other["room_id"] != enrollment["room_id"]:
            continue
        if other["weekday"] != enrollment["weekday"]:
            continue
        os = other["start_min"]
        oe = other["start_min"] + other["duration_min"] + buf
        if recurring_overlap(s, e, os, oe):
            return True
    return False


def window_inside_availability(instructor, weekday, start_min, end_min):
    """Recurring weekly window must lie entirely inside one availability window."""
    for w in instructor["weekly_availability"]:
        if w["weekday"] == weekday and w["start_min"] <= start_min and end_min <= w["end_min"]:
            return True
    return False


def dated_occurrence_conflict(studio_id, new_start_ms, new_end_ms, instructor_id, room_id, exclude_occ_id=None):
    """A new dated occurrence collides with a non-cancelled occurrence on the same
    instructor or room when half-open UTC windows overlap (no buffer) (PRD §3.5)."""
    NONCANCELLED = {"SCHEDULED", "COMPLETED", "MAKEUP_PENDING"}
    for occ in db.lesson_occurrences.values():
        if exclude_occ_id is not None and occ["id"] == exclude_occ_id:
            continue
        if occ["status"] not in NONCANCELLED:
            continue
        # scope to studio via enrollment
        enr = db.enrollments.get(occ["enrollment_id"])
        if enr is None or enr["studio_id"] != studio_id:
            continue
        if occ["instructor_id"] != instructor_id and occ["room_id"] != room_id:
            continue
        o_start = helpers.parse_iso_ms(occ["scheduled_start_utc"])
        o_end = helpers.parse_iso_ms(occ["scheduled_end_utc"])
        if new_start_ms < o_end and o_start < new_end_ms:
            return True
    return False


def instrument_unit_conflict(studio_id, unit_code, new_start_ms, new_end_ms):
    """Closed-interval overlap on the physical unit (endpoints inclusive) (PRD §3.8)."""
    for r in db.instrument_rentals.values():
        if r["studio_id"] != studio_id:
            continue
        if r["instrument_unit_code"] != unit_code:
            continue
        if r["status"] not in ("RESERVED", "ACTIVE"):
            continue
        r_start = helpers.parse_iso_ms(r["rental_start_utc"])
        r_end = helpers.parse_iso_ms(r["rental_end_utc"])
        if new_start_ms <= r_end and new_end_ms >= r_start:
            return True
    return False


# ----------------------------------------------------------------------------
# Recital derived counts and performance order (PRD §3.9)
# ----------------------------------------------------------------------------

def recompute_event_counts(event):
    regs = [r for r in db.recital_registrations.values()
            if r["recital_event_id"] == event["id"]]
    event["confirmed_count"] = sum(1 for r in regs if r["status"] == "CONFIRMED")
    event["waitlist_count"] = sum(1 for r in regs if r["status"] == "WAITLISTED")
    db.touch(event)


def recompute_performance_order(event):
    """1-based slot among CONFIRMED registrations, ordered registered_utc ASC,
    created_at ASC (PRD §3.9)."""
    confirmed = [r for r in db.recital_registrations.values()
                 if r["recital_event_id"] == event["id"] and r["status"] == "CONFIRMED"]
    confirmed.sort(key=lambda r: (helpers.parse_iso_ms(r["registered_utc"]), r["created_at"], r["_seq"]))
    for i, r in enumerate(confirmed, start=1):
        if r["performance_order"] != i:
            r["performance_order"] = i
            db.touch(r)


def promote_waitlist(event):
    """Promote earliest WAITLISTED -> CONFIRMED while confirmed_count < capacity."""
    while event["confirmed_count"] < event["venue_capacity"]:
        waiting = [r for r in db.recital_registrations.values()
                   if r["recital_event_id"] == event["id"] and r["status"] == "WAITLISTED"]
        if not waiting:
            break
        waiting.sort(key=lambda r: (helpers.parse_iso_ms(r["registered_utc"]), r["created_at"], r["_seq"]))
        promote = waiting[0]
        promote["status"] = "CONFIRMED"
        db.touch(promote)
        recompute_event_counts(event)
    recompute_performance_order(event)
