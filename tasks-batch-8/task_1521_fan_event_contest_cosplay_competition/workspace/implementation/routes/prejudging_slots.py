"""PreJudgingSlot routes."""

from flask import Blueprint, request

from db import DB, new_id, now_ts, parse_iso
from errors import (
    err_not_found, err_not_owner, err_invalid_state, err_entry_category_mismatch,
    err_slot_outside_window, err_slot_overlap, err_validation,
)
from middleware import require_roles
from response import success
from services.helpers import body_json, req_str, req_iso
from services.serializers import prejudging_slot_view, paginate

bp = Blueprint("prejudging_slots", __name__)

READ_ROLES = ("ContestLead", "Treasurer", "StageManager", "Judge", "SafetyOfficer", "Contestant")


@bp.route("/prejudging-slots", methods=["POST"])
def create_slot():
    require_roles("ContestLead")
    body = body_json()
    category_id = req_str(body, "category_id")
    panel_name = req_str(body, "panel_name")
    start_at = req_iso(body, "start_at")
    end_at = req_iso(body, "end_at")

    if parse_iso(end_at) <= parse_iso(start_at):
        raise err_validation("end_at must be strictly after start_at")

    category = DB.categories.get(category_id)
    if category is None:
        raise err_not_found("Category not found")

    contest = DB.contest_events.get(category["contest_id"])
    if contest is None:
        raise err_not_found("ContestEvent not found")

    # Temporal: slot within contest window.
    c_start = parse_iso(contest["start_at"])
    c_end = parse_iso(contest["end_at"])
    s_start = parse_iso(start_at)
    s_end = parse_iso(end_at)
    if s_start < c_start or s_end > c_end:
        raise err_slot_outside_window()

    # Temporal: overlap per (category_id, panel_name); half-open adjacency OK.
    for slot in DB.prejudging_slots.values():
        if slot["category_id"] != category_id or slot["panel_name"] != panel_name:
            continue
        ex_start = parse_iso(slot["start_at"])
        ex_end = parse_iso(slot["end_at"])
        if s_start < ex_end and ex_start < s_end:
            raise err_slot_overlap()

    ts = now_ts()
    slot = {
        "id": new_id(),
        "category_id": category_id,
        "panel_name": panel_name,
        "start_at": start_at,
        "end_at": end_at,
        "status": "OPEN",
        "booked_entry_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.prejudging_slots[slot["id"]] = slot
    return success(prejudging_slot_view(slot), status=201)


@bp.route("/prejudging-slots", methods=["GET"])
def list_slots():
    require_roles(*READ_ROLES)
    items = list(DB.prejudging_slots.values())
    category_id = request.args.get("category_id")
    booked_entry_id = request.args.get("booked_entry_id")
    status = request.args.get("status")
    if category_id is not None:
        items = [s for s in items if s["category_id"] == category_id]
    if booked_entry_id is not None:
        items = [s for s in items if s.get("booked_entry_id") == booked_entry_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    page, pag = paginate([prejudging_slot_view(s) for s in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/prejudging-slots/<sid>", methods=["GET"])
def get_slot(sid):
    require_roles(*READ_ROLES)
    slot = DB.prejudging_slots.get(sid)
    if slot is None:
        raise err_not_found("PreJudgingSlot not found")
    return success(prejudging_slot_view(slot))


@bp.route("/prejudging-slots/<sid>/book", methods=["POST"])
def book_slot(sid):
    user_id, _ = require_roles("Contestant")
    body = body_json()
    entry_id = req_str(body, "entry_id")

    slot = DB.prejudging_slots.get(sid)
    if slot is None:
        raise err_not_found("PreJudgingSlot not found")
    entry = DB.entries.get(entry_id)
    if entry is None:
        raise err_not_found("Entry not found")

    # Ownership: booking is for own entry.
    if entry["contestant_id"] != user_id:
        raise err_not_owner("Contestant may only book slots for own entries")

    if slot["status"] != "OPEN":
        raise err_invalid_state("Slot must be OPEN to book")
    if entry["status"] != "SAFETY_APPROVED":
        raise err_invalid_state("Entry must be SAFETY_APPROVED before craftsmanship review")
    if any(
        s["status"] == "BOOKED" and s.get("booked_entry_id") == entry_id
        for s in DB.prejudging_slots.values()
    ):
        raise err_invalid_state("Entry already holds another BOOKED slot")

    if entry["category_id"] != slot["category_id"]:
        raise err_entry_category_mismatch()

    slot["status"] = "BOOKED"
    slot["booked_entry_id"] = entry_id
    slot["updated_at"] = now_ts()
    slot["version"] += 1
    return success(prejudging_slot_view(slot))


@bp.route("/prejudging-slots/<sid>/release", methods=["POST"])
def release_slot(sid):
    user_id, role = require_roles("Contestant", "ContestLead")
    slot = DB.prejudging_slots.get(sid)
    if slot is None:
        raise err_not_found("PreJudgingSlot not found")

    if role == "Contestant":
        entry = DB.entries.get(slot.get("booked_entry_id") or "")
        if entry is None or entry["contestant_id"] != user_id:
            raise err_not_owner("Contestant may only release own bookings")

    if slot["status"] != "BOOKED":
        raise err_invalid_state("Slot must be BOOKED to release")

    slot["status"] = "OPEN"
    slot["booked_entry_id"] = None
    slot["updated_at"] = now_ts()
    slot["version"] += 1
    return success(prejudging_slot_view(slot))


@bp.route("/prejudging-slots/<sid>/complete", methods=["POST"])
def complete_slot(sid):
    require_roles("ContestLead")
    slot = DB.prejudging_slots.get(sid)
    if slot is None:
        raise err_not_found("PreJudgingSlot not found")
    if slot["status"] != "BOOKED":
        raise err_invalid_state("Slot must be BOOKED to complete")

    entry = DB.entries.get(slot.get("booked_entry_id") or "")
    ts = now_ts()
    if entry is not None and entry["status"] == "SAFETY_APPROVED":
        entry["status"] = "PREJUDGED"
        entry["updated_at"] = ts
        entry["version"] += 1

    slot["status"] = "COMPLETED"
    slot["updated_at"] = ts
    slot["version"] += 1
    return success(prejudging_slot_view(slot))
