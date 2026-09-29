"""Spill prevention, containment and asset quarantine (PRD 3.6)."""

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, cascade
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    q_str,
    v_bool,
    v_datetime,
    v_decimal,
    v_string,
)

bp = Blueprint("spills", __name__)

SPILL_READERS = ("ComplianceOfficer", "OpsCoordinator", "BargeMaster")
SPILL_STATUSES = ("OPEN", "CLOSED")


@bp.post("/spill-incidents")
@roles("BargeMaster")
def create_incident():
    data = body()
    order = body_ref(
        data, "delivery_order_id", store.delivery_orders, "ERR_DELIVERY_ORDER_NOT_FOUND"
    )
    if order is not None and g.user_id != order["asset_id"]:
        raise ApiError("ERR_ASSET_NOT_ASSIGNED")

    v_string(data, "delivery_order_id", min_len=1)
    reported_at = v_datetime(data, "reported_at")
    volume_liters = v_decimal(data, "volume_liters", 2, positive=True)
    boom_deployed = v_bool(data, "boom_deployed")
    if order is None:
        raise ApiError("ERR_DELIVERY_ORDER_NOT_FOUND")

    nomination, port, grade, customer, asset = calc.order_context(order)
    if order["logistics_status"] not in calc.ACTIVE_ORDER_STATES:
        raise ApiError("ERR_INVALID_ORDER_STATE")

    severity = (
        "MAJOR"
        if (volume_liters >= calc.MAJOR_VOLUME_LITERS or not boom_deployed)
        else "MINOR"
    )
    penalty_points = calc.MAJOR_PENALTY if severity == "MAJOR" else calc.MINOR_PENALTY

    incident = db.new_record()
    incident.update(
        {
            "delivery_order_id": order["id"],
            "asset_id": order["asset_id"],
            "port_id": nomination["port_id"] if nomination else None,
            "reported_at": reported_at,
            "volume_liters": volume_liters,
            "boom_deployed": boom_deployed,
            "containment_confirmed": False,
            "severity": severity,
            "penalty_points": penalty_points,
            "response_ref": None,
            "status": "OPEN",
            "closed_at": None,
        }
    )
    store.spill_incidents[incident["id"]] = incident

    # Reporting always suspends the delivery it happened on.
    order["logistics_status"] = "SUSPENDED"
    touch(order)
    if severity == "MAJOR":
        cascade.quarantine_asset(asset, order["id"])
    cascade.refresh_asset(asset, score=True)
    return success(serializers.spill_incident(incident), 201)


@bp.get("/spill-incidents/<rec_id>")
@roles(*SPILL_READERS)
def get_incident(rec_id):
    incident = path_ref(store.spill_incidents, rec_id, "ERR_SPILL_INCIDENT_NOT_FOUND")
    return success(serializers.spill_incident(incident))


@bp.get("/spill-incidents")
@roles(*SPILL_READERS)
def list_incidents():
    delivery_order_id = q_str("delivery_order_id")
    asset_id = q_str("asset_id")
    port_id = q_str("port_id")
    status = q_enum("status", SPILL_STATUSES)
    limit, offset = pagination()

    def match(row):
        if delivery_order_id is not None and row["delivery_order_id"] != delivery_order_id:
            return False
        if asset_id is not None and row["asset_id"] != asset_id:
            return False
        if port_id is not None and row["port_id"] != port_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.sorted_rows(store.spill_incidents, match)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.spill_incident(r) for r in page], limit, offset, len(rows))


@bp.post("/spill-incidents/<rec_id>/confirm-containment")
@roles("ComplianceOfficer")
def confirm_containment(rec_id):
    incident = path_ref(store.spill_incidents, rec_id, "ERR_SPILL_INCIDENT_NOT_FOUND")
    data = body()
    response_ref = v_string(data, "response_ref", min_len=1)

    incident["response_ref"] = response_ref
    incident["containment_confirmed"] = True
    touch(incident)
    return success(serializers.spill_incident(incident))


@bp.post("/spill-incidents/<rec_id>/close")
@roles("ComplianceOfficer")
def close_incident(rec_id):
    incident = path_ref(store.spill_incidents, rec_id, "ERR_SPILL_INCIDENT_NOT_FOUND")
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_SPILL_STATE")
    if not incident["containment_confirmed"] or incident["response_ref"] is None:
        raise ApiError("ERR_CONTAINMENT_NOT_CONFIRMED")

    incident["status"] = "CLOSED"
    incident["closed_at"] = db.now()
    touch(incident)
    return success(serializers.spill_incident(incident))
