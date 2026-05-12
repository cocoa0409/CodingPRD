"""MaintenanceBlock routes."""
from flask import Blueprint, request

from db import maintenance_blocks, rooms, stamp_create, stamp_update, lock
from errors import err
from middleware import require_auth
from response import success
from services.projections import project_maintenance_block
from services.validation import require_dict, required_str
from clock import parse_date, today_utc

bp = Blueprint("maintenance", __name__)

_MB_ROLES = ["HousekeepingStaff", "PlatformAdmin"]


def _windows_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open windows [a_start, a_end) and [b_start, b_end) overlap iff a_start < b_end and a_end > b_start."""
    return a_start < b_end and a_end > b_start


@bp.route("/hotel/maintenance-blocks", methods=["POST"])
@require_auth(roles=_MB_ROLES)
def create_block():
    body = require_dict(request.get_json(silent=True))
    room_id = required_str(body, "room_id")
    start_date_raw = required_str(body, "start_date")
    end_date_raw = required_str(body, "end_date")
    reason = required_str(body, "reason")

    try:
        sd = parse_date(start_date_raw)
        ed = parse_date(end_date_raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))

    if not (ed > sd):
        raise err("ERR_INVALID_INPUT", "end_date must be strictly greater than start_date")

    with lock():
        r = rooms.get(room_id)
        if r is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Room not found")

        # Priority 11: overlap with another non-cancelled block on same room
        for b in maintenance_blocks.values():
            if b.get("room_id") != room_id:
                continue
            if b.get("status") not in ("SCHEDULED", "ACTIVE"):
                continue
            bs = parse_date(b["start_date"])
            be = parse_date(b["end_date"])
            if _windows_overlap(sd, ed, bs, be):
                raise err("ERR_MAINTENANCE_OVERLAP",
                          "Overlaps existing scheduled/active maintenance block on this room")

        # Priority 12: room not currently OCCUPIED
        if r.get("housekeeping_status") == "OCCUPIED":
            raise err("ERR_ROOM_CURRENTLY_OCCUPIED", "Room is currently OCCUPIED")

        row = {
            "room_id": room_id,
            "start_date": sd.isoformat(),
            "end_date": ed.isoformat(),
            "reason": reason,
            "status": "SCHEDULED",
        }
        stamp_create(row, common_fields=True)
        maintenance_blocks[row["id"]] = row

        # If now() in [sd, ed): activate immediately
        today = today_utc()
        if sd <= today < ed:
            row["status"] = "ACTIVE"
            stamp_update(row)
            # cascade: room operational_status -> OUT_OF_ORDER if IN_SERVICE and not OCCUPIED
            if r.get("operational_status") == "IN_SERVICE" and r.get("housekeeping_status") != "OCCUPIED":
                r["operational_status"] = "OUT_OF_ORDER"
                stamp_update(r)
    return success(project_maintenance_block(row), 201)


@bp.route("/hotel/maintenance-blocks/<bid>/release", methods=["POST"])
@require_auth(roles=_MB_ROLES)
def release_block(bid):
    with lock():
        b = maintenance_blocks.get(bid)
        if b is None:
            raise err("ERR_NOT_FOUND", "MaintenanceBlock not found")
        if b.get("status") != "ACTIVE":
            raise err("ERR_INVALID_STATE", "MaintenanceBlock is not ACTIVE")
        b["status"] = "RELEASED"
        stamp_update(b)
        # Cascade: if no other ACTIVE block covers this room and op status OUT_OF_ORDER -> IN_SERVICE
        rm = rooms.get(b["room_id"])
        if rm is not None:
            has_other_active = any(
                bb.get("room_id") == rm["id"] and bb.get("status") == "ACTIVE" and bb["id"] != b["id"]
                for bb in maintenance_blocks.values()
            )
            if not has_other_active and rm.get("operational_status") == "OUT_OF_ORDER":
                rm["operational_status"] = "IN_SERVICE"
                if rm.get("housekeeping_status") != "OCCUPIED":
                    rm["housekeeping_status"] = "DIRTY"
                stamp_update(rm)
    return success(project_maintenance_block(b))


@bp.route("/hotel/maintenance-blocks/<bid>/cancel", methods=["POST"])
@require_auth(roles=_MB_ROLES)
def cancel_block(bid):
    with lock():
        b = maintenance_blocks.get(bid)
        if b is None:
            raise err("ERR_NOT_FOUND", "MaintenanceBlock not found")
        if b.get("status") != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "MaintenanceBlock is not SCHEDULED")
        b["status"] = "CANCELLED"
        stamp_update(b)
    return success(project_maintenance_block(b))
