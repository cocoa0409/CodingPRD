"""CommitteeMember endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_COMMITTEE_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_CHAIR_CONFLICT,
    ERR_INVALID_INTERVAL,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from util import parse_dt, is_valid_dt
from validate import (
    get_body, req_str, req_enum, req_datetime_str, require_path, raw_str,
)

bp = Blueprint("members", __name__)

ROLES_IN_COMMITTEE = {"MEMBER", "CHAIR"}


@bp.post("/members")
def create_member():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 4: committee FK existence.
    committee = None
    committee_id_raw = raw_str(body, "committee_id")
    if committee_id_raw is not None:
        committee = db["committees"].get(committee_id_raw)
        if committee is None:
            raise_error(ERR_COMMITTEE_NOT_FOUND, "committee_id does not resolve")
    # Priority 9, listed order: chair conflict -> interval sanity -> shape.
    role_raw = body.get("role_in_committee")
    if committee is not None and role_raw == "CHAIR":
        for m in db["members"].values():
            if (m["committee_id"] == committee["id"] and m["role_in_committee"] == "CHAIR"
                    and m["is_active"]):
                raise_error(ERR_CHAIR_CONFLICT, "committee already has an active CHAIR")
    ss_raw = raw_str(body, "service_start")
    se_raw = raw_str(body, "service_end")
    if ss_raw is not None and se_raw is not None and is_valid_dt(ss_raw) and is_valid_dt(se_raw):
        # Service windows permit equal endpoints (PRD §2.8).
        if parse_dt(ss_raw) > parse_dt(se_raw):
            raise_error(ERR_INVALID_INTERVAL, "service_start must not be after service_end")
    committee_id = req_str(body, "committee_id")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    role_in_committee = req_enum(body, "role_in_committee", ROLES_IN_COMMITTEE) \
        if body.get("role_in_committee") is not None else "MEMBER"
    service_start = req_datetime_str(body, "service_start")
    service_end = req_datetime_str(body, "service_end")
    rec = new_record("members", {
        "committee_id": committee_id,
        "full_name": full_name,
        "email": email,
        "role_in_committee": role_in_committee,
        "service_start": service_start,
        "service_end": service_end,
        "is_active": True,
    })
    return success_object(public(rec), status=201)


@bp.get("/members")
def list_members():
    return list_response("members", {
        "committee_id": request.args.get("committee_id"),
    })


@bp.get("/members/<rid>")
def get_member(rid):
    return get_one("members", rid, ERR_MEMBER_NOT_FOUND)


@bp.post("/members/<rid>/deactivate")
def deactivate_member(rid):
    authorized(["ProvostOfficer"])
    member = require_path("members", rid, ERR_MEMBER_NOT_FOUND)
    member["is_active"] = False
    touch(member)
    return success_object(public(member))
