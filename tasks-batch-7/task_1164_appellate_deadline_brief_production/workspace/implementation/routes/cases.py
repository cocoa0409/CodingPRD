"""Case endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import STORE
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import get_body, paginate, path_case
from services.workflows import open_case, reconcile_case

bp = Blueprint("cases", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/cases")
def create_case():
    auth = get_auth()
    require_roles(auth, ("Attorney", "CourtAdmin"))
    body = get_body()
    case = open_case(body)
    out = dict(case)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>")
def get_case(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    reconcile_case(case)
    out = dict(case)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/cases")
def list_cases():
    auth = get_auth()
    require_roles(auth, ALL)
    # Lazy clock-driven evaluation per PRD §2.5/§3.4/§3.8
    for case in list(STORE.cases.values()):
        reconcile_case(case)
    items = list(STORE.cases.values())
    court_id = request.args.get("court_id")
    if court_id is not None:
        items = [c for c in items if c["court_id"] == court_id]
    lead = request.args.get("lead_attorney_id")
    if lead is not None:
        items = [c for c in items if c["lead_attorney_id"] == lead]
    posture = request.args.get("posture")
    if posture is not None:
        items = [c for c in items if c["posture"] == posture]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)
