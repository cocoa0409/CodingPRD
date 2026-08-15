"""AccessGrant endpoints (PRD §2.11)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import raise_error, ERR_INVALID_STATE, ERR_GRANT_OVERLAP
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from services.grants import check_grant, find_full_overlap
from util import new_id, now_ts, parse_dt, program_clock_iso
from validate import get_body, req_str, req_enum, req_datetime, require_path_resource, require_body_ref

bp = Blueprint("grants", __name__)

GRANT_SCOPES = ["ITEM_READ", "ITEM_WRITE", "STATS_READ", "FORM_ASSEMBLE", "GRANT_ADMIN"]
READ_ROLES = ["ProgramDirector", "SecurityOfficer"]


@bp.post("/api/access-grants")
def create_grant():
    caller = authorized(["SecurityOfficer"])
    body = get_body()
    program_id = req_str(body, "program_id")
    grantee_user_id = req_str(body, "grantee_user_id")
    grant_scope = req_enum(body, "grant_scope", GRANT_SCOPES)
    valid_from = req_datetime(body, "valid_from")
    valid_until = req_datetime(body, "valid_until")

    program = require_body_ref("assessment_programs", program_id, "program_id")

    # Issuing new grants requires GRANT_ADMIN once the program has GRANT_ADMIN
    # grants configured (bootstrap: the first grants may be issued freely).
    check_grant(caller, program_id, "GRANT_ADMIN")

    from_dt, until_dt = parse_dt(valid_from), parse_dt(valid_until)
    if not from_dt < until_dt:
        raise_error(ERR_GRANT_OVERLAP, "valid_until must be strictly later than valid_from")

    if find_full_overlap(program_id, grantee_user_id, grant_scope, from_dt, until_dt) is not None:
        raise_error(
            ERR_GRANT_OVERLAP,
            "new grant's interval fully overlaps an existing active grant for the same grantee and scope",
        )

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "grantee_user_id": grantee_user_id,
        "grant_scope": grant_scope,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "revoked_at": None,
        "_valid_from_dt": from_dt,
        "_valid_until_dt": until_dt,
        "_seq": next_seq(),
    }
    db["access_grants"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/access-grants")
def list_grants():
    authorized(READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "grantee_user_id": request.args.get("grantee_user_id"),
        "grant_scope": request.args.get("grant_scope"),
    }
    return list_response("access_grants", filters)


@bp.get("/api/access-grants/<gid>")
def get_grant(gid):
    authorized(READ_ROLES)
    rec = require_path_resource("access_grants", gid)
    return get_one(rec)


@bp.post("/api/access-grants/<gid>/revoke")
def revoke_grant(gid):
    caller = authorized(["SecurityOfficer"])
    rec = require_path_resource("access_grants", gid)
    get_body()
    if rec["revoked_at"] is not None:
        raise_error(ERR_INVALID_STATE, "grant is already revoked")
    program = db["assessment_programs"].get(rec["program_id"])
    rec["revoked_at"] = program_clock_iso(program)
    touch(rec)
    return success_object(public(rec))
