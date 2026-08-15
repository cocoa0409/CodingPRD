"""HarvestLine endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_CROSS_SCOPE_REFERENCE,
    ERR_FIELD_NOT_OPEN,
    ERR_INVALID_STATE,
    ERR_LINE_NOT_PROVISIONAL,
    ERR_NOT_FOUND,
    ERR_SESSION_NOT_ACTIVE,
    ERR_TARE_EXCEEDS_GROSS,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("harvest_lines", __name__)

FIELD = ("FieldStaff", "FarmManager")
READERS = ("FarmManager", "FieldStaff")


def _make_line(session, crop, gross_weight_oz, container_count, status, offline_ref):
    field = domain.field_of_session(session)
    tare_oz, net_oz, line_charge_cents = domain.compute_line_values(
        crop, gross_weight_oz, container_count
    )
    line = domain.new_entity()
    line.update(
        {
            "session_id": session["id"],
            "field_id": field["id"],
            "crop_id": crop["id"],
            "gross_weight_oz": gross_weight_oz,
            "container_count": container_count,
            "tare_oz": tare_oz,
            "net_oz": net_oz,
            "line_charge_cents": line_charge_cents,
            "status": status,
            "offline_ref": offline_ref,
        }
    )
    db.harvest_lines[line["id"]] = line
    return line


@bp.post("/farm/harvest-lines")
def create_line():
    require(FIELD)
    body = get_body()
    check_no_undeclared(
        body, {"session_id", "crop_id", "gross_weight_oz", "container_count"}
    )
    session_id = req_str(body, "session_id")
    crop_id = req_str(body, "crop_id")
    gross = req_int(body, "gross_weight_oz", min_value=0)
    container_count = req_int(body, "container_count", min_value=0)
    # Body foreign keys (tier 5).
    session = db.visit_sessions.get(session_id)
    if session is None:
        raise_err(ERR_NOT_FOUND, "session_id does not resolve")
    crop = db.crops.get(crop_id)
    if crop is None:
        raise_err(ERR_NOT_FOUND, "crop_id does not resolve")
    # Tier 11: tare may not exceed gross (zero net is legal).
    if gross - container_count * domain.TARE_OZ_PER_CONTAINER < 0:
        raise_err(ERR_TARE_EXCEEDS_GROSS, "Tare exceeds gross weight")
    # Tier 12: session must be FIELD_ACTIVE, field must be OPEN.
    if session["visit_status"] != "FIELD_ACTIVE":
        raise_err(ERR_SESSION_NOT_ACTIVE, "Session is not FIELD_ACTIVE")
    field = domain.field_of_session(session)
    if field is None or field["status"] != "OPEN":
        raise_err(ERR_FIELD_NOT_OPEN, "Field is not OPEN")
    # Tier 13: crop must belong to the same season scope.
    if crop["season_id"] != field["season_id"]:
        raise_err(ERR_CROSS_SCOPE_REFERENCE, "Crop belongs to a different season")
    # Online staff weigh-out is born FINALIZED.
    line = _make_line(session, crop, gross, container_count, "FINALIZED", None)
    domain.tally_after_line_mutation(field, crop)
    return ok_object(domain.serialize_line(line), 201)


@bp.get("/farm/harvest-lines/<lid>")
def get_line(lid):
    require(READERS)
    line = db.harvest_lines.get(lid)
    if line is None:
        raise_err(ERR_NOT_FOUND, "HarvestLine not found")
    return ok_object(domain.serialize_line(line))


@bp.get("/farm/harvest-lines")
def list_lines():
    require(READERS)
    items = list(db.harvest_lines.values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        items = [l for l in items if l["session_id"] == session_id]
    field_id = request.args.get("field_id")
    if field_id is not None:
        items = [l for l in items if l["field_id"] == field_id]
    crop_id = request.args.get("crop_id")
    if crop_id is not None:
        items = [l for l in items if l["crop_id"] == crop_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return paginate(items, domain.serialize_line)


@bp.post("/farm/harvest-lines/<lid>/finalize")
def finalize_line(lid):
    require(FIELD)
    line = db.harvest_lines.get(lid)
    if line is None:
        raise_err(ERR_NOT_FOUND, "HarvestLine not found")
    if line["status"] != "PROVISIONAL":
        raise_err(ERR_LINE_NOT_PROVISIONAL, "Only a PROVISIONAL line can be finalized")
    session = db.visit_sessions.get(line["session_id"])
    if session is None or session["visit_status"] != "FIELD_ACTIVE":
        raise_err(ERR_SESSION_NOT_ACTIVE, "Session is not FIELD_ACTIVE")
    field = db.fields.get(line["field_id"])
    if field is None or field["status"] != "OPEN":
        raise_err(ERR_FIELD_NOT_OPEN, "Field is not OPEN")
    line["status"] = "FINALIZED"
    domain.touch(line)
    crop = db.crops.get(line["crop_id"])
    domain.tally_after_line_mutation(field, crop)
    return ok_object(domain.serialize_line(line))


@bp.post("/farm/harvest-lines/<lid>/void")
def void_line(lid):
    require(FIELD)
    line = db.harvest_lines.get(lid)
    if line is None:
        raise_err(ERR_NOT_FOUND, "HarvestLine not found")
    if line["status"] == "VOIDED":
        raise_err(ERR_INVALID_STATE, "Line is already VOIDED")
    session = db.visit_sessions.get(line["session_id"])
    if session is not None and session["visit_status"] == "CHECKED_OUT":
        raise_err(ERR_INVALID_STATE, "Cannot void a line whose session is CHECKED_OUT")
    was_finalized = line["status"] == "FINALIZED"
    line["status"] = "VOIDED"
    domain.touch(line)
    field = db.fields.get(line["field_id"])
    if field is not None:
        crop = db.crops.get(line["crop_id"]) if was_finalized else None
        domain.tally_after_line_mutation(field, crop)
    return ok_object(domain.serialize_line(line))
