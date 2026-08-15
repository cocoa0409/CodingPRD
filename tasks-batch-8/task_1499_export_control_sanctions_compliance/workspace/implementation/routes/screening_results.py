"""Screening result queries and match resolution."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_STATE
from middleware import auth, get_body, no_unknown, need, v_enum, find, page_params, filtered_sorted
from response import ok, list_response
from services.screening import recompute_posture
from services.cascade import cascade_party_hold
from services.audit import write_audit

bp = Blueprint("screening_results", __name__)


@bp.get("/compliance/screening-results/<rid>")
def get_screening_result(rid):
    auth()
    result = find(db.SCREENING_RESULTS, rid, "ScreeningResult")
    return ok(db.pub(result), "object", 200)


@bp.get("/compliance/screening-results")
def list_screening_results():
    auth()
    filters = {
        "party_id": request.args.get("party_id"),
        "matched_entry_id": request.args.get("matched_entry_id"),
        "status": request.args.get("status"),
        "trigger_context": request.args.get("trigger_context"),
    }
    items = filtered_sorted(db.SCREENING_RESULTS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/screening-results/<rid>/resolve")
def resolve_screening_result(rid):
    uid, role = auth("ComplianceManager")
    result = find(db.SCREENING_RESULTS, rid, "ScreeningResult")
    body = get_body()
    no_unknown(body, {"resolution"})
    resolution = v_enum(need(body, "resolution"), "resolution", ("FALSE_POSITIVE", "CONFIRMED_MATCH"))
    if result["status"] != "POTENTIAL_MATCH":
        raise ApiError(ERR_INVALID_STATE, "ScreeningResult is not POTENTIAL_MATCH", 409)
    result["status"] = resolution
    result["resolved_by_user_id"] = uid
    db.touch(result)
    party = find(db.PARTIES, result["party_id"], "Party")
    recompute_posture(party)
    if resolution == "CONFIRMED_MATCH":
        # Party flips to BLOCKED; hold every CLEARED|LICENSED order and their
        # PLANNED|SCREENED shipments in the same instant.
        cascade_party_hold(party)
        write_audit(
            "SCREENING_CONFIRMED_MATCH",
            "ScreeningResult",
            result["id"],
            role,
            uid,
            "ScreeningResult %s confirmed as match for party %s" % (result["id"], party["id"]),
        )
    return ok(db.pub(result), "object", 200)
