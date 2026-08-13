"""ExceptionFinding creation, false-positive closure, and the flat read
surface (PRD §3.6).
"""
from flask import Blueprint, g, request

import db
import errors
import helpers
from errors import ApiError
from middleware import (body, paginate, require_roles, scope_vendor_or_403,
                        vc_vendor_id)
from response import ok, ok_list
from serializers import serialize
from routes.cycles import _filter_exceptions

bp = Blueprint("exceptions", __name__, url_prefix="/vsa")

SOURCES = ("QUESTIONNAIRE", "EVIDENCE", "MONITORING")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@bp.post("/vendors/<vid>/cycles/<cid>/exceptions")
@require_roles("RiskAnalyst")
def create_exception(vid, cid):
    vendor = helpers.get_vendor(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    data = body()
    source = data.get("source")
    severity = data.get("severity")
    description = data.get("description")
    artifact_id = data.get("evidence_artifact_id")
    if source not in SOURCES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "source must be one of %s" % (SOURCES,))
    if severity not in SEVERITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "severity must be one of %s" % (SEVERITIES,))
    if not isinstance(description, str) or not description:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "description is required")
    if source == "EVIDENCE" and not artifact_id:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "evidence_artifact_id is required when source is EVIDENCE")
    if source != "EVIDENCE":
        artifact_id = None
    if artifact_id is not None:
        artifact = db.artifacts.get(artifact_id)
        if artifact is None or artifact["cycle_id"] != cid:
            raise ApiError(errors.ERR_REFERENTIAL_INTEGRITY, 422,
                           "evidence_artifact_id does not belong to this cycle")
    exception = {
        "cycle_id": cid,
        "source": source,
        "evidence_artifact_id": artifact_id,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "closure_reason": None,
    }
    helpers.stamp_new("exceptions", exception)
    db.exceptions[exception["id"]] = exception
    cycle["open_exception_count"] += 1
    helpers.touch("cycles", cycle)
    return ok(serialize("exception", exception), 201)


@bp.post("/vendors/<vid>/cycles/<cid>/exceptions/<eid>/mark-false-positive")
@require_roles("RiskAnalyst")
def mark_false_positive(vid, cid, eid):
    vendor = helpers.get_vendor(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    exception = helpers.get_child(db.exceptions, "cycle_id", cycle, eid,
                                  "ExceptionFinding")
    if exception["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an OPEN exception can be marked false positive")
    data = body()
    closure_reason = data.get("closure_reason")
    if not isinstance(closure_reason, str) or not closure_reason:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "closure_reason must be non-empty")
    exception["status"] = "CLOSED_FALSE_POSITIVE"
    exception["closure_reason"] = closure_reason
    cycle["open_exception_count"] -= 1
    helpers.touch("exceptions", exception)
    helpers.touch("cycles", cycle)
    return ok(serialize("exception", exception))


@bp.get("/exceptions/<eid>")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def get_exception(eid):
    exception = db.exceptions.get(eid)
    if exception is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404,
                       "ExceptionFinding %s not found" % eid)
    if g.role == "VendorContact":
        cycle = db.cycles.get(exception["cycle_id"])
        if cycle is None or vc_vendor_id() != cycle["vendor_id"]:
            raise ApiError(errors.ERR_FORBIDDEN, 403,
                           "VendorContact scope is limited to its own vendor")
    return ok(serialize("exception", exception))


@bp.get("/exceptions")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_exceptions():
    items = list(db.exceptions.values())
    if g.role == "VendorContact":
        scope = vc_vendor_id()
        items = [e for e in items
                 if (db.cycles.get(e["cycle_id"]) or {}).get("vendor_id") == scope]
    items = _filter_exceptions(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("exception", e) for e in page], limit, offset, total)
