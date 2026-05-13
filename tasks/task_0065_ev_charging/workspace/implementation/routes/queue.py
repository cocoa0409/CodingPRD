"""Queue endpoints."""

from flask import Blueprint, g, request

import db
from clock import now_iso
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from services import queue_service
from validators import (
    check_version,
    get_pagination,
    paginate_list,
    parse_json_body,
)


bp = Blueprint("queue", __name__)


@bp.post("/stations/<station_id>/queue-entries")
@require_roles({"EVDriver"})
def join_queue(station_id: str):
    station = db.stations.get(station_id)
    if station is None:
        raise_error("ERR_NOT_FOUND", "station not found")
    parse_json_body()  # body may be empty; validate JSON-ness

    waiting = queue_service.waiting_entries_at_station(station_id)
    position = (max(q["position"] for q in waiting) + 1) if waiting else 1
    record = {
        "station_id": station_id,
        "member_id": g.user_id,
        "position": position,
        "status": "WAITING",
        "enqueued_at": now_iso(),
    }
    db.with_common_fields(record)
    db.queue_entries[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/queue-entries/<entry_id>/abandon")
@require_roles({"EVDriver"})
def abandon_queue(entry_id: str):
    entry = db.queue_entries.get(entry_id)
    if entry is None:
        raise_error("ERR_NOT_FOUND", "queue entry not found")
    body = parse_json_body()
    check_version(body, entry)
    if entry["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your queue entry")
    if entry["status"] != "WAITING":
        raise_error("ERR_INVALID_STATE", "queue entry not WAITING")
    old_position = entry["position"]
    entry["status"] = "ABANDONED"
    db.bump(entry)
    queue_service.decrement_positions_after(entry["station_id"], old_position)
    return success(db.public(entry))


@bp.get("/stations/<station_id>/queue-entries")
@require_roles({"EVDriver", "StationOwner", "PlatformOperator", "CustomerService"})
def list_queue(station_id: str):
    if station_id not in db.stations:
        raise_error("ERR_NOT_FOUND", "station not found")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = [q for q in db.queue_entries.values() if q["station_id"] == station_id]
    items.sort(key=lambda q: q["_seq"])
    if status:
        items = [q for q in items if q["status"] == status]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)
