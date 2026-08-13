"""Producer endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object, success_list
from routes.common import (
    apply_pagination,
    get_json_body,
    lookup_or_404,
    parse_pagination,
    require_str,
)
from services import churn
from services.serializers import producer_view, activity_event_view

bp = Blueprint("producers", __name__)

ALL_ROLES = (
    "CarrierAdmin", "Producer", "SuitabilityReviewer",
    "Principal", "ComplianceOfficer", "OperationsDesk",
)


@bp.route("/producers", methods=["POST"])
def create_producer():
    require_roles("CarrierAdmin")
    body = get_json_body()
    license_number = require_str(body, "license_number")
    full_name = require_str(body, "full_name")
    home_state_code = require_str(body, "home_state_code")

    # license_number unique across all producers
    for p in db.producers.values():
        if p["license_number"] == license_number:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "license_number already registered",
                400,
            )

    now = db.now_formatted()
    producer = {
        "id": db.new_id(),
        "license_number": license_number,
        "full_name": full_name,
        "home_state_code": home_state_code,
        "status": "ACTIVE",
        "submitted_case_count_12m": 0,
        "completed_exchange_count_12m": 0,
        "rescinded_exchange_count_12m": 0,
        "rescission_rate_completed_bps": 0,
        "rescission_rate_submitted_bps": 0,
        "last_churn_eval_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.producers[producer["id"]] = producer
    return success_object(producer_view(producer), 201)


@bp.route("/producers/<pid>", methods=["GET"])
def get_producer(pid):
    require_roles(*ALL_ROLES)
    p = lookup_or_404(db.producers, pid, "Producer")
    return success_object(producer_view(p), 200)


@bp.route("/producers/<pid>/suspend", methods=["POST"])
def suspend_producer(pid):
    require_roles("ComplianceOfficer")
    p = lookup_or_404(db.producers, pid, "Producer")
    if p["status"] not in ("ACTIVE", "FLAGGED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Producer must be ACTIVE or FLAGGED to suspend",
            409,
        )
    now = db.now_formatted()
    p["status"] = "SUSPENDED"
    p["version"] += 1
    p["updated_at"] = now
    churn.append_event(p["id"], None, "PRODUCER_SUSPENDED")
    return success_object(producer_view(p), 200)


@bp.route("/producers/<pid>/reinstate", methods=["POST"])
def reinstate_producer(pid):
    require_roles("ComplianceOfficer")
    p = lookup_or_404(db.producers, pid, "Producer")
    if p["status"] != "SUSPENDED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Producer must be SUSPENDED to reinstate",
            409,
        )
    now = db.now_formatted()
    p["status"] = "ACTIVE"
    p["version"] += 1
    p["updated_at"] = now
    churn.append_event(p["id"], None, "PRODUCER_REINSTATED")
    # Mandatory churn re-evaluation: may land on FLAGGED if thresholds still met
    churn.evaluate_producer(p)
    return success_object(producer_view(p), 200)


@bp.route("/producers/<pid>/activity-events", methods=["GET"])
def list_producer_activity_events(pid):
    require_roles(*ALL_ROLES)
    p = lookup_or_404(db.producers, pid, "Producer")
    limit, offset = parse_pagination()
    event_type = request.args.get("event_type")
    items = [e for e in db.activity_events if e["producer_id"] == p["id"]]
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    page, total = apply_pagination(items, limit, offset)
    return success_list([activity_event_view(e) for e in page], limit, offset, total, 200)
