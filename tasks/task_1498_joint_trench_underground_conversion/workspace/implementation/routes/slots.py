"""OccupancySlot endpoints: reserve (geometry + window gates), list/get,
transitions (deeper-first install order, release)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_OWNERSHIP_VIOLATION,
    ERR_CHANGE_ORDER_FREEZE,
)
from middleware import require_roles, forbid
from response import success_object, success_list
from services import domain
from services.serializers import slot_view
from util import (
    get_json_body,
    get_or_404,
    parse_iso8601,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    require_int,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("slots", __name__, url_prefix="/api/occupancy-slots")

PM = "ProgramManager"
UC = "UtilityCoordinator"
ANY = "Any"

TRANSITION_TARGETS = {"INSTALLING", "INSTALLED", "INSTALL_FAILED", "VERIFIED", "RELEASED"}


@bp.route("", methods=["POST"])
@require_roles(UC)
def create_slot(_user_id: str, _role: str):
    body = get_json_body()
    # Ownership (priority 3): the coordinator may only reserve for its own
    # participation — checked on the raw reference before existence.
    if body.get("participation_id") is not None and body["participation_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION,
                  "UtilityCoordinator may only reserve slots for its own participation")
    # Existence, left to right: trench_segment_id, then participation_id.
    if body.get("trench_segment_id") is not None:
        get_or_404(db.segments, body["trench_segment_id"], "TrenchSegment")
    if body.get("participation_id") is not None:
        get_or_404(db.participations, body["participation_id"], "UtilityParticipation")
    segment_id = require_string(body, "trench_segment_id")
    participation_id = require_string(body, "participation_id")
    segment = db.segments[segment_id]
    participation = db.participations[participation_id]

    depth_top = require_int(body, "depth_top_inches")
    depth_bottom = require_int(body, "depth_bottom_inches")
    install_start = require_ts(body, "install_start_at")
    install_end = require_ts(body, "install_end_at")
    if depth_bottom <= depth_top:
        raise_err(ERR_VALIDATION, "depth_bottom_inches must exceed depth_top_inches")
    if parse_iso8601(install_start) >= parse_iso8601(install_end):
        raise_err(ERR_VALIDATION, "install_end_at must be after install_start_at")

    if segment["status"] not in {"SCHEDULED", "EXCAVATING"}:
        raise_err(ERR_INVALID_STATE,
                  "slot reservation requires segment SCHEDULED|EXCAVATING")
    if domain.is_segment_frozen(segment):
        raise_err(ERR_CHANGE_ORDER_FREEZE,
                  "segment is frozen by an APPROVED change order")

    domain.check_slot_geometry(segment, participation, depth_top, depth_bottom)
    domain.check_slot_window(segment, depth_top, depth_bottom,
                             install_start, install_end)

    slot = stamp_new({
        "trench_segment_id": segment_id,
        "participation_id": participation_id,
        "depth_top_inches": depth_top,
        "depth_bottom_inches": depth_bottom,
        "install_start_at": install_start,
        "install_end_at": install_end,
        "status": "RESERVED",
    })
    db.slots[slot["id"]] = slot
    return success_object(slot_view(slot), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_slots(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.slots.values())
    segment_id = query_arg("trench_segment_id")
    participation_id = query_arg("participation_id")
    status = query_arg("status")
    if segment_id:
        items = [s for s in items if s["trench_segment_id"] == segment_id]
    if participation_id:
        items = [s for s in items if s["participation_id"] == participation_id]
    if status:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([slot_view(s) for s in page], limit, offset, total)


@bp.route("/<sid>", methods=["GET"])
@require_roles(ANY)
def get_slot(sid: str, _user_id: str, _role: str):
    return success_object(slot_view(get_or_404(db.slots, sid, "OccupancySlot")))


@bp.route("/<sid>/transition", methods=["POST"])
@require_roles(UC, PM)
def transition_slot(sid: str, _user_id: str, _role: str):
    slot = get_or_404(db.slots, sid, "OccupancySlot")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    # Per-transition actors: VERIFIED belongs to the ProgramManager alone; the
    # working transitions belong to the owning UtilityCoordinator.
    if to == "VERIFIED":
        if _role != PM:
            forbid("only ProgramManager may verify a slot")
    else:
        if _role != UC:
            forbid("only the owning UtilityCoordinator may perform this transition")
        if slot["participation_id"] != _user_id:
            raise_err(ERR_OWNERSHIP_VIOLATION,
                      "UtilityCoordinator may only transition its own slots")

    current = slot["status"]
    if current in {"VERIFIED", "RELEASED"}:
        raise_err(ERR_INVALID_STATE, f"slot is terminal ({current})")

    if to == "INSTALLING":
        if current not in {"RESERVED", "INSTALL_FAILED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INSTALLING")
        segment = db.segments[slot["trench_segment_id"]]
        if segment["status"] != "EXCAVATING":
            raise_err(ERR_INVALID_STATE, "install requires segment EXCAVATING")
        domain.check_deeper_first(segment, slot)
        slot["status"] = "INSTALLING"

    elif to == "INSTALLED":
        if current != "INSTALLING":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INSTALLED")
        slot["status"] = "INSTALLED"

    elif to == "INSTALL_FAILED":
        if current != "INSTALLING":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INSTALL_FAILED")
        slot["status"] = "INSTALL_FAILED"

    elif to == "VERIFIED":
        if current != "INSTALLED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> VERIFIED")
        slot["status"] = "VERIFIED"

    elif to == "RELEASED":
        if current not in {"RESERVED", "INSTALL_FAILED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> RELEASED")
        slot["status"] = "RELEASED"
        # segment depth fields are derived at read; nothing to recompute.

    touch(slot)
    return success_object(slot_view(slot))
