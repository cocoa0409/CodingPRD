"""InspectionReport endpoints (PRD §3.5) + ReportPhoto.

One report per order. Submit computes condition_score & outcome.
"""
from flask import Blueprint, g, request

from db import db, stamp_create, touch
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     serialize, sort_by_created)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.lookups import (get_assignment, get_order, get_photo, get_report)

bp = Blueprint("reports", __name__)


def serialize_report(r):
    return serialize(r)


def serialize_photo(p):
    return serialize(p)


def _critical_count(report_id):
    return sum(1 for p in db.photos.values()
               if p["report_id"] == report_id and p.get("is_critical"))


def _recompute(report):
    """Recompute condition_score & outcome from current report values."""
    score, outcome = calc.condition_score_and_outcome(
        report["points_total"],
        report["points_failed"],
        report["road_test_done"],
        _critical_count(report["id"]),
    )
    report["condition_score"] = score
    report["outcome"] = outcome
    return outcome


@bp.route("/inspection-reports", methods=["POST"])
@require_roles("Inspector")
def create_report():
    body = get_json_body()
    require_fields(body, ["order_id", "assignment_id", "odometer_reading",
                          "points_total", "points_failed"])
    order = get_order(body["order_id"])
    assignment = get_assignment(body["assignment_id"])

    # ownership (priority 4): inspector owns the assignment authoring this report
    if assignment["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this assignment")

    # body well-formedness (priority 5)
    odometer = body["odometer_reading"]
    points_total = body["points_total"]
    points_failed = body["points_failed"]
    for name, val in (("odometer_reading", odometer), ("points_total", points_total),
                      ("points_failed", points_failed)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if points_total < 0 or points_failed < 0 or points_failed > points_total:
        raise err("ERR_INVALID_REQUEST", "points_failed must be between 0 and points_total")
    road_test = body.get("road_test_done", False)
    if road_test is None:
        road_test = False
    if not isinstance(road_test, bool):
        raise err("ERR_INVALID_REQUEST", "road_test_done must be a boolean")

    # business referential: an ACCEPTED assignment must exist for the order
    has_accepted = any(
        a["order_id"] == order["id"] and a["status"] == "ACCEPTED"
        for a in db.assignments.values()
    )
    if not has_accepted:
        raise err("ERR_NO_ACCEPTED_ASSIGNMENT", "No accepted assignment for this order")

    # state (priority 7): order must be DISPATCHED to start a report
    if order["workflow_status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Order is not in DISPATCHED state")

    report = {
        "order_id": order["id"],
        "assignment_id": assignment["id"],
        "odometer_reading": odometer,
        "points_total": points_total,
        "points_failed": points_failed,
        "road_test_done": road_test,
        "condition_score": None,
        "outcome": None,
        "status": "DRAFT",
    }
    stamp_create(report)
    db.reports[report["id"]] = report

    # cascade: order DISPATCHED -> IN_PROGRESS
    order["workflow_status"] = "IN_PROGRESS"
    touch(order)
    return success(serialize_report(report), status=201)


@bp.route("/inspection-reports/<report_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder", "Inspector")
def get_report_ep(report_id):
    r = get_report(report_id)
    return success(serialize_report(r), status=200)


@bp.route("/inspection-reports", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder", "Inspector")
def list_reports():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    assignment_id = request.args.get("assignment_id")
    items = list(db.reports.values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if assignment_id is not None:
        items = [r for r in items if r["assignment_id"] == assignment_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_report(r) for r in page], status=200, pagination=meta)


@bp.route("/inspection-reports/<report_id>/photos", methods=["POST"])
@require_roles("Inspector")
def add_photo(report_id):
    report = get_report(report_id)
    # ownership: inspector owns the authoring assignment
    assignment = db.assignments.get(report["assignment_id"])
    if assignment is None or assignment["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this report")
    # photos may be attached only while DRAFT or AMENDED
    if report["status"] not in ("DRAFT", "AMENDED"):
        raise err("ERR_INVALID_STATE", "Photos may only be added to a DRAFT/AMENDED report")

    body = get_json_body()
    require_fields(body, ["caption", "url"])
    is_critical = body.get("is_critical", False)
    if is_critical is None:
        is_critical = False
    if not isinstance(is_critical, bool):
        raise err("ERR_INVALID_REQUEST", "is_critical must be a boolean")

    photo = {
        "report_id": report["id"],
        "caption": body["caption"],
        "is_critical": is_critical,
        "url": body["url"],
    }
    stamp_create(photo, full=False)
    db.photos[photo["id"]] = photo
    return success(serialize_photo(photo), status=201)


@bp.route("/report-photos/<photo_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder", "Inspector")
def get_photo_ep(photo_id):
    p = get_photo(photo_id)
    return success(serialize_photo(p), status=200)


@bp.route("/report-photos", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder", "Inspector")
def list_photos():
    limit, offset = parse_pagination()
    report_id = request.args.get("report_id")
    items = list(db.photos.values())
    if report_id is not None:
        items = [p for p in items if p["report_id"] == report_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_photo(p) for p in page], status=200, pagination=meta)


@bp.route("/inspection-reports/<report_id>/submit", methods=["POST"])
@require_roles("Inspector")
def submit_report(report_id):
    report = get_report(report_id)
    assignment = db.assignments.get(report["assignment_id"])
    if assignment is None or assignment["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this report")
    # state (priority 7): submit from DRAFT or AMENDED
    if report["status"] not in ("DRAFT", "AMENDED"):
        raise err("ERR_INVALID_STATE", "Report is not in a submittable state")
    # empty report (business)
    if report["points_total"] < 1:
        raise err("ERR_EMPTY_REPORT", "Report has no checkpoints")

    # compute outcome to check critical-photo gate
    outcome = _recompute(report)
    if outcome == "FAIL" and _critical_count(report["id"]) < 1:
        raise err("ERR_CRITICAL_PHOTO_REQUIRED", "FAIL report requires a critical photo")

    report["status"] = "SUBMITTED"
    touch(report)
    # cascade: order IN_PROGRESS -> REPORTED
    order = db.orders[report["order_id"]]
    if order["workflow_status"] == "IN_PROGRESS":
        order["workflow_status"] = "REPORTED"
        touch(order)
    return success(serialize_report(report), status=200)


@bp.route("/inspection-reports/<report_id>/amend", methods=["POST"])
@require_roles("Inspector")
def amend_report(report_id):
    report = get_report(report_id)
    assignment = db.assignments.get(report["assignment_id"])
    if assignment is None or assignment["inspector_id"] != g.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this report")

    order = db.orders[report["order_id"]]
    # cannot amend after delivery (except via dispute)
    if order["workflow_status"] == "DELIVERED":
        raise err("ERR_REPORT_LOCKED", "Report cannot be amended after delivery")
    # state (priority 7): amend from SUBMITTED
    if report["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Report is not in SUBMITTED state")

    body = get_json_body()
    # apply optional revisions with validation
    new_total = body.get("points_total", report["points_total"])
    new_failed = body.get("points_failed", report["points_failed"])
    new_odo = body.get("odometer_reading", report["odometer_reading"])
    new_road = body.get("road_test_done", report["road_test_done"])
    for name, val in (("points_total", new_total), ("points_failed", new_failed),
                      ("odometer_reading", new_odo)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if not isinstance(new_road, bool):
        raise err("ERR_INVALID_REQUEST", "road_test_done must be a boolean")
    if new_total < 0 or new_failed < 0 or new_failed > new_total:
        raise err("ERR_INVALID_REQUEST", "points_failed must be between 0 and points_total")

    report["points_total"] = new_total
    report["points_failed"] = new_failed
    report["odometer_reading"] = new_odo
    report["road_test_done"] = new_road
    report["status"] = "AMENDED"
    # recompute score/outcome from amended values
    _recompute(report)
    touch(report)
    # cascade: order REPORTED -> IN_PROGRESS
    if order["workflow_status"] == "REPORTED":
        order["workflow_status"] = "IN_PROGRESS"
        touch(order)
    return success(serialize_report(report), status=200)
