"""Spend anomaly detection and triage (PRD 3.9)."""
from flask import Blueprint, request

from db import db, touch
from errors import fail
from middleware import authorize, user_id
from routes.common import lookup, optional_ref, serve, serve_list, serve_many
from services import flows
from validation import body, opt_str, req_enum, req_str

bp = Blueprint("anomalies", __name__)

READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "BusinessUnitOwner")
ROOT_CAUSE_KINDS = (
    "NEW_RESOURCE",
    "UTILIZATION_SPIKE",
    "COMMITMENT_EXPIRY",
    "UNTAGGED_ABSORPTION",
)
RESOLUTIONS = ("EXPLAINED", "FALSE_POSITIVE")


@bp.route("/finops/anomaly-scans", methods=["POST"])
@authorize("FinOpsAnalyst")
def anomaly_scan():
    data = body()
    scope = opt_str(data, "business_unit_id")
    if scope is None:
        scope = request.args.get("business_unit_id") or None
    return serve_many(flows.anomaly_scan(scope))


@bp.route("/finops/anomaly-alerts", methods=["GET"])
@authorize(*READERS)
def list_alerts():
    return serve_list(
        db.anomaly_alerts.values(),
        {
            "business_unit_id": "business_unit_id",
            "root_cause_cloud_resource_id": "root_cause_cloud_resource_id",
            "severity": "severity",
            "status": "status",
        },
    )


@bp.route("/finops/anomaly-alerts/<alert_id>", methods=["GET"])
@authorize(*READERS)
def get_alert(alert_id):
    return serve(lookup("anomaly_alerts", alert_id))


@bp.route("/finops/anomaly-alerts/<alert_id>/acknowledge", methods=["POST"])
@authorize("FinOpsAnalyst")
def acknowledge_alert(alert_id):
    alert = lookup("anomaly_alerts", alert_id)
    if alert["status"] != "ROUTED":
        fail("ERR_ALERT_STATE_INVALID", "Only a ROUTED alert may be acknowledged.")
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_by_user_id"] = user_id()
    touch(alert)
    return serve(alert)


@bp.route("/finops/anomaly-alerts/<alert_id>/attribute", methods=["POST"])
@authorize("FinOpsAnalyst")
def attribute_alert(alert_id):
    alert = lookup("anomaly_alerts", alert_id)
    data = body()
    resource = optional_ref("cloud_resources", req_str(data, "root_cause_cloud_resource_id"))
    root_cause_kind = req_enum(data, "root_cause_kind", ROOT_CAUSE_KINDS)

    if alert["status"] != "ACKNOWLEDGED":
        fail("ERR_ALERT_STATE_INVALID", "Only an ACKNOWLEDGED alert may be attributed.")
    if resource["lifecycle_state"] == "TERMINATED":
        fail(
            "ERR_RESOURCE_STATE_INVALID",
            "A TERMINATED resource may not be named as a root cause.",
        )
    if resource["business_unit_id"] != alert["business_unit_id"]:
        fail(
            "ERR_INVALID_REQUEST",
            "The named resource does not belong to the alert's business unit.",
        )

    alert["status"] = "ATTRIBUTED"
    alert["root_cause_cloud_resource_id"] = resource["id"]
    alert["root_cause_kind"] = root_cause_kind
    touch(alert)
    return serve(alert)


@bp.route("/finops/anomaly-alerts/<alert_id>/close", methods=["POST"])
@authorize("FinOpsController")
def close_alert(alert_id):
    alert = lookup("anomaly_alerts", alert_id)
    data = body()
    resolution = req_enum(data, "resolution", RESOLUTIONS)

    if resolution == "EXPLAINED":
        if alert["status"] != "ATTRIBUTED" or alert["root_cause_kind"] is None:
            fail(
                "ERR_ALERT_STATE_INVALID",
                "An alert may only be closed as EXPLAINED once attributed.",
            )
        alert["status"] = "CLOSED_EXPLAINED"
    else:
        if alert["status"] != "ACKNOWLEDGED":
            fail(
                "ERR_ALERT_STATE_INVALID",
                "An alert may only be closed as FALSE_POSITIVE from ACKNOWLEDGED.",
            )
        alert["status"] = "CLOSED_FALSE_POSITIVE"
        alert["root_cause_cloud_resource_id"] = None
        alert["root_cause_kind"] = None
    touch(alert)
    return serve(alert)
