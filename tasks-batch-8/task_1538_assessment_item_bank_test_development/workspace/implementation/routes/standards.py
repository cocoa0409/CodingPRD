"""ContentStandard endpoints."""
from flask import Blueprint, request

from db import db, next_seq
from errors import raise_error, ERR_DUPLICATE_CODE
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from util import new_id, now_ts
from validate import get_body, req_str, req_int, require_path_resource, require_body_ref

bp = Blueprint("standards", __name__)


@bp.post("/api/content-standards")
def create_standard():
    caller = authorized(["ProgramDirector"])
    body = get_body()
    program_id = req_str(body, "program_id")
    standard_code = req_str(body, "standard_code")
    strand = req_str(body, "strand")
    description = req_str(body, "description")
    depth_of_knowledge = req_int(body, "depth_of_knowledge", minimum=1, maximum=4)

    require_body_ref("assessment_programs", program_id, "program_id")

    for s in db["content_standards"].values():
        if s["program_id"] == program_id and s["standard_code"] == standard_code:
            raise_error(ERR_DUPLICATE_CODE, f"standard_code {standard_code} already exists in program")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "standard_code": standard_code,
        "strand": strand,
        "description": description,
        "depth_of_knowledge": depth_of_knowledge,
        "status": "ACTIVE",
        "_seq": next_seq(),
    }
    db["content_standards"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/content-standards")
def list_standards():
    authorized(ALL_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "strand": request.args.get("strand"),
    }
    return list_response("content_standards", filters)


@bp.get("/api/content-standards/<csid>")
def get_standard(csid):
    authorized(ALL_ROLES)
    rec = require_path_resource("content_standards", csid)
    return get_one(rec)
