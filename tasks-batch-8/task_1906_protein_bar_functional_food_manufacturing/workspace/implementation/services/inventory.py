"""Inventory ledger, FIFO reservations, and the two depth-limited cascades."""
from datetime import timedelta
from decimal import Decimal

from db import STORES, touch, base_record, CLOCK
from util import D, round2


def lot_available(lot):
    return D(lot["received_qty_kg"]) - D(lot["reserved_qty_kg"]) - D(lot["consumed_qty_kg"])


def released_lots_fifo(ingredient_id):
    lots = [l for l in STORES["lots"].values()
            if l["ingredient_id"] == ingredient_id and l["status"] == "RELEASED"]
    lots.sort(key=lambda l: (l["received_at_dt"], l["_seq"]))
    return lots


def reserve_fifo(ingredient_id, qty_needed):
    """Draw qty_needed from RELEASED lots, received_at ASC then created ASC.
    Returns (allocations, fully_covered). Mutates lot ledgers (with version
    bumps per §2.4)."""
    remaining = D(qty_needed)
    allocs = []
    for lot in released_lots_fifo(ingredient_id):
        if remaining <= 0:
            break
        avail = lot_available(lot)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        if take > 0:
            allocs.append({"lot_id": lot["id"], "ingredient_id": ingredient_id,
                           "qty_kg": take})
            lot["reserved_qty_kg"] = D(lot["reserved_qty_kg"]) + take
            touch(lot)
            remaining -= take
    return allocs, remaining <= 0


def release_run_reservations(run):
    """Release every open reservation of a run, decrementing lot ledgers."""
    touched = set()
    for alloc in run["reserved_lot_allocations"]:
        lot = STORES["lots"].get(alloc["lot_id"])
        if lot is None:
            continue
        lot["reserved_qty_kg"] = D(lot["reserved_qty_kg"]) - D(alloc["qty_kg"])
        touched.add(lot["id"])
    run["reserved_lot_allocations"] = []
    for lot_id in touched:
        touch(STORES["lots"][lot_id])


def compute_readiness(revision, run):
    """READY iff every ingredient line is fully reserved from RELEASED lots."""
    for line in revision["ingredient_lines"]:
        reserved = sum(
            (D(a["qty_kg"]) for a in run["reserved_lot_allocations"]
             if a["ingredient_id"] == line["ingredient_id"]),
            Decimal("0"))
        required = run_line_required_qty(line)
        if reserved < required:
            return "BLOCKED"
    return "READY"


def run_line_required_qty(line):
    """Quantity a run must reserve for a line (sweetener lines use the
    PROVISIONAL ceil-to-0.01 requirement, others the exact line qty)."""
    from services.calc import sweetener_provisional_line
    ing = STORES["ingredients"][line["ingredient_id"]]
    if ing["category"] == "SWEETENER":
        return sweetener_provisional_line(line, ing)
    return D(line["qty_kg_per_batch"])


def maybe_deplete(lot):
    """Auto-transition RELEASED -> DEPLETED at exact-zero availability."""
    if (lot["status"] == "RELEASED"
            and lot_available(lot) == 0
            and D(lot["reserved_qty_kg"]) == 0
            and D(lot["consumed_qty_kg"]) == D(lot["received_qty_kg"])):
        lot["status"] = "DEPLETED"
        # The transition rides on the same mutation's version increment.


def slot_for_run(run_id):
    for slot in STORES["slots"].values():
        if slot["run_id"] == run_id:
            return slot
    return None


def changeovers_for_run(run_id):
    return [c for c in STORES["changeovers"].values()
            if c.get("from_run_id") == run_id or c.get("to_run_id") == run_id]


def active_changeover_to_run(run_id):
    """Latest changeover event feeding this run."""
    evs = [c for c in STORES["changeovers"].values() if c.get("to_run_id") == run_id]
    if not evs:
        return None
    evs.sort(key=lambda c: c["_seq"])
    return evs[-1]


def system_cancel_changeover(event):
    """Bookkeeping-free system cancellation (no version bump per §3.7)."""
    if event["status"] in ("PENDING", "CLEANING_LOGGED", "FAILED"):
        event["status"] = "CANCELLED"


def cascade_reject_lot(lot):
    """CASCADE-REJECT (depth 3): release open reservations on this lot,
    recompute readiness, de-schedule READY->BLOCKED SCHEDULED runs."""
    for run in list(STORES["runs"].values()):
        if run["status"] not in ("PLANNED", "SCHEDULED"):
            continue
        lot_allocs = [a for a in run["reserved_lot_allocations"]
                      if a["lot_id"] == lot["id"]]
        if not lot_allocs:
            continue
        # link 1: release allocations on this lot
        released_qty = sum((D(a["qty_kg"]) for a in lot_allocs), Decimal("0"))
        run["reserved_lot_allocations"] = [
            a for a in run["reserved_lot_allocations"] if a["lot_id"] != lot["id"]]
        lot["reserved_qty_kg"] = D(lot["reserved_qty_kg"]) - released_qty
        # link 2: recompute readiness
        revision = STORES["revisions"].get(run["revision_id"])
        was = run["ingredient_readiness"]
        now = compute_readiness(revision, run)
        run["ingredient_readiness"] = now
        # link 3: READY->BLOCKED while SCHEDULED auto-de-schedules
        if was == "READY" and now == "BLOCKED" and run["status"] == "SCHEDULED":
            run["status"] = "PLANNED"
            run["cancel_reason"] = "INGREDIENT_SHORTAGE"
            slot = slot_for_run(run["id"])
            if slot is not None and slot["status"] == "CONFIRMED":
                slot["status"] = "RELEASED"
                touch(slot)
            event = active_changeover_to_run(run["id"])
            if event is not None:
                system_cancel_changeover(event)
        touch(run)
    touch(lot)


def cascade_supersede(old_revision, new_revision):
    """CASCADE-SUPERSEDE (depth 2): supersede the previously APPROVED revision
    and cancel its open runs (slots released, changeovers cancelled,
    reservations released)."""
    if old_revision is not None:
        old_revision["status"] = "SUPERSEDED"
        touch(old_revision)
        for run in list(STORES["runs"].values()):
            if run["revision_id"] != old_revision["id"]:
                continue
            if run["status"] not in ("PLANNED", "SCHEDULED"):
                continue
            release_run_reservations(run)
            run["status"] = "CANCELLED"
            run["cancel_reason"] = "FORMULA_SUPERSEDED"
            slot = slot_for_run(run["id"])
            if slot is not None and slot["status"] == "CONFIRMED":
                slot["status"] = "RELEASED"
                touch(slot)
            event = active_changeover_to_run(run["id"])
            if event is not None:
                system_cancel_changeover(event)
            touch(run)


def consume_run_reservations(run):
    """Start-of-production: reserved -> consumed per allocation; lots may
    auto-DEPLETE."""
    for alloc in run["reserved_lot_allocations"]:
        lot = STORES["lots"].get(alloc["lot_id"])
        if lot is None:
            continue
        lot["reserved_qty_kg"] = D(lot["reserved_qty_kg"]) - D(alloc["qty_kg"])
        lot["consumed_qty_kg"] = D(lot["consumed_qty_kg"]) + D(alloc["qty_kg"])
        maybe_deplete(lot)
        touch(lot)


# ---------- shelf-life missed-pull materialization ----------

def next_pull_index(study):
    return sum(1 for p in STORES["pulls"].values() if p["study_id"] == study["id"])


def pull_due_utc(study, index):
    return study["start_utc_dt"] + timedelta(days=int(study["pull_interval_days"]) * index)


def materialize_missed_pulls(study):
    """Due-but-unrecorded pulls whose grace window (due + 2 days) has elapsed
    become MISSED records. Only ACTIVE studies accrue missed pulls."""
    if study["status"] != "ACTIVE":
        return
    grace = timedelta(days=2)
    idx = next_pull_index(study)
    while CLOCK.current > pull_due_utc(study, idx) + grace:
        rec = base_record()
        rec.update({
            "study_id": study["id"],
            "pull_index": idx,
            "due_utc_dt": pull_due_utc(study, idx),
            "recorded_utc_dt": None,
            "hardness_n": None,
            "status": "MISSED",
        })
        STORES["pulls"][rec["id"]] = rec
        idx += 1


def evaluate_clock_transitions():
    """Clock-set evaluation: materialize MISSED pulls, then auto-COMPLETE
    ACTIVE studies whose expiry the clock has passed with a passing (or
    absent) projection."""
    from services.calc import hardness_projection
    for study in list(STORES["studies"].values()):
        if study["status"] != "ACTIVE":
            continue
        materialize_missed_pulls(study)
        if CLOCK.current > study["expiry_utc_dt"]:
            projected, _used = hardness_projection(study)
            if projected is None or projected <= D(study["hardness_limit_n"]):
                study["status"] = "COMPLETED"
                touch(study)
