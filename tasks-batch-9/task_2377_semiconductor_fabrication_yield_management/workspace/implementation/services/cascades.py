"""Shared cascade machinery (PRD 2.9, 3.2, 3.3, 3.6, 3.7, 3.8).

Every row touched by a cascade is mutated through `touch()`, so it gets a fresh
`updated_at` and a `version` incremented by exactly 1.
"""
import calc
import clock
from db import db, new_row, ordered, touch
from util import r2, r4

HOLD_PRECEDENCE = {"NONE": 0, "SPC_HOLD": 1, "QUAL_HOLD": 2, "ENGINEERING_HOLD": 3}


# ------------------------------------------------------------------- lookups

def chambers_of(equipment_id):
    return [c for c in ordered(db.chambers.values()) if c["equipment_id"] == equipment_id]


def open_runs_on_equipment(equipment_id):
    ids = {c["id"] for c in db.chambers.values() if c["equipment_id"] == equipment_id}
    return [r for r in ordered(db.step_runs.values()) if r["chamber_id"] in ids and r["status"] == "OPEN"]


def open_runs_on_chamber(chamber_id):
    return [
        r for r in ordered(db.step_runs.values())
        if r["chamber_id"] == chamber_id and r["status"] == "OPEN"
    ]


def in_fab_lots_with_open_run_on_chamber(chamber_id):
    out = []
    seen = set()
    for run in open_runs_on_chamber(chamber_id):
        lot = db.lots.get(run["lot_id"])
        if lot is None or lot["id"] in seen:
            continue
        if lot["flow_state"] in ("RELEASED", "IN_PROCESS"):
            seen.add(lot["id"])
            out.append(lot)
    return out


def in_fab_lots_with_open_run_on_step(step_id):
    out = []
    seen = set()
    for run in ordered(db.step_runs.values()):
        if run["step_id"] != step_id or run["status"] != "OPEN":
            continue
        lot = db.lots.get(run["lot_id"])
        if lot is None or lot["id"] in seen:
            continue
        if lot["flow_state"] in ("RELEASED", "IN_PROCESS"):
            seen.add(lot["id"])
            out.append(lot)
    return out


# --------------------------------------------------------------- equipment

def maybe_idle(equipment):
    """PRODUCTIVE -> IDLE once the last OPEN run on the tool's chambers closes."""
    if equipment["state"] == "PRODUCTIVE" and not open_runs_on_equipment(equipment["id"]):
        equipment["state"] = "IDLE"
        touch(equipment)


def abort_run(run):
    """StepRun OPEN -> ABORTED; the full reservation is credited back (PRD 3.6)."""
    if run["status"] != "OPEN":
        return
    run["status"] = "ABORTED"
    run["tracked_out_at"] = clock.now()
    touch(run)
    chamber = db.chambers.get(run["chamber_id"])
    equipment = None
    if chamber is not None:
        chamber["occupancy_state"] = "FREE"
        touch(chamber)
        equipment = db.equipment.get(chamber["equipment_id"])
    if equipment is not None:
        equipment["available_capacity_hours"] = r2(
            equipment["available_capacity_hours"] + run["reserved_hours"]
        )
        touch(equipment)
        maybe_idle(equipment)


# -------------------------------------------------------------------- holds

def raise_hold(lot, target, excursion_id):
    """Holds only ever escalate along HOLD_PRECEDENCE (PRD 2.9)."""
    if HOLD_PRECEDENCE[target] <= HOLD_PRECEDENCE[lot["hold_state"]]:
        return False
    lot["hold_state"] = target
    lot["hold_excursion_id"] = excursion_id
    touch(lot)
    return True


def release_hold(lot):
    lot["hold_state"] = "NONE"
    lot["hold_excursion_id"] = None
    touch(lot)


# --------------------------------------------------------------- excursions

def new_excursion(source_type, trigger_value, spc_chart_id=None, die_sort_run_id=None,
                  chamber_id=None, lot_id=None, failure_signature="NONE", out_of_spec=False):
    row = new_row({
        "spc_chart_id": spc_chart_id,
        "die_sort_run_id": die_sort_run_id,
        "chamber_id": chamber_id,
        "lot_id": lot_id,
        "source_type": source_type,
        "trigger_value": r4(trigger_value),
        "severity_variant": "PROVISIONAL",
        "severity_score": 0.0,
        "severity_band": "LOW",
        "affected_lot_count": 0,
        "status": "OPEN",
        "containment_scope": "NONE",
        "contained_by_user_id": None,
        "dispositioned_by_user_id": None,
        "disposition": "NONE",
        "failure_signature": failure_signature,
        "_opening_out_of_spec": out_of_spec,
    })
    db.excursions[row["id"]] = row
    score, band, count = calc.severity(row, "PROVISIONAL")
    row["severity_score"] = score
    row["severity_band"] = band
    row["affected_lot_count"] = count
    return row


def finalize_severity(excursion):
    score, band, count = calc.severity(excursion, "FINAL")
    excursion["severity_variant"] = "FINAL"
    excursion["severity_score"] = score
    excursion["severity_band"] = band
    excursion["affected_lot_count"] = count


def disqualify_chamber(chamber, excursion):
    """CHAMBER-scope containment: disqualify, abort the open run, hold its lot."""
    held = in_fab_lots_with_open_run_on_chamber(chamber["id"])
    if chamber["qual_state"] == "QUALIFIED":
        chamber["qual_state"] = "DISQUALIFIED"
        chamber["qualified_at"] = None
        chamber["qual_expires_at"] = None
        touch(chamber)
    for run in open_runs_on_chamber(chamber["id"]):
        abort_run(run)
    for lot in held:
        raise_hold(lot, "QUAL_HOLD", excursion["id"])


def down_equipment(chamber, excursion):
    """EQUIPMENT-scope containment: tool DOWN first, then abort its open runs."""
    equipment = db.equipment.get(chamber["equipment_id"])
    if equipment is None:
        return
    held = in_fab_lots_with_open_run_on_chamber(chamber["id"])
    left_qualified = chamber["qual_state"] == "QUALIFIED"
    if equipment["state"] in ("IDLE", "PRODUCTIVE"):
        equipment["state"] = "DOWN"
        touch(equipment)
    if left_qualified:
        chamber["qual_state"] = "DISQUALIFIED"
        chamber["qualified_at"] = None
        chamber["qual_expires_at"] = None
        touch(chamber)
    for run in open_runs_on_equipment(equipment["id"]):
        abort_run(run)
    if left_qualified:
        for lot in held:
            raise_hold(lot, "QUAL_HOLD", excursion["id"])


def apply_containment(excursion, scope, chamber):
    if scope == "SPC_CHART":
        chart = db.spc_charts.get(excursion["spc_chart_id"])
        if chart is None:
            return
        if chart["status"] == "MONITORING":
            chart["status"] = "SUSPENDED"
            touch(chart)
        for lot in in_fab_lots_with_open_run_on_step(chart["step_id"]):
            raise_hold(lot, "SPC_HOLD", excursion["id"])
    elif scope == "CHAMBER":
        if chamber is not None:
            disqualify_chamber(chamber, excursion)
    elif scope == "EQUIPMENT":
        if chamber is not None:
            down_equipment(chamber, excursion)


def particle_escalation(chamber, reading):
    """A reading strictly above the limit opens and self-contains an excursion."""
    lot_id = None
    for run in open_runs_on_chamber(chamber["id"]):
        lot_id = run["lot_id"]
        break
    excursion = new_excursion("PARTICLE", reading, chamber_id=chamber["id"], lot_id=lot_id)
    scope = ("EQUIPMENT"
             if reading >= calc.PARTICLE_TOOL_DOWN_MULT * chamber["particle_limit"]
             else "CHAMBER")
    finalize_severity(excursion)
    excursion["containment_scope"] = scope
    excursion["status"] = "CONTAINED"
    touch(excursion)
    apply_containment(excursion, scope, chamber)
    return excursion


# ------------------------------------------------------- requalification cascade

def requalification_cascade(recipe_id):
    """Implementing a high-risk change unqualifies chambers and holds their lots."""
    for chamber in ordered(db.chambers.values()):
        if chamber["qualified_recipe_id"] != recipe_id or chamber["qual_state"] != "QUALIFIED":
            continue
        held = in_fab_lots_with_open_run_on_chamber(chamber["id"])
        chamber["qual_state"] = "UNQUALIFIED"
        chamber["qualified_at"] = None
        chamber["qual_expires_at"] = None
        touch(chamber)
        for lot in held:
            raise_hold(lot, "QUAL_HOLD", None)
