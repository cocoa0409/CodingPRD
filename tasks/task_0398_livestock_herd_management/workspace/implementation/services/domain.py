"""Cross-cutting domain computations: animal-unit load, herd/pasture derived
fields, mortality rate, ADG, trace-event appending, and residue (clearance)
re-derivation.

Constants and formulas come from SCAFFOLD §1.3 and PRD §2.7-2.9, §3.4-3.6,
§3.11.
"""
from datetime import timedelta

from db import db, new_id, now_iso
from clock import clock
from util import round_half_up
from services.common import touch

AU_KG = 454                      # kg per animal-unit (PRD §2.7)
GESTATION_DAYS = {"CATTLE": 283, "SHEEP": 147, "GOAT": 150}
MORTALITY_WINDOW_DAYS = 365
ACTIVE_STATES = ("ACTIVE", "SUSPENDED")


# --------------------------------------------------------------------------
# Animal-unit load
# --------------------------------------------------------------------------
def animal_au(animal):
    """Full-precision AU contribution of one animal (NOT rounded per-animal)."""
    return animal["latest_weight_kg"] / AU_KG


def recompute_herd_loads(herd):
    """Recompute Herd.active_animal_count and total_au_load from live animals."""
    count = 0
    total = 0.0
    for a in db.animals.values():
        if a["herd_id"] == herd["id"] and a["life_status"] in ACTIVE_STATES:
            count += 1
            total += animal_au(a)
    herd["active_animal_count"] = count
    herd["total_au_load"] = round_half_up(total, 3)


def recompute_pasture_load(pasture):
    """Recompute Pasture.current_au_load from animals currently located there."""
    total = 0.0
    for a in db.animals.values():
        if a.get("current_pasture_id") == pasture["id"] and a["life_status"] in ACTIVE_STATES:
            total += animal_au(a)
    pasture["current_au_load"] = round_half_up(total, 3)


def recompute_pasture_by_id(pasture_id):
    if pasture_id and pasture_id in db.pastures:
        recompute_pasture_load(db.pastures[pasture_id])
        touch(db.pastures[pasture_id])


def herd_mortality_rate(herd):
    """Rolling mortality % over the trailing MORTALITY_WINDOW_DAYS window.

    deaths = RECORDED MortalityRecords for animals in this herd whose died_on
             is on or after window_start (clock_today - 365 days).
    denom  = active_animal_count + deaths.
    rate   = round(deaths / denom * 100, 2), or 0.00 when denom == 0.
    """
    today = clock.today()
    window_start = today - timedelta(days=MORTALITY_WINDOW_DAYS)
    herd_animal_ids = {a["id"] for a in db.animals.values() if a["herd_id"] == herd["id"]}
    deaths = 0
    for m in db.mortality_records.values():
        if m["status"] != "RECORDED":
            continue
        if m["animal_id"] not in herd_animal_ids:
            continue
        if m["died_on"] >= window_start:
            deaths += 1
    denom = herd["active_animal_count"] + deaths
    if denom <= 0:
        return 0.0
    return round_half_up(deaths / denom * 100.0, 2)


def recompute_mortality_rate(herd):
    herd["mortality_rate_pct"] = herd_mortality_rate(herd)


# --------------------------------------------------------------------------
# Average daily gain
# --------------------------------------------------------------------------
def _animal_weight_records(animal_id):
    recs = [w for w in db.weight_records.values() if w["animal_id"] == animal_id]
    # order by weighed_at, tie-break created_at (use creation sequence) ASC
    recs.sort(key=lambda w: (w["weighed_at"], w["_seq"]))
    return recs


def recompute_animal_weight_derived(animal):
    """Set Animal.latest_weight_kg and lifetime_adg_kg from its weight records."""
    recs = _animal_weight_records(animal["id"])
    if not recs:
        animal["latest_weight_kg"] = animal["birth_weight_kg"]
        animal["lifetime_adg_kg"] = 0.0
        return
    latest = recs[-1]
    animal["latest_weight_kg"] = latest["weight_kg"]
    age_days = (latest["weighed_at"] - animal["birth_date"]).days
    if age_days > 0:
        animal["lifetime_adg_kg"] = round_half_up(
            (latest["weight_kg"] - animal["birth_weight_kg"]) / age_days, 3)
    else:
        animal["lifetime_adg_kg"] = 0.0


def compute_interval_adg(animal_id, this_record):
    """Interval ADG for a newly-created weight record: gain since the prior
    record by weighed_at (tie-break created_at ASC). None for the first."""
    recs = _animal_weight_records(animal_id)
    prev = None
    for w in recs:
        if w["id"] == this_record["id"]:
            continue
        if (w["weighed_at"], w["_seq"]) < (this_record["weighed_at"], this_record["_seq"]):
            prev = w  # recs is sorted ascending, so last qualifying is the closest prior
    if prev is None:
        return None
    gap_days = (this_record["weighed_at"] - prev["weighed_at"]).days
    if gap_days <= 0:
        return None
    return round_half_up((this_record["weight_kg"] - prev["weight_kg"]) / gap_days, 3)


# --------------------------------------------------------------------------
# Trace chain
# --------------------------------------------------------------------------
def append_trace(animal_id, event_type, ref_entity, ref_id, occurred_on, detail=None):
    """Append an immutable TraceEvent (id + created_at only).

    occurred_on is a datetime.date (business date of the event).
    """
    ev = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "animal_id": animal_id,
        "event_type": event_type,
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "occurred_on": occurred_on,            # stored as date
        "detail": detail if detail is not None else {},
    }
    db.trace_events[ev["id"]] = ev
    return ev


# --------------------------------------------------------------------------
# Residue / meat clearance re-derivation
# --------------------------------------------------------------------------
def active_withholding_treatments(animal_id, after_date):
    """Non-VOIDED treatments for the animal whose clearance_date > after_date."""
    out = []
    for t in db.health_treatments.values():
        if t["animal_id"] != animal_id:
            continue
        if t["status"] == "VOIDED":
            continue
        if t["clearance_date"] is not None and t["clearance_date"] > after_date:
            out.append(t)
    return out


def rederive_clearance_for_animal(animal):
    """Recompute meat_clearance_status / meat_clear_on from remaining treatments
    against the current clock date. Drives WITHHELD->CLEAR when nothing holds.

    Returns True if the animal record was mutated."""
    today = clock.today()
    holding = active_withholding_treatments(animal["id"], today)
    mutated = False
    if holding:
        new_clear_on = max(t["clearance_date"] for t in holding)
        if animal["meat_clearance_status"] != "WITHHELD" or animal.get("meat_clear_on") != new_clear_on:
            mutated = True
        animal["meat_clearance_status"] = "WITHHELD"
        animal["meat_clear_on"] = new_clear_on
    else:
        if animal["meat_clearance_status"] != "CLEAR" or animal.get("meat_clear_on") is not None:
            mutated = True
        animal["meat_clearance_status"] = "CLEAR"
        animal["meat_clear_on"] = None
    return mutated
