"""Decision endpoints (PRD §3.8)."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import get_body, paginate, path_case, path_decision
from services.workflows import enter_decision

bp = Blueprint("decisions", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/cases/<cid>/decisions")
def create_decision(cid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk", "CourtAdmin"))
    case = path_case(cid)
    # Entry requires the case's argument to stand HELD or WAIVED
    args = [o for o in STORE.oral_arguments.values() if o["case_id"] == case["id"]]
    if not any(o["status"] in ("HELD", "WAIVED") for o in args):
        raise ApiError("ERR_INVALID_STATE",
                       "A decision requires an oral argument in HELD or WAIVED state", 409)
    body = get_body()
    dec = enter_decision(case, body)
    out = dict(dec)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/decisions")
def list_decisions(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [d for d in STORE.decisions.values() if d["case_id"] == case["id"]]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/decisions/<did>")
def get_decision(did):
    auth = get_auth()
    require_roles(auth, ALL)
    d = path_decision(did)
    out = dict(d)
    out.pop("_seq", None)
    return success_object(out)
