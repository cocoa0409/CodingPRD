"""Squawk routes and the maintenance lifecycle that drives aircraft grounding."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_str, get_body, get_user_context, parse_pagination,
                        require_fields, require_role)
from response import list_success, success
from services import cascade
from services.common import fk_or_404, find_or_404

bp = Blueprint("squawks", __name__)


@bp.post("/flight-school/squawks")
def create_squawk():
    _, role = get_user_context()
    require_role(role, {"Mechanic", "Instructor"})
    body = get_body()
    require_fields(body, ["aircraft_id", "description", "is_grounding"])
    aircraft_id = as_str(body, "aircraft_id")
    description = as_str(body, "description")
    is_grounding = body["is_grounding"]
    if not isinstance(is_grounding, bool):
        raise err(errors.ERR_INVALID_REQUEST, "is_grounding must be a boolean.")
    reported_by_instructor_id = body.get("reported_by_instructor_id")

    # FK existence (left-to-right): aircraft, then reporting instructor if given.
    aircraft = fk_or_404(db.aircraft, aircraft_id)
    if reported_by_instructor_id is not None:
        fk_or_404(db.instructors, reported_by_instructor_id)

    record = new_common()
    record.update({
        "aircraft_id": aircraft_id,
        "description": description,
        "is_grounding": is_grounding,
        "reported_by_instructor_id": reported_by_instructor_id,
        "status": "OPEN",
    })
    db.squawks[record["id"]] = record

    if is_grounding:
        aircraft["open_squawk_count"] += 1
        touch(aircraft)
        if aircraft["status"] == "AVAILABLE":
            cascade.ground_aircraft(aircraft)

    return success(public(record), status=201)


@bp.get("/flight-school/squawks")
def list_squawks():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Mechanic", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.squawks.values())
    for field in ("aircraft_id", "reported_by_instructor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(s) for s in page], limit, offset, total)


@bp.get("/flight-school/squawks/<squawk_id>")
def get_squawk(squawk_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Mechanic", "Instructor"})
    record = find_or_404(db.squawks, squawk_id)
    return success(public(record))


def _maybe_unground(aircraft):
    """Recompute open grounding squawk count; unground if it hit zero."""
    if aircraft["open_squawk_count"] == 0 and aircraft["status"] == "GROUNDED":
        cascade.unground_aircraft(aircraft)


@bp.post("/flight-school/squawks/<squawk_id>/resolve")
def resolve_squawk(squawk_id):
    _, role = get_user_context()
    require_role(role, {"Mechanic"})
    squawk = find_or_404(db.squawks, squawk_id)
    if squawk["status"] not in ("OPEN", "DEFERRED"):
        raise err(errors.ERR_SQUAWK_NOT_RESOLVABLE, "Squawk is not resolvable.")
    was_open = squawk["status"] == "OPEN"
    squawk["status"] = "RESOLVED"
    touch(squawk)
    # Decrement count only if it was a grounding squawk that had been OPEN.
    if squawk["is_grounding"] and was_open:
        aircraft = db.aircraft[squawk["aircraft_id"]]
        aircraft["open_squawk_count"] -= 1
        touch(aircraft)
        _maybe_unground(aircraft)
    return success(public(squawk))


@bp.post("/flight-school/squawks/<squawk_id>/defer")
def defer_squawk(squawk_id):
    _, role = get_user_context()
    require_role(role, {"Mechanic"})
    squawk = find_or_404(db.squawks, squawk_id)
    if squawk["status"] != "OPEN":
        raise err(errors.ERR_SQUAWK_NOT_OPEN, "Squawk is not OPEN.")
    if squawk["is_grounding"]:
        raise err(errors.ERR_GROUNDING_SQUAWK_NOT_DEFERRABLE,
                  "A grounding squawk cannot be deferred.")
    squawk["status"] = "DEFERRED"
    touch(squawk)
    return success(public(squawk))


@bp.post("/flight-school/squawks/<squawk_id>/reopen")
def reopen_squawk(squawk_id):
    _, role = get_user_context()
    require_role(role, {"Mechanic"})
    squawk = find_or_404(db.squawks, squawk_id)
    if squawk["status"] not in ("RESOLVED", "DEFERRED"):
        raise err(errors.ERR_SQUAWK_NOT_REOPENABLE, "Squawk is not reopenable.")
    was_deferred = squawk["status"] == "DEFERRED"
    squawk["status"] = "OPEN"
    touch(squawk)
    # Reopening a grounding squawk increments the count (a grounding squawk can
    # only have been RESOLVED, never DEFERRED, since grounding ones cannot be
    # deferred). Re-ground if necessary.
    if squawk["is_grounding"] and not was_deferred:
        aircraft = db.aircraft[squawk["aircraft_id"]]
        aircraft["open_squawk_count"] += 1
        touch(aircraft)
        if aircraft["status"] == "AVAILABLE":
            cascade.ground_aircraft(aircraft)
    return success(public(squawk))
