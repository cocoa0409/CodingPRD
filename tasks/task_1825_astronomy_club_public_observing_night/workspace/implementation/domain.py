"""Domain logic: constants, calculations, serializers, cascades, clock transitions."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from helpers import fmt_dt

# ----- pinned constants (scaffold calculations) -----
GRACE_PERIOD_DAYS = 7
LAPSE_PERIOD_DAYS = 37
COLLIMATION_INTERVAL_DAYS = 180
MOON_ILLUMINATION_LIMIT = 40
WEATHER_CANCEL_THRESHOLD = 70
GROUP_CAPACITY_PER_EVENT = 60
MIN_READINGS_PER_REPORT = 3
STRIKE_WINDOW_DAYS = 365
STRIKE_THROTTLE_LIMIT = 2
FEE_GRACE_DAYS = 2
FEE_DAILY_CENTS = 500
FEE_CAP_CENTS = 10000
DAYS_FULL_YEAR = 365

TIER_CODES = ("STUDENT", "INDIVIDUAL", "FAMILY", "PATRON")
EQUIPMENT_CLASSES = ("REFRACTOR", "REFLECTOR", "SCT", "DOBSONIAN", "SOLAR_SCOPE")
TICKET_KINDS = ("COLLIMATION", "REPAIR", "CLEANING")
TICKET_SEVERITIES = ("LOW", "MEDIUM", "HIGH")
EVENT_KINDS = ("PUBLIC_NIGHT", "MEMBER_NIGHT", "SOLAR_SESSION")
CANCEL_REASONS = ("WEATHER", "LOW_COVERAGE", "MOON", "OTHER")

NON_TERMINAL_LOAN = ("RESERVED", "CHECKED_OUT", "OVERDUE")


def new_id():
    return str(uuid.uuid4())


def mint(store):
    """Common system fields for a versioned resource."""
    return {
        "id": new_id(),
        "created_at": store.clock,
        "updated_at": store.clock,
        "version": 1,
        "_seq": store.next_seq(),
    }


def stamp(store, e):
    """Every mutation (including cascades/recomputes) refreshes updated_at and bumps version."""
    e["updated_at"] = store.clock
    e["version"] += 1


# ----- calculations -----

def prorate_amount(annual_cents, period_start, period_end):
    """dues_proration: full-year variant charges exactly; otherwise one final round-half-up."""
    days_total = (period_end - period_start).days
    if days_total == DAYS_FULL_YEAR:
        return annual_cents
    raw = (Decimal(annual_cents) * Decimal(days_total)) / Decimal(DAYS_FULL_YEAR)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def overdue_fee_cents(loan, ref):
    """overdue_fee: whole days late, first 2 free, 500 cents/day. Uncapped here."""
    days_late = (ref - loan["window_end"]).days
    if days_late < 0:
        days_late = 0
    billable = days_late - FEE_GRACE_DAYS
    if billable < 0:
        billable = 0
    return billable * FEE_DAILY_CENTS


def deposit_for_party(party_size):
    """group_deposit: marginal tiers — first 10 free, 11..30 at 1000, 31+ at 2000."""
    tier2 = max(0, min(party_size, 30) - 10) * 1000
    tier3 = max(0, party_size - 30) * 2000
    return tier2 + tier3


def median_and_grade(values):
    """dark_sky_median over Decimal sqm values; None median when no readings."""
    if not values:
        return None, None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        med = s[(n - 1) // 2]
    else:
        med = ((s[n // 2 - 1] + s[n // 2]) / Decimal(2)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    if med >= Decimal("21.50"):
        grade = "A"
    elif med >= Decimal("20.50"):
        grade = "B"
    elif med >= Decimal("19.50"):
        grade = "C"
    elif med >= Decimal("18.50"):
        grade = "D"
    else:
        grade = "F"
    return med, grade


def compute_strikes(store, member_id):
    """no_show_strikes: marks at or after logical_clock - 365 days (inclusive boundary)."""
    window_start = store.clock - timedelta(days=STRIKE_WINDOW_DAYS)
    return sum(1 for mk in store.no_show_marks
               if mk["member_id"] == member_id and mk["marked_at"] >= window_start)


def has_active_cert(store, member_id, equipment_class):
    """Certification gates only while ACTIVE and strictly before expires_at."""
    now = store.clock
    return any(c["member_id"] == member_id
               and c["equipment_class"] == equipment_class
               and c["status"] == "ACTIVE"
               and c["expires_at"] > now
               for c in store.certs.values())


def report_recompute(store, rep):
    """Sweep readings in the half-open window [period_start, period_end)."""
    vals = [r["sqm_value"] for r in store.readings.values()
            if rep["period_start"] <= r["taken_at"] < rep["period_end"]]
    rep["reading_count"] = len(vals)
    med, grade = median_and_grade(vals)
    rep["median_sqm"] = med
    rep["advocacy_grade"] = grade


def recompute_condition(store, tele):
    """condition_score_reconcile: full recompute over CLOSED tickets, floored at 0."""
    total = 100 + sum(t["condition_delta"] for t in store.tickets.values()
                      if t["telescope_id"] == tele["id"] and t["status"] == "CLOSED")
    tele["condition_score"] = max(0, total)


def recompute_coverage(store, ev):
    """operator_coverage: count CONFIRMED assignments; coverage lapse drops host to SCHEDULED."""
    ev["confirmed_operator_count"] = sum(
        1 for a in store.assignments.values()
        if a["event_id"] == ev["id"] and a["status"] == "CONFIRMED")
    if ev["status"] == "CONFIRMED" and ev["confirmed_operator_count"] < ev["min_operators"]:
        ev["status"] = "SCHEDULED"
    stamp(store, ev)


# ----- cascades -----

def release_telescope_if_reserved(store, telescope_id):
    tele = store.telescopes.get(telescope_id)
    if tele is not None and tele["status"] == "RESERVED":
        tele["status"] = "AVAILABLE"
        stamp(store, tele)


def cancel_loan(store, loan):
    loan["status"] = "CANCELLED"
    stamp(store, loan)
    release_telescope_if_reserved(store, loan["telescope_id"])


def cancel_reserved_loans_of(store, member_id):
    for l in store.loans.values():
        if l["member_id"] == member_id and l["status"] == "RESERVED":
            cancel_loan(store, l)


def withdraw_assignments_of(store, member_id):
    affected = set()
    for a in store.assignments.values():
        if a["member_id"] == member_id and a["status"] in ("INVITED", "CONFIRMED"):
            a["status"] = "WITHDRAWN"
            stamp(store, a)
            affected.add(a["event_id"])
    for eid in affected:
        recompute_coverage(store, store.events[eid])


def suspend_member(store, m):
    m["status"] = "SUSPENDED"
    m["effective_access_level"] = 0
    stamp(store, m)
    cancel_reserved_loans_of(store, m["id"])
    withdraw_assignments_of(store, m["id"])


def lapse_member(store, m):
    m["status"] = "LAPSED"
    m["effective_access_level"] = 0
    stamp(store, m)


def event_cancel_cascade(store, ev, reason):
    """Cancellation side effects; from CONFIRMED only CONFIRMED bookings cancel."""
    from_status = ev["status"]
    ev["status"] = "CANCELLED"
    ev["cancellation_reason"] = reason
    stamp(store, ev)
    for a in store.assignments.values():
        if a["event_id"] == ev["id"] and a["status"] in ("INVITED", "CONFIRMED"):
            a["status"] = "WITHDRAWN"
            stamp(store, a)
    for b in store.bookings.values():
        if b["event_id"] != ev["id"]:
            continue
        if from_status == "SCHEDULED" and b["status"] in ("PENDING", "CONFIRMED"):
            b["status"] = "CANCELLED"
            stamp(store, b)
        elif from_status == "CONFIRMED" and b["status"] == "CONFIRMED":
            b["status"] = "CANCELLED"
            b["_deposit_refund_note"] = "Deposit refunded due to event cancellation"
            stamp(store, b)
    ev["confirmed_operator_count"] = sum(
        1 for a in store.assignments.values()
        if a["event_id"] == ev["id"] and a["status"] == "CONFIRMED")


# ----- clock-driven automatic transitions -----

def fire_time_transitions(store):
    """Fired only by POST /club/_clock/set_current_utc — never by wall-clock time."""
    now = store.clock
    for c in list(store.certs.values()):
        if c["status"] == "ACTIVE" and now >= c["expires_at"]:
            c["status"] = "EXPIRED"
            stamp(store, c)
    for m in list(store.members.values()):
        dpt = m["dues_paid_through"]
        if m["status"] == "ACTIVE" and now >= dpt + timedelta(days=GRACE_PERIOD_DAYS):
            suspend_member(store, m)
        if m["status"] in ("ACTIVE", "SUSPENDED") and \
                now >= dpt + timedelta(days=LAPSE_PERIOD_DAYS):
            lapse_member(store, m)
    for l in list(store.loans.values()):
        if l["status"] == "CHECKED_OUT" and now >= l["window_end"]:
            l["status"] = "OVERDUE"
            stamp(store, l)
