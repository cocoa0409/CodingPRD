"""IncidentReport endpoints: filing workflow, penalties, closure."""

from flask import Blueprint, request

import calc
import errors
import serializers
from db import stamp_new, store, touch
from envelope import ok
from listing import page_out
from validators import (
    SEVERITIES,
    as_dt,
    as_enum,
    as_num,
    body,
    endpoint,
    get_or_404,
    opt,
    req,
)

bp = Blueprint("incidents", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _incident_or_404(incident_id):
    return get_or_404(store.incidents, incident_id, errors.ERR_INCIDENT_NOT_FOUND,
                      "IncidentReport")


@bp.route("/hazmat/shipments/<shipmentId>/incident-reports", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def create_incident(uid, role, shipmentId):
    shipment = get_or_404(store.shipments, shipmentId, errors.ERR_SHIPMENT_NOT_FOUND,
                          "Shipment")
    b = body()
    occurred_at = as_dt(req(b, "occurred_at"), "occurred_at")
    severity = as_enum(req(b, "severity"), "severity", SEVERITIES)
    incident = {
        "shipment_id": shipment["id"],
        "carrier_id": shipment["carrier_id"],
        "occurred_at": occurred_at,
        "severity": severity,
        "confirmed_severity": None,
        "phone_report_required": severity in ("MAJOR", "CATASTROPHIC"),
        "phone_deadline": occurred_at + calc.PHONE_DEADLINE,
        "written_report_deadline": occurred_at + calc.WRITTEN_DEADLINE,
        "phone_reported_at": None,
        "written_filed_at": None,
        "penalty_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(incident)
    store.incidents[incident["id"]] = incident
    return ok(serializers.incident(incident), 201)


@bp.route("/hazmat/incident-reports", methods=["GET"])
@endpoint(ALL_ROLES)
def list_incidents(uid, role):
    rows = list(store.incidents.values())
    shipment_id = request.args.get("shipment_id")
    if shipment_id is not None:
        rows = [i for i in rows if i["shipment_id"] == shipment_id]
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        rows = [i for i in rows if i["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    return page_out(rows, serializers.incident)


@bp.route("/hazmat/incident-reports/<incidentId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_incident(uid, role, incidentId):
    return ok(serializers.incident(_incident_or_404(incidentId)), 200)


@bp.route("/hazmat/incident-reports/<incidentId>/record-phone-report", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def record_phone_report(uid, role, incidentId):
    incident = _incident_or_404(incidentId)
    if incident["status"] != "DRAFT":
        raise errors.conflict(errors.ERR_INCIDENT_NOT_DRAFT,
                              "record-phone-report requires DRAFT")
    incident["phone_reported_at"] = store.clock
    incident["status"] = "PHONE_REPORTED"
    touch(incident)
    return ok(serializers.incident(incident), 200)


@bp.route("/hazmat/incident-reports/<incidentId>/file-written", methods=["POST"])
@endpoint(["ShipperComplianceOfficer"])
def file_written(uid, role, incidentId):
    incident = _incident_or_404(incidentId)
    ok_states = incident["status"] == "PHONE_REPORTED" or (
        incident["status"] == "DRAFT" and incident["severity"] == "MINOR"
    )
    if not ok_states:
        raise errors.conflict(
            errors.ERR_PHONE_REPORT_REQUIRED,
            "file-written requires PHONE_REPORTED, except MINOR from DRAFT",
        )
    incident["written_filed_at"] = store.clock
    incident["status"] = "WRITTEN_FILED"
    incident["penalty_cents"] = calc.incident_penalty_reported(incident)
    touch(incident)
    return ok(serializers.incident(incident), 200)


@bp.route("/hazmat/incident-reports/<incidentId>/close", methods=["POST"])
@endpoint(["Regulator"])
def close_incident(uid, role, incidentId):
    incident = _incident_or_404(incidentId)
    b = body()
    confirmed = as_enum(req(b, "confirmed_severity"), "confirmed_severity",
                        SEVERITIES)
    adjustment = as_num(opt(b, "adjustment_percent", 0), "adjustment_percent")
    if adjustment < -50 or adjustment > 50:
        raise errors.invalid("adjustment_percent must be between -50 and 50")
    if incident["status"] != "WRITTEN_FILED":
        raise errors.conflict(errors.ERR_INCIDENT_NOT_CLOSABLE,
                              "Close requires WRITTEN_FILED")
    incident["confirmed_severity"] = confirmed
    incident["penalty_cents"] = calc.incident_penalty_confirmed(
        incident, confirmed, adjustment
    )
    incident["status"] = "CLOSED"
    touch(incident)
    carrier = store.carriers.get(incident["carrier_id"])
    if carrier is not None:
        points = calc.SAFETY_POINTS[confirmed]
        carrier["safety_rating"] = max(calc.RATING_FLOOR,
                                       carrier["safety_rating"] - points)
        touch(carrier)
    return ok(serializers.incident(incident), 200)
