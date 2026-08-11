"""Custody trail helpers, segregation checks, destruction cascade, disposition sweep."""

from db import db
from errors import (
    ApiError,
    ERR_CUSTODY_SEGREGATION,
    ERR_CUSTODY_FLAGGED,
)
from util import make_event, bump


def append_custody_event(box_id, from_stage, to_stage, actor_user_id, actor_role, notes=None):
    evt = make_event(
        {
            "box_id": box_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "notes": notes,
        }
    )
    db.custody_events[evt["id"]] = evt
    return evt


def box_custody_trail(box_id):
    evts = [e for e in db.custody_events.values() if e["box_id"] == box_id]
    # Chronological = insertion order; created_at ties are routine under the
    # logical clock, and PRD's "greatest created_at" adjacency assumes no ties.
    evts.sort(key=lambda e: e.get("_seq", 0))
    return evts


def check_custody_segregation(box_id, actor_user_id):
    """The actor may not author two adjacent custody events on the same box."""
    trail = box_custody_trail(box_id)
    if not trail:
        return
    prev = trail[-1]
    if prev["actor_user_id"] == actor_user_id:
        raise ApiError(
            ERR_CUSTODY_SEGREGATION,
            "Actor authored the immediately preceding custody event on this box",
            422,
        )


def check_custody_flag(box):
    if box.get("custody_flagged"):
        raise ApiError(
            ERR_CUSTODY_FLAGGED,
            "Box is custody-flagged pending compliance review",
            409,
        )


def release_active_assignment(box, when_iso):
    """Release the box's ACTIVE shelf assignment (if any) and debit the slot."""
    for a in db.shelf_assignments.values():
        if a["box_id"] == box["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            a["released_at"] = when_iso
            bump(a)
            slot = db.shelf_slots.get(a["shelf_slot_id"])
            if slot:
                slot["occupied_weight_grams"] = max(
                    0, slot["occupied_weight_grams"] - box["intake_weight_grams"]
                )
                bump(slot)


def destruction_cascade(destroyed_box, when_iso):
    """Raise custody_flagged on every other non-final box of every non-CLOSED batch
    of the same client."""
    client_id = destroyed_box_client_id(destroyed_box)
    if client_id is None:
        return
    for box in db.boxes.values():
        if box["id"] == destroyed_box["id"]:
            continue
        if box["status"] in ("DESTROYED", "RETURNED"):
            continue
        batch = db.batches.get(box["batch_id"])
        if not batch or batch["client_id"] != client_id:
            continue
        if batch["status"] == "CLOSED":
            continue
        if not box.get("custody_flagged"):
            box["custody_flagged"] = True
            bump(box)


def destroyed_box_client_id(box):
    batch = db.batches.get(box["batch_id"])
    return batch["client_id"] if batch else None


def disposition_sweep():
    """Fire DELIVERED -> DISPOSITION_PENDING for batches whose disposition_at <= clock.

    Called whenever the logical clock is advanced.
    """
    from response import iso_ts

    now_dt = db.current_utc
    for batch in db.batches.values():
        if batch["status"] != "DELIVERED":
            continue
        disp = batch.get("disposition_at")
        if not disp:
            continue
        disp_dt = _parse_iso(disp)
        if now_dt >= disp_dt:
            when_iso = iso_ts(now_dt)
            batch["status"] = "DISPOSITION_PENDING"
            for box in db.boxes.values():
                if box["batch_id"] != batch["id"]:
                    continue
                if box["status"] in ("STORED", "SCAN_COMPLETE"):
                    if box["status"] == "STORED":
                        release_active_assignment(box, when_iso)
                    box["status"] = "AWAITING_DISPOSITION"
                    box["updated_at"] = when_iso
                    box["version"] += 1
            bump(batch)


def _parse_iso(iso):
    from datetime import datetime, timezone

    s = iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
