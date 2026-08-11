"""Further-review petition endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import STORE, now_iso, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_enum, new_entity, paginate, touch,
    path_case, path_petition, path_decision, fk_decision, court_for_case,
)
from services.workflows import (
    petition_due_at, grant_petition, deny_petition, create_filing,
    reconcile_case,
)

bp = Blueprint("petitions", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
PETITION_TYPES = ("REHEARING", "REHEARING_EN_BANC", "CERTIORARI")
TERMINAL_PETITION = ("GRANTED", "DENIED", "WITHDRAWN")


@bp.post("/appellate/cases/<cid>/petitions")
def create_petition(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    case = path_case(cid)
    body = get_body()
    ptype = req_enum(body, "petition_type", PETITION_TYPES)
    decision = fk_decision(body.get("basis_decision_id"))
    if decision["case_id"] != case["id"]:
        raise ApiError("ERR_FK_NOT_FOUND",
                       "basis_decision_id does not belong to this case", 404)
    # Admission check (priority 7)
    acting = STORE.attorneys.get(auth.user_id)
    if acting is None:
        raise ApiError("ERR_NOT_ADMITTED", "Acting attorney record not found", 403)
    if case["court_id"] not in (acting.get("admitted_court_ids") or []):
        raise ApiError("ERR_NOT_ADMITTED",
                       "Attorney not admitted to the case's court", 403)
    court = court_for_case(case)
    p = new_entity({
        "case_id": case["id"],
        "petition_type": ptype,
        "basis_decision_id": decision["id"],
        "due_at": petition_due_at(ptype, decision, court),
        "filed_at": None,
        "status": "DRAFT",
    })
    STORE.petitions[p["id"]] = p
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/petitions")
def list_case_petitions(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [p for p in STORE.petitions.values() if p["case_id"] == case["id"]]
    items = _filter(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/petitions/<pid>")
def get_petition(pid):
    auth = get_auth()
    require_roles(auth, ALL)
    p = path_petition(pid)
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/petitions")
def list_petitions():
    auth = get_auth()
    require_roles(auth, ALL)
    items = _filter(list(STORE.petitions.values()))
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/decisions/<did>/petitions")
def list_decision_petitions(did):
    auth = get_auth()
    require_roles(auth, ALL)
    decision = path_decision(did)
    items = [p for p in STORE.petitions.values()
             if p["basis_decision_id"] == decision["id"]]
    items = _filter(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


def _filter(items):
    pt = request.args.get("petition_type")
    if pt is not None:
        items = [p for p in items if p["petition_type"] == pt]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    bd = request.args.get("basis_decision_id")
    if bd is not None:
        items = [p for p in items if p["basis_decision_id"] == bd]
    return items


@bp.post("/appellate/petitions/<pid>/file")
def file_petition(pid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    p = path_petition(pid)
    if p["status"] in TERMINAL_PETITION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Petition is in a terminal state", 409)
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Petition must be DRAFT to file", 409)
    case = STORE.cases.get(p["case_id"])
    if case is not None:
        reconcile_case(case)
    # Priority 8: deadline currency — before the decision-issued check (17)
    if p.get("due_at") and parse_iso(now_iso()) > parse_iso(p["due_at"]):
        raise ApiError("ERR_DEADLINE_PASSED", "Petition due date has passed", 409)
    # Priority 17: decision issued
    if not case or case.get("posture") != "DECIDED":
        raise ApiError("ERR_DECISION_NOT_ISSUED",
                       "Cannot file petition before a decision issues", 409)
    p["status"] = "FILED"
    p["filed_at"] = now_iso()
    touch(p)
    ftype = "CERT_PETITION" if p["petition_type"] == "CERTIORARI" else "REHEARING_PETITION"
    create_filing(case, ftype, "EFILE", [], brief_id=None)
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/petitions/<pid>/grant")
def grant_petition_route(pid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    p = path_petition(pid)
    if p["status"] in TERMINAL_PETITION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Petition is in a terminal state", 409)
    if p["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Petition must be FILED to grant", 409)
    grant_petition(p)
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/petitions/<pid>/deny")
def deny_petition_route(pid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    p = path_petition(pid)
    if p["status"] in TERMINAL_PETITION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Petition is in a terminal state", 409)
    if p["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Petition must be FILED to deny", 409)
    deny_petition(p)
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/petitions/<pid>/withdraw")
def withdraw_petition(pid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    p = path_petition(pid)
    if p["status"] in TERMINAL_PETITION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Petition is in a terminal state", 409)
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Petition must be DRAFT to withdraw", 409)
    p["status"] = "WITHDRAWN"
    touch(p)
    out = dict(p)
    out.pop("_seq", None)
    return success_object(out)
