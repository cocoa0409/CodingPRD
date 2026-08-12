"""BlockAllocation endpoints."""

from flask import Blueprint, request as freq

from db import db
from errors import (
    ApiError,
    ERR_BLOCK_NOT_ACTIVE,
    ERR_BLOCK_NOT_DRAFT,
    ERR_BLOCK_NOT_FOUND,
    ERR_BLOCK_TIME_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROOM_NOT_FOUND,
    ERR_SERVICE_LINE_NOT_FOUND,
    ERR_SURGEON_NOT_FOUND,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import block_json
from services import (
    new_common,
    touch,
    release_block,
    bump_case,
    recompute_block_metrics,
    run_selector,
    scheduled_cases_of_block,
)
from util import (
    compute_release_deadline,
    iso_seconds,
    is_int,
    parse_date,
)

bp = Blueprint("blocks", __name__)

BLOCK_STATUSES = {"DRAFT", "ACTIVE", "RELEASED", "REDUCED", "CANCELLED"}


def _block_windows(block):
    """(start, end) window a block occupies on its room-day for overlap checks.

    DRAFT/ACTIVE: current window. RELEASED/REDUCED: original window.
    """
    if block["status"] in ("RELEASED", "REDUCED"):
        return block["start_minute"], block["start_minute"] + block["original_minutes"]
    return block["start_minute"], block["end_minute"]


def _check_room_overlap(or_id, date, start, end, exclude_id=None):
    for b in db.blocks.values():
        if b["id"] == exclude_id:
            continue
        if b["or_id"] != or_id or b["date"] != date:
            continue
        if b["status"] == "CANCELLED":
            continue
        bs, be = _block_windows(b)
        if start < be and bs < end:
            raise ApiError(
                ERR_BLOCK_TIME_OVERLAP,
                409,
                "another block overlaps the same room-date window",
            )


@bp.route("/blocks", methods=["POST"])
def create_block():
    require_roles("SchedulingAdmin")
    body = get_json_body()
    service_line_id = body.get("service_line_id")
    or_id = body.get("or_id")
    date = body.get("date")
    start_minute = body.get("start_minute")
    end_minute = body.get("end_minute")
    surgeon_id = body.get("surgeon_id")

    # existence of body FKs in declared order (service_line_id, or_id, surgeon_id)
    if isinstance(service_line_id, str) and service_line_id not in db.service_lines:
        raise ApiError(ERR_SERVICE_LINE_NOT_FOUND, 404, "service line not found")
    if isinstance(or_id, str) and or_id not in db.rooms:
        raise ApiError(ERR_ROOM_NOT_FOUND, 404, "operating room not found")
    if (
        surgeon_id is not None
        and isinstance(surgeon_id, str)
        and surgeon_id not in db.surgeons
    ):
        raise ApiError(ERR_SURGEON_NOT_FOUND, 404, "surgeon not found")

    # shape
    if not isinstance(service_line_id, str) or not service_line_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "service_line_id is required")
    if not isinstance(or_id, str) or not or_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "or_id is required")
    if surgeon_id is not None and not isinstance(surgeon_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "surgeon_id must be a string or null")
    try:
        parse_date(date)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "date must be YYYY-MM-DD")
    if not is_int(start_minute) or not (0 <= start_minute <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "start_minute must be an integer in [0,1440]"
        )
    if not is_int(end_minute) or not (0 <= end_minute <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "end_minute must be an integer in [0,1440]"
        )

    # time range
    if end_minute <= start_minute:
        raise ApiError(
            ERR_INVALID_TIME_RANGE, 400, "end_minute must be after start_minute"
        )

    # room overlap (business rule)
    _check_room_overlap(or_id, date, start_minute, end_minute)

    line = db.service_lines[service_line_id]
    rec = new_common()
    rec.update(
        {
            "service_line_id": service_line_id,
            "surgeon_id": surgeon_id,
            "or_id": or_id,
            "date": date,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "original_minutes": end_minute - start_minute,
            "reserved_minutes": 0,
            "forfeited_minutes": 0,
            "occupied_minutes": 0,
            "release_deadline_at": iso_seconds(
                compute_release_deadline(
                    date, start_minute, line["release_deadline_hours"]
                )
            ),
            "status": "DRAFT",
        }
    )
    db.blocks[rec["id"]] = rec
    return success_object(block_json(rec), 201)


@bp.route("/blocks", methods=["GET"])
def list_blocks():
    get_auth()
    items = list(db.blocks.values())
    sl = freq.args.get("service_line_id")
    if sl is not None:
        items = [b for b in items if b["service_line_id"] == sl]
    if "surgeon_id" in freq.args:
        sv = freq.args.get("surgeon_id")
        items = [b for b in items if b.get("surgeon_id") == sv]
    or_id = freq.args.get("or_id")
    if or_id is not None:
        items = [b for b in items if b["or_id"] == or_id]
    dt = freq.args.get("date")
    if dt is not None:
        items = [b for b in items if b["date"] == dt]
    st = freq.args.get("status")
    if st is not None:
        if st not in BLOCK_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [b for b in items if b["status"] == st]
    out = [block_json(b) for b in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/blocks/<blockId>", methods=["GET"])
def get_block(blockId):
    get_auth()
    rec = db.blocks.get(blockId)
    if rec is None:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    return success_object(block_json(rec))


@bp.route("/blocks/<blockId>/activate", methods=["POST"])
def activate_block(blockId):
    require_roles("SchedulingAdmin")
    rec = db.blocks.get(blockId)
    if rec is None:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_BLOCK_NOT_DRAFT, 409, "activate requires block status DRAFT")
    # activation-time integrity: room overlap (cannot fire given creation checks)
    _check_room_overlap(
        rec["or_id"], rec["date"], rec["start_minute"], rec["end_minute"],
        exclude_id=rec["id"],
    )
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(block_json(rec))


@bp.route("/blocks/<blockId>/release", methods=["POST"])
def release_block_endpoint(blockId):
    auth = require_roles("SchedulingAdmin", "Surgeon")
    rec = db.blocks.get(blockId)
    if rec is None:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    # ownership: surgeon may only release own surgeon-specific blocks;
    # shared blocks (surgeon_id null) are SchedulingAdmin-only.
    if auth.role == "Surgeon":
        if rec.get("surgeon_id") is None or rec["surgeon_id"] != auth.user_id:
            raise ApiError(
                ERR_NOT_RESOURCE_OWNER,
                403,
                "surgeon may only release own surgeon-specific blocks",
            )
    if rec["status"] != "ACTIVE":
        raise ApiError(
            ERR_BLOCK_NOT_ACTIVE, 409, "release requires block status ACTIVE"
        )
    new_slots = release_block(rec)
    for slot in new_slots:
        run_selector(slot)
    return success_object(block_json(rec))


@bp.route("/blocks/<blockId>/cancel", methods=["POST"])
def cancel_block(blockId):
    require_roles("SchedulingAdmin")
    rec = db.blocks.get(blockId)
    if rec is None:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    if rec["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_BLOCK_NOT_ACTIVE, 409, "cancel requires block status DRAFT or ACTIVE"
        )
    if rec["status"] == "ACTIVE":
        # cascade: all SCHEDULED cases in the block -> BUMPED
        for case in scheduled_cases_of_block(rec["id"]):
            bump_case(case)
        recompute_block_metrics(rec)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(block_json(rec))
