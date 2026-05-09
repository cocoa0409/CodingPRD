from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields
from envelope import created
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_INPUT, ERR_MAINTENANCE_WINDOW_OVERLAP
from validation import need_body, require_str, require_timestamp
from serializers import serialize_maintenance_window

bp = Blueprint("maintenance_windows", __name__)


@bp.post("/maintenance-windows")
def create_window():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))
    cabinet_id = require_str(body, "cabinet_id")
    window_start = require_timestamp(body, "window_start")
    window_end = require_timestamp(body, "window_end")

    if db.cabinets.get(cabinet_id) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")
    if window_end <= window_start:
        raise APIError(ERR_INVALID_INPUT, 400, "window_end must be > window_start")

    # Half-open intervals — [a.start, a.end) ∩ [b.start, b.end) == ∅; touching allowed.
    for w in db.maintenance_windows.values():
        if w["cabinet_id"] != cabinet_id:
            continue
        if w["status"] != "SCHEDULED":
            continue
        # Strict overlap (touching ok). Overlap iff a.start < b.end AND b.start < a.end.
        if window_start < w["window_end"] and w["window_start"] < window_end:
            raise APIError(ERR_MAINTENANCE_WINDOW_OVERLAP, 409,
                           "Maintenance window overlaps an existing scheduled window")

    cf = make_common_fields()
    win = {
        **cf,
        "cabinet_id": cabinet_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    }
    db.maintenance_windows[win["id"]] = win
    return created(serialize_maintenance_window(win))
