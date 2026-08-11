"""Plant-wide safety cascades and lazy fumigation clearance (PRD §2.5, §2.10)."""
import db
from services import calc


def unblock_shipments():
    """BLOCKED shipments whose allocated placements are all STORED -> PLANNED."""
    for s in db.store.shipments.values():
        if s["status"] != "BLOCKED":
            continue
        if all(db.store.placements[a["placement_id"]]["status"] == "STORED"
               for a in s["allocations"]):
            s["status"] = "PLANNED"
            db.touch(s)


def block_shipments_for(placement_ids):
    """PLANNED shipments allocating any of these placements -> BLOCKED."""
    ids = set(placement_ids)
    for s in db.store.shipments.values():
        if s["status"] != "PLANNED":
            continue
        if any(a["placement_id"] in ids for a in s["allocations"]):
            s["status"] = "BLOCKED"
            db.touch(s)


def aflatoxin_fail_cascade(lot):
    """FAIL: lot's STORED placements -> QUARANTINED; affected shipments -> BLOCKED."""
    quarantined = []
    for p in db.store.placements.values():
        if p["lot_id"] == lot["id"] and p["status"] == "STORED":
            p["status"] = "QUARANTINED"
            db.touch(p)
            quarantined.append(p["id"])
    block_shipments_for(quarantined)


def aflatoxin_pass_compensation(lot):
    """Resample-pass path: lot's QUARANTINED placements -> STORED; unblock."""
    for p in db.store.placements.values():
        if p["lot_id"] == lot["id"] and p["status"] == "QUARANTINED":
            p["status"] = "STORED"
            db.touch(p)
    unblock_shipments()


def dispose_cascade(lot):
    """Dispose: lot's QUARANTINED placements -> DISPOSED; bins lose the weight."""
    affected_bins = set()
    for p in db.store.placements.values():
        if p["lot_id"] == lot["id"] and p["status"] == "QUARANTINED":
            p["status"] = "DISPOSED"
            db.touch(p)
            affected_bins.add(p["bin_id"])
    for bin_id in affected_bins:
        b = db.store.bins.get(bin_id)
        if b is not None:
            db.touch(b)


def fumigation_start_cascade(event, bin_rec):
    """Start: bin AVAILABLE -> FUMIGATING; placements STORED -> FUMIGATION_HOLD;
    PLANNED shipments allocating them -> BLOCKED."""
    bin_rec["status"] = "FUMIGATING"
    bin_rec["fumigation_cleared_at"] = None
    db.touch(bin_rec)
    held = []
    for p in db.store.placements.values():
        if p["bin_id"] == bin_rec["id"] and p["status"] == "STORED":
            p["status"] = "FUMIGATION_HOLD"
            db.touch(p)
            held.append(p["id"])
    block_shipments_for(held)


def _clear_event(event):
    """AERATING -> CLEARED with full release cascade."""
    event["status"] = "CLEARED"
    db.touch(event)
    bin_rec = db.store.bins.get(event["bin_id"])
    if bin_rec is not None and bin_rec["status"] == "AERATING":
        bin_rec["status"] = "AVAILABLE"
        bin_rec["fumigation_cleared_at"] = None
        db.touch(bin_rec)
    for p in db.store.placements.values():
        if p["bin_id"] == event["bin_id"] and p["status"] == "FUMIGATION_HOLD":
            p["status"] = "STORED"
            db.touch(p)
    unblock_shipments()


def lazy_clearance():
    """Evaluated on clock-set and before any operation touching a bin: any
    AERATING event whose cleared_at is at or before the clock is cleared."""
    clock = db.store.clock
    for event in list(db.store.fumigations.values()):
        if (event["status"] == "AERATING"
                and event["_cleared_dt"] is not None
                and event["_cleared_dt"] <= clock):
            _clear_event(event)
