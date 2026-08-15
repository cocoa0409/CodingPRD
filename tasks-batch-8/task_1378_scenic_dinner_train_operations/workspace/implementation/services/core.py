"""Shared business logic: derived fields, calculations, cascades, sweeps.

Implements the PRD section 3 workflows: fare quoting (round-half-up on the unit
fare first), committed vs conservative class availability, galley load (ceil per
service then sum), the 48-hour refund rule, dining table selector, crew coverage,
the clock sweep, and the excursion/agreement/retire/deactivate cascades."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_UP, ROUND_HALF_UP

import db
from db import clock_now, new_entity, public, touch
from timeutil import parse_date, parse_iso, iso_z

# Fare constants (PRD section 2.6)
FARE_BY_CLASS = {"COACH": 6000, "FIRST_CLASS": 11000, "DINING": 15000}
BASE_SURGE_BP = 10000
MIN_HOLIDAY_SURGE_BP = 12000
MAX_SURGE_BP = 20000

# Galley constants (scaffold galley_load)
UNITS_PER_MEAL = 3
# BUFFER_PCT = 0.10 -> per-service load = ceil(count * 3 * 1.1) = ceil(count * 33/10)

FULL_REFUND_HOURS = 48
HOLD_MINUTES = 45
RAIN_CHECK_VALID_DAYS = 365
TURNAROUND_MINUTES = 60
SERVERS_PER_DINING_CAR = 2

SELLABLE_CLASSES = ("COACH", "FIRST_CLASS", "DINING")
STOCK_CLASS_MAP = {
    "LOCOMOTIVE": "LOCO",
    "COACH_CAR": "COACH",
    "FIRST_CLASS_CAR": "FIRST_CLASS",
    "DINING_CAR": "DINING",
}
CERT_ROLES = ("ENGINEER", "CONDUCTOR")


# ---------------------------------------------------------------------------
# Entity lookups / views
# ---------------------------------------------------------------------------

def excursion_bookings(excursion_id):
    return [b for b in db.bookings.values() if b["excursion_id"] == excursion_id]


def excursion_cars(excursion_id):
    return [
        c for c in db.car_assignments.values() if c["excursion_id"] == excursion_id
    ]


def excursion_crew(excursion_id):
    return [
        c for c in db.crew_assignments.values() if c["excursion_id"] == excursion_id
    ]


def find_manifest(excursion_id):
    for m in db.manifests.values():
        if m["excursion_id"] == excursion_id:
            return m
    return None


def class_capacity(excursion_id, class_code):
    return sum(
        c["effective_capacity"]
        for c in excursion_cars(excursion_id)
        if c["class_code"] == class_code
    )


def committed_used(excursion_id, class_code):
    return sum(
        b["party_size"]
        for b in excursion_bookings(excursion_id)
        if b["class_code"] == class_code and b["status"] in ("CONFIRMED", "CHECKED_IN")
    )


def excursion_view(exc):
    """Excursion serialization with committed-variant availability fields."""
    view = public(exc)
    for class_code, field in (
        ("COACH", "coach_seats_available"),
        ("FIRST_CLASS", "first_class_seats_available"),
        ("DINING", "dining_seats_available"),
    ):
        view[field] = class_capacity(exc["id"], class_code) - committed_used(
            exc["id"], class_code
        )
    return view


def manifest_view(manifest):
    return public(manifest)


# ---------------------------------------------------------------------------
# Capacity gates (class_seat_availability calculation)
# ---------------------------------------------------------------------------

def conservative_fits(excursion_id, class_code, party_size, exclude_booking_id=None):
    """Conservative gate: capacity must cover CONFIRMED + CHECKED_IN + unexpired
    HELD (optionally excluding one booking) plus the incoming party_size."""
    cap = class_capacity(excursion_id, class_code)
    now = clock_now()
    used = 0
    for b in excursion_bookings(excursion_id):
        if b["class_code"] != class_code or b["id"] == exclude_booking_id:
            continue
        if b["status"] in ("CONFIRMED", "CHECKED_IN"):
            used += b["party_size"]
        elif b["status"] == "HELD" and parse_iso(b["expires_at"]) > now:
            used += b["party_size"]
    return cap - used >= party_size


# ---------------------------------------------------------------------------
# Galley load (ceil per service first, then sum)
# ---------------------------------------------------------------------------

def _service_units(diner_count):
    # ceil(diner_count * 3 * 1.1) computed exactly: ceil(n * 33 / 10)
    return (diner_count * 33 + 9) // 10


def galley_inclusion_statuses(exc):
    """REGULAR: net (CONFIRMED/CHECKED_IN). HOLIDAY: conservative_prep also
    includes unexpired HELD dining bookings."""
    if exc["event_type"] == "HOLIDAY":
        return ("CONFIRMED", "CHECKED_IN", "HELD")
    return ("CONFIRMED", "CHECKED_IN")


def compute_galley(exc):
    now = clock_now()
    statuses = galley_inclusion_statuses(exc)
    early = 0
    late = 0
    for b in excursion_bookings(exc["id"]):
        if b["class_code"] != "DINING" or b["status"] not in statuses:
            continue
        if b["status"] == "HELD" and parse_iso(b["expires_at"]) <= now:
            continue  # only unexpired holds are pre-counted
        if b["dining_service"] == "EARLY":
            early += b["party_size"]
        elif b["dining_service"] == "LATE":
            late += b["party_size"]
    galley = _service_units(early) + _service_units(late)
    return early, late, galley


def recompute_manifest(excursion_id):
    """Recompute a DRAFT manifest's counts; a changed recompute is a real
    mutation (version +1, updated_at refresh). LOCKED/PROVISIONED are frozen."""
    manifest = find_manifest(excursion_id)
    if manifest is None or manifest["status"] != "DRAFT":
        return
    exc = db.excursions.get(excursion_id)
    if exc is None:
        return
    early, late, galley = compute_galley(exc)
    if (
        manifest["early_diner_count"] != early
        or manifest["late_diner_count"] != late
        or manifest["galley_load_units"] != galley
    ):
        manifest["early_diner_count"] = early
        manifest["late_diner_count"] = late
        manifest["galley_load_units"] = galley
        touch(manifest)


# ---------------------------------------------------------------------------
# Fares and refunds
# ---------------------------------------------------------------------------

def quote_fare(exc, class_code, party_size, rain_check=None):
    """unit fare = round_half_up(base * surge_bp / 10000); total = unit * party;
    paid = total or max(0, total - rain_check value). Rounding pinned: the unit
    fare is rounded BEFORE multiplying by party size."""
    base = FARE_BY_CLASS[class_code]
    unit = int(
        (Decimal(base) * Decimal(exc["surge_multiplier_bp"]) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    total = unit * party_size
    if rain_check is not None:
        paid = max(0, total - rain_check["value_cents"])
    else:
        paid = total
    return unit, total, paid


def slot_start_instant(exc):
    """service_date midnight UTC plus start_minute minutes."""
    slot = db.slots.get(exc["slot_id"])
    day = parse_date(exc["service_date"])
    midnight = datetime.combine(day, time(0, 0, 0), tzinfo=timezone.utc)
    return midnight + timedelta(minutes=slot["start_minute"])


def compute_refund(exc, booking):
    """48-hour rule: cancel at least 48h before slot start (boundary inclusive)
    refunds paid_cents in full; inside the window half of paid_cents rounded
    half-up."""
    now = clock_now()
    start = slot_start_instant(exc)
    if start - now >= timedelta(hours=FULL_REFUND_HOURS):
        return booking["paid_cents"]
    return int(
        (Decimal(booking["paid_cents"]) * Decimal("0.5")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


# ---------------------------------------------------------------------------
# Dining table selector (selector_policy)
# ---------------------------------------------------------------------------

def select_dining_table(exc, dining_service, party_size):
    """Walk DINING cars by ascending position and tables by ascending number.
    A table is free iff no CONFIRMED/CHECKED_IN booking of this excursion holds
    it for this service, and the car's per-service seated load plus this party
    stays within the car's effective_capacity. Returns (car_assignment, table)
    or None when the pool is empty."""
    cars = [c for c in excursion_cars(exc["id"]) if c["class_code"] == "DINING"]
    cars.sort(key=lambda c: (c["position"], c["_seq"]))
    for car in cars:
        stock = db.rolling_stock.get(car["stock_id"])
        if stock is None:
            continue
        load = 0
        taken = set()
        for b in excursion_bookings(exc["id"]):
            if (
                b["dining_car_assignment_id"] == car["id"]
                and b["dining_service"] == dining_service
                and b["status"] in ("CONFIRMED", "CHECKED_IN")
            ):
                load += b["party_size"]
                taken.add(b["dining_table_number"])
        if load + party_size > car["effective_capacity"]:
            continue
        for table_no in range(1, stock["table_count"] + 1):
            if table_no not in taken:
                return car, table_no
    return None


# ---------------------------------------------------------------------------
# Consist / crew readiness gates
# ---------------------------------------------------------------------------

def consist_complete(excursion_id):
    cars = excursion_cars(excursion_id)
    has_loco = any(c["class_code"] == "LOCO" for c in cars)
    has_pax = any(c["class_code"] in ("COACH", "FIRST_CLASS", "DINING") for c in cars)
    return has_loco and has_pax


def crew_coverage_ok(excursion_id):
    counts = {}
    for ca in excursion_crew(excursion_id):
        if ca["status"] == "ASSIGNED":
            counts[ca["position"]] = counts.get(ca["position"], 0) + 1
    dining_cars = sum(
        1 for c in excursion_cars(excursion_id) if c["class_code"] == "DINING"
    )
    if counts.get("ENGINEER", 0) < 1:
        return False
    if counts.get("CONDUCTOR", 0) < 1:
        return False
    if counts.get("CAR_HOST", 0) < 1:
        return False
    if dining_cars >= 1:
        if counts.get("CHEF", 0) < 1:
            return False
        if counts.get("SERVER", 0) < SERVERS_PER_DINING_CAR * dining_cars:
            return False
    return True


# ---------------------------------------------------------------------------
# Maintenance window geometry
# ---------------------------------------------------------------------------

def _day_window(date_str):
    day = parse_date(date_str)
    start = datetime.combine(day, time(0, 0, 0), tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def window_intersects_date(ws, we, date_str):
    day_start, day_end = _day_window(date_str)
    return ws < day_end and we > day_start


def stock_wo_buffer_conflict(stock_id, ws, we, exclude_wo_id=None):
    """60-minute turnaround buffer vs every other SCHEDULED/IN_PROGRESS work
    order on the same unit; mere adjacency is a conflict."""
    buffer = timedelta(minutes=TURNAROUND_MINUTES)
    for wo in db.work_orders.values():
        if wo["stock_id"] != stock_id or wo["id"] == exclude_wo_id:
            continue
        if wo["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        ows = parse_iso(wo["window_start"])
        owe = parse_iso(wo["window_end"])
        if ws < owe + buffer and ows < we + buffer:
            return True
    return False


def stock_has_wo_on_date(stock_id, date_str):
    """Mirror guard at car-assign time: any SCHEDULED/IN_PROGRESS work-order
    window of this unit intersecting the excursion's service_date."""
    for wo in db.work_orders.values():
        if wo["stock_id"] != stock_id:
            continue
        if wo["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if window_intersects_date(
            parse_iso(wo["window_start"]), parse_iso(wo["window_end"]), date_str
        ):
            return True
    return False


def stock_on_committed_excursion_dates(stock_id, ws, we):
    """WO-create guard: window intersects the service_date of a PUBLISHED or
    BOARDING excursion whose consist already includes this unit."""
    for ca in db.car_assignments.values():
        if ca["stock_id"] != stock_id:
            continue
        exc = db.excursions.get(ca["excursion_id"])
        if exc is None or exc["status"] not in ("PUBLISHED", "BOARDING"):
            continue
        if window_intersects_date(ws, we, exc["service_date"]):
            return True
    return False


def stock_on_other_excursion_same_date(stock_id, excursion_id, service_date):
    """Car-assign guard: unit already assigned to a different excursion on the
    same service_date."""
    for ca in db.car_assignments.values():
        if ca["stock_id"] != stock_id or ca["excursion_id"] == excursion_id:
            continue
        other = db.excursions.get(ca["excursion_id"])
        if other is not None and other["service_date"] == service_date:
            return True
    return False


def stock_on_published_or_boarding(stock_id):
    """Retire guard: unit sits on the consist of a PUBLISHED or BOARDING
    excursion."""
    for ca in db.car_assignments.values():
        if ca["stock_id"] != stock_id:
            continue
        exc = db.excursions.get(ca["excursion_id"])
        if exc is not None and exc["status"] in ("PUBLISHED", "BOARDING"):
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def _issue_rain_check(booking, reason):
    today = clock_now().date()
    rc = new_entity(
        {
            "booking_id": booking["id"],
            "customer_email": booking["customer_email"],
            "value_cents": booking["paid_cents"],
            "reason": reason,
            "issued_on": today.isoformat(),
            "expires_on": (today + timedelta(days=RAIN_CHECK_VALID_DAYS)).isoformat(),
            "status": "ISSUED",
            "redeemed_booking_id": None,
        }
    )
    db.rain_checks[rc["id"]] = rc
    return rc


def cancel_excursion(exc, reason, slot_final_status):
    """Full section 3.6 cancellation cascade. slot_final_status is OPEN for a
    manual OperationsManager cancel and RELEASED for the agreement cascade.
    The excursion's own version increments exactly once."""
    exc["cancel_reason"] = reason
    exc["status"] = "CANCELLED"

    slot = db.slots.get(exc["slot_id"])
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = slot_final_status
        touch(slot)

    for b in sorted(excursion_bookings(exc["id"]), key=lambda e: e["_seq"]):
        if b["status"] == "HELD":
            b["status"] = "CANCELLED"  # swept holds never refund
            touch(b)
        elif b["status"] in ("CONFIRMED", "CHECKED_IN"):
            b["status"] = "RAIN_CHECKED"
            touch(b)
            _issue_rain_check(b, reason)

    for ca in sorted(excursion_crew(exc["id"]), key=lambda e: e["_seq"]):
        if ca["status"] == "ASSIGNED":
            ca["status"] = "RELEASED"
            touch(ca)

    touch(exc)
    # DRAFT manifest recomputes its shrinking counts; LOCKED stands untouched.
    recompute_manifest(exc["id"])


def terminate_agreement(agreement):
    """Section 3.8 cascade: OPEN and RESERVED slots go RELEASED; the excursion
    holding a RESERVED slot is cancelled with TRACK_RIGHTS_LOST; CONSUMED slots
    are untouched. The agreement's version increments by 1."""
    agreement["status"] = "TERMINATED"
    touch(agreement)
    mine = [s for s in db.slots.values() if s["agreement_id"] == agreement["id"]]
    mine.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for slot in mine:
        if slot["status"] == "OPEN":
            slot["status"] = "RELEASED"
            touch(slot)
        elif slot["status"] == "RESERVED":
            exc = None
            for cand in db.excursions.values():
                if cand["slot_id"] == slot["id"] and cand["status"] in (
                    "DRAFT",
                    "PUBLISHED",
                    "BOARDING",
                ):
                    exc = cand
                    break
            if exc is not None:
                cancel_excursion(exc, "TRACK_RIGHTS_LOST", "RELEASED")
            else:
                slot["status"] = "RELEASED"
                touch(slot)
        # CONSUMED and already-RELEASED slots are left untouched


def retire_stock(stock):
    """Retirement ripple: SCHEDULED work orders are cancelled; the unit's car
    assignments are stripped from DRAFT excursions (each affected excursion's
    version increments by 1); the unit's own version increments."""
    for wo in sorted(
        (w for w in db.work_orders.values() if w["stock_id"] == stock["id"]),
        key=lambda e: e["_seq"],
    ):
        if wo["status"] == "SCHEDULED":
            wo["status"] = "CANCELLED"
            touch(wo)
    affected_excursions = set()
    for ca in list(db.car_assignments.values()):
        if ca["stock_id"] != stock["id"]:
            continue
        exc = db.excursions.get(ca["excursion_id"])
        if exc is not None and exc["status"] == "DRAFT":
            affected_excursions.add(exc["id"])
            del db.car_assignments[ca["id"]]
    for exc_id in affected_excursions:
        exc = db.excursions.get(exc_id)
        if exc is not None:
            touch(exc)
    stock["status"] = "OUT_OF_SERVICE"
    touch(stock)


def deactivate_member(member):
    """Releases every ASSIGNED crew assignment the member holds on excursions
    still in DRAFT or PUBLISHED, bumping each affected excursion's version."""
    member["status"] = "INACTIVE"
    touch(member)
    affected_excursions = set()
    for ca in sorted(
        (c for c in db.crew_assignments.values() if c["crew_member_id"] == member["id"]),
        key=lambda e: e["_seq"],
    ):
        if ca["status"] != "ASSIGNED":
            continue
        exc = db.excursions.get(ca["excursion_id"])
        if exc is not None and exc["status"] in ("DRAFT", "PUBLISHED"):
            ca["status"] = "RELEASED"
            touch(ca)
            affected_excursions.add(exc["id"])
    for exc_id in affected_excursions:
        exc = db.excursions.get(exc_id)
        if exc is not None:
            touch(exc)


def mark_operated(exc):
    """BOARDING -> OPERATED: slot CONSUMED; CHECKED_IN bookings COMPLETED;
    still-CONFIRMED bookings NO_SHOW (no refund); ASSIGNED crew COMPLETED."""
    exc["status"] = "OPERATED"
    slot = db.slots.get(exc["slot_id"])
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = "CONSUMED"
        touch(slot)
    for b in sorted(excursion_bookings(exc["id"]), key=lambda e: e["_seq"]):
        if b["status"] == "CHECKED_IN":
            b["status"] = "COMPLETED"
            touch(b)
        elif b["status"] == "CONFIRMED":
            b["status"] = "NO_SHOW"
            touch(b)
    for ca in sorted(excursion_crew(exc["id"]), key=lambda e: e["_seq"]):
        if ca["status"] == "ASSIGNED":
            ca["status"] = "COMPLETED"
            touch(ca)
    touch(exc)


# ---------------------------------------------------------------------------
# Clock sweep (clock_sweep calculation)
# ---------------------------------------------------------------------------

def sweep():
    """Runs on every clock advance, in fixed order: first HELD bookings whose
    expires_at is at or before the new instant -> CANCELLED (no refund),
    earliest expires_at first; then ISSUED rain-checks whose expires_on is
    earlier than the new clock date -> EXPIRED, earliest expires_on first."""
    now = clock_now()
    held = [
        b
        for b in db.bookings.values()
        if b["status"] == "HELD" and parse_iso(b["expires_at"]) <= now
    ]
    held.sort(key=lambda b: (parse_iso(b["expires_at"]), b["_seq"]))
    for b in held:
        b["status"] = "CANCELLED"
        touch(b)
        recompute_manifest(b["excursion_id"])
    today = now.date().isoformat()
    expired = [
        r
        for r in db.rain_checks.values()
        if r["status"] == "ISSUED" and r["expires_on"] < today
    ]
    expired.sort(key=lambda r: (r["expires_on"], r["_seq"]))
    for r in expired:
        r["status"] = "EXPIRED"
        touch(r)
