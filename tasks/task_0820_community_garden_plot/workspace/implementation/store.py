"""In-memory data store, logical clock, constants, calculations and serializers.

Storage is process-local Python dicts only. Nothing is seeded at import time;
every entity is created through the declared API surface.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import uuid

# ---------------------------------------------------------------------------
# In-memory tables (all keyed by id)
# ---------------------------------------------------------------------------
gardens = {}
plots = {}
gardeners = {}
applications = {}
assignments = {}
work_logs = {}
water_readings = {}
compliance_cases = {}
tools = {}
tool_loans = {}
shed_bookings = {}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Id / time helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Calculation constants
# ---------------------------------------------------------------------------
BASE_FEE_CENTS = {"SMALL": 3000, "MEDIUM": 5000, "LARGE": 8000}
WATER_DEPOSIT_CENTS = {"SMALL": 500, "MEDIUM": 1000, "LARGE": 1500}
REQUIRED_WORK_HOURS = {"SMALL": 8, "MEDIUM": 12, "LARGE": 16}
WORK_SHORTFALL_PENALTY_CENTS_PER_HOUR = 1500
WATER_FREE_GALLONS_PER_PERIOD = {"SMALL": 100, "MEDIUM": 200, "LARGE": 350}
WATER_RATE_CENTS_PER_GALLON = Decimal("3.5")
SEASON_PERIODS = 3
TOOL_LATE_FINE_CENTS_PER_HOUR = 200
PRIORITY_TENURE_WEIGHT = 10
PRIORITY_STANDING_BONUS = {"GOOD": 5, "PROBATION": 0, "SUSPENDED": -100}
PRIORITY_STRIKE_WEIGHT = 3
CURE_GRACE_DAYS = 14

SIZES = {"SMALL", "MEDIUM", "LARGE"}


def _rhu(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def provisional_fee_cents(size):
    return BASE_FEE_CENTS[size] + WATER_DEPOSIT_CENTS[size]


def water_overage_charge_cents(assignment):
    size = assignment["size"]
    free = WATER_FREE_GALLONS_PER_PERIOD[size]
    total = 0
    for p in range(1, SEASON_PERIODS + 1):
        reading = _reading_for(assignment["id"], p)
        gallons = reading["gallons_used"] if reading else 0
        overage = Decimal(str(gallons)) - Decimal(free)
        if overage < 0:
            overage = Decimal(0)
        charge = (overage * WATER_RATE_CENTS_PER_GALLON).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        total += int(charge)
    return total


def _reading_for(assignment_id, period_index):
    for r in water_readings.values():
        if r["assignment_id"] == assignment_id and r["period_index"] == period_index:
            return r
    return None


def final_fee_cents(assignment):
    size = assignment["size"]
    base = BASE_FEE_CENTS[size]
    deposit = WATER_DEPOSIT_CENTS[size]
    water_overage = water_overage_charge_cents(assignment)
    shortfall = REQUIRED_WORK_HOURS[size] - assignment["logged_work_hours"]
    if shortfall < 0:
        shortfall = 0
    work_penalty = _rhu(Decimal(str(shortfall)) * Decimal(WORK_SHORTFALL_PENALTY_CENTS_PER_HOUR))
    final = base + water_overage + work_penalty - deposit
    if final < 0:
        final = 0
    return final


def priority_score(gardener):
    return (
        gardener["tenure_seasons"] * PRIORITY_TENURE_WEIGHT
        + PRIORITY_STANDING_BONUS[gardener["standing"]]
        - gardener["strike_count"] * PRIORITY_STRIKE_WEIGHT
    )


def tool_late_fine_cents(returned_at, due_at):
    if returned_at <= due_at:
        return 0
    delta = returned_at - due_at
    seconds = delta.total_seconds()
    hours_late = int(seconds // 3600)
    if seconds % 3600 > 0:
        hours_late += 1
    return hours_late * TOOL_LATE_FINE_CENTS_PER_HOUR


def standing_for(strike_count):
    if strike_count <= 0:
        return "GOOD"
    if strike_count <= 2:
        return "PROBATION"
    return "SUSPENDED"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _garden_counts(garden_id):
    rows = [p for p in plots.values() if p["garden_id"] == garden_id]
    total = len(rows)
    available = len([p for p in rows if p["status"] == "AVAILABLE"])
    return total, available


def ser_garden(g):
    total, available = _garden_counts(g["id"])
    return {
        "id": g["id"],
        "name": g["name"],
        "season_label": g["season_label"],
        "season_start": iso(g["season_start"]),
        "season_end": iso(g["season_end"]),
        "offer_window_days": g["offer_window_days"],
        "total_plots": total,
        "available_plot_count": available,
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }


def ser_plot(p):
    return {
        "id": p["id"],
        "garden_id": p["garden_id"],
        "label": p["label"],
        "size": p["size"],
        "status": p["status"],
        "current_assignment_id": p["current_assignment_id"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_gardener(g):
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "email": g["email"],
        "tenure_seasons": g["tenure_seasons"],
        "standing": g["standing"],
        "strike_count": g["strike_count"],
        "balance_owed_cents": g["balance_owed_cents"],
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }


def ser_application(a):
    return {
        "id": a["id"],
        "gardener_id": a["gardener_id"],
        "garden_id": a["garden_id"],
        "requested_size": a["requested_size"],
        "status": a["status"],
        "priority_score_at_submission": a["priority_score_at_submission"],
        "offered_plot_id": a["offered_plot_id"],
        "offer_expires_at": iso(a["offer_expires_at"]),
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "plot_id": a["plot_id"],
        "gardener_id": a["gardener_id"],
        "garden_id": a["garden_id"],
        "application_id": a["application_id"],
        "renewed_from_assignment_id": a["renewed_from_assignment_id"],
        "season_start": iso(a["season_start"]),
        "season_end": iso(a["season_end"]),
        "size": a["size"],
        "occupancy_status": a["occupancy_status"],
        "fee_status": a["fee_status"],
        "provisional_fee_cents": a["provisional_fee_cents"],
        "final_fee_cents": a["final_fee_cents"],
        "required_work_hours": a["required_work_hours"],
        "logged_work_hours": a["logged_work_hours"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_work_log(w):
    return {
        "id": w["id"],
        "assignment_id": w["assignment_id"],
        "hours": w["hours"],
        "logged_on": iso(w["logged_on"]),
        "note": w["note"],
        "created_at": iso(w["created_at"]),
    }


def ser_water_reading(r):
    return {
        "id": r["id"],
        "assignment_id": r["assignment_id"],
        "period_index": r["period_index"],
        "gallons_used": r["gallons_used"],
        "recorded_on": iso(r["recorded_on"]),
        "created_at": iso(r["created_at"]),
    }


def ser_compliance_case(c):
    return {
        "id": c["id"],
        "assignment_id": c["assignment_id"],
        "gardener_id": c["gardener_id"],
        "violation_type": c["violation_type"],
        "status": c["status"],
        "cure_deadline": iso(c["cure_deadline"]),
        "opened_on": iso(c["opened_on"]),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_tool(t):
    return {
        "id": t["id"],
        "garden_id": t["garden_id"],
        "name": t["name"],
        "category": t["category"],
        "cleaning_buffer_hours": t["cleaning_buffer_hours"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_tool_loan(l):
    return {
        "id": l["id"],
        "tool_id": l["tool_id"],
        "gardener_id": l["gardener_id"],
        "checked_out_at": iso(l["checked_out_at"]),
        "due_at": iso(l["due_at"]),
        "returned_at": iso(l["returned_at"]),
        "status": l["status"],
        "late_fine_cents": l["late_fine_cents"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
    }


def ser_shed_booking(b):
    return {
        "id": b["id"],
        "garden_id": b["garden_id"],
        "gardener_id": b["gardener_id"],
        "starts_at": iso(b["starts_at"]),
        "ends_at": iso(b["ends_at"]),
        "purpose": b["purpose"],
        "created_at": iso(b["created_at"]),
    }
