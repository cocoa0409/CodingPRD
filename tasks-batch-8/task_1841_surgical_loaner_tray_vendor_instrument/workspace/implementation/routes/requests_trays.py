"""LoanerRequest + LoanerTray routes."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, req_int, opt_bool, req_enum
from response import success_object, success_list, parse_pagination
from services import core
from services.core import LEAD_HOURS, PREP_BUFFER_MINUTES

bp = Blueprint("requests_trays", __name__)

PRIORITY_CLASSES = {"STANDARD", "URGENT", "EMERGENT"}


def _get_request_or_404(request_id):
    r = db.requests.get(request_id)
    if r is None:
        raise_err("ERR_REQUEST_NOT_FOUND", "Loaner request not found")
    return r


def _get_tray_or_404(tray_id):
    t = db.trays.get(tray_id)
    if t is None:
        raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")
    return t


# ---------------------------------------------------------------------------
# Loaner requests
# ---------------------------------------------------------------------------

@bp.post("/requests")
def create_request():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["ORScheduler"])

    case_id = req_str(body, "case_id")
    vendor_id = req_str(body, "vendor_id")
    priority_class = req_enum(body, "priority_class", PRIORITY_CLASSES)

    # Body FK existence in declared input order: case_id then vendor_id.
    if case_id not in db.cases:
        raise_err("ERR_CASE_NOT_FOUND", "Case not found")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err("ERR_VENDOR_NOT_FOUND", "Vendor not found")

    if vendor["status"] != "ACTIVE":
        raise_err("ERR_VENDOR_NOT_ACTIVE", "Vendor is not ACTIVE")

    request = {
        "case_id": case_id,
        "vendor_id": vendor_id,
        "priority_class": priority_class,
        "status": "DRAFT",
        "readiness": "NOT_READY",
        "required_delivery_by": None,
        "penalty_exposure_cents": 0,
        "submitted_at": None,
    }
    core.stamp_new(request)
    db.requests[request["id"]] = request
    return success_object(core.serialize(request), status=201)


@bp.get("/requests")
def list_requests():
    get_auth()
    case_id = flask_request.args.get("case_id")
    vendor_id = flask_request.args.get("vendor_id")
    status = flask_request.args.get("status")
    readiness = flask_request.args.get("readiness")
    items = sorted(db.requests.values(), key=lambda r: r["_seq"])
    if case_id:
        items = [r for r in items if r["case_id"] == case_id]
    if vendor_id:
        items = [r for r in items if r["vendor_id"] == vendor_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if readiness:
        items = [r for r in items if r["readiness"] == readiness]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(r) for r in page], limit, offset, total)


@bp.get("/requests/<id>")
def get_request(id):
    get_auth()
    request = _get_request_or_404(id)
    return success_object(core.serialize(request))


@bp.post("/requests/<id>/trays")
def add_tray(id):
    _, role = get_auth()
    body = get_body(required=True)

    tray_code = req_str(body, "tray_code")
    declared_instrument_count = req_int(body, "declared_instrument_count", min_value=1)
    implant_flag = opt_bool(body, "implant_flag", default=False)
    replacement_value_cents = req_int(body, "replacement_value_cents", min_value=1)

    require_role(role, ["ORScheduler"])
    request = _get_request_or_404(id)

    if request["status"] != "DRAFT":
        raise_err("ERR_REQUEST_INVALID_STATE", "Trays can only be added while the request is DRAFT")

    for t in db.trays.values():
        if t["request_id"] == id and t["tray_code"] == tray_code:
            raise_err("ERR_DUPLICATE_TRAY_CODE", "tray_code already used within the request")

    tray = {
        "request_id": id,
        "tray_code": tray_code,
        "declared_instrument_count": declared_instrument_count,
        "implant_flag": implant_flag,
        "replacement_value_cents": replacement_value_cents,
        "status": "EXPECTED",
        "delivered_instrument_count": None,
        "returned_instrument_count": None,
        "shortage_count": 0,
        "rework_count": 0,
        "required_sterile_ready_by": None,
        "projected_sterile_ready_at": None,
    }
    core.stamp_new(tray)
    db.trays[tray["id"]] = tray
    core.recompute_readiness(request)
    return success_object(core.serialize(tray), status=201)


@bp.get("/requests/<id>/trays")
def list_request_trays(id):
    get_auth()
    _get_request_or_404(id)
    items = core.trays_of_request(id)
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(t) for t in page], limit, offset, total)


@bp.post("/requests/<id>/submit")
def submit_request(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORScheduler"])
    request = _get_request_or_404(id)

    if request["status"] != "DRAFT":
        raise_err("ERR_REQUEST_INVALID_STATE", "Only a DRAFT request can be submitted")

    trays = core.trays_of_request(id)
    if not trays:
        raise_err("ERR_REQUEST_NO_TRAYS", "Request has no trays")

    case = db.cases.get(request["case_id"])
    lead_hours = LEAD_HOURS[request["priority_class"]]
    start = db.parse_dt(case["scheduled_start_at"])
    if (start - db.now_dt()) < timedelta(hours=lead_hours):
        raise_err("ERR_REQUEST_DEADLINE_INFEASIBLE", "Submission deadline is not feasible")

    request["submitted_at"] = db.fmt_ts(db.now_dt())
    request["status"] = "SUBMITTED"
    core.touch(request)
    return success_object(core.serialize(request))


@bp.post("/requests/<id>/decide")
def decide_request(id):
    _, role = get_auth()
    body = get_body(required=True)

    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})

    require_role(role, ["VendorCoordinator"])
    request = _get_request_or_404(id)

    if request["status"] != "SUBMITTED":
        raise_err("ERR_REQUEST_INVALID_STATE", "Only a SUBMITTED request can be decided")

    if decision == "APPROVE":
        vendor = db.vendors.get(request["vendor_id"])
        if vendor is None or vendor["status"] != "ACTIVE":
            raise_err("ERR_VENDOR_NOT_ACTIVE", "Vendor is not ACTIVE")
        case = db.cases.get(request["case_id"])
        start = db.parse_dt(case["scheduled_start_at"])
        lead = LEAD_HOURS[request["priority_class"]]
        request["required_delivery_by"] = db.fmt_ts(start - timedelta(hours=lead))
        for tray in core.trays_of_request(id):
            tray["required_sterile_ready_by"] = db.fmt_ts(start - timedelta(minutes=PREP_BUFFER_MINUTES))
            tray["projected_sterile_ready_at"] = None
            core.touch(tray)
        request["status"] = "APPROVED"
        core.recompute_readiness(request)
    else:
        request["status"] = "REJECTED"

    core.touch(request)
    return success_object(core.serialize(request))


@bp.post("/requests/<id>/cancel")
def cancel_request(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORScheduler"])
    request = _get_request_or_404(id)

    if request["status"] not in {"DRAFT", "SUBMITTED", "APPROVED"}:
        raise_err("ERR_REQUEST_INVALID_STATE", "Request cannot be cancelled from its current state")

    core.cancel_request_cascade(request)
    return success_object(core.serialize(request))


# ---------------------------------------------------------------------------
# Trays
# ---------------------------------------------------------------------------

@bp.get("/trays")
def list_trays():
    get_auth()
    request_id = flask_request.args.get("request_id")
    status = flask_request.args.get("status")
    items = sorted(db.trays.values(), key=lambda t: t["_seq"])
    if request_id:
        items = [t for t in items if t["request_id"] == request_id]
    if status:
        items = [t for t in items if t["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(t) for t in page], limit, offset, total)


@bp.get("/trays/<id>")
def get_tray(id):
    get_auth()
    tray = _get_tray_or_404(id)
    return success_object(core.serialize(tray))


@bp.post("/trays/<id>/mark-missing")
def mark_missing(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["VendorCoordinator"])
    tray = _get_tray_or_404(id)

    if tray["status"] != "EXPECTED":
        raise_err("ERR_TRAY_INVALID_STATE", "Only an EXPECTED tray can be marked missing")

    tray["status"] = "MISSING"
    core.recompute_tray_projection(tray)
    core.touch(tray)
    core.create_escalation(tray["request_id"], "MISSING_TRAY", linked_tray_id=tray["id"])
    request = db.requests.get(tray["request_id"])
    if request is not None:
        core.recompute_readiness(request)
    return success_object(core.serialize(tray))


@bp.post("/trays/<id>/stage")
def stage_tray(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORCirculatorNurse"])
    tray = _get_tray_or_404(id)

    if tray["status"] != "STERILE_READY":
        raise_err("ERR_TRAY_INVALID_STATE", "Only a STERILE_READY tray can be staged")

    request = db.requests.get(tray["request_id"])
    case = db.cases.get(request["case_id"]) if request else None
    if case is None or case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "The request's case must be SCHEDULED to stage trays")

    tray["status"] = "STAGED"
    core.recompute_tray_projection(tray)
    core.touch(tray)
    if request is not None:
        core.recompute_readiness(request)
    return success_object(core.serialize(tray))
