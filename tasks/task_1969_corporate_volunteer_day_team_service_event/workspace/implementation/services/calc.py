"""Calculation rules (scaffold Table 3) implemented exactly as specified.

Money is always integer cents; fractional results round half-up via Decimal.
Hours may carry one decimal place; sums are exact.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import math

from db import db

# --- constants from scaffold ---
TAX_RATE = Decimal("0.0875")
ADULT_RATIO = 8
MINOR_RATIO = 4
VENDOR_DAILY_CAPACITY = 6
TURNAROUND_BUFFER_MINUTES = 30
REPEAT_CAP_UPLIFT_PCT = Decimal("0.10")
OFFSET_CAP_PCT = Decimal("0.50")
RECENCY_WINDOW_DAYS = 90
SUSPEND_RATING_THRESHOLD = Decimal("2.50")
REINSTATE_RATING_THRESHOLD = Decimal("3.00")
SUSPEND_MIN_SURVEYS = 3
REPEAT_RATING_THRESHOLD = Decimal("4.0")
REPEAT_WINDOW_DAYS = 180

DIETARY_TAGS = {"VEGETARIAN", "VEGAN", "GLUTEN_FREE"}


def rh_cents(value):
    """Round half-up to whole cents (integer)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rh_2dp(value):
    """Round half-up to 2 decimal places, returned as float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours_1dp(value):
    """Round half-up to 1 decimal hour, returned as float."""
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- age / minor
def compute_is_minor(dob, event_start_dt):
    """True iff volunteer age < 18 at the event start (date granularity)."""
    d = event_start_dt.date()
    age = d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))
    return age < 18


# ---------------------------------------------------------------- event hours
def scheduled_hours(ev):
    """Duration from event_start_at to event_end_at in hours (1 decimal)."""
    secs = Decimal(str((ev["_end"] - ev["_start"]).total_seconds()))
    return hours_1dp(secs / Decimal(3600))


# ---------------------------------------------------------------- registrations
def event_registrations(ev):
    return [r for r in db.registrations.values() if r["event_id"] == ev["id"]]


def project_registrations(project):
    return [r for r in db.registrations.values() if r["project_id"] == project["id"]]


def reg_is_minor(reg):
    ev = db.events.get(reg["event_id"])
    vol = db.volunteers.get(reg["volunteer_id"])
    if ev is None or vol is None:
        return False
    return compute_is_minor(vol["_dob"], ev["_start"])


def headcounts(ev):
    regs = event_registrations(ev)
    registered = sum(1 for r in regs if r["rsvp_status"] in ("REGISTERED", "CONFIRMED", "CHECKED_IN"))
    confirmed = sum(1 for r in regs if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN"))
    checked_in = sum(1 for r in regs if r["rsvp_status"] == "CHECKED_IN")
    return registered, confirmed, checked_in


def project_confirmed_count(project):
    return sum(
        1
        for r in project_registrations(project)
        if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN")
    )


def supervision_requirement(project):
    """ceil(adult_confirmed/8) + ceil(minor_confirmed/4); 0 when no confirmed."""
    adult = 0
    minor = 0
    for r in project_registrations(project):
        if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN"):
            if reg_is_minor(r):
                minor += 1
            else:
                adult += 1
    if adult + minor == 0:
        return 0
    return math.ceil(adult / ADULT_RATIO) + math.ceil(minor / MINOR_RATIO)


def active_staff_leads(project):
    return sum(
        1
        for a in db.assignments.values()
        if a["project_id"] == project["id"] and a["status"] == "ACTIVE"
    )


def site_prep_complete(project):
    """>=1 RECEIVED order for the project AND none in {SUBMITTED, APPROVED}."""
    orders = [o for o in db.orders.values() if o["project_id"] == project["id"]]
    has_received = any(o["status"] == "RECEIVED" for o in orders)
    in_pipeline = any(o["status"] in ("SUBMITTED", "APPROVED") for o in orders)
    return has_received and not in_pipeline


# ---------------------------------------------------------------- hours credits
def registration_verified_hours(reg):
    total = Decimal("0")
    for rec in db.impacts.values():
        if rec["registration_id"] == reg["id"] and rec["status"] in ("VERIFIED", "PUBLISHED"):
            total += Decimal(str(rec["hours_attended"]))
    return hours_1dp(total)


def event_total_scheduled_hours(ev):
    total = Decimal("0")
    for r in event_registrations(ev):
        total += Decimal(str(r["scheduled_hours_credit"]))
    return hours_1dp(total)


def event_total_verified_hours(ev):
    total = Decimal("0")
    for rec in db.impacts.values():
        if rec["event_id"] == ev["id"] and rec["status"] in ("VERIFIED", "PUBLISHED"):
            total += Decimal(str(rec["hours_attended"]))
    return hours_1dp(total)


# ---------------------------------------------------------------- spend position
def event_spend(ev):
    """(projected_spend_cents, committed_spend_cents)."""
    projected = 0
    committed = 0
    for o in db.orders.values():
        if o["event_id"] != ev["id"]:
            continue
        if o["status"] in ("SUBMITTED", "APPROVED", "RECEIVED"):
            projected += o["order_total_cents"]
        if o["status"] in ("APPROVED", "RECEIVED"):
            committed += o["order_total_cents"]
    for m in db.meal_plans.values():
        if m["event_id"] != ev["id"]:
            continue
        if m["status"] in ("ORDERED", "FULFILLED"):
            projected += m["total_cost_cents"] or 0
            committed += m["total_cost_cents"] or 0
    for t in db.manifests.values():
        if t["event_id"] != ev["id"]:
            continue
        if t["status"] in ("BOOKED", "CONFIRMED", "COMPLETED"):
            projected += t["cost_cents"]
        if t["status"] in ("CONFIRMED", "COMPLETED"):
            committed += t["cost_cents"]
    return projected, committed


# ---------------------------------------------------------------- sponsorship
def effective_cap_cents(sp):
    ev = db.events.get(sp["event_id"])
    if ev is not None and ev["repeat_booking_bonus"]:
        return rh_cents(Decimal(sp["pledge_cap_cents"]) * (Decimal(1) + REPEAT_CAP_UPLIFT_PCT))
    return sp["pledge_cap_cents"]


def provisional_amount(sp):
    """Forward-looking estimate (used while PLEDGED/COMMITTED)."""
    ev = db.events.get(sp["event_id"])
    if ev is None:
        return 0
    _, confirmed, _ = headcounts(ev)
    if sp["match_type"] == "FLAT":
        base = sp["rate_cents"]
    elif sp["match_type"] == "PER_CHECK_IN":
        base = sp["rate_cents"] * confirmed
    else:  # PER_VERIFIED_HOUR
        base = rh_cents(
            Decimal(sp["rate_cents"]) * Decimal(confirmed) * Decimal(str(scheduled_hours(ev)))
        )
    return min(base, effective_cap_cents(sp))


def settled_amount(sp):
    """Chronological actuals at settle time."""
    ev = db.events.get(sp["event_id"])
    if ev is None:
        return 0
    _, _, checked_in = headcounts(ev)
    if sp["match_type"] == "FLAT":
        base = sp["rate_cents"]
    elif sp["match_type"] == "PER_CHECK_IN":
        base = sp["rate_cents"] * checked_in
    else:  # PER_VERIFIED_HOUR
        base = rh_cents(Decimal(sp["rate_cents"]) * Decimal(str(event_total_verified_hours(ev))))
    return min(base, effective_cap_cents(sp))


def sponsorship_credit_and_net(ev):
    """(sponsorship_credit_cents, net_event_cost_cents) per fixed evaluation order."""
    _, committed = event_spend(ev)
    credit = 0
    for sp in db.sponsorships.values():
        if sp["event_id"] != ev["id"]:
            continue
        if sp["status"] == "SETTLED":
            credit += sp["settled_amount_cents"] or 0
        elif sp["status"] == "COMMITTED":
            credit += sp["provisional_amount_cents"]
    offset = min(credit, rh_cents(OFFSET_CAP_PCT * Decimal(committed)))
    return credit, committed - offset


# ---------------------------------------------------------------- posture
def event_posture(ev):
    """BLOCKED | PARTIAL | READY per event_readiness_posture calc."""
    projects = [
        p
        for p in db.projects.values()
        if p["event_id"] == ev["id"] and p["status"] in ("MATCHED", "LOCKED")
    ]
    if not projects:
        return "BLOCKED"
    # (a) at least one LOCKED project
    if not any(p["status"] == "LOCKED" for p in projects):
        return "PARTIAL"
    # (b) every project: active >= required AND confirmed >= min
    for p in projects:
        if active_staff_leads(p) < supervision_requirement(p):
            return "PARTIAL"
        if project_confirmed_count(p) < p["min_volunteers"]:
            return "PARTIAL"
    # (c) no order in SUBMITTED/APPROVED
    for o in db.orders.values():
        if o["event_id"] == ev["id"] and o["status"] in ("SUBMITTED", "APPROVED"):
            return "PARTIAL"
    # (d) every LOCKED project site prep complete
    for p in projects:
        if p["status"] == "LOCKED" and not site_prep_complete(p):
            return "PARTIAL"
    # (e) meal demand
    regs = event_registrations(ev)
    meal_need = sum(
        1 for r in regs if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN") and r["wants_meal"]
    )
    if meal_need > 0:
        has_meal = any(
            m["event_id"] == ev["id"] and m["status"] in ("ORDERED", "FULFILLED")
            for m in db.meal_plans.values()
        )
        if not has_meal:
            return "PARTIAL"
    # (f) transit demand/supply
    transit_need = sum(
        1 for r in regs if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN") and r["wants_transport"]
    )
    if transit_need > 0:
        supply = 0
        for t in db.manifests.values():
            if t["event_id"] == ev["id"] and t["status"] in ("CONFIRMED", "COMPLETED"):
                veh = db.vehicles.get(t["vehicle_id"])
                if veh is not None:
                    supply += veh["seat_capacity"]
        if supply < transit_need:
            return "PARTIAL"
    return "READY"


# ---------------------------------------------------------------- manifests
def manifest_assigned_seats(manifest):
    return sum(
        1
        for r in db.registrations.values()
        if r["transport_manifest_id"] == manifest["id"]
        and r["rsvp_status"] in ("REGISTERED", "CONFIRMED", "CHECKED_IN")
    )


def vehicle_window_conflict(vehicle_id, new_depart, new_return, exclude_id=None):
    """Half-open intervals with 30-minute turnaround buffer; adjacency at exactly
    the buffer is legal."""
    buffer = timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    for m in db.manifests.values():
        if m["vehicle_id"] != vehicle_id or m["id"] == exclude_id:
            continue
        if m["status"] not in ("BOOKED", "CONFIRMED", "COMPLETED"):
            continue
        if new_depart >= m["_return"] + buffer:
            continue
        if new_return + buffer <= m["_depart"]:
            continue
        return True
    return False


# ---------------------------------------------------------------- meal plans
def vendor_day_pool(vendor_name, event_date, exclude_id=None):
    """Sum of ordered_headcount over MealPlans with same vendor_name and same UTC
    calendar date of their event's event_start_at, status ORDERED/FULFILLED."""
    total = 0
    for m in db.meal_plans.values():
        if m["id"] == exclude_id or m["vendor_name"] != vendor_name:
            continue
        if m["status"] not in ("ORDERED", "FULFILLED"):
            continue
        ev = db.events.get(m["event_id"])
        if ev is None:
            continue
        if ev["_start"].date() == event_date:
            total += m["ordered_headcount"] or 0
    return total


def meal_snapshot(ev, plan):
    """(ordered_headcount, dietary_headcount) at order time."""
    eligible = [
        r
        for r in event_registrations(ev)
        if r["rsvp_status"] in ("CONFIRMED", "CHECKED_IN") and r["wants_meal"]
    ]
    ordered = len(eligible)
    dietary = 0
    for r in eligible:
        vol = db.volunteers.get(r["volunteer_id"])
        if vol is not None and any(t in DIETARY_TAGS for t in vol["dietary_tags"]):
            dietary += 1
    return ordered, dietary


# ---------------------------------------------------------------- feedback / reputation
def event_avg_feedback(ev):
    regs = {r["id"] for r in event_registrations(ev)}
    ratings = [s["rating"] for s in db.surveys.values() if s["registration_id"] in regs]
    if not ratings:
        return None
    mean = Decimal(sum(ratings)) / Decimal(len(ratings))
    return rh_2dp(mean)


def partner_surveys(partner):
    """All surveys reachable via Registration -> ServiceProject.nonprofit_id."""
    out = []
    for s in db.surveys.values():
        reg = db.registrations.get(s["registration_id"])
        if reg is None:
            continue
        project = db.projects.get(reg["project_id"])
        if project is None or project["nonprofit_id"] != partner["id"]:
            continue
        out.append(s)
    return out


def partner_reputation(partner):
    """Recency-weighted mean, 2dp round-half-up; null until first survey."""
    surveys = partner_surveys(partner)
    if not surveys:
        return None, 0
    now = db.now()
    window_start = now - timedelta(days=RECENCY_WINDOW_DAYS)
    wsum = Decimal("0")
    rsum = Decimal("0")
    for s in surveys:
        w = Decimal("1.0") if s["_created"] >= window_start else Decimal("0.5")
        wsum += w
        rsum += Decimal(s["rating"]) * w
    return rh_2dp(rsum / wsum), len(surveys)


def partner_completed_event_count(partner):
    count = 0
    for ev in db.events.values():
        if ev["status"] not in ("COMPLETED", "CLOSED"):
            continue
        has_completed_project = any(
            p["event_id"] == ev["id"]
            and p["nonprofit_id"] == partner["id"]
            and p["status"] == "COMPLETED"
            for p in db.projects.values()
        )
        if has_completed_project:
            count += 1
    return count


def procurement_line_total(quantity, unit_cost_cents):
    """Per-line: round_half_up(quantity * unit_cost_cents * 1.0875). Lines are
    rounded FIRST, then summed (nested rounding order is mandatory)."""
    return rh_cents(Decimal(quantity) * Decimal(unit_cost_cents) * (Decimal(1) + TAX_RATE))
