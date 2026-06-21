"""IROPS cascade tear-down logic (PRD §3.9)."""
import db
from services import occupancy


def irops_cancel_cascade(flight):
    """Cancel cascade: assignments -> CANCELLED, CUTE/GSE HELD -> CANCELLED,
    REQUESTED/CONFIRMED slot permits -> FORFEITED.

    Order (PRD §3.9): assignments first (with pinned counter reconciliation),
    then CUTE/GSE allocations, then slot permits.
    """
    fid = flight["id"]

    # 1) GateAssignments in {PLANNED, OCCUPIED, TOWED_AWAY} -> CANCELLED
    for a in db.gate_assignments.values():
        if a.get("flight_id") != fid:
            continue
        if a["status"] in ("PLANNED", "OCCUPIED", "TOWED_AWAY"):
            occupancy.teardown_counters(a)  # pinned step 1 + step 2
            a["status"] = "CANCELLED"
            db.touch(a)

    # 2) HELD CuteAllocations -> CANCELLED
    for c in db.cute_allocations.values():
        if c.get("flight_id") == fid and c["status"] == "HELD":
            c["status"] = "CANCELLED"
            db.touch(c)

    # 2b) HELD GseAllocations -> CANCELLED
    for g in db.gse_allocations.values():
        if g.get("flight_id") == fid and g["status"] == "HELD":
            g["status"] = "CANCELLED"
            db.touch(g)

    # 3) REQUESTED/CONFIRMED SlotPermits -> FORFEITED
    for p in db.slot_permits.values():
        if p.get("flight_id") == fid and p["status"] in ("REQUESTED", "CONFIRMED"):
            p["status"] = "FORFEITED"
            db.touch(p)


def irops_divert_cascade(flight):
    """Divert cascade: PLANNED/OCCUPIED GateAssignments -> RELEASED, counters
    decremented. Slots, CUTE, GSE are kept untouched (PRD §3.9)."""
    fid = flight["id"]
    for a in db.gate_assignments.values():
        if a.get("flight_id") != fid:
            continue
        if a["status"] in ("PLANNED", "OCCUPIED"):
            occupancy.teardown_counters(a)
            a["status"] = "RELEASED"
            db.touch(a)
