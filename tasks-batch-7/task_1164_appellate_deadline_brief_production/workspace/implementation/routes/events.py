"""Appeal event endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import STORE
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import get_body, paginate, path_case, path_event
from services.workflows import log_event

bp = Blueprint("events", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/cases/<cid>/events")
def create_event(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "CourtClerk", "CourtAdmin"))
    case = path_case(cid)
    body = get_body()
    ev = log_event(case, body)
    out = dict(ev)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/events")
def list_events(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [e for e in STORE.events.values() if e["case_id"] == case["id"]]
    etype = request.args.get("event_type")
    if etype is not None:
        items = [e for e in items if e["event_type"] == etype]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/events/<eid>")
def get_event(eid):
    auth = get_auth()
    require_roles(auth, ALL)
    ev = path_event(eid)
    out = dict(ev)
    out.pop("_seq", None)
    return success_object(out)
