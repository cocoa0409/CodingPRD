"""TestPressing endpoints: create, ship, review."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_TEST_PRESSING_NOT_FOUND,
    ERR_ORDER_INVALID_STATE, ERR_STAMPERS_NOT_READY,
    ERR_TEST_PRESSING_INVALID_STATE,
)
from middleware import get_auth, require_role, require_customer_ownership
from response import success_object
from services import risk as risk_service
from services.constants import TP_MAX_QUANTITY
from .press_orders import get_order_or_404

bp = Blueprint("test_pressings", __name__)


def get_tp_or_404(tp_id):
    t = db.test_pressings.get(tp_id)
    if not t:
        raise ApiError(ERR_TEST_PRESSING_NOT_FOUND, "Test pressing id does not exist", 404)
    return t


@bp.route("/press-orders/<oid>/test-pressings", methods=["POST"])
def create_test_pressing(oid):
    _, role = get_auth()
    require_role(role, ["PressOperator"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}

    quantity = body.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1 or quantity > TP_MAX_QUANTITY:
        raise ApiError(ERR_INVALID_REQUEST, "quantity must be an integer between 1 and 20", 400)

    # state precondition (priority 5): order must be TOOLING
    if order["production_status"] != "TOOLING":
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be TOOLING to produce a test pressing", 409)

    # linked-entity gate (priority 7): latest ToolingJob must be STAMPER_READY
    jobs = [j for j in db.tooling_jobs.values() if j["press_order_id"] == order["id"]]
    latest = None
    if jobs:
        latest = max(jobs, key=lambda j: (j["round_number"], j["created_at"]))
    if latest is None or latest["status"] != "STAMPER_READY":
        raise ApiError(ERR_STAMPERS_NOT_READY, "Latest tooling job is not STAMPER_READY", 409)

    order["tp_round"] += 1
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()

    # supersede any prior round resting in REVISION_REQUESTED
    for t in db.test_pressings.values():
        if t["press_order_id"] == order["id"] and t["status"] == "REVISION_REQUESTED":
            t["status"] = "SUPERSEDED"
            t["version"] += 1
            t["updated_at"] = db.timestamp_now()

    now = db.timestamp_now()
    tp = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": order["id"],
        "round_number": order["tp_round"],
        "quantity": quantity,
        "status": "PRODUCED",
        "decision_notes": None,
    }
    db.test_pressings[tp["id"]] = tp
    return success_object(serializers.test_pressing(tp), 201)


@bp.route("/test-pressings/<tid>/ship", methods=["POST"])
def ship_test_pressing(tid):
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    tp = get_tp_or_404(tid)
    if tp["status"] != "PRODUCED":
        raise ApiError(ERR_TEST_PRESSING_INVALID_STATE, "ship requires PRODUCED", 409)

    order = db.press_orders[tp["press_order_id"]]
    tp["status"] = "UNDER_REVIEW"
    tp["version"] += 1
    tp["updated_at"] = db.timestamp_now()

    if order["production_status"] == "TOOLING":
        order["production_status"] = "AWAITING_TP_APPROVAL"
        order["version"] += 1
        order["updated_at"] = db.timestamp_now()

    return success_object(serializers.test_pressing(tp))


@bp.route("/test-pressings/<tid>/review", methods=["POST"])
def review_test_pressing(tid):
    user_id, role = get_auth()
    require_role(role, ["Customer"])
    tp = get_tp_or_404(tid)
    order = db.press_orders[tp["press_order_id"]]
    release = db.releases[order["release_id"]]
    require_customer_ownership(user_id, role, release)

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    notes = body.get("notes")
    if decision not in ("APPROVE", "REQUEST_REVISION"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REQUEST_REVISION", 400)
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_INVALID_REQUEST, "notes must be a string", 400)

    if tp["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_TEST_PRESSING_INVALID_STATE, "review requires UNDER_REVIEW", 409)

    if decision == "APPROVE":
        tp["status"] = "APPROVED"
        tp["decision_notes"] = notes
        tp["version"] += 1
        tp["updated_at"] = db.timestamp_now()

        if order["production_status"] == "AWAITING_TP_APPROVAL":
            order["production_status"] = "QUEUED"
            order["version"] += 1
            order["updated_at"] = db.timestamp_now()
        risk_service.recompute_release_risk(release, "SCHEDULE", order["id"])
    else:
        tp["status"] = "REVISION_REQUESTED"
        tp["decision_notes"] = notes
        tp["version"] += 1
        tp["updated_at"] = db.timestamp_now()

        # supersede current tooling job (STAMPER_READY -> SUPERSEDED), open re-cut
        jobs = [j for j in db.tooling_jobs.values() if j["press_order_id"] == order["id"]]
        if jobs:
            latest = max(jobs, key=lambda j: (j["round_number"], j["created_at"]))
            if latest["status"] == "STAMPER_READY":
                latest["status"] = "SUPERSEDED"
                latest["version"] += 1
                latest["updated_at"] = db.timestamp_now()
            new_round = latest["round_number"] + 1
        else:
            new_round = order["tp_round"] + 1

        now = db.timestamp_now()
        new_job = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "press_order_id": order["id"],
            "round_number": new_round,
            "status": "QUEUED",
            "attempt_count": 0,
            "plating_bath_id": None,
            "plating_start": None,
            "plating_end": None,
            "defect_note": None,
        }
        db.tooling_jobs[new_job["id"]] = new_job

        order["_tp_revision_count"] = order.get("_tp_revision_count", 0) + 1
        if order["production_status"] == "AWAITING_TP_APPROVAL":
            order["production_status"] = "TOOLING"
        order["version"] += 1
        order["updated_at"] = db.timestamp_now()

        risk_service.recompute_release_risk(release, "TP_REVISION", order["id"])

    return success_object(serializers.test_pressing(tp))
