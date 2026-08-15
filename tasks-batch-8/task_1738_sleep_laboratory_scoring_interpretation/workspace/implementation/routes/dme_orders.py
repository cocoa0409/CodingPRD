"""DME order dispatch, delivery, and adherence follow-up (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_RX_INVALID_STATE,
    ERR_DME_ORDER_ACTIVE,
    ERR_DME_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import DME_TERMINAL, adherence_compliant
from services.core import new_record, touch
from util import CLOCK
from validate import get_body, req_str, req_enum, req_num, require_path_resource, require_body_ref

bp = Blueprint("dme_orders", __name__)

RESOLUTION_ACTIONS = {"CONTINUE_THERAPY", "ESCALATE_TO_PHYSICIAN"}


@bp.post("/dme-orders")
def create_dme_order():
    authorized(["DmeCoordinator"])
    body = get_body()
    # Priority 3: body FK existence.
    rx = require_body_ref("therapy_prescriptions", body.get("prescription_id"))
    # Priority 4: shape.
    prescription_id = req_str(body, "prescription_id")
    vendor_name = req_str(body, "vendor_name")
    # Priority 7: prescription must be ORDERED.
    if rx["status"] != "ORDERED":
        raise_error(ERR_RX_INVALID_STATE,
                    f"DME dispatch requires an ORDERED prescription, found {rx['status']}")
    # Priority 11: one non-terminal DME order per prescription.
    for existing in db["dme_orders"].values():
        if (existing["prescription_id"] == prescription_id
                and existing["status"] not in DME_TERMINAL):
            raise_error(ERR_DME_ORDER_ACTIVE,
                        "a non-terminal DmeOrder already exists for the prescription")
    rec = new_record("dme_orders", {
        "prescription_id": prescription_id,
        "vendor_name": vendor_name,
        "dispatched_at": CLOCK.now_iso(),
        "delivered_at": None,
        "follow_up_usage_hours_avg": None,
        "follow_up_compliant_nights_percent": None,
        "adherence_compliant": None,
        "resolution_action": None,
        "status": "DISPATCHED",
    })
    return success_object(public(rec), status=201)


@bp.get("/dme-orders")
def list_dme_orders():
    return list_response("dme_orders", query_filters("prescription_id", "status"))


@bp.get("/dme-orders/<dmeOrderId>")
def get_dme_order(dmeOrderId):
    return get_one("dme_orders", dmeOrderId)


def _require_dispatched(dme):
    if dme["status"] != "DISPATCHED":
        raise_error(ERR_DME_INVALID_STATE,
                    f"action requires DISPATCHED, found {dme['status']}")


@bp.post("/dme-orders/<dmeOrderId>/deliver")
def deliver_dme_order(dmeOrderId):
    authorized(["DmeCoordinator"])
    dme = require_path_resource("dme_orders", dmeOrderId)
    _require_dispatched(dme)
    dme["status"] = "DELIVERED"
    dme["delivered_at"] = CLOCK.now_iso()
    touch(dme)
    rx = db["therapy_prescriptions"].get(dme["prescription_id"])
    if rx is not None and rx["status"] == "ORDERED":
        rx["status"] = "FULFILLED"
        touch(rx)
    return success_object(public(dme))


@bp.post("/dme-orders/<dmeOrderId>/decline")
def decline_dme_order(dmeOrderId):
    authorized(["DmeCoordinator"])
    dme = require_path_resource("dme_orders", dmeOrderId)
    _require_dispatched(dme)
    dme["status"] = "DECLINED"
    touch(dme)
    return success_object(public(dme))


@bp.post("/dme-orders/<dmeOrderId>/cancel")
def cancel_dme_order(dmeOrderId):
    authorized(["DmeCoordinator"])
    dme = require_path_resource("dme_orders", dmeOrderId)
    _require_dispatched(dme)
    dme["status"] = "CANCELLED"
    touch(dme)
    return success_object(public(dme))


@bp.post("/dme-orders/<dmeOrderId>/record-follow-up")
def record_follow_up(dmeOrderId):
    authorized(["DmeCoordinator"])
    dme = require_path_resource("dme_orders", dmeOrderId)
    body = get_body()
    usage_hours_avg = req_num(body, "usage_hours_avg")
    compliant_nights_percent = req_num(body, "compliant_nights_percent")
    if dme["status"] != "DELIVERED":
        raise_error(ERR_DME_INVALID_STATE,
                    f"record-follow-up requires DELIVERED, found {dme['status']}")
    compliant = adherence_compliant(usage_hours_avg, compliant_nights_percent)
    dme["follow_up_usage_hours_avg"] = usage_hours_avg
    dme["follow_up_compliant_nights_percent"] = compliant_nights_percent
    dme["adherence_compliant"] = compliant
    dme["status"] = "FOLLOW_UP_PASSED" if compliant else "ADHERENCE_REVIEW"
    touch(dme)
    return success_object(public(dme))


@bp.post("/dme-orders/<dmeOrderId>/resolve-adherence")
def resolve_adherence(dmeOrderId):
    authorized(["DmeCoordinator"])
    dme = require_path_resource("dme_orders", dmeOrderId)
    body = get_body()
    action = req_enum(body, "action", RESOLUTION_ACTIONS)
    if dme["status"] != "ADHERENCE_REVIEW":
        raise_error(ERR_DME_INVALID_STATE,
                    f"resolve-adherence requires ADHERENCE_REVIEW, found {dme['status']}")
    dme["resolution_action"] = action
    dme["status"] = "FOLLOW_UP_RESOLVED"
    touch(dme)
    return success_object(public(dme))
