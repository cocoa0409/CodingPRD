"""Business logic: computed fields, calculations, and cascades.

All formulas follow SCAFFOLD.yaml §1.3 and PRD §3 verbatim.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# ---- calculation constants (scaffold §1.3) ----
PRIORITY_BASE = {"ELECTRONICS": 10, "TEXTILE": 5, "BIKE": 7}
PRIORITY_SEVERITY_WEIGHT = 8
PRIORITY_DIFFICULTY_WEIGHT = 2
PRIORITY_HAZARD_BONUS = 15

RELIABILITY_INITIAL = 100
RELIABILITY_NO_SHOW = 15
RELIABILITY_LEFT_EARLY = 5
RELIABILITY_COMPLETED = 2
RELIABILITY_THRESHOLD = 40

DONATION_BASE = {"ELECTRONICS": 1500, "TEXTILE": 800, "BIKE": 1000}
DONATION_CAP_CENTS = 5000

ACTIVE_ITEM_STATUSES = {"REGISTERED", "TRIAGED", "QUEUED", "ASSIGNED", "IN_REPAIR", "OUTCOME_RECORDED"}
ITEM_TERMINAL = {"VERIFIED", "WITHDRAWN"}
SHIFT_TERMINAL = {"COMPLETED", "LEFT_EARLY", "CANCELLED", "NO_SHOW"}


def _dec(value):
    return Decimal(str(value))


def round_half_up_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def kg_out(dec):
    return float(dec.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def rate_out(dec):
    return float(dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- queries ---

def stations_of(event_id):
    return [s for s in db.stations.values() if s["event_id"] == event_id]


def shifts_of_event(event_id):
    return [s for s in db.shifts.values() if s["event_id"] == event_id]


def items_of_event(event_id):
    return [i for i in db.items.values() if i["event_id"] == event_id]


def checked_in_count(station_id):
    return sum(
        1
        for s in db.shifts.values()
        if s["station_id"] == station_id and s["status"] == "CHECKED_IN"
    )


def reliability(fixer_id):
    """clamped(100 - 15*NO_SHOW - 5*LEFT_EARLY + 2*COMPLETED) over terminal shifts."""
    score = RELIABILITY_INITIAL
    for s in db.shifts.values():
        if s["fixer_id"] != fixer_id:
            continue
        if s["status"] == "NO_SHOW":
            score -= RELIABILITY_NO_SHOW
        elif s["status"] == "LEFT_EARLY":
            score -= RELIABILITY_LEFT_EARLY
        elif s["status"] == "COMPLETED":
            score += RELIABILITY_COMPLETED
    return max(0, min(100, score))


def posture(event):
    """ACCEPTING iff INTAKE_OPEN and >=1 OPEN station and no open CRITICAL incident."""
    if event["status"] != "INTAKE_OPEN":
        return "RESTRICTED"
    if not any(s["status"] == "OPEN" for s in stations_of(event["id"])):
        return "RESTRICTED"
    for inc in db.incidents.values():
        if (
            inc["event_id"] == event["id"]
            and inc["severity"] == "CRITICAL"
            and inc["status"] == "REPORTED"
        ):
            return "RESTRICTED"
    return "ACCEPTING"


def active_item_count(event_id):
    return sum(1 for i in items_of_event(event_id) if i["status"] in ACTIVE_ITEM_STATUSES)


def current_triage(item_id):
    """The single non-superseded TriageRecord for the item, or None."""
    for t in db.triage_records.values():
        if t["item_id"] == item_id and t["superseded_by_id"] is None:
            return t
    return None


def reserved_qty(stock_id):
    return sum(
        r["quantity"]
        for r in db.reservations.values()
        if r["part_stock_id"] == stock_id and r["status"] == "RESERVED"
    )


def committed_parts_cost_event(event_id):
    total = 0
    for r in db.reservations.values():
        if r["status"] != "COMMITTED":
            continue
        item = db.items.get(r["repair_item_id"])
        if item is not None and item["event_id"] == event_id:
            total += r["cost_cents"]
    return total


def _outcome_weight(o):
    item = db.items[o["item_id"]]
    w = o["weight_kg_actual"] if o["weight_kg_actual"] is not None else item["weight_kg_estimated"]
    return _dec(w)


def diversion_kg(event_id, statuses):
    """Sum of outcome contributions for the event over the given verification statuses."""
    total = Decimal("0")
    for o in db.outcomes.values():
        item = db.items.get(o["item_id"])
        if item is None or item["event_id"] != event_id:
            continue
        if o["verification_status"] not in statuses:
            continue
        if o["outcome"] == "FIXED":
            total += _outcome_weight(o)
        elif o["outcome"] == "PARTIALLY_FIXED":
            total += _outcome_weight(o) * Decimal("0.5")
    return total


# ------------------------------------------------------- waiver validity ---

def refresh_waiver(w):
    """Lazy ACTIVE -> EXPIRED transition (no version bump; system-lazy)."""
    if w["status"] == "ACTIVE":
        if db.parse_dt(w["signed_at"]) + timedelta(days=365) <= db.clock.current:
            w["status"] = "EXPIRED"


def waiver_still_valid(w):
    return (
        w["status"] == "ACTIVE"
        and db.parse_dt(w["signed_at"]) + timedelta(days=365) > db.clock.current
    )


def waivers_of_visitor(visitor_id):
    return [w for w in db.waivers.values() if w["visitor_id"] == visitor_id]


# ------------------------------------------------------------- cascades ---

def auto_pause_if_empty(station):
    """OPEN station whose last checked-in fixer left auto-transitions to PAUSED."""
    if station["status"] == "OPEN" and checked_in_count(station["id"]) == 0:
        station["status"] = "PAUSED"
        db.touch(station)


def release_reservation(reservation):
    reservation["status"] = "RELEASED"
    db.touch(reservation)


def requeue_fixer_items(fixer_id):
    """Every item assigned to the fixer in ASSIGNED/IN_REPAIR returns to QUEUED."""
    for it in db.items.values():
        if it["assigned_fixer_id"] == fixer_id and it["status"] in ("ASSIGNED", "IN_REPAIR"):
            it["assigned_fixer_id"] = None
            it["assigned_station_id"] = None
            it["status"] = "QUEUED"
            db.touch(it)


def suspend_fixer(fixer):
    """Four-hop suspension cascade (PRD §3.6)."""
    if fixer["status"] != "SUSPENDED":
        fixer["status"] = "SUSPENDED"
        db.touch(fixer)
    for s in db.shifts.values():
        if s["fixer_id"] == fixer["id"] and s["status"] not in SHIFT_TERMINAL:
            was_checked_in = s["status"] == "CHECKED_IN"
            s["status"] = "CANCELLED"
            db.touch(s)
            if was_checked_in:
                station = db.stations.get(s["station_id"])
                if station is not None:
                    auto_pause_if_empty(station)
    requeue_fixer_items(fixer["id"])


def event_close_sweep(event):
    """Ops-run checkpoint for REPAIR_ACTIVE -> CLOSED (PRD §3.7)."""
    for s in shifts_of_event(event["id"]):
        if s["status"] == "CONFIRMED":
            s["status"] = "NO_SHOW"
            db.touch(s)
        elif s["status"] == "CHECKED_IN":
            s["status"] = "LEFT_EARLY"
            db.touch(s)
    event_item_ids = {i["id"] for i in items_of_event(event["id"])}
    for r in db.reservations.values():
        if r["repair_item_id"] in event_item_ids and r["status"] == "RESERVED":
            r["status"] = "EXPIRED"
            db.touch(r)
    for st in stations_of(event["id"]):
        if st["status"] in ("SETUP", "OPEN", "PAUSED"):
            st["status"] = "CLOSED"
            db.touch(st)


def event_cancel_cascade(event):
    """Full teardown for -> CANCELLED (PRD §3.7)."""
    for it in items_of_event(event["id"]):
        if it["status"] in ITEM_TERMINAL:
            continue
        for r in db.reservations.values():
            if r["repair_item_id"] == it["id"] and r["status"] == "RESERVED":
                release_reservation(r)
        it["assigned_fixer_id"] = None
        it["assigned_station_id"] = None
        it["status"] = "WITHDRAWN"
        db.touch(it)
    for s in shifts_of_event(event["id"]):
        if s["status"] in SHIFT_TERMINAL:
            continue
        was_checked_in = s["status"] == "CHECKED_IN"
        s["status"] = "CANCELLED"
        db.touch(s)
        if was_checked_in:
            station = db.stations.get(s["station_id"])
            if station is not None:
                auto_pause_if_empty(station)
    for st in stations_of(event["id"]):
        if st["status"] != "CLOSED":
            st["status"] = "CLOSED"
            db.touch(st)


# --------------------------------------------------------- calculations ---

def priority_score(category, severity, difficulty, hazard_flag):
    raw = (
        PRIORITY_BASE[category]
        + PRIORITY_SEVERITY_WEIGHT * severity
        + PRIORITY_DIFFICULTY_WEIGHT * difficulty
        + (PRIORITY_HAZARD_BONUS if hazard_flag else 0)
    )
    return max(0, min(100, raw))


def suggested_donation_cents(category, parts_cost_cents):
    """Pinned evaluation order: rate keyed on base alone (scaffold §1.3)."""
    base = DONATION_BASE[category]
    if base < 1000:
        rate = Decimal("0.5")
    elif base < 1500:
        rate = Decimal("0.6")
    else:
        rate = Decimal("0.75")
    share = round_half_up_int(_dec(parts_cost_cents) * rate)
    return min(DONATION_CAP_CENTS, base + share)


def in_kind_age_multiplier(age_years):
    age = _dec(age_years)
    if age <= 1:
        return Decimal("0.8")
    if age <= 4:
        return Decimal("0.5")
    return Decimal("0.2")


def donation_receipt_value(donation):
    """Per-line round_half_up FIRST, then sum (never the other way around)."""
    if donation["donation_type"] == "MONETARY":
        return donation["amount_cents"]
    total = 0
    for line in donation["in_kind_lines"]:
        line_value = _dec(line["declared_value_cents"]) * in_kind_age_multiplier(line["age_years"])
        total += round_half_up_int(line_value)
    return total


def donation_campaign_value(donation):
    if donation["donation_type"] == "MONETARY":
        amount = donation["amount_cents"]
        if donation["event_id"] is not None:
            event = db.events.get(donation["event_id"])
            if event is not None:
                starts = db.parse_dt(event["starts_at"])
                ends = db.parse_dt(event["ends_at"])
                if starts <= db.clock.current <= ends:
                    return amount * 2
        return amount
    return sum(line["declared_value_cents"] for line in donation["in_kind_lines"])
