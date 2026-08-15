"""Aircraft endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import aircraft_view, new_common
from util import as_str, body, paginate_sorted, required

bp = Blueprint("aircraft", __name__)


def _get_aircraft(aid):
    a = db.aircraft.get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft not found")
    return a


@bp.route("/aircraft", methods=["POST"])
def create_aircraft():
    require_roles("FleetOps")
    data = body()
    program_id = as_str(required(data, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if not program:
        raise ApiError("ERR_NOT_FOUND", 404, "Program not found")
    tail_number = as_str(required(data, "tail_number"), "tail_number")
    class_id = as_str(required(data, "class_id"), "class_id")
    cls = db.aircraft_classes.get(class_id)
    if not cls or cls["program_id"] != program_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft class not found")
    for a in db.aircraft.values():
        if a["program_id"] == program_id and a["tail_number"] == tail_number:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "tail_number must be unique within program",
            )

    rec = new_common()
    rec.update({
        "tail_number": tail_number,
        "program_id": program_id,
        "class_id": class_id,
        "aircraft_status": "IN_SERVICE",
        "total_hours_flown": 0.0,
    })
    db.aircraft[rec["id"]] = rec
    return ok(aircraft_view(rec), status=201)


@bp.route("/aircraft/<aid>", methods=["GET"])
def get_aircraft(aid):
    require_roles(*ALL_ROLES)
    return ok(aircraft_view(_get_aircraft(aid)))


@bp.route("/aircraft", methods=["GET"])
def list_aircraft():
    require_roles(*ALL_ROLES)
    program_id = request.args.get("program_id")
    class_id = request.args.get("class_id")
    status = request.args.get("aircraft_status")
    items = list(db.aircraft.values())
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if class_id is not None:
        items = [a for a in items if a["class_id"] == class_id]
    if status is not None:
        items = [a for a in items if a["aircraft_status"] == status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([aircraft_view(a) for a in page], total, limit, offset)
