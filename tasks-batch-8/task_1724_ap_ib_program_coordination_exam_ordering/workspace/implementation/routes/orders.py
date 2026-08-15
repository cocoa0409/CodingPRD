"""ExamOrder endpoints (PRD 3.4): DRAFT -> SUBMITTED -> LOCKED -> RECONCILED.

The DRAFT order is a living document: lines and estimate_total_cents are computed
live at read time. Submission freezes both, stamps submitted_at/submitted_late.
PATCH of adjustments is the API's single OCC-guarded write (PRD 2.7).
"""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BUDGET_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NEGATIVE_QUANTITY,
    ERR_ORDER_ALREADY_EXISTS,
    ERR_STALE_VERSION,
    ERR_TEACHER_NOT_AUTHORIZED,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services import derived
from services.core import new_record, touch
from services.serialize import serialize_order
from util import CLOCK
from validate import (
    get_body, reject_unknown_fields, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("exam_orders", __name__)

READ_ROLES = ["ApCoordinator", "Registrar"]
WRITE_ROLES = ["ApCoordinator"]
RESOLVED_STATUSES = ("SAT", "NO_SHOW", "CANCELLED")


@bp.post("/exam-orders")
def create_order():
    require_roles(get_caller(), WRITE_ROLES)
    body = get_body()
    reject_unknown_fields(body, {"cycle_id"})
    cycle_id = req_str(body, "cycle_id")
    cycle = require_ref("exam_cycles", cycle_id, "cycle_id")
    if cycle["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "exam orders require the cycle to be OPEN")
    for o in db["exam_orders"].values():
        if o["cycle_id"] == cycle["id"]:
            raise_error(ERR_ORDER_ALREADY_EXISTS,
                        "an ExamOrder already exists for this cycle")
    rec = new_record("exam_orders", {
        "cycle_id": cycle["id"],
        "status": "DRAFT",
        "adjustments": [],
        "lines": None,               # computed live while DRAFT
        "estimate_total_cents": None,  # computed live while DRAFT
        "final_total_cents": None,
        "submitted_late": None,
        "submitted_at": None,
        "locked_at": None,
        "reconciled_at": None,
    })
    return success_object(serialize_order(rec), status=201)


@bp.get("/exam-orders")
def list_orders():
    require_roles(get_caller(), READ_ROLES)
    filters = [
        ("cycle_id", request.args.get("cycle_id")),
        ("status", request.args.get("status")),
    ]
    return list_response(db["exam_orders"].values(), filters, serialize_order)


@bp.get("/exam-orders/<rid>")
def get_order(rid):
    require_roles(get_caller(), READ_ROLES)
    order = require_path_resource("exam_orders", rid)
    return success_object(serialize_order(order))


@bp.patch("/exam-orders/<rid>")
def patch_order(rid):
    require_roles(get_caller(), WRITE_ROLES)
    order = require_path_resource("exam_orders", rid)
    body = get_body()
    reject_unknown_fields(body, {"expected_exam_order_version", "adjustments"})
    expected = req_int(body, "expected_exam_order_version")
    adjustments = body.get("adjustments")
    if adjustments is not None:
        if not isinstance(adjustments, list):
            raise_error(ERR_INVALID_REQUEST, "adjustments must be an array")
        seen = set()
        for item in adjustments:
            if not isinstance(item, dict):
                raise_error(ERR_INVALID_REQUEST, "each adjustment must be an object")
            for key in item:
                if key not in ("course_id", "delta"):
                    raise_error(ERR_INVALID_REQUEST,
                                f"unexpected field in adjustment: {key}")
            cid = item.get("course_id")
            if cid is None or not isinstance(cid, str):
                raise_error(ERR_INVALID_REQUEST,
                            "adjustment requires course_id (string)")
            if cid in seen:
                raise_error(ERR_INVALID_REQUEST,
                            "duplicate adjustment for course_id: " + cid)
            seen.add(cid)
            delta = item.get("delta")
            if delta is None or isinstance(delta, bool) or not isinstance(delta, int):
                raise_error(ERR_INVALID_REQUEST, "adjustment requires delta (integer)")
        # Priority 5: every referenced course must resolve and belong to the cycle.
        for item in adjustments:
            course = db["courses"].get(item["course_id"])
            if course is None:
                from errors import ERR_REFERENCE_NOT_FOUND
                raise_error(ERR_REFERENCE_NOT_FOUND,
                            f"adjustment course_id does not resolve: {item['course_id']}")
            if course["cycle_id"] != order["cycle_id"]:
                raise_error(ERR_INVALID_REQUEST,
                            "adjustment course_id belongs to a different cycle")
    # OCC (PRD 2.7): the one version-guarded write in the API.
    if expected != order["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_exam_order_version does not match the order's current version")
    # Priority 6 state gate: adjustments editable only while DRAFT.
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"order in {order['status']} may not be edited")
    # Priority 9 quota: no course's ordered_count may be driven below zero.
    if adjustments is not None:
        for item in adjustments:
            base = derived.course_registered_count(item["course_id"])
            if base + item["delta"] < 0:
                raise_error(ERR_NEGATIVE_QUANTITY,
                            "adjustment would drive ordered_count below 0")
        order["adjustments"] = [
            {"course_id": item["course_id"], "delta": item["delta"]}
            for item in adjustments
        ]
    touch(order)
    return success_object(serialize_order(order))


@bp.post("/exam-orders/<rid>/submit")
def submit_order(rid):
    require_roles(get_caller(), WRITE_ROLES)
    body = get_body()
    reject_unknown_fields(body, set())
    order = require_path_resource("exam_orders", rid)
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"order in {order['status']} cannot be submitted")
    cycle = db["exam_cycles"][order["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "order submission requires the cycle to be OPEN")
    now = CLOCK.now()
    estimate, lines = derived.compute_estimate(order, now)
    # Priority 10 fiscal gate.
    if estimate > cycle["budget_cap_cents"]:
        raise_error(ERR_BUDGET_EXCEEDED,
                    "estimate_total_cents exceeds the cycle budget cap")
    # Freeze the snapshot at this instant.
    order["lines"] = lines
    order["estimate_total_cents"] = estimate
    order["submitted_at"] = now
    order["submitted_late"] = now > cycle["order_deadline_at"]  # strict; AT is on time
    order["status"] = "SUBMITTED"
    touch(order)
    return success_object(serialize_order(order))


@bp.post("/exam-orders/<rid>/lock")
def lock_order(rid):
    require_roles(get_caller(), WRITE_ROLES)
    body = get_body()
    reject_unknown_fields(body, set())
    order = require_path_resource("exam_orders", rid)
    if order["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"order in {order['status']} cannot be locked")
    for line in order["lines"] or []:
        if line["ordered_count"] > 0 and derived.authorized_teacher_count(line["course_id"]) < 1:
            raise_error(ERR_TEACHER_NOT_AUTHORIZED,
                        f"course {line['course_id']} has no AUTHORIZED teacher")
    order["status"] = "LOCKED"
    order["locked_at"] = CLOCK.now()
    touch(order)
    return success_object(serialize_order(order))


@bp.post("/exam-orders/<rid>/reconcile")
def reconcile_order(rid):
    require_roles(get_caller(), WRITE_ROLES)
    body = get_body()
    reject_unknown_fields(body, set())
    order = require_path_resource("exam_orders", rid)
    if order["status"] != "LOCKED":
        raise_error(ERR_INVALID_STATE,
                    f"order in {order['status']} cannot be reconciled")
    for r in db["registrations"].values():
        if r["cycle_id"] == order["cycle_id"] and r["registration_status"] not in RESOLVED_STATUSES:
            raise_error(ERR_INVALID_STATE,
                        "every registration in the cycle must be resolved "
                        "(SAT, NO_SHOW, or CANCELLED) before reconcile")
    order["final_total_cents"] = derived.compute_final_total(order)
    order["status"] = "RECONCILED"
    order["reconciled_at"] = CLOCK.now()
    touch(order)
    return success_object(serialize_order(order))
