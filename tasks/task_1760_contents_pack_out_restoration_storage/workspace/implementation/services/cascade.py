"""Cascade helpers: placement release, disposal record lifecycle, item status moves."""

from db import store
from helpers import (
    make_common_fields,
    touch,
    active_placement_of_item,
    job_of_item,
)
from services.recompute import (
    recompute_vault,
    recompute_provisional_statements_for_job,
    recompute_job_accrued,
    recompute_room,
)


def release_active_placement(item, reason):
    """Release the item's ACTIVE placement (if any) with the given reason.
    Handles vault decrement + provisional accrual recompute + job accrued recompute.
    Returns the placement released, or None."""
    placement = active_placement_of_item(item["id"])
    if placement is None:
        return None
    placement["status"] = "RELEASED"
    placement["released_on"] = store.today_str()
    placement["release_reason"] = reason
    touch(placement)
    vault = store.vaults.get(placement["vault_id"])
    if vault is not None:
        recompute_vault(vault)
    job = job_of_item(item)
    if job is not None:
        recompute_provisional_statements_for_job(job["id"])
        recompute_job_accrued(job)
    return placement


def set_item_processing(item, new_status):
    item["processing_status"] = new_status
    touch(item)
    room = store.rooms.get(item["room_id"])
    if room is not None:
        recompute_room(room)
        touch(room)


def ensure_disposal_record(item):
    """Auto-create a DRAFT DisposalRecord if none non-VOIDED exists. Returns record."""
    for rec in store.disposal_records.values():
        if rec["item_id"] == item["id"] and rec["status"] != "VOIDED":
            return rec
    rec = make_common_fields()
    rec.update({
        "item_id": item["id"],
        "disposal_method": None,
        "manifest_number": None,
        "facility_name": None,
        "photo_ref": None,
        "status": "DRAFT",
        "documented_by_user_id": None,
        "verified_by_user_id": None,
        "documented_at": None,
    })
    store.disposal_records[rec["id"]] = rec
    return rec


def void_open_disposal_record(item):
    """Void the item's DRAFT/DOCUMENTED disposal record (re-triage SALVAGEABLE path)."""
    for rec in store.disposal_records.values():
        if rec["item_id"] == item["id"] and rec["status"] in ("DRAFT", "DOCUMENTED"):
            rec["status"] = "VOIDED"
            touch(rec)
            return rec
    return None
