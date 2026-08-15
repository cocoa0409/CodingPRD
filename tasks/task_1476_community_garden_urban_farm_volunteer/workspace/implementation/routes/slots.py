"""Shift slots (PRD section 3.5)."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_invalid_request, err_not_found, err_state, err_stale_version
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_bool, opt_int, pagination_args, parse_dt, req_enum, req_int, req_str, require_field

bp = Blueprint("slots", __name__)

TASK_TYPES = {"PLANTING", "WEEDING", "HARVEST", "IRRIGATION", "COMPOST", "REPAIR", "OUTREACH"}
SLOT_TARGETS = {"OPEN", "LOCKED", "COMPLETED", "CANCELLED"}
STAFF = ["GardenAdmin", "Coordinator"]


@bp.post("/api/shift-slots")
def create_slot():
    ctx = require_auth()
    require_role(ctx, STAFF)
    data = body()
    # existence (tier 3): season, then optional required_tool_id
    season_id = require_field(data, "season_id")
    season = db.seasons.get(season_id)
    if season is None:
        raise err_not_found("season")
    tool_id = data.get("required_tool_id")
    if tool_id is not None and db.tools.get(tool_id) is None:
        raise err_not_found("tool")
    # shape (tier 5)
    task_type = req_enum(data, "task_type", TASK_TYPES)
    starts = parse_dt(require_field(data, "starts_at"), "starts_at")
    ends = parse_dt(require_field(data, "ends_at"), "ends_at")
    if ends <= starts:
        raise err_invalid_request("ends_at must be strictly after starts_at")
    capacity_total = req_int(data, "capacity_total")
    capacity_youth = req_int(data, "capacity_youth")
    if capacity_total <= 0:
        raise err_invalid_request("capacity_total must be > 0")
    if capacity_youth < 0 or capacity_youth > capacity_total:
        raise err_invalid_request("capacity_youth must be >= 0 and <= capacity_total")
    requires_ps = opt_bool(data, "requires_produce_safety", False)
    tool_qty = opt_int(data, "required_tool_qty", 0)
    if tool_qty < 0:
        raise err_invalid_request("required_tool_qty must be >= 0")
    # temporal (tier 13): slot window inside the season operating window
    if starts < season["season_starts_at"] or ends > season["season_ends_at"]:
        raise err("ERR_OUTSIDE_SEASON_WINDOW", "slot window lies outside the season window")
    rec = services.create_record({
        "season_id": season_id,
        "task_type": task_type,
        "starts_at": starts,
        "ends_at": ends,
        "capacity_total": capacity_total,
        "capacity_youth": capacity_youth,
        "requires_produce_safety": requires_ps,
        "required_tool_id": tool_id,
        "required_tool_qty": tool_qty,
        "next_waitlist_position": 1,
        "status": "DRAFT",
    })
    db.slots[rec["id"]] = rec
    return ok(services.slot_view(rec), status=201)


@bp.get("/api/shift-slots")
def list_slots():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.slots.values(),
        {"season_id": "season_id", "task_type": "task_type", "status": "status"},
        request.args, services.slot_view,
    )
    total = len(items)
    return ok([services.slot_view(s) for s in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_slot(slot_id):
    slot = db.slots.get(slot_id)
    if slot is None:
        raise err_not_found("slot")
    return slot


@bp.get("/api/shift-slots/<slotId>")
def get_slot(slotId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.slot_view(_get_slot(slotId)))


@bp.patch("/api/shift-slots/<slotId>")
def patch_slot(slotId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    slot = _get_slot(slotId)
    data = body()
    # shape (tier 5): expected_slot_version required by the OCC contract
    expected = req_int(data, "expected_slot_version")
    new_capacity_total = slot["capacity_total"]
    if data.get("capacity_total") is not None:
        new_capacity_total = req_int(data, "capacity_total")
        if new_capacity_total <= 0:
            raise err_invalid_request("capacity_total must be > 0")
    new_capacity_youth = slot["capacity_youth"]
    if data.get("capacity_youth") is not None:
        new_capacity_youth = req_int(data, "capacity_youth")
    if new_capacity_youth < 0 or new_capacity_youth > new_capacity_total:
        raise err_invalid_request("capacity_youth must be >= 0 and <= capacity_total")
    new_starts = slot["starts_at"]
    if data.get("starts_at") is not None:
        new_starts = parse_dt(data["starts_at"], "starts_at")
    new_ends = slot["ends_at"]
    if data.get("ends_at") is not None:
        new_ends = parse_dt(data["ends_at"], "ends_at")
    if new_ends <= new_starts:
        raise err_invalid_request("ends_at must be strictly after starts_at")
    # from-state (tier 6): editable only while DRAFT or OPEN
    if slot["status"] not in {"DRAFT", "OPEN"}:
        raise err_state("SLOT")
    # OCC (tier 17)
    if expected != slot["version"]:
        raise err_stale_version()
    slot["capacity_total"] = new_capacity_total
    slot["capacity_youth"] = new_capacity_youth
    slot["starts_at"] = new_starts
    slot["ends_at"] = new_ends
    services.bump(slot)
    # re-evaluate OPEN/FULL against the updated capacity
    services.recompute_slot_status(slot)
    return ok(services.slot_view(slot))


@bp.post("/api/shift-slots/<slotId>/transition")
def transition_slot(slotId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    slot = _get_slot(slotId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in SLOT_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(SLOT_TARGETS)}")
    status = slot["status"]

    if to_state == "OPEN":
        if status != "DRAFT":
            raise err_state("SLOT")
        season = db.seasons.get(slot["season_id"])
        if season is None or season["status"] not in {"OPEN_ENROLLMENT", "PLANTING", "GROWING", "HARVESTING"}:
            raise err("ERR_SEASON_NOT_ACCEPTING", "season is not accepting slot openings")
        slot["status"] = "OPEN"
        services.bump(slot)

    elif to_state == "LOCKED":
        if status not in {"OPEN", "FULL"}:
            raise err_state("SLOT")
        slot["status"] = "LOCKED"
        services.bump(slot)

    elif to_state == "COMPLETED":
        if status != "LOCKED":
            raise err_state("SLOT")
        if any(s["slot_id"] == slot["id"] and s["status"] == "CHECKED_IN"
               for s in db.signups.values()):
            raise err("ERR_SIGNUPS_STILL_CHECKED_IN", "signups remain CHECKED_IN on this slot")
        slot["status"] = "COMPLETED"
        services.bump(slot)
        services.complete_slot_cascade(slot)

    elif to_state == "CANCELLED":
        if status not in {"DRAFT", "OPEN", "FULL"}:
            raise err_state("SLOT")
        slot["status"] = "CANCELLED"
        services.bump(slot)
        services.cancel_slot_cascade(slot)

    return ok(services.slot_view(slot))
