"""Shared computation helpers: posture, counts, calculations, serialization.

All durations use Decimal arithmetic and round_half_up to two decimal places.
All entities are plain dicts living in db.store. created_at/updated_at/version
common-field bookkeeping is centralized here.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import store, iso

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations)
# ---------------------------------------------------------------------------
SURGE_HIGH_PCT = Decimal("85.0")
SURGE_CRITICAL_PCT = Decimal("95.0")
LONG_STAY_MULT = Decimal("1.5")
ED_BOARDING_SLA_HOURS = Decimal("4.0")
REQUEST_EXPIRY_RUNS = 2

ISO_WASTE_PENALTY = -10
TELE_WASTE_PENALTY = -5
PREFERRED_UNIT_BONUS = 50
PLACEMENT_POSTURE_BONUS = {"GREEN": 20, "YELLOW": 10, "RED": 0, "CLOSED": 0}

EVS_TYPE_BASE = {"STAT": 100, "ISOLATION": 70, "ROUTINE": 40}
EVS_POSTURE_BONUS = {"RED": 30, "YELLOW": 15, "GREEN": 0, "CLOSED": 0}
AGING_WINDOW_MIN = 30
AGING_STEP = 5

POSTURE_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2, "CLOSED": 3}

STAFFED_STATUSES = {"CLEAN", "DIRTY", "OCCUPIED"}


# ---------------------------------------------------------------------------
# Common-field bookkeeping
# ---------------------------------------------------------------------------
def stamp_new(record):
    """Set id/created_at/updated_at/version for a freshly created entity."""
    now = iso(store.clock_now())
    # created_at/updated_at reflect record bookkeeping; here we use the simulated
    # clock so they stay consistent and monotone with business time under tests.
    record.setdefault("id", store.new_id())
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    # store raw clock for deterministic tie-breaks (created_at ASC)
    record["_created_clock"] = store.clock_now()
    return record


def touch(record):
    """Bump updated_at + version on a mutation."""
    record["updated_at"] = iso(store.clock_now())
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round2(value):
    """round_half_up to 2 decimal places, returning a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# Unit counts + posture
# ---------------------------------------------------------------------------
def unit_beds(unit_id):
    return [b for b in store.beds.values() if b["unit_id"] == unit_id]


def declared_surge_level(unit_id):
    """Highest level among OPEN SurgeEvents for the unit (GREEN<YELLOW<RED)."""
    rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    best = "GREEN"
    for s in store.surge_events.values():
        if s["unit_id"] == unit_id and s["status"] == "OPEN":
            if rank[s["level"]] > rank[best]:
                best = s["level"]
    return best


def recompute_unit(unit):
    """Recompute all derived count + posture fields for a unit in place."""
    beds = unit_beds(unit["id"])
    total = sum(1 for b in beds if b["status"] != "RETIRED")
    staffed = sum(1 for b in beds if b["status"] in STAFFED_STATUSES)
    occupied = sum(1 for b in beds if b["status"] == "OCCUPIED")
    clean = sum(1 for b in beds if b["status"] == "CLEAN")

    unit["total_bed_count"] = total
    unit["staffed_bed_count"] = staffed
    unit["occupied_bed_count"] = occupied
    unit["clean_available_count"] = clean

    if staffed == 0:
        unit["occupancy_pct"] = 0.00
        derived = "CLOSED"
    else:
        pct = Decimal(occupied) / Decimal(staffed) * Decimal(100)
        pct = pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        unit["occupancy_pct"] = float(pct)
        if pct >= SURGE_CRITICAL_PCT:
            derived = "RED"
        elif pct >= SURGE_HIGH_PCT:
            derived = "YELLOW"
        else:
            derived = "GREEN"

    unit["derived_posture"] = derived
    declared = declared_surge_level(unit["id"])
    unit["declared_surge_level"] = declared
    # effective = max severity of derived and declared
    if POSTURE_RANK[derived] >= POSTURE_RANK[declared]:
        unit["effective_posture"] = derived
    else:
        unit["effective_posture"] = declared


def get_unit_effective_posture(unit_id):
    unit = store.units.get(unit_id)
    if unit is None:
        return "CLOSED"
    recompute_unit(unit)
    return unit["effective_posture"]


# ---------------------------------------------------------------------------
# Encounter time calculations
# ---------------------------------------------------------------------------
def _parse_iso(s):
    """Parse one of our iso() strings back to a datetime for math (rarely needed)."""
    from datetime import datetime, timezone
    if s is None:
        return None
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2).astimezone(timezone.utc)


def _hours_between(start_dt, end_dt):
    delta = (end_dt - start_dt).total_seconds() / 3600.0
    return round2(delta)


def encounter_placement_unit(enc):
    """Unit owning the encounter's current bed, or last bed if discharged."""
    bed_id = enc.get("current_bed_id")
    if bed_id is None and enc.get("status") == "DISCHARGED":
        bed_id = enc.get("_last_bed_id")
    if bed_id is None:
        return None
    bed = store.beds.get(bed_id)
    if bed is None:
        return None
    return store.units.get(bed["unit_id"])


def recompute_encounter(enc):
    """Recompute live derived fields on an Encounter (LOS, boarding, barriers)."""
    now = store.clock_now()

    # open barrier count
    enc["open_barrier_count"] = sum(
        1 for b in store.discharge_barriers.values()
        if b["encounter_id"] == enc["id"] and b["status"] == "OPEN"
    )

    # boarding hours
    status = enc["status"]
    admit_decision = enc.get("_admit_decision_dt")
    if status == "BOARDING" and admit_decision is not None:
        enc["boarding_hours"] = _hours_between(admit_decision, now)
    elif enc.get("_boarding_frozen") is not None:
        enc["boarding_hours"] = enc["_boarding_frozen"]
    else:
        enc["boarding_hours"] = 0.00
    enc["boarding_breached"] = Decimal(str(enc["boarding_hours"])) >= ED_BOARDING_SLA_HOURS

    # length of stay
    admitted = enc.get("_admitted_dt")
    if admitted is None:
        enc["length_of_stay_hours"] = 0.00
        enc["long_stay_flag"] = False
    else:
        if status == "DISCHARGED":
            end = enc.get("_discharged_dt")
        else:
            end = now
        los = _hours_between(admitted, end)
        enc["length_of_stay_hours"] = los
        unit = encounter_placement_unit(enc)
        if unit is not None:
            threshold = Decimal(str(unit.get("gmlos_days", 3))) * Decimal(24) * LONG_STAY_MULT
            enc["long_stay_flag"] = Decimal(str(los)) >= threshold
        else:
            enc["long_stay_flag"] = False


# ---------------------------------------------------------------------------
# EVS priority score
# ---------------------------------------------------------------------------
def evs_priority_score(task):
    bed = store.beds.get(task["bed_id"])
    base = EVS_TYPE_BASE[task["task_type"]]
    posture = "CLOSED"
    if bed is not None:
        posture = get_unit_effective_posture(bed["unit_id"])
    surge = EVS_POSTURE_BONUS.get(posture, 0)
    requested = task.get("_requested_dt")
    if requested is None:
        wait_minutes = 0
    else:
        wait_minutes = math.floor((store.clock_now() - requested).total_seconds() / 60)
        if wait_minutes < 0:
            wait_minutes = 0
    aging = math.floor(wait_minutes / AGING_WINDOW_MIN) * AGING_STEP
    return base + surge + aging


def recompute_evs_task(task):
    task["priority_score"] = evs_priority_score(task)


# ---------------------------------------------------------------------------
# Serialization — strip private fields (keys starting with "_")
# ---------------------------------------------------------------------------
def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_unit(unit):
    recompute_unit(unit)
    return public(unit)


def serialize_bed(bed):
    return public(bed)


def serialize_encounter(enc):
    recompute_encounter(enc)
    return public(enc)


def serialize_bed_request(req):
    return public(req)


def serialize_evs_task(task):
    recompute_evs_task(task)
    return public(task)


def serialize_barrier(b):
    return public(b)


def serialize_surge(s):
    return public(s)


def serialize_huddle(h):
    return public(h)


def serialize_adt(ev):
    return public(ev)
