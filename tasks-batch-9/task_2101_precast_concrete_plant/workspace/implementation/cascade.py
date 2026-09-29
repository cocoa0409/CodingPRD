"""Shared cascade hops (PRD 2.11). Every hop of a chain completes, and each row
a cascade touches is mutated: updated_at refreshed, version incremented."""
import calc
import db


def touch_project_of(piece):
    project = db.store.projects.get(piece["project_id"])
    if project is not None:
        db.touch(project)
    return project


def run_curing_cycles(run_id):
    return [c for c in db.store.curing_cycles.values() if c["bed_run_id"] == run_id]


def run_cylinder_sets(run_id):
    rows = [s for s in db.store.cylinder_sets.values() if s["bed_run_id"] == run_id]
    return db.by_seq(rows)


def curing_complete(run_id):
    """The run has at least one curing cycle and every one is COMPLETED."""
    cycles = run_curing_cycles(run_id)
    return bool(cycles) and all(c["status"] == "COMPLETED" for c in cycles)


def evaluate_release_ready(run):
    """CURING -> RELEASE_READY, evaluated after every break and every cycle
    completion (PRD 3.5). One-way: a run that already reached RELEASE_READY or
    RELEASED never reverts."""
    if run["status"] != "CURING":
        return False
    has_met_release_set = any(
        s["purpose"] == "RELEASE" and s["status"] == "RELEASE_MET"
        for s in run_cylinder_sets(run["id"]))
    if not has_met_release_set:
        return False
    if not curing_complete(run["id"]):
        return False

    run["status"] = "RELEASE_READY"
    db.touch(run)
    # hop: every piece held awaiting release strength clears
    for piece in db.store.pieces.values():
        if (piece["bed_run_id"] == run["id"]
                and piece["qc_status"] == "HOLD"
                and piece["qc_hold_reason"] == "AWAITING_RELEASE_STRENGTH"):
            piece["qc_status"] = "CLEARED"
            piece["qc_hold_reason"] = None
            db.touch(piece)
            touch_project_of(piece)
    return True


def active_placement_of(piece_id):
    for placement in db.store.yard_placements.values():
        if placement["piece_id"] == piece_id and placement["status"] == "ACTIVE":
            return placement
    return None


def release_placement(placement, reason):
    """Placement ACTIVE -> RELEASED plus its slot recompute."""
    placement["status"] = "RELEASED"
    placement["released_at"] = db.store.now_iso()
    placement["release_reason"] = reason
    db.touch(placement)
    slot = db.store.yard_slots.get(placement["yard_slot_id"])
    if slot is not None:
        db.touch(slot)
    return placement


def scrap_piece(piece):
    """Hops 2-4 of the reject-recast cascade (PRD 3.9)."""
    piece["qc_status"] = "REJECTED"
    piece["production_status"] = "SCRAPPED"
    piece["qc_hold_reason"] = None
    db.touch(piece)
    placement = active_placement_of(piece["id"])
    if placement is not None:
        release_placement(placement, "SCRAP")
    touch_project_of(piece)


def repair_piece(piece):
    """The Piece side of a report closing CLOSED_ACCEPTED (PRD 3.9)."""
    if piece["qc_status"] == "NONCONFORMING":
        piece["qc_status"] = "REPAIRED"
        piece["qc_hold_reason"] = None
        db.touch(piece)
    touch_project_of(piece)


def recompute_set_after_break(cylinder_set, run):
    """Rerun cylinder_set_qualified_strength over every break and restate the
    set, then attempt the release cascade."""
    mix = db.store.mix_designs.get(run["mix_design_id"])
    required = mix["required_release_psi"] if mix else 0
    changed = calc.recompute_cylinder_set(cylinder_set)
    for break_row in changed:
        db.touch(break_row)
    cylinder_set["status"] = calc.cylinder_set_status(cylinder_set, required)
    db.touch(cylinder_set)
    # The CURING -> RELEASE_READY move is re-evaluated after every break; the
    # evaluation itself requires a RELEASE set that has reached RELEASE_MET.
    evaluate_release_ready(run)
