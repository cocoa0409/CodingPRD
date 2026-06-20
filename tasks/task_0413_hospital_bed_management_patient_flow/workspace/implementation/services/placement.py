"""Bed-eligibility safety checks, auto-place selector, and EVS auto-task creation.

The four checks (isolation, telemetry, cohort, availability) apply identically to
assign, confirm, and transfer — evaluated in that fixed order (PRD §2.11).
"""

from decimal import Decimal

import errors
from errors import err
from db import store
from services import common


# ---------------------------------------------------------------------------
# Safety checks for a concrete (patient -> bed) placement
# ---------------------------------------------------------------------------
def check_bed_safety(encounter, bed):
    """Run isolation -> telemetry -> cohort -> availability in order. Raises on
    the first violation; returns None on success."""
    # isolation
    if encounter.get("requires_isolation") and not bed.get("isolation_capable"):
        raise err(errors.ERR_ISOLATION_REQUIRED,
                  "Patient requires isolation but bed is not isolation_capable")
    # telemetry
    if encounter.get("requires_telemetry") and not bed.get("telemetry_capable"):
        raise err(errors.ERR_TELEMETRY_REQUIRED,
                  "Patient requires telemetry but bed is not telemetry_capable")
    # cohort (SEMIPRIVATE only)
    if bed.get("room_type") == "SEMIPRIVATE":
        cohort = bed.get("sex_cohort", "NONE")
        if cohort not in ("NONE", encounter["sex"]):
            raise err(errors.ERR_COHORT_CONFLICT,
                      "SEMIPRIVATE bed cohort conflicts with patient sex")
    # availability
    if bed.get("status") != "CLEAN":
        raise err(errors.ERR_BED_NOT_AVAILABLE, "Target bed is not CLEAN")


# ---------------------------------------------------------------------------
# Eligibility predicate for the auto-place candidate pool
# ---------------------------------------------------------------------------
def is_eligible(bed, encounter, acceptable_unit_types):
    if bed.get("status") != "CLEAN":
        return False
    unit = store.units.get(bed["unit_id"])
    if unit is None:
        return False
    if acceptable_unit_types:
        if unit["unit_type"] not in acceptable_unit_types:
            return False
    if encounter.get("requires_isolation") and not bed.get("isolation_capable"):
        return False
    if encounter.get("requires_telemetry") and not bed.get("telemetry_capable"):
        return False
    if bed.get("room_type") == "SEMIPRIVATE":
        cohort = bed.get("sex_cohort", "NONE")
        if cohort not in ("NONE", encounter["sex"]):
            return False
    return True


def match_score(bed, encounter, preferred_unit_id):
    """Integer placement match score (PRD §3.4)."""
    score = 0
    if bed.get("isolation_capable") and not encounter.get("requires_isolation"):
        score += common.ISO_WASTE_PENALTY
    if bed.get("telemetry_capable") and not encounter.get("requires_telemetry"):
        score += common.TELE_WASTE_PENALTY
    posture = common.get_unit_effective_posture(bed["unit_id"])
    score += common.PLACEMENT_POSTURE_BONUS.get(posture, 0)
    if preferred_unit_id is not None and bed["unit_id"] == preferred_unit_id:
        score += common.PREFERRED_UNIT_BONUS
    return score


def select_best_bed(encounter, acceptable_unit_types, preferred_unit_id):
    """Pick the highest-scoring eligible bed; tie-break occupancy_pct ASC then
    created_at ASC. Returns (bed, score) or (None, None) when pool empty."""
    candidates = []
    for bed in store.beds.values():
        if is_eligible(bed, encounter, acceptable_unit_types):
            score = match_score(bed, encounter, preferred_unit_id)
            unit = store.units.get(bed["unit_id"])
            common.recompute_unit(unit)
            occ = Decimal(str(unit["occupancy_pct"]))
            candidates.append((score, occ, bed["_created_clock"], bed))
    if not candidates:
        return None, None
    # max score; tie-break: lower occupancy_pct, then earlier created_at
    best = max(
        candidates,
        key=lambda c: (c[0], -float(c[1]), -c[2].timestamp()),
    )
    return best[3], best[0]


# ---------------------------------------------------------------------------
# Bed status side-effects (CLEAN->OCCUPIED, OCCUPIED->DIRTY) + auto EvsTask
# ---------------------------------------------------------------------------
def occupy_bed(bed, encounter):
    """CLEAN -> OCCUPIED system side-effect."""
    bed["status"] = "OCCUPIED"
    bed["current_encounter_id"] = encounter["id"]
    bed["sex_cohort"] = encounter["sex"]
    common.touch(bed)
    unit = store.units.get(bed["unit_id"])
    if unit is not None:
        common.recompute_unit(unit)


def vacate_bed(bed, departing_encounter):
    """OCCUPIED -> DIRTY system side-effect on transfer-out/discharge/cancel.
    Auto-creates a REQUESTED EvsTask for the bed."""
    bed["status"] = "DIRTY"
    bed["current_encounter_id"] = None
    common.touch(bed)
    unit = store.units.get(bed["unit_id"])
    if unit is not None:
        common.recompute_unit(unit)
    # auto EvsTask
    task_type = "ISOLATION" if departing_encounter.get("requires_isolation") else "ROUTINE"
    create_auto_evs_task(bed, task_type)


def create_auto_evs_task(bed, task_type):
    now = store.clock_now()
    task = {
        "bed_id": bed["id"],
        "task_type": task_type,
        "status": "REQUESTED",
        "assigned_tech_id": None,
        "requested_at": None,
        "priority_score": 0,
        "_requested_dt": now,
    }
    common.stamp_new(task)
    from db import iso
    task["requested_at"] = iso(now)
    common.recompute_evs_task(task)
    store.evs_tasks[task["id"]] = task
    return task


def cancel_open_evs_tasks_for_bed(bed_id):
    """Cancel any non-terminal EvsTask on this bed (REQUESTED/ASSIGNED/IN_PROGRESS)."""
    for task in store.evs_tasks.values():
        if task["bed_id"] == bed_id and task["status"] in ("REQUESTED", "ASSIGNED", "IN_PROGRESS"):
            task["status"] = "CANCELLED"
            common.touch(task)
