"""TestBlueprint endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_DUPLICATE_CODE,
    ERR_BLUEPRINT_NOT_DRAFT,
    ERR_BLUEPRINT_NOT_LOCKED,
    ERR_EMPTY_BLUEPRINT,
    ERR_INVALID_SECTION_SIZE,
    ERR_FORMS_STILL_ACTIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from util import new_id, now_ts
from validate import get_body, req_str, require_path_resource, require_body_ref

bp = Blueprint("blueprints", __name__)

READ_ROLES = ["ProgramDirector", "TestAssembler", "Psychometrician"]


def _validate_sections(body):
    sections = body.get("sections")
    if not isinstance(sections, list) or len(sections) < 1 or len(sections) > 8:
        raise_error(ERR_INVALID_REQUEST, "sections must be an array of 1..8 entries")
    out = []
    for i, s in enumerate(sections):
        if not isinstance(s, dict):
            raise_error(ERR_INVALID_REQUEST, f"sections[{i}] must be an object")
        strand = s.get("strand")
        if not isinstance(strand, str) or strand.strip() == "":
            raise_error(ERR_INVALID_REQUEST, f"sections[{i}].strand must be a non-empty string")
        for f in ("item_count", "dok_min", "dok_max"):
            v = s.get(f)
            if v is None or isinstance(v, bool) or not isinstance(v, int):
                raise_error(ERR_INVALID_REQUEST, f"sections[{i}].{f} must be an integer")
        out.append(
            {
                "strand": strand,
                "item_count": s["item_count"],
                "dok_min": s["dok_min"],
                "dok_max": s["dok_max"],
            }
        )
    return out


@bp.post("/api/test-blueprints")
def create_blueprint():
    caller = authorized(["TestAssembler"])
    body = get_body()
    program_id = req_str(body, "program_id")
    blueprint_code = req_str(body, "blueprint_code")
    sections = _validate_sections(body)

    require_body_ref("assessment_programs", program_id, "program_id")

    for b in db["test_blueprints"].values():
        if b["program_id"] == program_id and b["blueprint_code"] == blueprint_code:
            raise_error(ERR_DUPLICATE_CODE, f"blueprint_code {blueprint_code} already exists in program")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "blueprint_code": blueprint_code,
        "sections": sections,
        "total_items_required": sum(s["item_count"] for s in sections),
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    db["test_blueprints"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/test-blueprints")
def list_blueprints():
    authorized(READ_ROLES)
    filters = {"program_id": request.args.get("program_id")}
    return list_response("test_blueprints", filters)


@bp.get("/api/test-blueprints/<bid>")
def get_blueprint(bid):
    authorized(READ_ROLES)
    rec = require_path_resource("test_blueprints", bid)
    return get_one(rec)


@bp.post("/api/test-blueprints/<bid>/lock")
def lock_blueprint(bid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("test_blueprints", bid)
    get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_BLUEPRINT_NOT_DRAFT, "blueprint must be DRAFT to lock")
    if not rec["sections"]:
        raise_error(ERR_EMPTY_BLUEPRINT, "blueprint must have at least one section to lock")
    for s in rec["sections"]:
        if s["item_count"] < 1:
            raise_error(ERR_INVALID_SECTION_SIZE, "each section's item_count must be >= 1")
    rec["status"] = "LOCKED"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/test-blueprints/<bid>/supersede")
def supersede_blueprint(bid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("test_blueprints", bid)
    get_body()
    if rec["status"] != "LOCKED":
        raise_error(ERR_BLUEPRINT_NOT_LOCKED, "blueprint must be LOCKED to supersede")
    for form in db["test_forms"].values():
        if form["blueprint_id"] == bid and form["status"] != "ARCHIVED":
            raise_error(ERR_FORMS_STILL_ACTIVE, "forms under this blueprint are still active")
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return success_object(public(rec))
