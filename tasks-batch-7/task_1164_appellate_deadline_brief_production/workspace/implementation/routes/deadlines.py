"""Deadline endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import STORE
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import paginate, path_case, path_deadline, path_event

bp = Blueprint("deadlines", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


def _apply_filters(items):
    kind = request.args.get("kind")
    if kind is not None:
        items = [d for d in items if d["kind"] == kind]
    met = request.args.get("met")
    if met is not None:
        if met.lower() in ("true", "1"):
            mv = True
        elif met.lower() in ("false", "0"):
            mv = False
        else:
            mv = None
        if mv is not None:
            items = [d for d in items if d["met"] == mv]
    basis = request.args.get("basis_event_id")
    if basis is not None:
        items = [d for d in items if d.get("basis_event_id") == basis]
    return items


@bp.get("/appellate/cases/<cid>/deadlines")
def list_case_deadlines(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [d for d in STORE.deadlines.values() if d["case_id"] == case["id"]]
    items = _apply_filters(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/deadlines/<did>")
def get_deadline(did):
    auth = get_auth()
    require_roles(auth, ALL)
    d = path_deadline(did)
    out = dict(d)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/deadlines")
def list_deadlines():
    auth = get_auth()
    require_roles(auth, ALL)
    items = list(STORE.deadlines.values())
    items = _apply_filters(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/events/<eid>/deadlines")
def list_event_deadlines(eid):
    auth = get_auth()
    require_roles(auth, ALL)
    ev = path_event(eid)
    items = [d for d in STORE.deadlines.values() if d.get("basis_event_id") == ev["id"]]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)
