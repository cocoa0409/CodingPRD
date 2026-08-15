"""Repeat-complainant outreach cases (PRD §3.6)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_outreach_case
from services import touch, refresh_complainant
from util import now
from validate import validate, parse_pagination

bp = Blueprint("outreach", __name__)

ALLOWED = ["CommunityLiaison", "NoiseOfficeAdmin"]
TRIGGERS = ["REPEAT_THRESHOLD", "RESTRICTED_THRESHOLD", "MANUAL"]


def _get_case(cid):
    c = db.outreach_cases.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", f"OutreachCase {cid} not found")
    return c


@bp.post("/outreach-cases")
def create_case():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("complainant_id", "str", True),
        ("trigger_reason", "enum", True, {"enum": TRIGGERS}),
    ])
    require_role(caller, ["CommunityLiaison"])
    complainant = db.complainants.get(data["complainant_id"])
    if complainant is None:
        raise err("ERR_COMPLAINANT_NOT_FOUND",
                  f"Complainant {data['complainant_id']} not found")
    if complainant["standing"] not in ("REPEAT", "RESTRICTED"):
        raise err("ERR_STANDING_NOT_ELEVATED",
                  "Manual outreach requires standing REPEAT or RESTRICTED")
    t = now()
    c = {
        "id": new_id(),
        "complainant_id": complainant["id"],
        "trigger_reason": data["trigger_reason"],
        "status": "OPEN",
        "contact_attempts": 0,
        "opened_at": t,
        "resolved_at": None,
        "resolution_summary": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.outreach_cases[c["id"]] = c
    return success_object(ser_outreach_case(c), status=201)


@bp.get("/outreach-cases")
def list_cases():
    caller = get_caller()
    require_role(caller, ALLOWED)
    limit, offset = parse_pagination(request.args)
    f_complainant = request.args.get("complainant_id")
    f_status = request.args.get("status")
    items = sorted(db.outreach_cases.values(), key=lambda c: c["created_at"])
    if f_complainant is not None:
        items = [c for c in items if c["complainant_id"] == f_complainant]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_outreach_case(c) for c in page], limit, offset, total)


@bp.get("/outreach-cases/<caseId>")
def get_case(caseId):
    caller = get_caller()
    require_role(caller, ALLOWED)
    c = _get_case(caseId)
    return success_object(ser_outreach_case(c))


@bp.post("/outreach-cases/<caseId>/log-contact")
def log_contact(caseId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("outcome", "enum", True, {"enum": ["NO_ANSWER", "REACHED"]}),
    ])
    require_role(caller, ["CommunityLiaison"])
    c = _get_case(caseId)
    outcome = data["outcome"]
    if outcome == "NO_ANSWER":
        if c["status"] == "OPEN":
            c["status"] = "CONTACT_ATTEMPTED"
        elif c["status"] != "CONTACT_ATTEMPTED":
            raise err("ERR_INVALID_OUTREACH_STATE",
                      "NO_ANSWER requires status OPEN or CONTACT_ATTEMPTED")
    else:  # REACHED
        if c["status"] not in ("OPEN", "CONTACT_ATTEMPTED"):
            raise err("ERR_INVALID_OUTREACH_STATE",
                      "REACHED requires status OPEN or CONTACT_ATTEMPTED")
        c["status"] = "ENGAGED"
    c["contact_attempts"] += 1
    touch(c)
    return success_object(ser_outreach_case(c))


@bp.post("/outreach-cases/<caseId>/resolve")
def resolve_case(caseId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("resolution_summary", "str", True)])
    require_role(caller, ["CommunityLiaison"])
    c = _get_case(caseId)
    if c["status"] != "ENGAGED":
        raise err("ERR_INVALID_OUTREACH_STATE", "resolve requires status ENGAGED")
    t = now()
    c["status"] = "RESOLVED"
    c["resolved_at"] = t
    c["resolution_summary"] = data["resolution_summary"]
    touch(c)
    # decisive side effect: reset the complainant's repeat baseline, recompute
    complainant = db.complainants.get(c["complainant_id"])
    if complainant is not None:
        complainant["repeat_baseline_at"] = t
        refresh_complainant(complainant)
    return success_object(ser_outreach_case(c))


@bp.post("/outreach-cases/<caseId>/mark-dormant")
def mark_dormant(caseId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    c = _get_case(caseId)
    if c["status"] != "ENGAGED":
        raise err("ERR_INVALID_OUTREACH_STATE",
                  "mark-dormant requires status ENGAGED")
    c["status"] = "DORMANT"
    touch(c)
    return success_object(ser_outreach_case(c))


@bp.post("/outreach-cases/<caseId>/reactivate")
def reactivate(caseId):
    caller = get_caller()
    get_body()
    require_role(caller, ["CommunityLiaison"])
    c = _get_case(caseId)
    if c["status"] != "DORMANT":
        raise err("ERR_INVALID_OUTREACH_STATE",
                  "reactivate requires status DORMANT")
    c["status"] = "OPEN"
    touch(c)
    return success_object(ser_outreach_case(c))
