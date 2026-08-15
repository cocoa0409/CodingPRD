"""Processing lines + waiver creation under lines."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_LINE_VERSION,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_int,
    check_string,
    parse_iso8601,
    parse_pagination,
)
from response import success_object, success_list
from services.core import new_entity, _touch, lazy_line, lazy_waiver
from services.serializers import (
    serialize_line,
    serialize_waiver,
    serialize_sanitation_run,
    serialize_preop,
)

bp = Blueprint("lines", __name__)

LINE_TYPES = ("EVISCERATION", "DEBONING")


@bp.route("/poultry/lines", methods=["POST"])
def create_line():
    require_roles("PlantManager")
    body = get_json_body()
    check_no_unknown(body, {"line_code", "line_type", "rated_speed_bpm"})
    check_required(body, ["line_code", "line_type", "rated_speed_bpm"])
    check_string(body["line_code"], "line_code")
    check_enum(body["line_type"], LINE_TYPES, "line_type")
    check_int(body["rated_speed_bpm"], "rated_speed_bpm", min_value=1)

    line = new_entity()
    line.update({
        "line_code": body["line_code"],
        "line_type": body["line_type"],
        "rated_speed_bpm": body["rated_speed_bpm"],
    })
    db.lines[line["id"]] = line
    return success_object(serialize_line(line), 201)


@bp.route("/poultry/lines/<line_id>", methods=["GET"])
def get_line(line_id):
    require_roles(*db_roles_all())
    line = db.lines.get(line_id)
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Processing line not found", 404)
    lazy_line(line_id)
    return success_object(serialize_line(line))


def db_roles_all():
    return (
        "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
        "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
    )


@bp.route("/poultry/lines/<line_id>/waivers", methods=["GET"])
def list_line_waivers(line_id):
    require_roles(*db_roles_all())
    line = db.lines.get(line_id)
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Processing line not found", 404)
    lazy_line(line_id)
    items = [w for w in db.waivers.values() if w["line_id"] == line_id]
    items.sort(key=lambda w: w["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_waiver(w) for w in page], limit, offset, len(items))


@bp.route("/poultry/lines/<line_id>/sanitation-runs", methods=["GET"])
def list_line_sanitation_runs(line_id):
    require_roles(*db_roles_all())
    line = db.lines.get(line_id)
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Processing line not found", 404)
    items = [r for r in db.sanitation_runs.values() if r["line_id"] == line_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_sanitation_run(r) for r in page], limit, offset, len(items))


@bp.route("/poultry/lines/<line_id>/pre-op-inspections", methods=["GET"])
def list_line_preops(line_id):
    require_roles(*db_roles_all())
    line = db.lines.get(line_id)
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Processing line not found", 404)
    items = [p for p in db.preop_inspections.values() if p["line_id"] == line_id]
    items.sort(key=lambda p: p["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_preop(p) for p in page], limit, offset, len(items))


@bp.route("/poultry/lines/<line_id>/waivers", methods=["POST"])
def create_waiver(line_id):
    require_roles("PlantManager")
    line = db.lines.get(line_id)
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Processing line not found", 404)
    body = get_json_body()
    check_no_unknown(
        body,
        {"max_speed_bpm", "effective_from", "effective_to", "expected_line_version"},
    )
    check_required(
        body, ["max_speed_bpm", "effective_from", "effective_to", "expected_line_version"]
    )
    check_int(body["max_speed_bpm"], "max_speed_bpm", min_value=1)
    effective_from = parse_iso8601(body["effective_from"], "effective_from")
    effective_to = parse_iso8601(body["effective_to"], "effective_to")
    if effective_from >= effective_to:
        raise ApiError(
            ERR_INVALID_REQUEST, "effective_from must be strictly earlier than effective_to", 400
        )
    check_int(body["expected_line_version"], "expected_line_version")

    # OCC (priority 3.5) — before any business validation
    if body["expected_line_version"] != line["version"]:
        raise ApiError(
            ERR_STALE_LINE_VERSION,
            "expected_line_version does not match the line's current version",
            412,
        )

    # Supersede overlapping DRAFT/SUBMITTED waivers on this line (half-open windows)
    for w in db.waivers.values():
        if w["line_id"] != line_id or w["status"] not in ("DRAFT", "SUBMITTED"):
            continue
        if w["effective_from"] < effective_to and effective_from < w["effective_to"]:
            w["status"] = "SUPERSEDED"
            _touch(w)

    waiver = new_entity()
    waiver.update({
        "line_id": line_id,
        "max_speed_bpm": body["max_speed_bpm"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "denial_count": 0,
        "approved_by": None,
    })
    db.waivers[waiver["id"]] = waiver

    # Waiver creation increments the line's version by 1
    _touch(line)

    return success_object(serialize_waiver(waiver), 201)
