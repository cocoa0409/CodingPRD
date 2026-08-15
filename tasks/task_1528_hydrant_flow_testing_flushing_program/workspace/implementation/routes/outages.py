"""HydrantOutage endpoints: create (three-hop cascade), list, get,
acknowledge-notification, close."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_HYDRANT_NOT_FOUND,
    ERR_HYDRANT_NOT_IN_SERVICE,
    ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED,
    ERR_NOTIFICATION_NOT_ACKNOWLEDGED,
    ERR_OPEN_WORK_ORDERS_EXIST,
    ERR_OUTAGE_NOT_ACTIVE,
    ERR_OUTAGE_NOT_FOUND,
    ERR_PROGRAM_NOT_OPEN,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import outage_view
from services import (
    ACK_DEADLINE_HOURS,
    cancel_scheduled_flow_tests_for_outage,
    open_work_orders_exist,
)
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("outages", __name__)


def get_outage_or_404(outage_id):
    o = db.store.outages.get(outage_id)
    if o is None:
        raise not_found(ERR_OUTAGE_NOT_FOUND, "HydrantOutage")
    return o


@bp.post("/outages")
def create_outage():
    user_id, role = auth()
    body = validate_body([
        F("hydrant_id", "str"),
        F("reason", "enum", arg={"VALVE_FAILURE", "LEAK", "DAMAGE", "OTHER"}),
        F("expected_return_date", "datetime", required=False, nullable=True),
    ])
    require_role(role, {"FieldOperator"})
    hydrant = db.store.hydrants.get(body["hydrant_id"])
    if hydrant is None:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    if hydrant["status"] != "IN_SERVICE":
        raise ApiError(ERR_HYDRANT_NOT_IN_SERVICE, "Hydrant must be IN_SERVICE", 409)
    program = db.store.programs[hydrant["program_id"]]
    if program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, "The hydrant's program must be OPEN", 409)
    now = db.now()
    outage = new_base()
    outage.update({
        "hydrant_id": hydrant["id"],
        "reason": body["reason"],
        "expected_return_date": body["expected_return_date"],
        "status": "ACTIVE",
        "notification_status": "PENDING",
        "notified_at": now,
        "ack_deadline": now + timedelta(hours=ACK_DEADLINE_HOURS),
        "acknowledged_at": None,
        "acknowledged_by_user_id": None,
        "escalated": False,
        "closed_at": None,
    })
    db.store.outages[outage["id"]] = outage
    # CASCADE hop 1: hydrant leaves IN_SERVICE
    hydrant["status"] = "OUT_OF_SERVICE"
    hydrant["active_outage_id"] = outage["id"]
    touch(hydrant)
    # CASCADE hop 2: program counters
    program["hydrants_out_of_service_count"] += 1
    program["unacknowledged_notification_count"] += 1
    touch(program)
    # CASCADE hop 3: SCHEDULED flow tests of this hydrant -> CANCELLED
    cancel_scheduled_flow_tests_for_outage(hydrant["id"])
    return success_object(outage_view(outage), code=201)


@bp.get("/outages")
def list_outages():
    auth_any()
    items = list(db.store.outages.values())
    hydrant_id = request.args.get("hydrant_id")
    if hydrant_id is not None:
        items = [o for o in items if o["hydrant_id"] == hydrant_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return success_list([outage_view(o) for o in page], meta)


@bp.get("/outages/<outage_id>")
def get_outage(outage_id):
    auth_any()
    return success_object(outage_view(get_outage_or_404(outage_id)))


@bp.post("/outages/<outage_id>/acknowledge-notification")
def acknowledge_notification(outage_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FireDeptLiaison"})
    outage = get_outage_or_404(outage_id)
    if outage["notification_status"] != "PENDING":
        raise ApiError(
            ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED,
            "Notification has already been acknowledged",
            409,
        )
    outage["notification_status"] = "ACKNOWLEDGED"
    outage["acknowledged_at"] = db.now()
    outage["acknowledged_by_user_id"] = user_id
    touch(outage)
    hydrant = db.store.hydrants[outage["hydrant_id"]]
    program = db.store.programs[hydrant["program_id"]]
    program["unacknowledged_notification_count"] -= 1
    touch(program)
    return success_object(outage_view(outage))


@bp.post("/outages/<outage_id>/close")
def close_outage(outage_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    outage = get_outage_or_404(outage_id)
    if outage["status"] != "ACTIVE":
        raise ApiError(ERR_OUTAGE_NOT_ACTIVE, "Outage must be ACTIVE to close", 409)
    if outage["notification_status"] != "ACKNOWLEDGED":
        raise ApiError(
            ERR_NOTIFICATION_NOT_ACKNOWLEDGED,
            "Notification must be ACKNOWLEDGED before closing the outage",
            409,
        )
    if open_work_orders_exist(outage["hydrant_id"]):
        raise ApiError(
            ERR_OPEN_WORK_ORDERS_EXIST,
            "Work orders in DRAFT, SUBMITTED, or APPROVED exist for this hydrant",
            409,
        )
    outage["status"] = "CLOSED"
    outage["closed_at"] = db.now()
    touch(outage)
    hydrant = db.store.hydrants[outage["hydrant_id"]]
    hydrant["status"] = "IN_SERVICE"
    hydrant["active_outage_id"] = None
    touch(hydrant)
    program = db.store.programs[hydrant["program_id"]]
    program["hydrants_out_of_service_count"] -= 1
    touch(program)
    return success_object(outage_view(outage))
