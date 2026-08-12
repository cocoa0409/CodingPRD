"""Filing endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_enum, req_str_list, opt_str, paginate,
    path_case, path_filing, path_brief,
)
from services.workflows import (
    create_filing, accept_filing, reject_filing, FILING_TYPES, FILING_METHODS,
)

bp = Blueprint("filings", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
TERMINAL_FILING = ("ACCEPTED", "REJECTED")


@bp.post("/appellate/cases/<cid>/filings")
def create_filing_route(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "ParalegalStaff"))
    case = path_case(cid)
    body = get_body()
    ftype = req_enum(body, "filing_type", FILING_TYPES)
    method = req_enum(body, "method", FILING_METHODS)
    served = req_str_list(body, "served_party_emails")
    brief_id = body.get("brief_id")
    if brief_id is not None:
        if not isinstance(brief_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "brief_id must be a string", 400)
        brief = STORE.briefs.get(brief_id)
        if brief is None:
            raise ApiError("ERR_FK_NOT_FOUND", "brief_id not found", 404)
    # Service completeness (priority 16): EFILE brief must serve at least one party
    if ftype == "BRIEF" and method == "EFILE" and len(served) == 0:
        raise ApiError("ERR_SERVICE_INCOMPLETE",
                       "E-filed brief must serve at least one party email", 422)
    if ftype == "NOTICE_OF_APPEAL" and len(served) == 0:
        raise ApiError("ERR_SERVICE_INCOMPLETE",
                       "Notice of appeal must serve all adverse parties", 422)
    filing = create_filing(case, ftype, method, served,
                           brief_id=brief_id if ftype == "BRIEF" else None)
    out = dict(filing)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/filings")
def list_case_filings(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [f for f in STORE.filings.values() if f["case_id"] == case["id"]]
    items = _filter(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/filings/<fid>")
def get_filing(fid):
    auth = get_auth()
    require_roles(auth, ALL)
    f = path_filing(fid)
    out = dict(f)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/filings")
def list_filings():
    auth = get_auth()
    require_roles(auth, ALL)
    items = list(STORE.filings.values())
    items = _filter(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/briefs/<bid>/filings")
def list_brief_filings(bid):
    auth = get_auth()
    require_roles(auth, ALL)
    brief = path_brief(bid)
    items = [f for f in STORE.filings.values() if f.get("brief_id") == brief["id"]]
    items = _filter(items)
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


def _filter(items):
    ft = request.args.get("filing_type")
    if ft is not None:
        items = [f for f in items if f["filing_type"] == ft]
    st = request.args.get("status")
    if st is not None:
        items = [f for f in items if f["status"] == st]
    bid = request.args.get("brief_id")
    if bid is not None:
        items = [f for f in items if f.get("brief_id") == bid]
    return items


@bp.post("/appellate/filings/<fid>/accept")
def accept_filing_route(fid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    f = path_filing(fid)
    if f["status"] in TERMINAL_FILING:
        raise ApiError("ERR_ALREADY_TERMINAL", "Filing already decided", 409)
    # Priority 5: state
    if f["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Filing must be SUBMITTED to accept", 409)
    # Priority 9: brief over-limit (for brief filings)
    if f["filing_type"] == "BRIEF" and f.get("brief_id"):
        brief = STORE.briefs.get(f["brief_id"])
        if brief and brief.get("over_limit"):
            raise ApiError("ERR_BRIEF_OVER_LIMIT",
                           "Brief exceeds the court's length limit", 422)
    # EFILE acceptance requires non-empty served list
    if f["method"] == "EFILE" and not (f.get("served_party_emails") or []):
        raise ApiError("ERR_SERVICE_INCOMPLETE",
                       "Electronic filing cannot be accepted with empty service list", 422)
    accept_filing(f)
    out = dict(f)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/filings/<fid>/reject")
def reject_filing_route(fid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    f = path_filing(fid)
    if f["status"] in TERMINAL_FILING:
        raise ApiError("ERR_ALREADY_TERMINAL", "Filing already decided", 409)
    if f["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Filing must be SUBMITTED to reject", 409)
    body = get_body()
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError("ERR_INVALID_REQUEST", "reason is required", 400)
    reject_filing(f)
    out = dict(f)
    out.pop("_seq", None)
    return success_object(out)
