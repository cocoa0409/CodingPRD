"""Exemption request endpoints: file, list, get, start-review, decide, appeal."""
from datetime import timedelta

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import json_object, parse_body, require_path_entity, require_min_length

bp = Blueprint("exemptions", __name__)

_OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPEALED")


@bp.post("/v1/buildings/<building_id>/exemption-requests")
def create_exemption_request(building_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    building = require_path_entity(store.buildings, building_id)
    if building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    body = json_object()
    cycle = None
    if isinstance(body.get("cycle_id"), str):
        cycle = store.cycles.get(body["cycle_id"])
        if cycle is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Referenced cycle does not exist")
    if cycle is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cycle_id is required")
    from validation import validate_schema
    validate_schema(body, {
        "cycle_id": ("string", True, None),
        "request_type": ("string", True, ["EXEMPTION", "EXTENSION"]),
        "reason": ("string", True, None),
        "requested_extension_days": ("integer", False, None),
    })
    require_min_length(body, "reason", 10)
    if body["request_type"] == "EXTENSION":
        days = body.get("requested_extension_days")
        if days is None or not (1 <= days <= 90):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "requested_extension_days is required for EXTENSION and must be in 1..90")
    # Safety gate (tier 9): EXEMPTION blocked once a report is filed for the cycle.
    if body["request_type"] == "EXEMPTION":
        report = core.report_for(building["id"], cycle["id"])
        if report is not None and report["status"] in ("SUBMITTED", "VERIFIED", "CERTIFIED"):
            raise ApiError("ERR_REPORT_ALREADY_FILED", 409,
                           "A report in SUBMITTED, VERIFIED, or CERTIFIED exists for this cycle")
    # Constraint gate (tier 10): at most one open request per building+cycle.
    for er in store.exemption_requests.values():
        if (er["building_id"] == building["id"] and er["cycle_id"] == cycle["id"]
                and er["status"] in _OPEN_STATUSES):
            raise ApiError("ERR_EXEMPTION_REQUEST_OPEN", 409,
                           "An open exemption request already exists for this building and cycle")
    request = db.new_common({
        "id": db.new_id(),
        "building_id": building["id"],
        "cycle_id": cycle["id"],
        "request_type": body["request_type"],
        "reason": body["reason"],
        "requested_extension_days": body.get("requested_extension_days"),
        "status": "SUBMITTED",
        "appeal_used": False,
        "decision_note": None,
        "extended_deadline_at": None,
    })
    store.exemption_requests[request["id"]] = request
    return created(request)


@bp.get("/v1/exemption-requests")
def list_exemption_requests():
    get_context()
    rows = list(store.exemption_requests.values())
    rows = paginate.filter(rows, "building_id")
    rows = paginate.filter(rows, "cycle_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/exemption-requests/<request_id>")
def get_exemption_request(request_id):
    get_context()
    req = require_path_entity(store.exemption_requests, request_id)
    return ok(req)


@bp.post("/v1/exemption-requests/<request_id>/start-review")
def start_review(request_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    req = require_path_entity(store.exemption_requests, request_id)
    if req["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SUBMITTED or APPEALED request can enter review")
    req["status"] = "UNDER_REVIEW"
    db.touch(req)
    return ok(req)


@bp.post("/v1/exemption-requests/<request_id>/decide")
def decide(request_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    req = require_path_entity(store.exemption_requests, request_id)
    body = parse_body({
        "decision": ("string", True, ["APPROVED", "DENIED"]),
        "decision_note": ("string", True, None),
    }, allow_empty=False)
    if req["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an UNDER_REVIEW request can be decided")
    if body["decision"] == "APPROVED" and req["request_type"] == "EXTENSION":
        for er in store.exemption_requests.values():
            if (er["id"] != req["id"] and er["building_id"] == req["building_id"]
                    and er["cycle_id"] == req["cycle_id"]
                    and er["request_type"] == "EXTENSION" and er["status"] == "APPROVED"):
                raise ApiError("ERR_EXTENSION_ALREADY_GRANTED", 409,
                               "An APPROVED EXTENSION already exists for this building and cycle")
    req["decision_note"] = body["decision_note"]
    if body["decision"] == "DENIED":
        req["status"] = "DENIED_FINAL" if req["appeal_used"] else "DENIED"
        db.touch(req)
        return ok(req)
    # APPROVED
    req["status"] = "APPROVED"
    if req["request_type"] == "EXTENSION":
        cycle = store.cycles.get(req["cycle_id"])
        req["extended_deadline_at"] = (cycle["filing_deadline_at"]
                                       + timedelta(days=req["requested_extension_days"]))
        # Waiver cascade: every ASSESSED|NOTICED LATE_SUBMISSION fine for the pair.
        for f in store.fines.values():
            if (f["building_id"] == req["building_id"] and f["cycle_id"] == req["cycle_id"]
                    and f["fine_type"] == "LATE_SUBMISSION"
                    and f["status"] in ("ASSESSED", "NOTICED")):
                f["status"] = "WAIVED"
                f["waive_reason"] = "AUTO_EXTENSION_APPROVED"
                db.touch(f)
        building = store.buildings.get(req["building_id"])
        if building is not None:
            core.recompute_owner_exposure(building["owner_id"])
    db.touch(req)
    return ok(req)


@bp.post("/v1/exemption-requests/<request_id>/appeal")
def appeal(request_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    req = require_path_entity(store.exemption_requests, request_id)
    building = store.buildings.get(req["building_id"])
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    body = parse_body({"appeal_note": ("string", True, None)}, allow_empty=False)
    require_min_length(body, "appeal_note", 10)
    if req["status"] != "DENIED" or req["appeal_used"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DENIED request with its appeal unused can be appealed")
    req["status"] = "APPEALED"
    req["appeal_used"] = True
    db.touch(req)
    return ok(req)
