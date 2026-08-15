"""Complainant registry endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_complainant, ser_complaint, ser_outreach_case
from services import touch
from util import now
from validate import validate, parse_pagination

bp = Blueprint("complainants", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]


def _get_complainant(cid):
    c = db.complainants.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Complainant {cid} not found")
    return c


@bp.post("/complainants")
def create_complainant():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("full_name", "str", True),
        ("email", "str", True),
        ("phone", "str", False),
        ("address_line", "str", True),
        ("zone_code", "str", True),
        ("outreach_opt_in", "bool", False),
    ])
    require_role(caller, ["CommunityLiaison", "NoiseOfficeAdmin"])
    t = now()
    c = {
        "id": new_id(),
        "full_name": data["full_name"],
        "email": data["email"],
        "phone": data.get("phone"),
        "address_line": data["address_line"],
        "zone_code": data["zone_code"],
        "outreach_opt_in": data.get("outreach_opt_in", True),
        "standing": "GOOD_STANDING",
        "complaints_90d": 0,
        "filed_total": 0,
        "open_count": 0,
        "closed_count": 0,
        "withdrawn_count": 0,
        "substantiated_count": 0,
        "repeat_baseline_at": None,
        "low_priority_flag": False,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.complainants[c["id"]] = c
    return success_object(ser_complainant(c), status=201)


@bp.get("/complainants")
def list_complainants():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    standing = request.args.get("standing")
    zone = request.args.get("zone_code")
    items = sorted(db.complainants.values(), key=lambda c: c["created_at"])
    if standing is not None:
        items = [c for c in items if c["standing"] == standing]
    if zone is not None:
        items = [c for c in items if c["zone_code"] == zone]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_complainant(c) for c in page], limit, offset, total)


@bp.get("/complainants/<complainantId>")
def get_complainant(complainantId):
    caller = get_caller()
    require_role(caller, STAFF + ["Complainant"])
    c = _get_complainant(complainantId)
    if caller.role == "Complainant" and c["id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "A Complainant may read only their own record")
    return success_object(ser_complainant(c))


@bp.patch("/complainants/<complainantId>")
def update_complainant(complainantId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("full_name", "str", False),
        ("email", "str", False),
        ("phone", "str", False),
        ("address_line", "str", False),
        ("zone_code", "str", False),
        ("outreach_opt_in", "bool", False),
    ])
    require_role(caller, ["CommunityLiaison", "NoiseOfficeAdmin"])
    c = _get_complainant(complainantId)
    for field in ("full_name", "email", "phone", "address_line", "zone_code",
                  "outreach_opt_in"):
        if field in data:
            c[field] = data[field]
    touch(c)
    return success_object(ser_complainant(c))


@bp.get("/complainants/<complainantId>/noise-complaints")
def list_complainant_complaints(complainantId):
    caller = get_caller()
    require_role(caller, STAFF + ["Complainant"])
    c = _get_complainant(complainantId)
    if caller.role == "Complainant" and c["id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "A Complainant may read only their own complaints")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted((x for x in db.complaints.values()
                    if x["complainant_id"] == c["id"]),
                   key=lambda x: x["created_at"])
    if status is not None:
        items = [x for x in items if x["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_complaint(x) for x in page], limit, offset, total)


@bp.get("/complainants/<complainantId>/outreach-cases")
def list_complainant_outreach(complainantId):
    caller = get_caller()
    require_role(caller, ["CommunityLiaison", "NoiseOfficeAdmin"])
    c = _get_complainant(complainantId)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted((x for x in db.outreach_cases.values()
                    if x["complainant_id"] == c["id"]),
                   key=lambda x: x["created_at"])
    if status is not None:
        items = [x for x in items if x["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_outreach_case(x) for x in page], limit, offset, total)
