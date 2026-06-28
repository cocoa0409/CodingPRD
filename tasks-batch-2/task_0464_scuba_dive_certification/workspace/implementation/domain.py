"""Domain logic: calculations, eligibility, cascades, conserved quantities,
datetime parsing, and serializers.

Every rule traces to a PRD sentence (Section 2 / 3) and the scaffold tables.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import errors

# ---------------------------------------------------------------------------
# Calculation constants (scaffold 1.3)
# ---------------------------------------------------------------------------
POOL_BASE_RATIO = 8
POOL_ASSISTANT_BONUS = 4
OW_BASE_RATIO = 4
OW_ASSISTANT_BONUS = 2

EL_WEIGHT = Decimal("0.2")
POOL_WEIGHT = Decimal("0.3")
OW_WEIGHT = Decimal("0.5")

AIR_BASE_CENTS = 1200
NITROX_SURCHARGE_LOW = 800
NITROX_SURCHARGE_MID = 1400
NITROX_SURCHARGE_HIGH = 2200
LARGE_TANK_THRESHOLD_L = 12
LARGE_TANK_FACTOR = Decimal("1.25")

GROUP_DISCOUNT_MIN_PARTY = 4
GROUP_DISCOUNT_PCT = Decimal("0.15")
DEPOSIT_PCT = Decimal("0.30")

LATE_MULTIPLIER = Decimal("1.5")

WAIVER_VALID_DAYS = 365
VIP_INTERVAL_DAYS = 365
HYDRO_INTERVAL_DAYS = 1825

CERT_RANK = {"NONE": 0, "OPEN_WATER": 1, "ADVANCED": 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to a whole integer, half-up (PRD 2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.
    Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise errors.invalid_request("Datetime must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("Malformed datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def billed_days(from_ts, to_ts):
    """Whole billed days, partial rounded up, floor 1 (PRD 2.6 / 3.8)."""
    seconds = (to_ts - from_ts).total_seconds()
    import math
    days = math.ceil(seconds / 86400.0)
    return max(1, days)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def instructor_ratio_capacity(session_type, assistant_count):
    if session_type == "POOL":
        return POOL_BASE_RATIO + POOL_ASSISTANT_BONUS * assistant_count
    return OW_BASE_RATIO + OW_ASSISTANT_BONUS * assistant_count


def enrollment_completion_pct(enrollment, course):
    req_pool = course["required_pool_sessions"]
    req_ow = course["required_open_water_sessions"]
    pool_att = enrollment["pool_sessions_attended"]
    ow_att = enrollment["open_water_sessions_attended"]

    if req_pool == 0:
        pool_frac = Decimal(1)
    else:
        pool_frac = min(Decimal(1), Decimal(pool_att) / Decimal(req_pool))
    if req_ow == 0:
        ow_frac = Decimal(1)
    else:
        ow_frac = min(Decimal(1), Decimal(ow_att) / Decimal(req_ow))

    raw = (EL_WEIGHT * Decimal(enrollment["elearning_pct"])
           + POOL_WEIGHT * (pool_frac * 100)
           + OW_WEIGHT * (ow_frac * 100))
    return round_half_up(raw)


def fill_price(gas, o2_pct, tank_capacity_liters):
    base = AIR_BASE_CENTS
    if gas == "AIR":
        subtotal = base
    else:  # NITROX
        if o2_pct <= 32:
            surcharge = NITROX_SURCHARGE_LOW
        elif o2_pct <= 36:
            surcharge = NITROX_SURCHARGE_MID
        else:
            surcharge = NITROX_SURCHARGE_HIGH
        subtotal = base + surcharge
    factor = LARGE_TANK_FACTOR if tank_capacity_liters > LARGE_TANK_THRESHOLD_L else Decimal(1)
    return round_half_up(Decimal(subtotal) * factor)


def trip_booking_total(trip, tanks, party_size):
    subtotal_cents = trip["base_fare_cents"] + tanks * trip["fill_addon_cents"]
    discount_pct = GROUP_DISCOUNT_PCT if party_size >= GROUP_DISCOUNT_MIN_PARTY else Decimal(0)
    total_cents = round_half_up(Decimal(subtotal_cents) * (Decimal(1) - discount_pct))
    deposit_cents = round_half_up(Decimal(total_cents) * DEPOSIT_PCT)
    balance_due_cents = total_cents - deposit_cents
    return total_cents, deposit_cents, balance_due_cents


def rental_estimated_cost(checkout_at, scheduled_return_at, daily_rate_cents):
    return billed_days(checkout_at, scheduled_return_at) * daily_rate_cents


def rental_actual_cost(checkout_at, scheduled_return_at, actual_return_at,
                       daily_rate_cents, damage_fee_cents):
    est_days = billed_days(checkout_at, scheduled_return_at)
    act_days = billed_days(checkout_at, actual_return_at)
    on_time_days = min(act_days, est_days)
    late_days = max(0, act_days - est_days)
    late_rate = round_half_up(Decimal(daily_rate_cents) * LATE_MULTIPLIER)
    return on_time_days * daily_rate_cents + late_days * late_rate + damage_fee_cents


def rental_settlement(actual_cost_cents, estimated_cost_cents, deposit_cents):
    balance_over_estimate = max(0, actual_cost_cents - estimated_cost_cents)
    return max(0, deposit_cents - balance_over_estimate)


def waiver_expiry(signed_at):
    return signed_at + timedelta(days=WAIVER_VALID_DAYS)


def gear_service_due(serviced_at, service_type):
    if service_type == "VIP":
        return serviced_at + timedelta(days=VIP_INTERVAL_DAYS)
    return serviced_at + timedelta(days=HYDRO_INTERVAL_DAYS)


# ---------------------------------------------------------------------------
# Waiver / medical status (PRD 2.8 / 3.1)
# ---------------------------------------------------------------------------
def latest_waiver(diver_id):
    """The diver's most recently signed waiver (by signed_at; _seq tiebreak)."""
    candidates = [w for w in db.waivers.values() if w["diver_id"] == diver_id]
    if not candidates:
        return None
    return max(candidates, key=lambda w: (w["_signed_at_dt"], w["_seq"]))


def has_active_waiver(diver_id):
    """Active = clock strictly before expires_at AND it is the latest waiver."""
    w = latest_waiver(diver_id)
    if w is None:
        return False
    return clock.get_now() < w["_expires_at_dt"]


def recompute_medical_status(diver):
    """Derived from the diver's latest *active* waiver (PRD 2.8)."""
    w = latest_waiver(diver["id"])
    if w is None or not (clock.get_now() < w["_expires_at_dt"]):
        diver["medical_status"] = "UNKNOWN"
    elif w["medical_flagged"]:
        diver["medical_status"] = "RESTRICTED"
    else:
        diver["medical_status"] = "CLEAR"


# ---------------------------------------------------------------------------
# Conserved quantities (PRD 2.5)
# ---------------------------------------------------------------------------
def recompute_diver_deposit(diver):
    """deposit_on_hold_cents = sum of deposit_cents over ACTIVE rentals."""
    total = sum(r["deposit_cents"] for r in db.rental_agreements.values()
                if r["diver_id"] == diver["id"] and r["status"] == "ACTIVE")
    diver["deposit_on_hold_cents"] = total
    db.touch(diver)


def recompute_session_seats(session):
    """confirmed_seats = count of BOOKED bookings on this session."""
    count = sum(1 for b in db.session_bookings.values()
                if b["session_id"] == session["id"] and b["status"] == "BOOKED")
    session["confirmed_seats"] = count


def recompute_instructor_active(instructor):
    count = sum(1 for s in db.sessions.values()
                if s["primary_instructor_id"] == instructor["id"] and s["status"] == "SCHEDULED")
    instructor["active_session_count"] = count
    db.touch(instructor)


def recompute_trip_divers(trip):
    count = sum(1 for tb in db.trip_bookings.values()
                if tb["trip_id"] == trip["id"] and tb["status"] == "CONFIRMED")
    trip["confirmed_divers"] = count


# ---------------------------------------------------------------------------
# Eligibility (PRD 3.3) — auto-evaluated bidirectionally
# ---------------------------------------------------------------------------
def eligibility_preconditions_hold(enrollment, course, diver):
    """All five eligibility conditions of PRD 3.3."""
    if enrollment["elearning_pct"] != 100:
        return False
    if enrollment["pool_sessions_attended"] < course["required_pool_sessions"]:
        return False
    if enrollment["open_water_sessions_attended"] < course["required_open_water_sessions"]:
        return False
    if not has_active_waiver(diver["id"]):
        return False
    if diver["medical_status"] != "CLEAR":
        return False
    return True


def recompute_enrollment(enrollment, raise_on_gate=False):
    """Recompute completion_pct and auto-advance/revert ACTIVE<->ELIGIBLE.

    raise_on_gate: when True (explicit recompute / eligibility evaluation entry
    point), a failing medical/waiver gate raises ERR_WAIVER_REQUIRED rather than
    silently advancing (PRD 3.3). For internal cascades we never raise.
    """
    course = db.courses[enrollment["course_id"]]
    diver = db.divers[enrollment["diver_id"]]
    enrollment["completion_pct"] = enrollment_completion_pct(enrollment, course)

    status = enrollment["status"]
    if status not in ("ACTIVE", "ELIGIBLE"):
        # terminal states (COMPLETED / WITHDRAWN) are untouched.
        db.touch(enrollment)
        return

    holds = eligibility_preconditions_hold(enrollment, course, diver)

    if status == "ACTIVE":
        if holds:
            enrollment["status"] = "ELIGIBLE"
        else:
            if raise_on_gate and _gate_specifically_fails(enrollment, course, diver):
                # Surface waiver gate failure on explicit evaluation only when the
                # *training* prerequisites are otherwise met (PRD 3.3 final sentence).
                raise errors.waiver_required()
    elif status == "ELIGIBLE":
        if not holds:
            enrollment["status"] = "ACTIVE"
    db.touch(enrollment)


def _gate_specifically_fails(enrollment, course, diver):
    """True if the *only* thing blocking eligibility is the medical/waiver gate
    (training tracks all satisfied). Used to decide whether explicit eligibility
    evaluation should raise ERR_WAIVER_REQUIRED (PRD 3.3)."""
    training_ok = (
        enrollment["elearning_pct"] == 100
        and enrollment["pool_sessions_attended"] >= course["required_pool_sessions"]
        and enrollment["open_water_sessions_attended"] >= course["required_open_water_sessions"]
    )
    if not training_ok:
        return False
    gate_fails = (not has_active_waiver(diver["id"])) or diver["medical_status"] == "RESTRICTED"
    return gate_fails


# ---------------------------------------------------------------------------
# Serializers — produce exactly the public field set per entity
# ---------------------------------------------------------------------------
def _common(obj):
    return {
        "id": obj["id"],
        "created_at": obj["created_at"],
        "updated_at": obj["updated_at"],
        "version": obj["version"],
    }


def ser_diver(d):
    out = _common(d)
    out.update({
        "full_name": d["full_name"],
        "email": d["email"],
        "cert_level": d["cert_level"],
        "nitrox_certified": d["nitrox_certified"],
        "medical_status": d["medical_status"],
        "deposit_on_hold_cents": d["deposit_on_hold_cents"],
    })
    return out


def ser_instructor(i):
    out = _common(i)
    out.update({
        "full_name": i["full_name"],
        "rating": i["rating"],
        "active_session_count": i["active_session_count"],
    })
    return out


def ser_course(c):
    out = _common(c)
    out.update({
        "title": c["title"],
        "course_type": c["course_type"],
        "required_pool_sessions": c["required_pool_sessions"],
        "required_open_water_sessions": c["required_open_water_sessions"],
        "price_cents": c["price_cents"],
        "grants_specialty": c["grants_specialty"],
    })
    return out


def ser_enrollment(e):
    out = _common(e)
    out.update({
        "diver_id": e["diver_id"],
        "course_id": e["course_id"],
        "status": e["status"],
        "elearning_pct": e["elearning_pct"],
        "pool_sessions_attended": e["pool_sessions_attended"],
        "open_water_sessions_attended": e["open_water_sessions_attended"],
        "completion_pct": e["completion_pct"],
        "certification_card_id": e["certification_card_id"],
    })
    return out


def ser_session(s):
    out = _common(s)
    out.update({
        "course_id": s["course_id"],
        "session_type": s["session_type"],
        "primary_instructor_id": s["primary_instructor_id"],
        "assistant_count": s["assistant_count"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "max_students": s["max_students"],
        "confirmed_seats": s["confirmed_seats"],
        "status": s["status"],
    })
    return out


def ser_session_booking(b):
    out = _common(b)
    out.update({
        "session_id": b["session_id"],
        "enrollment_id": b["enrollment_id"],
        "status": b["status"],
    })
    return out


def ser_certification_card(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "diver_id": c["diver_id"],
        "enrollment_id": c["enrollment_id"],
        "level": c["level"],
        "specialty": c["specialty"],
        "issued_at": c["issued_at"],
    }


def ser_waiver(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "diver_id": w["diver_id"],
        "medical_flagged": w["medical_flagged"],
        "signed_at": w["signed_at"],
        "expires_at": w["expires_at"],
    }


def ser_boat(b):
    out = _common(b)
    out.update({
        "name": b["name"],
        "capacity": b["capacity"],
        "turnaround_minutes": b["turnaround_minutes"],
    })
    return out


def ser_dive_trip(t):
    out = _common(t)
    out.update({
        "boat_id": t["boat_id"],
        "starts_at": t["starts_at"],
        "ends_at": t["ends_at"],
        "min_cert_level": t["min_cert_level"],
        "base_fare_cents": t["base_fare_cents"],
        "fill_addon_cents": t["fill_addon_cents"],
        "confirmed_divers": t["confirmed_divers"],
        "status": t["status"],
    })
    return out


def ser_trip_booking(tb):
    out = _common(tb)
    out.update({
        "trip_id": tb["trip_id"],
        "diver_id": tb["diver_id"],
        "tanks": tb["tanks"],
        "party_size": tb["party_size"],
        "total_cents": tb["total_cents"],
        "deposit_cents": tb["deposit_cents"],
        "balance_due_cents": tb["balance_due_cents"],
        "status": tb["status"],
    })
    return out


def ser_rental(r):
    out = _common(r)
    out.update({
        "diver_id": r["diver_id"],
        "item_description": r["item_description"],
        "daily_rate_cents": r["daily_rate_cents"],
        "deposit_cents": r["deposit_cents"],
        "checkout_at": r["checkout_at"],
        "scheduled_return_at": r["scheduled_return_at"],
        "actual_return_at": r["actual_return_at"],
        "damage_fee_cents": r["damage_fee_cents"],
        "estimated_cost_cents": r["estimated_cost_cents"],
        "actual_cost_cents": r["actual_cost_cents"],
        "deposit_refund_cents": r["deposit_refund_cents"],
        "status": r["status"],
    })
    return out


def ser_fill(f):
    out = _common(f)
    out.update({
        "diver_id": f["diver_id"],
        "gas": f["gas"],
        "o2_pct": f["o2_pct"],
        "tank_capacity_liters": f["tank_capacity_liters"],
        "price_cents": f["price_cents"],
    })
    return out


def ser_gear_order(g):
    out = _common(g)
    out.update({
        "diver_id": g["diver_id"],
        "service_type": g["service_type"],
        "serviced_at": g["serviced_at"],
        "next_due_at": g["next_due_at"],
        "status": g["status"],
    })
    return out
