"""Public serialization for each entity.

Strips internal-only keys (those starting with '_') and computes derived
read-only fields (e.g. Animal.milk_eligible against the logical clock,
Herd.active_animal_count).
"""
import db
import clock
from util import iso_format


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Derived / computed reads
# ---------------------------------------------------------------------------

def herd_active_animal_count(herd_id):
    """Count of this herd's animals whose status is ACTIVE or DRY (PRD §2.8)."""
    n = 0
    for a in db.animals.values():
        if a["herd_id"] == herd_id and a["status"] in ("ACTIVE", "DRY"):
            n += 1
    return n


def compute_milk_eligible(animal):
    """milk_eligible is false while any ACTIVE HealthTreatment on this animal has
    milk_withhold_until > current clock (SCAFFOLD Animal.milk_eligible).

    The stored animal["milk_eligible"] is the authoritative value (set on
    treatment record/clear/void/cull). This re-derives it against the live
    clock for reads so that advancing the clock past a withhold makes milk
    saleable again without an explicit mutation (PRD §3.9).
    """
    # Terminal animals keep their stored value (set false at cull).
    if animal["status"] in ("SOLD", "CULLED", "DIED"):
        return animal["milk_eligible"]
    now = clock.now()
    for t in db.health_treatments.values():
        if t["animal_id"] != animal["id"]:
            continue
        if t["status"] != "ACTIVE":
            continue
        withhold_until = t["_milk_withhold_until_dt"]
        if withhold_until > now:
            return False
    return True


# ---------------------------------------------------------------------------
# Per-entity serializers
# ---------------------------------------------------------------------------

def herd_out(rec):
    out = _public(rec)
    out["active_animal_count"] = herd_active_animal_count(rec["id"])
    return out


def parlor_out(rec):
    return _public(rec)


def ration_out(rec):
    return _public(rec)


def price_sheet_out(rec):
    return _public(rec)


def animal_out(rec):
    out = _public(rec)
    out["milk_eligible"] = compute_milk_eligible(rec)
    return out


def lactation_out(rec):
    return _public(rec)


def test_day_record_out(rec):
    return _public(rec)


def milking_shift_out(rec):
    return _public(rec)


def breeding_event_out(rec):
    return _public(rec)


def calving_event_out(rec):
    return _public(rec)


def health_treatment_out(rec):
    return _public(rec)


def milk_check_out(rec):
    return _public(rec)


def cull_decision_out(rec):
    return _public(rec)
