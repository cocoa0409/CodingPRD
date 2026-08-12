"""AogRequest endpoints: file, list, get, source-search, escalate, cancel,
quote sub-collection."""

from flask import Blueprint, request

from auth import require_roles, forbid_unless_owner, ALL_BUSINESS
from calc import TRACE_RANK
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_FORBIDDEN, ERR_CUSTOMER_NOT_FOUND, ERR_PART_NOT_FOUND,
                    ERR_AOG_REQUEST_NOT_FOUND, ERR_NEEDED_BY_IN_PAST,
                    ERR_NO_SOURCE_AVAILABLE)
from helpers import (new_record, touch, get_or_404, bump_unit_status,
                     ser_request, ser_quote, sort_asc)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_enum, as_dt, as_list, fmt_dt, bad)

bp = Blueprint("requests", __name__)

CONDITIONS = {"NEW", "OVERHAULED", "SERVICEABLE", "AS_REMOVED"}
TRACE_LEVELS = set(TRACE_RANK.keys())


@bp.post("/aog/aog-requests")
def create_request():
    uid, role = require_roles("AogDeskAgent", "CustomerContact")
    body = get_body()
    customer_id = as_str(req_present(body, "customer_id"), "customer_id")
    tail = as_str(req_present(body, "aircraft_tail"), "aircraft_tail")
    airport = as_str(req_present(body, "airport_code"), "airport_code")
    part_id = as_str(req_present(body, "part_id"), "part_id")
    quantity = as_int(req_present(body, "quantity"), "quantity")
    if quantity < 1:
        bad("quantity must be >= 1")
    acceptable = as_list(req_present(body, "condition_acceptable"),
                         "condition_acceptable")
    if not acceptable or any(c not in CONDITIONS for c in acceptable):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "condition_acceptable must be a non-empty subset of "
                       "NEW, OVERHAULED, SERVICEABLE, AS_REMOVED")
    min_trace = as_enum(req_present(body, "min_trace_doc"), "min_trace_doc",
                        TRACE_LEVELS)
    needed_raw = req_present(body, "needed_by_utc")
    needed_dt = as_dt(needed_raw, "needed_by_utc")
    # ownership (priority 2) before body FK existence (priority 3)
    forbid_unless_owner(role, uid, customer_id)
    get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND, "Customer")
    get_or_404("parts", part_id, ERR_PART_NOT_FOUND, "PartMaster")
    if needed_dt <= clock.current:
        raise ApiError(ERR_NEEDED_BY_IN_PAST, 422,
                       "needed_by_utc must be strictly after the current "
                       "clock")
    rec = new_record("requests", {
        "customer_id": customer_id,
        "aircraft_tail": tail,
        "airport_code": airport,
        "part_id": part_id,
        "quantity": quantity,
        "condition_acceptable": list(acceptable),
        "min_trace_doc": min_trace,
        "needed_by_utc": needed_raw,
        "escalated": False,
        "status": "OPEN",
        "reserved_unit_id": None,
        "last_search_candidate_count": 0,
        "_needed_by_dt": needed_dt,
    })
    return success(ser_request(rec), 201)


@bp.get("/aog/aog-requests")
def list_requests():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["requests"].values())
    if role == "CustomerContact":
        recs = [r for r in recs if r["customer_id"] == uid]
    q = request.args
    if q.get("customer_id") is not None:
        recs = [r for r in recs if r["customer_id"] == q.get("customer_id")]
    if q.get("status") is not None:
        recs = [r for r in recs if r["status"] == q.get("status")]
    if q.get("part_id") is not None:
        recs = [r for r in recs if r["part_id"] == q.get("part_id")]
    if q.get("reserved_unit_id") is not None:
        recs = [r for r in recs
                if r["reserved_unit_id"] == q.get("reserved_unit_id")]
    return paged([ser_request(r) for r in sort_asc(recs)], limit, offset)


@bp.get("/aog/aog-requests/<rid>")
def get_request(rid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("requests", rid, ERR_AOG_REQUEST_NOT_FOUND, "AogRequest")
    return success(ser_request(rec))


def _release_pin(req):
    """Release the request's pinned unit (RESERVED -> AVAILABLE)."""
    uid_ = req.get("reserved_unit_id")
    if uid_:
        unit = store["units"].get(uid_)
        if unit is not None and unit["status"] == "RESERVED":
            bump_unit_status(unit, "AVAILABLE")
            unit["reserved_by_request_id"] = None
        req["reserved_unit_id"] = None


@bp.post("/aog/aog-requests/<rid>/source-search")
def source_search(rid):
    require_roles("AogDeskAgent")
    req = get_or_404("requests", rid, ERR_AOG_REQUEST_NOT_FOUND, "AogRequest")
    if req["status"] not in ("OPEN", "QUOTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Request status does not permit a sourcing search")
    # release any prior pin first
    changed = False
    if req.get("reserved_unit_id"):
        _release_pin(req)
        changed = True
    pool = [u for u in store["units"].values()
            if u["part_id"] == req["part_id"]
            and u["status"] == "AVAILABLE"
            and u["condition"] in req["condition_acceptable"]
            and TRACE_RANK[u["trace_doc_level"]] >= TRACE_RANK[req["min_trace_doc"]]]
    pool.sort(key=lambda u: (u["created_at"], u["_seq"]))
    if not pool:
        if req["last_search_candidate_count"] != 0 or changed:
            req["last_search_candidate_count"] = 0
            touch(req)
        raise ApiError(ERR_NO_SOURCE_AVAILABLE, 422,
                       "No eligible source unit available")
    winner = pool[0]
    bump_unit_status(winner, "RESERVED")
    winner["reserved_by_request_id"] = req["id"]
    req["reserved_unit_id"] = winner["id"]
    req["last_search_candidate_count"] = len(pool)
    touch(req)
    return success(ser_request(req))


@bp.post("/aog/aog-requests/<rid>/escalate")
def escalate_request(rid):
    require_roles("AogDeskAgent")
    req = get_or_404("requests", rid, ERR_AOG_REQUEST_NOT_FOUND, "AogRequest")
    if req["status"] in ("CANCELLED", "CLOSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Terminal request cannot be escalated")
    req["escalated"] = True
    touch(req)
    return success(ser_request(req))


@bp.post("/aog/aog-requests/<rid>/cancel")
def cancel_request(rid):
    uid, role = require_roles("AogDeskAgent", "CustomerContact")
    req = get_or_404("requests", rid, ERR_AOG_REQUEST_NOT_FOUND, "AogRequest")
    if role == "CustomerContact":
        forbid_unless_owner(role, uid, req["customer_id"])
    if req["status"] not in ("OPEN", "QUOTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only OPEN or QUOTED requests can be cancelled")
    if req["status"] == "QUOTED" and role != "AogDeskAgent":
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Only a desk agent may cancel a QUOTED request")
    # cascade: every non-terminal quote -> CANCELLED
    for q in store["quotes"].values():
        if q["aog_request_id"] == req["id"] and \
                q["status"] in ("DRAFT", "ISSUED"):
            q["status"] = "CANCELLED"
            touch(q)
    _release_pin(req)
    req["status"] = "CANCELLED"
    touch(req)
    return success(ser_request(req))


@bp.get("/aog/aog-requests/<rid>/quotes")
def list_request_quotes(rid):
    uid, role = require_roles(*ALL_BUSINESS)
    get_or_404("requests", rid, ERR_AOG_REQUEST_NOT_FOUND, "AogRequest")
    limit, offset = page_params()
    recs = [q for q in store["quotes"].values() if q["aog_request_id"] == rid]
    if role == "CustomerContact":
        recs = [q for q in recs if q["customer_id"] == uid]
    return paged([ser_quote(q) for q in sort_asc(recs)], limit, offset)
