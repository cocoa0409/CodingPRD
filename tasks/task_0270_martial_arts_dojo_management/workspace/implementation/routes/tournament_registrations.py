"""Tournament registrations (PRD §3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_WAIVER_NOT_SIGNED, ERR_MEMBER_NOT_ACTIVE, ERR_EVENT_IN_PAST,
    ERR_INVALID_STATE, ERR_UNAUTHORIZED,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, parse_pagination, paginate, sort_by_created,
    parse_iso8601,
)
from services.serialize import view, view_list
from services import domain

bp = Blueprint("tournament_registrations", __name__)


@bp.post("/dojo/tournament-registrations")
def create_registration():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    body = get_json_body()
    require_fields(body, ["member_id", "enrollment_id", "tournament_name", "event_date"])

    # FK existence (priority 4)
    member = db.members.get(body["member_id"])
    if member is None:
        raise err(ERR_FK_NOT_FOUND, "member_id references a non-existent member.")
    enrollment = db.enrollments.get(body["enrollment_id"])
    if enrollment is None:
        raise err(ERR_FK_NOT_FOUND, "enrollment_id references a non-existent enrollment.")

    if role == ROLE_MEMBER and body["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only register themselves.")

    # structural validity (priority 5)
    if not isinstance(body["tournament_name"], str) or not (1 <= len(body["tournament_name"]) <= 120):
        raise err(ERR_INVALID_REQUEST, "tournament_name must be 1..120 chars.")
    event_dt = parse_iso8601(body["event_date"])

    # waiver gate (priority 9)
    if not member["waiver_signed"]:
        raise err(ERR_WAIVER_NOT_SIGNED, "Member waiver not signed.")
    # member-active gate (priority 10)
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE.")
    # event-in-past gate (priority 19)
    if not (event_dt > db.now()):
        raise err(ERR_EVENT_IN_PAST, "event_date must be strictly in the future.")

    division = domain.tournament_division(member["date_of_birth"], body["event_date"])

    now = db.now_iso()
    rid = db.new_id()
    reg = {
        "id": rid,
        "member_id": body["member_id"],
        "enrollment_id": body["enrollment_id"],
        "tournament_name": body["tournament_name"],
        "event_date": body["event_date"],
        "division": division,
        "status": "REGISTERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.tournament_registrations[rid] = reg
    return success(view(reg), 201)


@bp.get("/dojo/tournament-registrations/<rid>")
def get_registration(rid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    reg = db.tournament_registrations.get(rid)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Tournament registration not found.")
    if role == ROLE_MEMBER and reg["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only read their own registrations.")
    return success(view(reg), 200)


@bp.get("/dojo/tournament-registrations")
def list_registrations():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    items = []
    for r in db.tournament_registrations.values():
        if role == ROLE_MEMBER and r["member_id"] != user_id:
            continue
        if member_id is not None and r["member_id"] != member_id:
            continue
        if enrollment_id is not None and r["enrollment_id"] != enrollment_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/tournament-registrations/<rid>/withdraw")
def withdraw_registration(rid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_MEMBER, ROLE_FRONTDESK])
    reg = db.tournament_registrations.get(rid)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Tournament registration not found.")
    if role == ROLE_MEMBER and reg["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only withdraw their own registrations.")
    if reg["status"] != "REGISTERED":
        raise err(ERR_INVALID_STATE, "Registration not in REGISTERED state.")
    reg["status"] = "WITHDRAWN"
    domain.touch(reg)
    return success(view(reg), 200)
