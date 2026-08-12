"""Calculation rules (PRD §3.5-§3.7): weekly minutes, charter pricing,
shortage credit, fuel escalation, invoice totals, SLA, on-time metrics."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import db

SOFT_CAP_MINUTES = 2400
HARD_CAP_MINUTES = 2700
MAX_DOUBLING_DELAY_MINUTES = 45
ON_TIME_GRACE_MINUTES = 5
FREE_CANCEL_HOURS = 72
REDUCED_CANCEL_HOURS = 24
REQUIRED_BEHIND_WHEEL_MINUTES = 2400
REQUIRED_CLASSROOM_MINUTES = 1200


def _round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) to integer cents via Decimal."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


# --- driver weekly minutes --------------------------------------------------

def driver_week_minutes(driver_id, week_monday, week_sunday, extra=0):
    """Sum of planned minutes of the driver's CONFIRMED/EN_ROUTE/COMPLETED
    assignments whose service date falls in the ISO week, plus `extra`."""
    total = extra
    for a in db.all_of("assignments"):
        if a.get("driver_id") != driver_id:
            continue
        if a["status"] not in ("CONFIRMED", "EN_ROUTE", "COMPLETED"):
            continue
        day = db.day_of_assignment(a)
        if day is None:
            continue
        d = db.parse_date(day["service_date"])
        if d is None or d < week_monday or d > week_sunday:
            continue
        total += a["planned_end_minute"] - a["planned_start_minute"]
    return total


def weekly_assigned_minutes_current(driver_id):
    """Driver.weekly_assigned_minutes: ISO week containing the clock date."""
    monday, sunday = db.week_bounds(db.clock_date())
    return driver_week_minutes(driver_id, monday, sunday)


# --- overlap helpers ---------------------------------------------------------
# Half-open intervals [start, end): intersect iff s1 < e2 and s2 < e1.

def half_open_intersects(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def closed_buffered_intersects_half_open(buf_lo, buf_hi, s, e):
    """Closed [buf_lo, buf_hi] vs half-open [s, e)."""
    return buf_lo < e and s <= buf_hi


def driver_assignment_conflicts(driver_id, date_str, start, end, exclude_ids=()):
    for a in db.all_of("assignments"):
        if a.get("driver_id") != driver_id or a["id"] in exclude_ids:
            continue
        if a["status"] not in ("CONFIRMED", "EN_ROUTE"):
            continue
        day = db.day_of_assignment(a)
        if day is None or day["service_date"] != date_str:
            continue
        if half_open_intersects(
            a["planned_start_minute"], a["planned_end_minute"], start, end
        ):
            return True
    # scheduled charters on the same date occupy the driver too
    for t in db.all_of("charter_trips"):
        if t.get("assigned_driver_id") != driver_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if t["trip_date"] != date_str:
            continue
        buf_lo = t["pickup_minute"] - 30
        buf_hi = t["return_minute"] + 30
        if closed_buffered_intersects_half_open(buf_lo, buf_hi, start, end):
            return True
    return False


def bus_assignment_conflicts(bus_id, date_str, start, end, exclude_ids=()):
    for a in db.all_of("assignments"):
        if a.get("bus_id") != bus_id or a["id"] in exclude_ids:
            continue
        if a["status"] not in ("CONFIRMED", "EN_ROUTE"):
            continue
        day = db.day_of_assignment(a)
        if day is None or day["service_date"] != date_str:
            continue
        if half_open_intersects(
            a["planned_start_minute"], a["planned_end_minute"], start, end
        ):
            return True
    # scheduled charters occupy the bus with a closed +/-30m buffered window
    for t in db.all_of("charter_trips"):
        if t.get("assigned_bus_id") != bus_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if t["trip_date"] != date_str:
            continue
        buf_lo = t["pickup_minute"] - 30
        buf_hi = t["return_minute"] + 30
        if closed_buffered_intersects_half_open(buf_lo, buf_hi, start, end):
            return True
    return False


def charter_bus_conflict(bus_id, date_str, pickup, return_minute, exclude_trip_id=None):
    """Charter buffered window [pickup-30, return+30] (closed) vs other
    SCHEDULED/IN_PROGRESS charters' buffered windows on same bus+date."""
    lo = pickup - 30
    hi = return_minute + 30
    for t in db.all_of("charter_trips"):
        if t.get("assigned_bus_id") != bus_id:
            continue
        if t["id"] == exclude_trip_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if t["trip_date"] != date_str:
            continue
        other_lo = t["pickup_minute"] - 30
        other_hi = t["return_minute"] + 30
        # closed vs closed intersection
        if lo <= other_hi and other_lo <= hi:
            return True
    return False


def driver_charter_conflicts(driver_id, date_str, pickup, return_minute):
    """Driver overlap for charter schedule: CONFIRMED route assignments whose
    half-open planned interval intersects the charter's planned interval."""
    for a in db.all_of("assignments"):
        if a.get("driver_id") != driver_id:
            continue
        if a["status"] not in ("CONFIRMED", "EN_ROUTE"):
            continue
        day = db.day_of_assignment(a)
        if day is None or day["service_date"] != date_str:
            continue
        if half_open_intersects(
            a["planned_start_minute"], a["planned_end_minute"], pickup, return_minute
        ):
            return True
    return False


def bus_assignment_conflicts_for_charter(bus_id, date_str, pickup, return_minute):
    """Charter schedule: CONFIRMED route assignments whose [planned_start,
    planned_end) intersects the charter's closed buffered window."""
    lo = pickup - 30
    hi = return_minute + 30
    for a in db.all_of("assignments"):
        if a.get("bus_id") != bus_id:
            continue
        if a["status"] not in ("CONFIRMED", "EN_ROUTE"):
            continue
        day = db.day_of_assignment(a)
        if day is None or day["service_date"] != date_str:
            continue
        if closed_buffered_intersects_half_open(
            lo, hi, a["planned_start_minute"], a["planned_end_minute"]
        ):
            return True
    return False


# --- charter pricing ----------------------------------------------------------

def charter_quote_price(contract, estimated_hours_x10, estimated_miles):
    hourly = contract["charter_hourly_rate_cents"]
    per_mile = contract["charter_per_mile_cents"]
    return (estimated_hours_x10 * hourly) // 10 + estimated_miles * per_mile


def charter_final_price(contract, estimated_hours_x10, actual_hours_x10, actual_miles):
    hourly = contract["charter_hourly_rate_cents"]
    per_mile = contract["charter_per_mile_cents"]
    base = (actual_hours_x10 * hourly) // 10 + actual_miles * per_mile
    overage_hours_x10 = max(0, actual_hours_x10 - estimated_hours_x10)
    overage = (overage_hours_x10 * hourly * 125) // 1000
    return base + overage


def charter_cancel_fee(trip, quote_price_cents):
    """Tiered cancellation fee from whole hours between clock now and pickup."""
    trip_date = db.parse_date(trip["trip_date"])
    pickup_dt = datetime.combine(
        trip_date, time(0, 0), tzinfo=timezone.utc
    ) + timedelta(minutes=trip["pickup_minute"])
    delta_seconds = (pickup_dt - db.clock_now()).total_seconds()
    hours_before = int(
        (Decimal(str(delta_seconds)) / Decimal(3600)).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    if hours_before >= FREE_CANCEL_HOURS:
        return 0
    if hours_before >= REDUCED_CANCEL_HOURS:
        return _round_half_up_cents(quote_price_cents * 25, 100)
    return _round_half_up_cents(quote_price_cents * 50, 100)


# --- shortage credit -----------------------------------------------------------

def shortage_credit(contract, day):
    """Computed at reconcile from the final billable accounting."""
    assignments = db.assignments_of_day(day["id"])
    if contract["penalty_mode"] == "FLAT_PER_ROUTE":
        return day["uncovered_routes"] * contract["shortage_penalty_flat_cents"]
    # PER_STUDENT_MINUTE
    total = 0
    for a in assignments:
        if a["billable"]:
            continue
        if a["status"] not in ("PLANNED", "CONFIRMED", "NO_SHOW"):
            continue
        route = db.route_of_assignment(a)
        if route is None:
            continue
        total += (
            route["student_count"]
            * contract["assumed_minutes_per_missed_route"]
            * contract["shortage_penalty_per_student_minute_cents"]
        )
    return total


# --- fuel escalation -----------------------------------------------------------

def fuel_day_gallons_x1000(day):
    """Milli-gallons for a service day: COMPLETED assignments on the day plus
    COMPLETED charters with trip_date == service_date."""
    total = 0
    for a in db.assignments_of_day(day["id"]):
        if a["status"] != "COMPLETED":
            continue
        bus = db.find("buses", a.get("bus_id"))
        if bus is None or not bus.get("mpg_x10"):
            continue
        miles = a.get("actual_miles") or 0
        total += (miles * 10000) // bus["mpg_x10"]
    contract_id = day["contract_id"]
    for t in db.all_of("charter_trips"):
        if t["contract_id"] != contract_id:
            continue
        if t["status"] != "COMPLETED":
            continue
        if t["trip_date"] != day["service_date"]:
            continue
        bus = db.find("buses", t.get("assigned_bus_id"))
        if bus is None or not bus.get("mpg_x10"):
            continue
        miles = t.get("actual_miles") or 0
        total += (miles * 10000) // bus["mpg_x10"]
    return total


def fuel_adjustment_per_gallon_cents(contract, avg_price):
    """Tiered per-gallon escalation rate; 0 when the trigger is not met."""
    base = contract["fuel_base_price_cents"]
    trigger_pct = contract["fuel_escalation_trigger_pct"]
    share_pct = contract["fuel_escalation_share_pct"]
    if avg_price * 100 < base * (100 + trigger_pct):
        return 0
    excess = avg_price - base
    tier1_width = (base * 10) // 100  # floor of 10% of base
    tier1_excess = min(excess, tier1_width)
    tier2_excess = excess - tier1_excess
    tier1_rate = _round_half_up_cents(tier1_excess * share_pct, 100)
    share2 = min(Decimal(100), Decimal(share_pct) * Decimal(3) / Decimal(2))
    tier2_rate = int(
        (Decimal(tier2_excess) * share2 / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return tier1_rate + tier2_rate


def raw_fuel_adjustment(contract, period_month, day_statuses):
    """Sum of per-day rounded fuel adjustments over the input set of days."""
    entry = fuel_entry_for(contract["district_id"], period_month)
    if entry is None:
        return 0
    adj_per_gallon = fuel_adjustment_per_gallon_cents(
        contract, entry["avg_price_cents_per_gallon"]
    )
    if adj_per_gallon == 0:
        return 0
    total = 0
    for day in db.all_of("service_days"):
        if day["contract_id"] != contract["id"]:
            continue
        if day["service_date"][:7] != period_month:
            continue
        if day["status"] not in day_statuses:
            continue
        gallons_x1000 = fuel_day_gallons_x1000(day)
        total += _round_half_up_cents(gallons_x1000 * adj_per_gallon, 1000)
    return total


def fuel_entry_for(district_id, period_month):
    for e in db.all_of("fuel_entries"):
        if e["district_id"] == district_id and e["effective_month"] == period_month:
            return e
    return None


# --- invoices ------------------------------------------------------------------

def _period_days(contract, period_month, statuses):
    return [
        d
        for d in db.all_of("service_days")
        if d["contract_id"] == contract["id"]
        and d["service_date"][:7] == period_month
        and d["status"] in statuses
    ]


def _period_charters_completed(contract, period_month):
    return [
        t
        for t in db.all_of("charter_trips")
        if t["contract_id"] == contract["id"]
        and t["trip_date"][:7] == period_month
        and t["status"] == "COMPLETED"
    ]


def compute_invoice_lines(contract, period_month, variant):
    """variant: 'PROVISIONAL' (draft) or 'FINAL' (issue).

    Returns dict with bus_lines_cents, charter_lines_cents,
    shortage_credit_cents, fuel_adjustment_cents, total_cents."""
    if variant == "PROVISIONAL":
        day_statuses = ("RECONCILED", "INVOICED", "LOCKED")
    else:
        day_statuses = ("RECONCILED",)

    bus_lines = 0
    for day in _period_days(contract, period_month, day_statuses):
        if day["status"] in ("RECONCILED", "INVOICED"):
            billable = sum(
                1 for a in db.assignments_of_day(day["id"]) if a.get("billable")
            )
            bus_lines += billable * contract["daily_rate_per_bus_cents"]
        elif day["status"] == "LOCKED":
            bus_lines += day["required_routes"] * contract["daily_rate_per_bus_cents"]

    charter_lines = sum(
        t.get("final_price_cents") or 0
        for t in _period_charters_completed(contract, period_month)
    )

    shortage = sum(
        d.get("shortage_credit_cents") or 0
        for d in _period_days(contract, period_month, ("RECONCILED",))
    )

    # Fuel input set is identical for both variants: RECONCILED days only.
    fuel_raw = raw_fuel_adjustment(contract, period_month, ("RECONCILED",))

    preliminary = bus_lines + charter_lines - shortage
    if preliminary + fuel_raw > contract["monthly_cap_cents"]:
        fuel_adj = max(0, contract["monthly_cap_cents"] - preliminary)
    else:
        fuel_adj = fuel_raw
    total = preliminary + fuel_adj
    # The invoice total may never exceed the monthly cap, even when the
    # preliminary total alone already exceeds it (fuel truncates to zero and
    # the cap then binds the total itself).
    if total > contract["monthly_cap_cents"]:
        total = contract["monthly_cap_cents"]
    return {
        "bus_lines_cents": bus_lines,
        "charter_lines_cents": charter_lines,
        "shortage_credit_cents": shortage,
        "fuel_adjustment_cents": fuel_adj,
        "total_cents": total,
    }


def district_outstanding_balance(district_id):
    """Sum of total_cents over ISSUED invoices across the district's contracts."""
    total = 0
    for inv in db.all_of("invoices"):
        if inv["status"] != "ISSUED":
            continue
        contract = db.find("contracts", inv["contract_id"])
        if contract is not None and contract["district_id"] == district_id:
            total += inv["total_cents"]
    return total


# --- incident SLA ---------------------------------------------------------------

def sla_window_hours(severity):
    if severity == "CRITICAL":
        return 24
    if severity == "HIGH":
        return 72
    return 168
