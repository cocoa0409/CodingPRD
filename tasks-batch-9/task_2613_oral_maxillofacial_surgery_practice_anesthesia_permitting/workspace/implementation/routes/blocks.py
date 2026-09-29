"""Operating-room block time and the minute ledger."""
from flask import Blueprint

from db import db, new_record, ordered, touch
from errors import ApiError
from middleware import authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import BLOCK_STATUSES, path_row, referenced_row
from services.scheduling import duration_minutes, recompute_block
from timeutil import parse_date
from validation import (q_enum, q_string, read_body, v_id, v_instant, v_int,
                        v_string)

bp = Blueprint("blocks", __name__)


@bp.post("/block-times")
def create_block():
    authorize("SchedulingCoordinator", "PracticeAdministrator")
    body = read_body(
        required=("practice_id", "surgeon_id", "room_code", "block_start", "block_end"),
        optional=("release_deadline_hours",),
    )
    practice_id = v_id(body, "practice_id")
    surgeon_id = v_id(body, "surgeon_id")
    room_code = v_string(body, "room_code", min_len=1, max_len=16)
    block_start = v_instant(body, "block_start")
    block_end = v_instant(body, "block_end")
    release_deadline_hours = v_int(body, "release_deadline_hours", minimum=0,
                                  maximum=336, default=48)
    if parse_date(block_end) <= parse_date(block_start):
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'block_end' must be strictly later than 'block_start'.")

    referenced_row(db.practices, practice_id)
    surgeon = referenced_row(db.staff, surgeon_id)
    scope_check(surgeon["practice_id"], practice_id)
    if surgeon["role_type"] != "SURGEON":
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'surgeon_id' must reference a staff member whose role_type is SURGEON.")

    duration = duration_minutes(block_start, block_end)
    block = new_record({
        "practice_id": practice_id,
        "surgeon_id": surgeon_id,
        "room_code": room_code,
        "block_start": block_start,
        "block_end": block_end,
        "release_deadline_hours": release_deadline_hours,
        "status": "RESERVED",
        "block_duration_minutes": duration,
        "committed_minutes": 0,
        "released_minutes": 0,
        "open_minutes": duration,
        "utilization_pct": 0.00,
    })
    db.blocks[block["id"]] = block
    return send(block, 201)


@bp.get("/block-times/<block_id>")
def read_block(block_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.blocks, block_id))


@bp.get("/block-times")
def list_blocks():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    surgeon_id = q_string("surgeon_id")
    status = q_enum("status", BLOCK_STATUSES)
    rows = ordered([b for b in db.blocks.values()
                    if (practice_id is None or b["practice_id"] == practice_id)
                    and (surgeon_id is None or b["surgeon_id"] == surgeon_id)
                    and (status is None or b["status"] == status)])
    return send_list(rows)


@bp.post("/block-times/<block_id>/release")
def release_block(block_id):
    authorize("SchedulingCoordinator")
    block = path_row(db.blocks, block_id)
    read_body(optional=("release_note",))

    if block["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    recompute_block(block)
    if int(block["committed_minutes"]) > 0:
        block["released_minutes"] = int(block["released_minutes"]) + int(block["open_minutes"])
        block["status"] = "PARTIALLY_RELEASED"
    else:
        block["released_minutes"] = int(block["block_duration_minutes"])
        block["status"] = "RELEASED"
    recompute_block(block)
    block["open_minutes"] = 0
    touch(block)
    return send(block)
