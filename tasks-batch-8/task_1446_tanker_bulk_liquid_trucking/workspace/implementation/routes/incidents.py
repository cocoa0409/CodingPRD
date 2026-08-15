"""Spill incidents: driver reporting and the safety-office review loop
(PRD 3.7)."""
from flask import Blueprint, request

from authz import ALL_ROLES, DRIVER, SAFETY_OFFICER, require_roles
from calc import REPORTABLE_DEADLINE, severity_for
from db import store
from errors import err
from respond import success
from serialize import ser_spill_incident
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_datetime, req_number, sorted_by_creation, touch,
)

bp = Blueprint("spill_incidents", __name__)

# Shipment states from which an incident may be closed (past transit).
CLOSABLE_SHIPMENT_STATUSES = ("DELIVERED", "VARIANCE_REVIEW", "RECONCILED", "CANCELLED")


def _incident_invalid(msg):
    return err("ERR_INCIDENT_INVALID_STATE", msg)


@bp.route("/shipments/<sid>/spill-incidents", methods=["POST"])
def report_incident(sid):
    uid, _role = require_roles([DRIVER])
    s = get_or_404(store.shipments, "shipments", sid)
    # Priority 2 identity: only the assigned driver reports spills on it.
    if uid != s["driver_id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Only the assigned driver may report a spill on this shipment")
    # Priority 4: shape.
    data = json_body()
    reject_unknown(data, {"occurred_at", "gallons_spilled"})
    occurred_at = req_datetime(data, "occurred_at")
    gallons = req_number(data, "gallons_spilled", minimum=0, exclusive_minimum=True)
    # Priority 6: only while IN_TRANSIT or DELIVERING.
    if s["status"] not in ("IN_TRANSIT", "DELIVERING"):
        raise err("ERR_SHIPMENT_INVALID_STATE",
                  "Spills may be reported only while the shipment is IN_TRANSIT or DELIVERING")
    severity = severity_for(gallons)
    # Priority 8 temporal: REPORTABLE incidents carry a 12-hour reporting
    # deadline; exactly 12 hours is still on time.
    if severity == "REPORTABLE" and store.clock - occurred_at > REPORTABLE_DEADLINE:
        raise err("ERR_REPORT_DEADLINE_MISSED",
                  "A REPORTABLE spill must be reported within 12 hours of occurred_at")
    i = {
        "id": new_id(),
        "_seq": next(store.seq),
        "shipment_id": s["id"],
        "reported_by_driver_id": uid,
        "occurred_at": occurred_at,
        "reported_at": store.clock,
        "gallons_spilled": gallons,
        "severity": severity,
        "closed_by_user_id": None,
        "status": "REPORTED",
    }
    i.update(new_common_fields())
    store.spill_incidents[i["id"]] = i
    return success(ser_spill_incident(i), status=201)


@bp.route("/spill-incidents", methods=["GET"])
def list_incidents():
    require_roles(ALL_ROLES)
    shipment_id = request.args.get("shipment_id")
    reporter = request.args.get("reported_by_driver_id")
    status = request.args.get("status")
    items = [i for i in store.spill_incidents.values()
             if (shipment_id is None or i["shipment_id"] == shipment_id)
             and (reporter is None or i["reported_by_driver_id"] == reporter)
             and (status is None or i["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_spill_incident(i) for i in page],
                   response_type="array", pagination=pagination)


@bp.route("/spill-incidents/<iid>", methods=["GET"])
def get_incident(iid):
    require_roles(ALL_ROLES)
    return success(ser_spill_incident(get_or_404(store.spill_incidents, "spill_incidents", iid)))


@bp.route("/spill-incidents/<iid>/start-review", methods=["POST"])
def start_review(iid):
    require_roles([SAFETY_OFFICER])
    i = get_or_404(store.spill_incidents, "spill_incidents", iid)
    reject_unknown(json_body(), set())
    if i["status"] != "REPORTED":
        raise _incident_invalid("Start-review requires the incident to be REPORTED")
    i["status"] = "UNDER_REVIEW"
    touch(i)
    return success(ser_spill_incident(i))


@bp.route("/spill-incidents/<iid>/request-info", methods=["POST"])
def request_info(iid):
    require_roles([SAFETY_OFFICER])
    i = get_or_404(store.spill_incidents, "spill_incidents", iid)
    reject_unknown(json_body(), set())
    if i["status"] != "UNDER_REVIEW":
        raise _incident_invalid("Request-info requires the incident to be UNDER_REVIEW")
    i["status"] = "REPORTED"
    touch(i)
    return success(ser_spill_incident(i))


@bp.route("/spill-incidents/<iid>/close", methods=["POST"])
def close_incident(iid):
    uid, _role = require_roles([SAFETY_OFFICER])
    i = get_or_404(store.spill_incidents, "spill_incidents", iid)
    reject_unknown(json_body(), set())
    if i["status"] != "UNDER_REVIEW":
        raise _incident_invalid("Close requires the incident to be UNDER_REVIEW")
    s = store.shipments[i["shipment_id"]]
    if s["status"] not in CLOSABLE_SHIPMENT_STATUSES:
        raise err("ERR_SHIPMENT_NOT_DELIVERED",
                  "Incident close requires the shipment to be past transit")
    i["closed_by_user_id"] = uid
    i["status"] = "CLOSED"
    touch(i)
    return success(ser_spill_incident(i))


@bp.route("/spill-incidents/<iid>/reopen", methods=["POST"])
def reopen_incident(iid):
    uid, _role = require_roles([SAFETY_OFFICER])
    i = get_or_404(store.spill_incidents, "spill_incidents", iid)
    reject_unknown(json_body(), set())
    if i["status"] != "CLOSED":
        raise _incident_invalid("Reopen requires the incident to be CLOSED")
    # Priority 9: segregation of duties — the reopener must differ from the
    # officer who closed the incident.
    if uid == i["closed_by_user_id"]:
        raise err("ERR_SAME_OPERATOR_SEGREGATION",
                  "The reopening officer must differ from the closing officer")
    i["closed_by_user_id"] = None
    i["status"] = "UNDER_REVIEW"
    touch(i)
    return success(ser_spill_incident(i))
