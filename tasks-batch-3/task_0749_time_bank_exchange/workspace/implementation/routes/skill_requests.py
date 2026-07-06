"""SkillRequest routes."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE
from response import envelope_object, envelope_array
from services import validators, pagination
from services.serializers import skill_request_dto
from db import parse_iso

bp = Blueprint("skill_requests", __name__)


@bp.route("/skill-requests", methods=["POST"])
def create_request():
    user_id, _ = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, [
        "member_id", "skill_code", "needed_minutes",
        "earliest_start_utc", "latest_start_utc"
    ])
    member_id = validators.require_str(payload, "member_id")
    skill_code = validators.require_str(payload, "skill_code")
    needed = validators.require_minute_multiple(payload, "needed_minutes", 15, 480)
    earliest = validators.require_datetime(payload, "earliest_start_utc")
    latest = validators.require_datetime(payload, "latest_start_utc")
    if parse_iso(latest) <= parse_iso(earliest):
        raise_err(ERR_INVALID_REQUEST, "latest_start_utc must be > earliest_start_utc")

    if db.members.get(member_id) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")
    if member_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal request.member_id")

    r = {
        "member_id": member_id,
        "skill_code": skill_code,
        "needed_minutes": needed,
        "earliest_start_utc": earliest,
        "latest_start_utc": latest,
        "status": "OPEN",
    }
    db.stamp_new(r)
    db.skill_requests[r["id"]] = r
    return envelope_object(skill_request_dto(r), status=201)


@bp.route("/skill-requests", methods=["GET"])
def list_requests():
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.skill_requests.values())
    for k in ("member_id", "skill_code", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([skill_request_dto(x) for x in window], limit, offset, total)


@bp.route("/skill-requests/<rid>", methods=["GET"])
def get_req(rid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    r = db.skill_requests.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Request not found")
    return envelope_object(skill_request_dto(r), status=200)


@bp.route("/skill-requests/<rid>/cancel", methods=["POST"])
def cancel_req(rid):
    user_id, _ = require_role({ROLE_MEMBER})
    r = db.skill_requests.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Request not found")
    if r["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Request.status must be OPEN")
    if r["member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal request.member_id")
    r["status"] = "CANCELLED"
    db.touch(r)
    return envelope_object(skill_request_dto(r), status=200)
