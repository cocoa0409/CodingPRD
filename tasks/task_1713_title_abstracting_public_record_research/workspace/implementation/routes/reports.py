"""AbstractReport endpoints: opening the report (OCC-guarded), submit,
buffered review-slot booking, approve, and require-revision."""

from datetime import timedelta

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
    ERR_SLOT_INVALID,
    ERR_SLOT_CONFLICT,
    ERR_REPORT_ALREADY_ACTIVE,
    ERR_STALE_VERSION,
    ERR_OPEN_CURATIVE_REQUIREMENTS,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    ACTIVE_REPORT_STATES,
    report_view,
    reports_of_order,
    order_open_curative_count,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    parse_dt,
)

bp = make_blueprint("reports")

REVIEW_BUFFER_MINUTES = 30

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "title": {"type": "string", "required": True},
    "expected_abstract_order_version": {"type": "integer", "required": True},
}

_START_REVIEW_SPEC = {
    "review_slot_start": {"type": "datetime", "required": True},
    "review_slot_end": {"type": "datetime", "required": True},
}

_REASON_SPEC = {
    "reason": {"type": "string", "required": True},
}


def _get_report_or_404(rid):
    return require_fk("reports", rid, ERR_REPORT_NOT_FOUND, "report")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


@bp.post("/abstract-reports")
def create_report():
    uid, role = authenticate(["Abstracter"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    _require_order_not_terminal(order)
    if order["status"] != "SEARCH_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not SEARCH_COMPLETE")
    for r in reports_of_order(order["id"]):
        if r["status"] in ACTIVE_REPORT_STATES:
            raise ApiError(ERR_REPORT_ALREADY_ACTIVE, 409, "order already has an active report")
    if body["expected_abstract_order_version"] != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_abstract_order_version does not match current version")

    report = db.new_entity("reports", {
        "order_id": order["id"],
        "title": body["title"],
        "revision_number": 0,
        "revision_reason": None,
        "reviewer_examiner_ref": None,
        "review_slot_start": None,
        "review_slot_end": None,
        "status": "DRAFT",
    })
    order["status"] = "REPORT_DRAFTING"
    db.touch(order)
    return success_obj(report_view(report), 201)


@bp.get("/abstract-reports/<rid>")
def get_report(rid):
    authenticate(ALL_ROLES)
    return success_obj(report_view(_get_report_or_404(rid)), 200)


@bp.get("/abstract-reports")
def list_reports():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("reports"), ["order_id", "status", "reviewer_examiner_ref"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([report_view(r) for r in page], limit, offset, total, has_more)


@bp.post("/abstract-reports/<rid>/submit")
def submit_report(rid):
    uid, role = authenticate(["Abstracter"])
    body_json()
    report = _get_report_or_404(rid)
    order = db.get("orders", report["order_id"])
    _require_order_not_terminal(order)
    if order["status"] != "REPORT_DRAFTING":
        raise ApiError(ERR_INVALID_STATE, 409, "parent order is not REPORT_DRAFTING")
    if report["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError(ERR_INVALID_STATE, 409, "report is not in DRAFT or REVISION_REQUIRED")
    report["status"] = "SUBMITTED"
    db.touch(report)
    order["status"] = "REPORT_UNDER_REVIEW"
    db.touch(order)
    return success_obj(report_view(report), 200)


@bp.post("/abstract-reports/<rid>/start-review")
def start_review(rid):
    uid, role = authenticate(["Examiner"])
    body = body_json()
    check_shape(body, _START_REVIEW_SPEC)
    report = _get_report_or_404(rid)
    _require_order_not_terminal(db.get("orders", report["order_id"]))
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "report is not SUBMITTED")

    slot_start = parse_dt(body["review_slot_start"], "review_slot_start")
    slot_end = parse_dt(body["review_slot_end"], "review_slot_end")
    if not slot_end > slot_start:
        raise ApiError(ERR_SLOT_INVALID, 422, "review_slot_end must be later than review_slot_start")

    # Buffered calendar: the gap to every other non-CANCELLED slot booked to
    # this examiner must be >= 30 minutes on both sides; exactly 30 is allowed.
    buffer = timedelta(minutes=REVIEW_BUFFER_MINUTES)
    for other in db.all_of("reports"):
        if other["id"] == report["id"] or other["status"] == "CANCELLED":
            continue
        if other.get("reviewer_examiner_ref") != uid:
            continue
        if not other.get("review_slot_start") or not other.get("review_slot_end"):
            continue
        o_start = parse_dt(other["review_slot_start"], "review_slot_start")
        o_end = parse_dt(other["review_slot_end"], "review_slot_end")
        if not (slot_end + buffer <= o_start or o_end + buffer <= slot_start):
            raise ApiError(ERR_SLOT_CONFLICT, 409, "review slot conflicts with the examiner's buffered calendar")

    report["reviewer_examiner_ref"] = uid
    report["review_slot_start"] = body["review_slot_start"]
    report["review_slot_end"] = body["review_slot_end"]
    report["status"] = "UNDER_REVIEW"
    db.touch(report)
    return success_obj(report_view(report), 200)


@bp.post("/abstract-reports/<rid>/approve")
def approve_report(rid):
    uid, role = authenticate(["Examiner"])
    body_json()
    report = _get_report_or_404(rid)
    if report["reviewer_examiner_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the booked reviewing examiner may approve")
    order = db.get("orders", report["order_id"])
    _require_order_not_terminal(order)
    if report["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "report is not UNDER_REVIEW")
    if order_open_curative_count(order["id"]) > 0:
        raise ApiError(ERR_OPEN_CURATIVE_REQUIREMENTS, 409, "order has OPEN curative requirements")
    report["status"] = "APPROVED"
    db.touch(report)
    order["status"] = "READY_FOR_DELIVERY"
    db.touch(order)
    return success_obj(report_view(report), 200)


@bp.post("/abstract-reports/<rid>/require-revision")
def require_revision(rid):
    uid, role = authenticate(["Examiner"])
    body = body_json()
    check_shape(body, _REASON_SPEC)
    report = _get_report_or_404(rid)
    if report["reviewer_examiner_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the booked reviewing examiner may require revision")
    order = db.get("orders", report["order_id"])
    _require_order_not_terminal(order)
    if report["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "report is not UNDER_REVIEW")
    report["status"] = "REVISION_REQUIRED"
    report["revision_number"] = report.get("revision_number", 0) + 1
    report["revision_reason"] = body["reason"]
    db.touch(report)
    order["status"] = "REPORT_DRAFTING"
    db.touch(order)
    return success_obj(report_view(report), 200)
