"""Member, Waiver, Instructor routes (PRD 3.1, 3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso
from constants import WAIVER_VALID_DAYS
from db import db, iso_ts
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN_ROLE,
)
from helpers import (
    get_json_body,
    require_fields,
    require_enum,
    lookup,
    base_common_fields,
    waiver_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import member_out, waiver_out, instructor_out
from services.derive import recompute_member_waiver, touch

bp = Blueprint("members", __name__)

READ_ROLES_ALL = ["FacilityManager", "FrontDesk", "Member", "Instructor"]


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@bp.post("/v1/members")
def create_member():
    _, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk"])
    body = get_json_body()
    require_fields(body, ["facility_id", "full_name"])
    lookup(db.facilities, body["facility_id"])
    tier = body.get("tier", "NONE")
    require_enum(tier, {"NONE", "BRONZE", "GOLD"}, "tier")

    member = base_common_fields()
    member.update({
        "facility_id": body["facility_id"],
        "full_name": body["full_name"],
        "tier": tier,
        "token_balance": 0,
        "monthly_member_minutes_used": 0,
        "no_show_strikes": 0,
        "waiver_ok": False,
    })
    db.members[member["id"]] = member
    return success(member_out(member), status=201)


@bp.get("/v1/members/<member_id>")
def get_member(member_id):
    user_id, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk", "Member"])
    member = lookup(db.members, member_id)
    # Member acts only on own resources (PRD 2.1).
    if role == "Member" and user_id != member_id:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only read their own record")
    return success(member_out(member), status=200)


@bp.get("/v1/members")
def list_members():
    _, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk"])
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    items = [m for m in db.members.values()
             if facility_id is None or m["facility_id"] == facility_id]
    page, meta = paginate(items, limit, offset)
    return success([member_out(m) for m in page], status=200, pagination=meta)


@bp.post("/v1/members/<member_id>/wallet/top-up")
def top_up(member_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk"])
    member = lookup(db.members, member_id)
    body = get_json_body()
    require_fields(body, ["tokens"])
    tokens = body["tokens"]
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise err(ERR_INVALID_REQUEST, "tokens must be a non-negative integer")
    member["token_balance"] += tokens
    touch(member)
    return success(member_out(member), status=200)


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------
@bp.post("/v1/waivers")
def sign_waiver():
    user_id, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk", "Member"])
    body = get_json_body()
    require_fields(body, ["facility_id", "member_id"])
    lookup(db.facilities, body["facility_id"])
    member = lookup(db.members, body["member_id"])
    # A Member acting on self must pass their own id (PRD 2.1 / 3.2).
    if role == "Member" and user_id != body["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only sign their own waiver")

    signed_at = clock.now()
    expires_at = signed_at + timedelta(days=WAIVER_VALID_DAYS)

    waiver = waiver_common_fields()
    waiver.update({
        "facility_id": body["facility_id"],
        "member_id": body["member_id"],
        "signed_at": iso_ts(signed_at),
        "expires_at": iso_ts(expires_at),
        "status": "SIGNED",
    })
    db.waivers[waiver["id"]] = waiver
    recompute_member_waiver(member)
    return success(waiver_out(waiver), status=201)


@bp.get("/v1/waivers/<waiver_id>")
def get_waiver(waiver_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk", "Member"])
    waiver = lookup(db.waivers, waiver_id)
    return success(waiver_out(waiver), status=200)


@bp.get("/v1/waivers")
def list_waivers():
    _, role = authenticate()
    require_role(role, ["FacilityManager", "FrontDesk", "Member"])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    facility_id = request.args.get("facility_id")
    items = [
        w for w in db.waivers.values()
        if (member_id is None or w["member_id"] == member_id)
        and (facility_id is None or w["facility_id"] == facility_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([waiver_out(w) for w in page], status=200, pagination=meta)


@bp.post("/v1/waivers/<waiver_id>/void")
def void_waiver(waiver_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    waiver = lookup(db.waivers, waiver_id)
    if waiver["status"] != "SIGNED":
        raise err(ERR_INVALID_STATE, "Only a SIGNED waiver may be voided")
    waiver["status"] = "VOID"
    # Waiver is immutable except this explicit status flip; no version/updated_at.
    member = db.members.get(waiver["member_id"])
    if member is not None:
        recompute_member_waiver(member)
    return success(waiver_out(waiver), status=200)


# ---------------------------------------------------------------------------
# Instructors
# ---------------------------------------------------------------------------
@bp.post("/v1/instructors")
def create_instructor():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "full_name", "rate_cents_per_hour"])
    lookup(db.facilities, body["facility_id"])
    rate = body["rate_cents_per_hour"]
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
        raise err(ERR_INVALID_REQUEST, "rate_cents_per_hour must be >= 0")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err(ERR_INVALID_REQUEST, "active must be a boolean")

    instructor = base_common_fields()
    instructor.update({
        "facility_id": body["facility_id"],
        "full_name": body["full_name"],
        "rate_cents_per_hour": rate,
        "active": active,
    })
    db.instructors[instructor["id"]] = instructor
    return success(instructor_out(instructor), status=201)


@bp.get("/v1/instructors/<instructor_id>")
def get_instructor(instructor_id):
    _, role = authenticate()
    require_role(role, READ_ROLES_ALL)
    instructor = lookup(db.instructors, instructor_id)
    return success(instructor_out(instructor), status=200)


@bp.get("/v1/instructors")
def list_instructors():
    _, role = authenticate()
    require_role(role, READ_ROLES_ALL)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    items = [i for i in db.instructors.values()
             if facility_id is None or i["facility_id"] == facility_id]
    page, meta = paginate(items, limit, offset)
    return success([instructor_out(i) for i in page], status=200, pagination=meta)
