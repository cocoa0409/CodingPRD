"""TestForm and FormItemSlot endpoints (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_CODE,
    ERR_BLUEPRINT_NOT_LOCKED,
    ERR_FORM_NOT_ASSEMBLING,
    ERR_FORM_NOT_EQUATED,
    ERR_FORM_NOT_PUBLISHED,
    ERR_ARCHIVE_TOO_EARLY,
    ERR_NO_PUBLISHED_DOSSIER,
    ERR_STALE_VERSION,
    ERR_SLOT_ITEM_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one, truthy_param
from services.common import touch
from services.forms import assemble_form
from services.grants import check_grant
from util import new_id, now_ts, parse_dt, program_clock_iso
from validate import (
    get_body, req_str, req_int, opt_bool, req_datetime,
    require_path_resource, require_body_ref,
)

bp = Blueprint("forms", __name__)

READ_ROLES = ["ProgramDirector", "TestAssembler", "Psychometrician"]
ARCHIVE_WINDOW = timedelta(days=90)


@bp.post("/api/test-forms")
def create_form():
    caller = authorized(["TestAssembler"])
    body = get_body()
    blueprint_id = req_str(body, "blueprint_id")
    form_code = req_str(body, "form_code")
    intended_admin_date = req_datetime(body, "intended_admin_date")

    blueprint = require_body_ref("test_blueprints", blueprint_id, "blueprint_id")
    if blueprint["status"] != "LOCKED":
        raise_error(ERR_BLUEPRINT_NOT_LOCKED, "forms may only be created under a LOCKED blueprint")

    for f in db["test_forms"].values():
        if f["blueprint_id"] == blueprint_id and f["form_code"] == form_code:
            raise_error(ERR_DUPLICATE_CODE, f"form_code {form_code} already exists in blueprint")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "blueprint_id": blueprint_id,
        "program_id": blueprint["program_id"],
        "form_code": form_code,
        "intended_admin_date": intended_admin_date,
        "status": "ASSEMBLING",
        "assembled_at": None,
        "published_at": None,
        "_admin_dt": parse_dt(intended_admin_date),
        "_seq": next_seq(),
    }
    db["test_forms"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/test-forms")
def list_forms():
    authorized(READ_ROLES)
    include_archived = truthy_param("include_archived")
    filters = {
        "blueprint_id": request.args.get("blueprint_id"),
        "program_id": request.args.get("program_id"),
        "status": request.args.get("status"),
    }

    def visible(rec):
        if rec["status"] == "ARCHIVED" and not include_archived:
            return False
        return True

    return list_response("test_forms", filters, exclude=visible)


@bp.get("/api/test-forms/<fid>")
def get_form(fid):
    authorized(READ_ROLES)
    rec = require_path_resource("test_forms", fid)
    return get_one(rec)


@bp.post("/api/test-forms/<fid>/assemble")
def assemble(fid):
    caller = authorized(["TestAssembler"])
    rec = require_path_resource("test_forms", fid)
    body = get_body()
    expected = req_int(body, "expected_form_version")
    if expected != rec["version"]:
        raise_error(ERR_STALE_VERSION, "expected_form_version does not match the form's current version")
    if rec["status"] != "ASSEMBLING":
        raise_error(ERR_FORM_NOT_ASSEMBLING, "form must be ASSEMBLING to assemble")
    blueprint = db["test_blueprints"].get(rec["blueprint_id"])
    program = db["assessment_programs"].get(rec["program_id"])
    assemble_form(rec, blueprint, program)
    return success_object(public(rec))


@bp.post("/api/test-forms/<fid>/publish")
def publish(fid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("test_forms", fid)
    get_body()
    if rec["status"] != "EQUATED":
        raise_error(ERR_FORM_NOT_EQUATED, "form must be EQUATED to publish")
    has_published_dossier = any(
        d["form_id"] == fid and d["status"] == "PUBLISHED"
        for d in db["validity_dossiers"].values()
    )
    if not has_published_dossier:
        raise_error(ERR_NO_PUBLISHED_DOSSIER, "no PUBLISHED ValidityDossier exists for this form")
    program = db["assessment_programs"].get(rec["program_id"])
    rec["status"] = "PUBLISHED"
    rec["published_at"] = program_clock_iso(program)
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/test-forms/<fid>/archive")
def archive(fid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("test_forms", fid)
    get_body()
    if rec["status"] != "PUBLISHED":
        raise_error(ERR_FORM_NOT_PUBLISHED, "form must be PUBLISHED to archive")
    program = db["assessment_programs"].get(rec["program_id"])
    if program["_clock_dt"] <= rec["_admin_dt"] + ARCHIVE_WINDOW:
        raise_error(ERR_ARCHIVE_TOO_EARLY, "program clock must be more than 90 days past intended_admin_date")
    rec["status"] = "ARCHIVED"
    touch(rec)
    return success_object(public(rec))


# ---------------------------------------------------------------------------
# Form item slots
# ---------------------------------------------------------------------------

@bp.post("/api/test-forms/<fid>/slots")
def create_slot(fid):
    caller = authorized(["TestAssembler"])
    form = require_path_resource("test_forms", fid)
    body = get_body()
    item_id = req_str(body, "item_id")
    section_index = req_int(body, "section_index", minimum=0)
    position_in_section = req_int(body, "position_in_section", minimum=1)
    is_anchor = opt_bool(body, "is_anchor", default=False)

    if form["status"] != "ASSEMBLING":
        raise_error(ERR_FORM_NOT_ASSEMBLING, "slots may only be added to an ASSEMBLING form")
    check_grant(caller, form["program_id"], "FORM_ASSEMBLE")

    item = require_body_ref("items", item_id, "item_id")
    if item["status"] != "OPERATIONAL" or item["security_posture"] not in ("SECURED", "EXPOSED"):
        raise_error(ERR_SLOT_ITEM_INVALID, "slot item must be OPERATIONAL with posture SECURED or EXPOSED")
    for s in db["form_item_slots"].values():
        if s["form_id"] == fid and s["item_id"] == item_id:
            raise_error(ERR_SLOT_ITEM_INVALID, "item already appears on this form")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "form_id": fid,
        "item_id": item_id,
        "section_index": section_index,
        "position_in_section": position_in_section,
        "is_anchor": is_anchor,
        "points_possible": item["max_score_points"],
        "_seq": next_seq(),
    }
    db["form_item_slots"][rec["id"]] = rec
    touch(form)
    return success_object(public(rec), status=201)


@bp.get("/api/form-item-slots")
def list_slots():
    authorized(READ_ROLES)
    section_raw = request.args.get("section_index")
    filters = {
        "form_id": request.args.get("form_id"),
        "item_id": request.args.get("item_id"),
    }
    if section_raw is not None:
        try:
            filters["section_index"] = int(section_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "section_index must be an integer")
    return list_response("form_item_slots", filters)


@bp.get("/api/form-item-slots/<sid>")
def get_slot(sid):
    authorized(READ_ROLES)
    rec = require_path_resource("form_item_slots", sid)
    return get_one(rec)


@bp.delete("/api/form-item-slots/<sid>")
def delete_slot(sid):
    caller = authorized(["TestAssembler"])
    rec = require_path_resource("form_item_slots", sid)
    form = db["test_forms"].get(rec["form_id"])
    if form is not None and form["status"] != "ASSEMBLING":
        raise_error(ERR_FORM_NOT_ASSEMBLING, "slots may only be removed from an ASSEMBLING form")
    del db["form_item_slots"][sid]
    if form is not None:
        touch(form)
    return "", 204
