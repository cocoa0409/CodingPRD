"""ServiceWindow endpoints (PRD §3.8): create maintenance/blackout window."""
from flask import Blueprint

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response
import clock
from services import calc

bp = Blueprint("windows", __name__)


@bp.route("/service-windows", methods=["POST"])
def create_window():
    p = authenticate()
    authorize(p, {"SystemAdmin"})
    data = validate.body()
    window_type = validate.require_enum(data, "window_type", validate.WINDOW_TYPES)
    department_id = validate.opt_str(data, "department_id", None)
    jurisdiction_id = validate.opt_str(data, "jurisdiction_id", None)
    starts_at_raw = validate.require_str(data, "starts_at")
    ends_at_raw = validate.require_str(data, "ends_at")
    try:
        starts_at = clock.parse_iso(starts_at_raw)
        ends_at = clock.parse_iso(ends_at_raw)
    except ValueError:
        raise errors.invalid_request("starts_at/ends_at must be ISO 8601 instants.")

    # priority 3: existence of referenced scope id (left-to-right).
    if department_id is not None and department_id not in db.departments:
        raise errors.not_found("Department not found.")
    if jurisdiction_id is not None and jurisdiction_id not in db.jurisdictions:
        raise errors.not_found("Jurisdiction not found.")

    # priority 19: scope consistency.
    if window_type == "MAINTENANCE":
        if department_id is None or jurisdiction_id is not None:
            raise errors.window_scope_invalid()
    else:  # BLACKOUT
        if jurisdiction_id is None or department_id is not None:
            raise errors.window_scope_invalid()

    # ends_at strictly after starts_at (schema constraint).
    if not (ends_at > starts_at):
        raise errors.invalid_request("ends_at must be strictly after starts_at.")

    # priority 20: overlap with existing same-type, same-scope window.
    for w in db.windows.values():
        if w["window_type"] != window_type:
            continue
        if window_type == "MAINTENANCE" and w["department_id"] != department_id:
            continue
        if window_type == "BLACKOUT" and w["jurisdiction_id"] != jurisdiction_id:
            continue
        w_start = clock.parse_iso(w["starts_at"])
        w_end = clock.parse_iso(w["ends_at"])
        if calc.windows_collide(window_type, starts_at, ends_at, w_start, w_end):
            raise errors.window_overlap()

    rec = {
        "window_type": window_type,
        "department_id": department_id,
        "jurisdiction_id": jurisdiction_id,
        "starts_at": clock.fmt(starts_at),
        "ends_at": clock.fmt(ends_at),
    }
    db.stamp_common(rec)
    db.windows[rec["id"]] = rec
    return response.object_response(serialize.view("window", rec), 201)
