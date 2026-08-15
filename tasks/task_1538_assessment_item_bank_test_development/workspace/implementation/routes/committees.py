"""ReviewCommittee endpoints."""
from flask import Blueprint, request

from db import db, next_seq
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from util import new_id, now_ts
from validate import get_body, req_str, req_enum, req_int, require_path_resource, require_body_ref

bp = Blueprint("committees", __name__)

COMMITTEE_KINDS = ["CONTENT", "BIAS_SENSITIVITY"]
READ_ROLES = ["ProgramDirector", "ContentReviewer", "BiasSensitivityReviewer"]


@bp.post("/api/review-committees")
def create_committee():
    caller = authorized(["ProgramDirector"])
    body = get_body()
    program_id = req_str(body, "program_id")
    committee_kind = req_enum(body, "committee_kind", COMMITTEE_KINDS)
    name = req_str(body, "name")
    quorum_size = req_int(body, "quorum_size", minimum=2, maximum=7)

    require_body_ref("assessment_programs", program_id, "program_id")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "committee_kind": committee_kind,
        "name": name,
        "quorum_size": quorum_size,
        "status": "ACTIVE",
        "_seq": next_seq(),
    }
    db["review_committees"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/review-committees")
def list_committees():
    authorized(READ_ROLES)
    filters = {"program_id": request.args.get("program_id")}
    return list_response("review_committees", filters)


@bp.get("/api/review-committees/<cid>")
def get_committee(cid):
    authorized(READ_ROLES)
    rec = require_path_resource("review_committees", cid)
    return get_one(rec)
