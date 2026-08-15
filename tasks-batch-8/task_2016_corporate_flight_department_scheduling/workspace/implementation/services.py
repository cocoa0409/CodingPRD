"""Business logic: derivations, selector, calculations, cascades, clock sweep.

Implements SCAFFOLD.yaml section 1.3 (calculations) and the state-machine
side effects from section 1.2, with PRD.md prose as the tie-breaker.
All money is integer cents; every pinned rounding step is round-half-up.
"""

from datetime import timedelta
from decimal import Decimal

from httpkit import err, err_fk_not_found, err_not_found
from store import db
from util import D, new_uuid, round_half_up_cents

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

AIRCRAFT_TYPES = ["LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET", "TURBOPROP"]
DOC_KINDS = ["AIRWORTHINESS_CERT", "REGISTRATION", "INSURANCE",
             "OPS_SPECS", "NOISE_CERT", "INTERNATIONAL_PERMIT"]
REQUIRED_DOC_KINDS = {"AIRWORTHINESS_CERT", "REGISTRATION", "INSURANCE"}
SEAT_QUALIFICATIONS = ["PIC", "SIC"]
PRIORITY_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
TRIP_KINDS = ["BUSINESS", "PERSONAL", "MIXED"]
MAINTENANCE_KINDS = ["SCHEDULED_INSPECTION", "UNSCHEDULED_REPAIR",
                     "AVIONICS_UPGRADE", "ENGINE_OVERHAUL"]

COST_PER_MINUTE_CENTS = {
    "LIGHT_JET": 8500,
    "MIDSIZE_JET": 14000,
    "HEAVY_JET": 23000,
    "TURBOPROP": 5000,
}

TURN_BUFFER_MINUTES = 90
DUTY_LIMIT_MINUTES = 840
DUTY_WINDOW_HOURS = 24
BAND_1_MAX_MILES = 500
BAND_2_MAX_MILES = 1500

# Leg statuses that hold an aircraft tail (aircraft_interval_overlap input set)
AIRCRAFT_HOLDING_STATUSES = ("AIRCRAFT_ASSIGNED", "CREWED", "RELEASED")
# Leg statuses that hold a crew member (crew_interval_overlap input set)
CREW_HOLDING_STATUSES = ("CREWED", "RELEASED")


# ---------------------------------------------------------------------------
# Generic resource helpers
# ---------------------------------------------------------------------------

def touch(resource):
    """Mutation bookkeeping: refresh updated_at and increment version by 1."""
    resource["updated_at"] = db.now()
    resource["version"] += 1


def new_common():
    ts = db.now()
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# ---------------------------------------------------------------------------
# Lookup helpers -- path params (ERR_NOT_FOUND) and body FKs (ERR_FK_NOT_FOUND)
# ---------------------------------------------------------------------------

def _lookup(table, rid, fk):
    r = table.get(rid)
    if r is None:
        if fk:
            raise err_fk_not_found(f"Referenced resource {rid} does not exist")
        raise err_not_found(f"Resource {rid} does not exist")
    return r


def get_aircraft(rid, fk=False):
    return _lookup(db.aircraft, rid, fk)


def get_document(rid, fk=False):
    return _lookup(db.documents, rid, fk)


def get_crew_member(rid, fk=False):
    return _lookup(db.crew_members, rid, fk)


def get_business_unit(rid, fk=False):
    return _lookup(db.business_units, rid, fk)


def get_passenger(rid, fk=False):
    return _lookup(db.passengers, rid, fk)


def get_trip(rid, fk=False):
    return _lookup(db.trips, rid, fk)


def get_leg(rid, fk=False):
    return _lookup(db.flight_legs, rid, fk)


def get_maintenance_window(rid, fk=False):
    return _lookup(db.maintenance_windows, rid, fk)


def get_catering_order(rid, fk=False):
    return _lookup(db.catering_orders, rid, fk)


def get_ground_transport(rid, fk=False):
    return _lookup(db.ground_transports, rid, fk)


def get_charter(rid, fk=False):
    return _lookup(db.charter_supplements, rid, fk)


def get_rate_period(rid, fk=False):
    return _lookup(db.sifl_rate_periods, rid, fk)


def legs_of_trip(trip_id):
    return [lg for lg in db.flight_legs.values() if lg["trip_request_id"] == trip_id]


def catering_of_leg(leg_id):
    return [o for o in db.catering_orders.values() if o["flight_leg_id"] == leg_id]


def transports_of_leg(leg_id):
    return [t for t in db.ground_transports.values() if t["flight_leg_id"] == leg_id]


def windows_of_aircraft(aircraft_id):
    return [w for w in db.maintenance_windows.values()
            if w["aircraft_id"] == aircraft_id]


def documents_of_aircraft(aircraft_id):
    return [d for d in db.documents.values() if d["aircraft_id"] == aircraft_id]


def accepted_charter_for_trip(trip_id):
    for c in db.charter_supplements.values():
        if c["trip_request_id"] == trip_id and c["status"] == "ACCEPTED":
            return c
    return None


# ---------------------------------------------------------------------------
# Derived state: document currency and aircraft posture (PRD 2.7)
# ---------------------------------------------------------------------------

def document_status(doc):
    """CURRENT while expires_at is strictly later than the logical clock."""
    return "CURRENT" if doc["expires_at"] > db.now() else "EXPIRED"


def aircraft_posture(a):
    """Returns (posture, posture_reason). MAINTENANCE_HOLD dominates
    DOCUMENT_LAPSE when both apply; half-open maintenance intervals; document
    lapse boundary is inclusive (expires_at <= now)."""
    now = db.now()
    if a["status"] == "GROUNDED":
        return "MAINTENANCE_HOLD", "Aircraft is grounded"
    for w in windows_of_aircraft(a["id"]):
        if w["status"] == "IN_PROGRESS":
            return "MAINTENANCE_HOLD", "Maintenance window in progress"
    for w in windows_of_aircraft(a["id"]):
        if (w["status"] == "PLANNED"
                and w["window_start_utc"] <= now < w["window_end_utc"]):
            return "MAINTENANCE_HOLD", "Planned maintenance window contains current time"
    for d in documents_of_aircraft(a["id"]):
        if d["doc_kind"] in REQUIRED_DOC_KINDS and d["expires_at"] <= now:
            return "DOCUMENT_LAPSE", f"Required document {d['doc_kind']} has lapsed"
    return "AVAILABLE", None


# ---------------------------------------------------------------------------
# Interval predicates
# ---------------------------------------------------------------------------

def _overlaps(start1, end1, start2, end2):
    """Half-open interval intersection: [start1, end1) vs [start2, end2)."""
    return start1 < end2 and start2 < end1


def aircraft_buffered_interval(leg):
    """[departure - 90min, arrival + 90min) — the turn buffer applies to both
    ends of the interval (PRD 3.3)."""
    buf = timedelta(minutes=TURN_BUFFER_MINUTES)
    return (leg["scheduled_departure_utc"] - buf,
            leg["scheduled_arrival_utc"] + buf)


def aircraft_interval_conflict(aircraft_id, leg, occupancy):
    """Buffered half-open overlap on the same tail (aircraft_interval_overlap):
    the candidate leg's buffered interval intersects an occupied leg's
    buffered interval. Half-open: buffered start exactly equal to the other's
    buffered end does not overlap."""
    ls, le = aircraft_buffered_interval(leg)
    for other in occupancy:
        if other["aircraft_id"] != aircraft_id:
            continue
        os_, oe = aircraft_buffered_interval(other)
        if _overlaps(ls, le, os_, oe):
            return True
    return False


def crew_interval_conflict(crew_id, leg):
    """Unbuffered half-open overlap against CREWED/RELEASED legs where the
    crew member serves as PIC or SIC. Adjacent endpoints are permitted."""
    ls, le = leg["scheduled_departure_utc"], leg["scheduled_arrival_utc"]
    for other in db.flight_legs.values():
        if other["id"] == leg["id"]:
            continue
        if other["status"] not in CREW_HOLDING_STATUSES:
            continue
        if crew_id not in (other["pic_crew_id"], other["sic_crew_id"]):
            continue
        if _overlaps(ls, le, other["scheduled_departure_utc"],
                     other["scheduled_arrival_utc"]):
            return True
    return False


def maintenance_conflict(aircraft_id, leg):
    """True when any PLANNED/IN_PROGRESS window on the tail intersects the
    leg's own scheduled interval (departure inclusive, arrival exclusive)."""
    ls, le = leg["scheduled_departure_utc"], leg["scheduled_arrival_utc"]
    for w in windows_of_aircraft(aircraft_id):
        if w["status"] not in ("PLANNED", "IN_PROGRESS"):
            continue
        if _overlaps(w["window_start_utc"], w["window_end_utc"], ls, le):
            return True
    return False


# ---------------------------------------------------------------------------
# Duty windows (SCAFFOLD duty_time_check)
# ---------------------------------------------------------------------------

def _window_open_for(crew, departure):
    """Effective duty window for a leg departing at `departure`: if the leg
    departs outside the crew member's current 24h window (or none is open),
    a fresh window opens at the departure and used minutes reset to zero."""
    start = crew["duty_window_start_utc"]
    if start is None:
        return 0
    if not (start <= departure < start + timedelta(hours=DUTY_WINDOW_HOURS)):
        return 0
    return crew["duty_minutes_used"]


def duty_check_passes(crew, leg):
    """Inclusive boundary: used + block <= 840 is permitted."""
    return _window_open_for(crew, leg["scheduled_departure_utc"]) + leg["block_minutes"] <= DUTY_LIMIT_MINUTES


def accrue_duty(trip):
    """Dispatch side effect: each leg's block minutes are charged to that
    leg's PIC and SIC; a fresh duty window opens at the leg's departure when
    the leg falls outside the crew member's current window."""
    crew_leg_map = {}
    for lg in legs_of_trip(trip["id"]):
        if lg["status"] not in ("CREWED", "RELEASED", "COMPLETED"):
            continue
        for cid in (lg["pic_crew_id"], lg["sic_crew_id"]):
            if cid is None:
                continue
            crew_leg_map.setdefault(cid, []).append(lg)
    for cid, legs in crew_leg_map.items():
        crew = db.crew_members.get(cid)
        if crew is None:
            continue
        for lg in sorted(legs, key=lambda l: (l["scheduled_departure_utc"], l["_seq"])):
            dep = lg["scheduled_departure_utc"]
            start = crew["duty_window_start_utc"]
            if start is None or not (start <= dep < start + timedelta(hours=DUTY_WINDOW_HOURS)):
                crew["duty_window_start_utc"] = dep
                crew["duty_minutes_used"] = 0
            crew["duty_minutes_used"] += lg["block_minutes"]
        touch(crew)


# ---------------------------------------------------------------------------
# Aircraft selector (SCAFFOLD aircraft_selector) with staged error attribution
# ---------------------------------------------------------------------------

def select_aircraft(trip, leg, occupancy):
    """Pick an aircraft for one PLANNED leg.

    Candidate elimination follows the validation priority order so the
    surfaced error is deterministic when the pool empties:
      posture/availability (ERR_AIRCRAFT_NOT_AVAILABLE) ->
      buffered interval conflict (ERR_AIRCRAFT_INTERVAL_CONFLICT) ->
      maintenance-window conflict (ERR_MAINTENANCE_CONFLICT) ->
      capacity / empty fleet (ERR_NO_CANDIDATE_AIRCRAFT).
    """
    pool = list(db.aircraft.values())
    if not pool:
        raise err("ERR_NO_CANDIDATE_AIRCRAFT", 422,
                  "Selector candidate pool is empty; trip is charter-eligible")

    pool = [a for a in pool
            if a["status"] == "ACTIVE" and aircraft_posture(a)[0] == "AVAILABLE"]
    if not pool:
        raise err("ERR_AIRCRAFT_NOT_AVAILABLE", 422,
                  "No aircraft with AVAILABLE posture can take this leg")

    pool = [a for a in pool
            if not aircraft_interval_conflict(a["id"], leg, occupancy)]
    if not pool:
        raise err("ERR_AIRCRAFT_INTERVAL_CONFLICT", 422,
                  "Every available aircraft has a buffered interval conflict")

    pool = [a for a in pool if not maintenance_conflict(a["id"], leg)]
    if not pool:
        raise err("ERR_MAINTENANCE_CONFLICT", 422,
                  "A maintenance window intersects the leg interval on every candidate")

    needed = len(trip["passenger_ids"])
    pool = [a for a in pool if a["passenger_capacity"] >= needed]
    if not pool:
        raise err("ERR_NO_CANDIDATE_AIRCRAFT", 422,
                  "Selector candidate pool is empty; trip is charter-eligible")

    # Ranking: smallest sufficient capacity, home-base match, created_at ASC.
    pool.sort(key=lambda a: (a["passenger_capacity"],
                             0 if a["home_base_icao"] == leg["origin_icao"] else 1,
                             a["created_at"], a["_seq"]))
    return pool[0]


def run_assignment(trip):
    """Run the selector over every PLANNED leg (leg_sequence ASC). Atomic:
    any failure leaves the trip untouched."""
    planned = [lg for lg in legs_of_trip(trip["id"]) if lg["status"] == "PLANNED"]
    planned.sort(key=lambda l: (l["leg_sequence"], l["_seq"]))
    # Occupancy snapshot: legs already holding tails before this pass begins.
    # Tentative in-pass assignments do not join the conflict set, so legs of
    # the same trip may share a tail when their buffered intervals permit.
    occupancy = [lg for lg in db.flight_legs.values()
                 if lg["status"] in AIRCRAFT_HOLDING_STATUSES]
    picks = []
    for lg in planned:
        picks.append((lg, select_aircraft(trip, lg, occupancy)))
    return picks


# ---------------------------------------------------------------------------
# SIFL imputed income (SCAFFOLD sifl_imputed_income)
# ---------------------------------------------------------------------------

def personal_use_passengers(trip):
    """Which passengers generate imputed income, by trip_kind."""
    if trip["trip_kind"] == "PERSONAL":
        return list(trip["passenger_ids"])
    if trip["trip_kind"] == "MIXED":
        return [trip["requester_id"]]
    return []


def find_rate_period(instant):
    """The SiflRatePeriod whose [start, end) contains the instant."""
    for p in db.sifl_rate_periods.values():
        if p["period_start_utc"] <= instant < p["period_end_utc"]:
            return p
    return None


def sifl_line_cents(period, leg, passenger):
    """Per-(leg, passenger) SIFL charge, rounded half-up to whole cents
    BEFORE any summation (rounding order is pinned)."""
    miles = leg["distance_statute_miles"]
    band1 = min(miles, BAND_1_MAX_MILES)
    band2 = max(0, min(miles, BAND_2_MAX_MILES) - BAND_1_MAX_MILES)
    band3 = max(0, miles - BAND_2_MAX_MILES)
    base = (period["terminal_charge_cents"]
            + band1 * period["rate_band_1_cents_per_mile"]
            + band2 * period["rate_band_2_cents_per_mile"]
            + band3 * period["rate_band_3_cents_per_mile"])
    if passenger["sifl_control_employee"]:
        line = D(base) * D(period["control_employee_multiplier_pct"]) / D(100)
        return round_half_up_cents(line)
    return int(base)


def compute_sifl(trip, leg_filter):
    """Sum over (leg, personal-use passenger) lines.

    leg_filter: predicate over the trip's legs selecting the variant's input
    set (final: COMPLETED only; provisional: all legs regardless of status).
    Returns (total_cents, leg_count_included).
    """
    total = 0
    count = 0
    pax_ids = personal_use_passengers(trip)
    for lg in legs_of_trip(trip["id"]):
        if not leg_filter(lg):
            continue
        count += 1
        for pid in pax_ids:
            pax = db.passengers.get(pid)
            if pax is None:
                continue
            period = find_rate_period(lg["scheduled_arrival_utc"])
            if period is None:
                raise err("ERR_RATE_PERIOD_NOT_FOUND", 422,
                          "No SiflRatePeriod covers a leg's scheduled_arrival_utc")
            total += sifl_line_cents(period, lg, pax)
    return total, count


# ---------------------------------------------------------------------------
# Trip cost allocation (SCAFFOLD trip_cost_allocation)
# ---------------------------------------------------------------------------

def compute_allocation(trip):
    """Owned-fleet variant: block_minutes x aircraft-type rate + services.
    Charter variant: prorated share of the ACCEPTED charter quote with the
    cent remainder credited/debited to the highest leg_sequence leg so the
    shares sum exactly to the quote."""
    completed = [lg for lg in legs_of_trip(trip["id"]) if lg["status"] == "COMPLETED"]
    completed.sort(key=lambda l: (l["leg_sequence"], l["created_at"], l["_seq"]))

    charter = accepted_charter_for_trip(trip["id"])
    if charter is not None:
        quote = charter["quoted_cost_cents"]
        total_block = sum(lg["block_minutes"] for lg in completed)
        shares = []
        for lg in completed:
            if total_block > 0:
                share = round_half_up_cents(
                    D(quote) * D(lg["block_minutes"]) / D(total_block))
            else:
                share = 0
            shares.append(share)
        if completed:
            remainder = quote - sum(shares)
            shares[-1] += remainder
        return sum(shares)

    total = 0
    for lg in completed:
        aircraft = db.aircraft.get(lg["aircraft_id"]) if lg["aircraft_id"] else None
        rate = COST_PER_MINUTE_CENTS[aircraft["aircraft_type"]] if aircraft else 0
        catering = sum(o["quoted_cost_cents"] for o in catering_of_leg(lg["id"])
                       if o["status"] == "DELIVERED")
        ground = sum(t["quoted_cost_cents"] for t in transports_of_leg(lg["id"])
                     if t["status"] == "COMPLETED")
        total += lg["block_minutes"] * rate + catering + ground
    return total


# ---------------------------------------------------------------------------
# Cascades (SCAFFOLD state-machine side effects)
# ---------------------------------------------------------------------------

def cascade_leg_cancelled(leg):
    """Leg -> CANCELLED side effect: services still REQUESTED/CONFIRMED are
    cancelled with it."""
    for o in catering_of_leg(leg["id"]):
        if o["status"] in ("REQUESTED", "CONFIRMED"):
            o["status"] = "CANCELLED"
            touch(o)
    for t in transports_of_leg(leg["id"]):
        if t["status"] in ("REQUESTED", "CONFIRMED"):
            t["status"] = "CANCELLED"
            touch(t)


def cascade_trip_terminal(trip, only_planned_legs=False):
    """Trip reject/cancel cascade: legs drop to CANCELLED, services still
    REQUESTED/CONFIRMED cascade with them."""
    for lg in legs_of_trip(trip["id"]):
        if only_planned_legs:
            targets = ("PLANNED",)
        else:
            targets = ("PLANNED", "AIRCRAFT_ASSIGNED", "CREWED", "RELEASED")
        if lg["status"] in targets:
            lg["status"] = "CANCELLED"
            touch(lg)
            cascade_leg_cancelled(lg)


def cascade_aircraft_grounded(aircraft):
    """Ground side effect: every leg holding this tail in AIRCRAFT_ASSIGNED
    or CREWED reverts to PLANNED with the aircraft (and crew pairing)
    cleared, freeing the trip for a fresh assignment pass."""
    for lg in db.flight_legs.values():
        if lg["aircraft_id"] != aircraft["id"]:
            continue
        if lg["status"] not in ("AIRCRAFT_ASSIGNED", "CREWED"):
            continue
        lg["aircraft_id"] = None
        lg["pic_crew_id"] = None
        lg["sic_crew_id"] = None
        lg["status"] = "PLANNED"
        touch(lg)


# ---------------------------------------------------------------------------
# Logical clock advance (PRD 2.4): four automatic consequences
# ---------------------------------------------------------------------------

def advance_clock(to_dt):
    db.clock = to_dt
    now = db.now()
    # Maintenance windows whose start has been reached move to IN_PROGRESS.
    for w in db.maintenance_windows.values():
        if w["status"] == "PLANNED" and w["window_start_utc"] <= now:
            w["status"] = "IN_PROGRESS"
            touch(w)
    # Charter quotes still QUOTED expire once the trip's departure has passed.
    for c in db.charter_supplements.values():
        if c["status"] != "QUOTED":
            continue
        trip = db.trips.get(c["trip_request_id"])
        if trip is not None and now > trip["requested_departure_utc"]:
            c["status"] = "EXPIRED"
            touch(c)
    # DocumentPermit.status and Aircraft.posture are derived on read against
    # the logical clock, so their recomputation is implicit.
