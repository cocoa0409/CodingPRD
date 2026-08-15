"""Business logic: calculations (§1.3), cascades, derived fields, gating."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_record, bump
from errors import err

# ---- Constants (SCAFFOLD §1.3) ---------------------------------------------
SPECTATOR_FT_PER_SHELL_INCH = 70
DRIFT_THRESHOLD_MPH = Decimal("8")
DRIFT_FACTOR_PER_MPH = Decimal("0.05")
DRIFT_FACTOR_CAP = Decimal("1.5")
STANDBY_BASE_FEE_CENTS = 25000
STANDBY_HOURLY_RATE_CENTS = 14500
ENGINE_SURCHARGE_CENTS = 30000
GUARD_SPACING_FT = 100
DUD_HALT_MIN = 2
DUD_RATE_LIMIT = Decimal("0.05")
WEATHER_VALIDITY_MIN = 30
GO_NO_GO_WINDOW_MIN = 60
WIND_SUSTAINED_LIMIT_MPH = Decimal("20")
WIND_GUST_LIMIT_MPH = Decimal("25")
SOAK_MINUTES = 15
VENUE_BUFFER_MIN = 120

EVENT_TERMINAL = {"CLOSED", "DENIED", "CANCELLED"}
EVENT_CANCELLABLE = {"DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED",
                     "STANDBY_CONFIRMED", "READY"}
# Event states in which the permit has been approved (product may move).
EVENT_PERMIT_APPROVED = {"APPROVED", "STANDBY_CONFIRMED", "READY", "IN_PROGRESS",
                         "SHOW_COMPLETE", "SWEEP_VERIFIED", "CLOSED"}


# ---- Entity lookups ----------------------------------------------------------

def event_of(record):
    return store.displays.get(record["display_event_id"])


def magazine_of_batch(batch):
    return store.magazines.get(batch["magazine_id"])


def operator_of_batch(batch):
    mag = magazine_of_batch(batch)
    return mag["operator_id"] if mag else None


def current_site_plan(ev):
    plans = [p for p in store.site_plans.values()
             if p["display_event_id"] == ev["id"] and p["status"] == "CURRENT"]
    return plans[-1] if plans else None


def approved_application(ev):
    apps = [a for a in store.permit_applications.values()
            if a["display_event_id"] == ev["id"] and a["status"] == "APPROVED"]
    if not apps:
        return None
    return sorted(apps, key=lambda a: a["_seq"])[-1]


# ---- Derived fields ----------------------------------------------------------

def magazine_posture(mag):
    """ACTIVE while clock <= inspection_due_at; LAPSED the instant it passes."""
    return "ACTIVE" if store.clock <= mag["inspection_due_at"] else "LAPSED"


def recompute_magazine_mass(mag):
    """c_magazine_mass: sum(qty_at_magazine x new_per_unit_lbs) over ALL batches
    of the magazine (QUARANTINED stock still occupies it), 2dp round-half-up."""
    total = Decimal("0")
    for b in store.batches.values():
        if b["magazine_id"] == mag["id"]:
            total += Decimal(b["qty_at_magazine"]) * b["new_per_unit_lbs"]
    mag["current_new_lbs"] = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recompute_batch_status(batch):
    if batch["status"] == "QUARANTINED":
        return
    batch["quantity_remaining"] = batch["quantity_units"] - batch["qty_expended"]
    if batch["quantity_remaining"] == 0:
        batch["status"] = "DEPLETED"
    elif batch["qty_at_show"] > 0:
        batch["status"] = "CHECKED_OUT"
    else:
        batch["status"] = "IN_MAGAZINE"


def event_movement_sums(event_id):
    co = re = ex = 0
    for mv in store.movements.values():
        if mv["display_event_id"] != event_id:
            continue
        if mv["movement_type"] == "CHECK_OUT":
            co += mv["quantity"]
        elif mv["movement_type"] == "RETURN":
            re += mv["quantity"]
        else:
            ex += mv["quantity"]
    return co, re, ex


def batches_at_show(event_id):
    return [b for b in store.batches.values() if b["_at_show"].get(event_id, 0) > 0]


# ---- Calculations ------------------------------------------------------------

def rsd_for_diameter(diameter_in):
    """c_fallout_base: 70 ft per shell inch, round-half-up to integer feet."""
    return int((Decimal(SPECTATOR_FT_PER_SHELL_INCH) * diameter_in).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def angular_delta(a_deg, b_deg):
    diff = abs(a_deg - b_deg) % 360
    return min(diff, 360 - diff)


def wind_adjusted_radius(base_ft, reading, spectator_arc_center_deg):
    """c_wind_adjusted_fallout (no intermediate rounding of the factor)."""
    wind = reading["wind_speed_mph"]
    if wind < DRIFT_THRESHOLD_MPH:
        return base_ft
    downwind = (reading["wind_direction_deg"] + 180) % 360
    delta = angular_delta(spectator_arc_center_deg, downwind)
    factor = min(Decimal("1") + (wind - DRIFT_THRESHOLD_MPH) * DRIFT_FACTOR_PER_MPH,
                 DRIFT_FACTOR_CAP)
    base = Decimal(base_ft)
    if delta <= 45:
        adjusted = base * factor
    elif delta <= 135:
        adjusted = base * (Decimal("1") + (factor - Decimal("1")) / 2)
    else:
        adjusted = base
    return int(adjusted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def planned_hours(ev):
    secs = (ev["scheduled_end_at"] - ev["scheduled_start_at"]).total_seconds()
    return math.ceil(secs / 3600)


def provisional_fee_cents(ev, standby_engines):
    """c_standby_fee provisional: ceil-hour estimate on the scheduled window."""
    return (STANDBY_BASE_FEE_CENTS
            + planned_hours(ev) * STANDBY_HOURLY_RATE_CENTS
            + standby_engines * ENGINE_SURCHARGE_CENTS)


def final_fee_cents(ev):
    """c_standby_fee final: minute-prorated actuals, hours line rounded half-up
    to whole cents, then integer line items summed. (Rounding elapsed time up
    to whole hours before multiplying is expressly forbidden.)"""
    app = approved_application(ev)
    engines = app["standby_engines"] if app else 0
    confirmed = ev["standby_confirmed_at"] or ev["closed_at"]
    secs = (ev["closed_at"] - confirmed).total_seconds()
    elapsed_minutes = math.ceil(secs / 60)
    hours_line = (Decimal(elapsed_minutes) * STANDBY_HOURLY_RATE_CENTS / 60).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return STANDBY_BASE_FEE_CENTS + int(hours_line) + engines * ENGINE_SURCHARGE_CENTS


def required_guards(radius_ft, arc_degrees):
    """c_required_guards: arc length unrounded until the division."""
    arc_length = 2 * math.pi * radius_ft * (arc_degrees / 360)
    return max(1, math.ceil(arc_length / GUARD_SPACING_FT))


# ---- Cascades ----------------------------------------------------------------

def _release_posts(ev):
    for p in store.security_posts.values():
        if p["display_event_id"] == ev["id"] and p["status"] in (
                "UNSTAFFED", "STAFFED", "SECURED"):
            p["status"] = "RELEASED"
            bump(p)


def _withdraw_applications(ev):
    for a in store.permit_applications.values():
        if a["display_event_id"] == ev["id"] and a["status"] in (
                "SUBMITTED", "INFO_REQUESTED"):
            a["status"] = "WITHDRAWN"
            bump(a)


def _auto_return_batch(batch, ev):
    """Write an auto-generated RETURN for this batch's remaining on-site qty."""
    q = batch["_at_show"].get(ev["id"], 0)
    if q <= 0:
        return
    mv = new_record(with_version=False)
    mv.update({
        "product_batch_id": batch["id"],
        "display_event_id": ev["id"],
        "movement_type": "RETURN",
        "quantity": q,
        "driver_name": None,
        "vehicle_placard": None,
        "cdl_hazmat_endorsed": None,
        "auto_generated": True,
        "recorded_by_user_id": "system",
    })
    store.movements[mv["id"]] = mv
    batch["_at_show"][ev["id"]] = batch["_at_show"].get(ev["id"], 0) - q
    batch["qty_at_show"] -= q
    batch["qty_at_magazine"] += q
    recompute_batch_status(batch)
    bump(batch)
    mag = magazine_of_batch(batch)
    if mag:
        recompute_magazine_mass(mag)
        bump(mag)


def cancel_event(ev, cancellation_reason):
    """The §3.7 cancellation cascade — identical for manual cancel, weather
    NO_GO, and operator suspension."""
    ev["status"] = "CANCELLED"
    ev["cancellation_reason"] = cancellation_reason
    if cancellation_reason == "WEATHER_NO_GO":
        ev["weather_decision"] = "NO_GO"
    _release_posts(ev)
    _withdraw_applications(ev)
    for batch in list(store.batches.values()):
        _auto_return_batch(batch, ev)
    bump(ev)


def evaluate_auto_close(ev):
    """SWEEP_VERIFIED -> CLOSED when no FILED incident remains and net
    checked-out product (CHECK_OUT - RETURN - EXPEND) is exactly zero.
    Evaluated after every sweep verify, incident close, and RETURN movement."""
    if ev["status"] != "SWEEP_VERIFIED":
        return
    if any(i["display_event_id"] == ev["id"] and i["status"] == "FILED"
           for i in store.incidents.values()):
        return
    co, re, ex = event_movement_sums(ev["id"])
    if co - re - ex != 0:
        return
    ev["status"] = "CLOSED"
    ev["closed_at"] = store.clock
    ev["final_standby_fee_cents"] = final_fee_cents(ev)
    bump(ev)


# ---- Gates shared by endpoints ----------------------------------------------

def check_operator_exists(uid):
    op = store.operators.get(uid)
    if op is None:
        err("ERR_NOT_FOUND", f"operator {uid} not found")
    return op


def check_operator_active(uid):
    op = store.operators.get(uid)
    if op is not None and op["status"] == "SUSPENDED":
        err("ERR_OPERATOR_SUSPENDED", "operator is SUSPENDED")
    return op


def check_display_ownership(ev, uid):
    if ev["operator_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "display belongs to another operator")


def venue_conflict(operator_uid, venue_id, start, end):
    """A new booking conflicts when its window — each window carrying its own
    120-minute trailing buffer — overlaps another non-terminal event at the
    same venue. Overlap requires a positive shared span: contact at a single
    instant (a start exactly at the prior window's buffered end) is not an
    overlap, so the comparison is strict."""
    buf = timedelta(minutes=VENUE_BUFFER_MIN)
    new_end_buffered = end + buf
    for ev in store.displays.values():
        if ev["venue_id"] != venue_id or ev["status"] in EVENT_TERMINAL:
            continue
        if ev["scheduled_start_at"] < new_end_buffered and \
                start < ev["scheduled_end_at"] + buf:
            err("ERR_VENUE_CONFLICT",
                "venue booking overlaps another non-terminal event")
