"""CriticalFinding and NotificationLog endpoints."""

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from calc import dec
from db import db as store
from errors import ApiError
from middleware import (
    BRIDGE_INSPECTOR,
    DISTRICT_ENGINEER,
    QA_REVIEWER,
    authenticate,
    authenticate_read,
)

bp = Blueprint("findings", __name__)

SEVERITIES = ("URGENT", "IMMEDIATE")
FINDING_STATUSES = ("OPEN", "MITIGATED", "RESOLVED")
NOTIFICATION_STATUSES = ("PENDING", "OWNER_NOTIFIED", "FHWA_REPORTED")
RESTRICTION_ACTIONS = ("NONE", "RESTRICT", "CLOSE")
TIERS = ("BRIDGE_OWNER", "FHWA")
CHANNELS = ("EMAIL", "PHONE", "PORTAL")


@bp.post("/critical-findings")
def create_critical_finding():
    authenticate(BRIDGE_INSPECTOR, QA_REVIEWER)
    body = params.json_body()
    bridge_id = params.get_string(body, "bridge_id", required=True)
    source_inspection_id = params.get_string(body, "source_inspection_id", required=True)
    severity = params.get_enum(body, "severity", SEVERITIES, required=True)
    description = params.get_string(body, "description", required=True)
    element_condition_id = params.get_string(body, "element_condition_id")

    bridge = services.get_bridge(bridge_id)
    inspection = services.get_inspection(source_inspection_id)
    element = None
    if element_condition_id is not None:
        element = services.get_element_condition(element_condition_id)

    if inspection["status"] not in ("SUBMITTED", "IN_QA", "ACCEPTED"):
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if inspection["bridge_id"] != bridge_id:
        raise ApiError("ERR_ELEMENT_INSPECTION_MISMATCH")
    if element is not None and element["inspection_id"] != source_inspection_id:
        raise ApiError("ERR_ELEMENT_INSPECTION_MISMATCH")
    if severity == "IMMEDIATE" and (element is None or dec(element["cs4_qty"]) <= 0):
        raise ApiError("ERR_NO_CS4_DEFICIENCY")

    record = db.new_record(
        {
            "bridge_id": inspection["bridge_id"],
            "source_inspection_id": source_inspection_id,
            "element_condition_id": element_condition_id,
            "severity": severity,
            "finding_status": "OPEN",
            "notification_status": "PENDING",
            "restriction_action": "NONE",
            "restriction_authorized_by_id": None,
            "restriction_imposed_at": None,
            "notification_late": False,
            "description": description,
            "mitigation_note": None,
            "resolution_note": None,
        }
    )
    record["notification_due_at"] = calc.notification_due_at(record["created_at"])
    store.critical_findings[record["id"]] = record
    services.settle_and_touch(bridge)
    return response.object_response(serializers.critical_finding(record), 201)


@bp.get("/critical-findings/<finding_id>")
def read_critical_finding(finding_id):
    authenticate_read()
    record = services.get_critical_finding(finding_id)
    return response.object_response(serializers.critical_finding(record))


@bp.get("/critical-findings")
def list_critical_findings():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    source_inspection_id = params.query_string("source_inspection_id")
    element_condition_id = params.query_string("element_condition_id")
    authorized_by_id = params.query_string("restriction_authorized_by_id")
    severity = params.query_enum("severity", SEVERITIES)
    finding_status = params.query_enum("finding_status", FINDING_STATUSES)
    notification_status = params.query_enum("notification_status", NOTIFICATION_STATUSES)
    restriction_action = params.query_enum("restriction_action", RESTRICTION_ACTIONS)
    notification_late = params.query_bool("notification_late")
    items = []
    for record in services.rows("critical_findings"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if source_inspection_id is not None and record["source_inspection_id"] != source_inspection_id:
            continue
        if element_condition_id is not None and record["element_condition_id"] != element_condition_id:
            continue
        if authorized_by_id is not None and record["restriction_authorized_by_id"] != authorized_by_id:
            continue
        if severity is not None and record["severity"] != severity:
            continue
        if finding_status is not None and record["finding_status"] != finding_status:
            continue
        if notification_status is not None and record["notification_status"] != notification_status:
            continue
        if restriction_action is not None and record["restriction_action"] != restriction_action:
            continue
        data = serializers.critical_finding(record)
        if notification_late is not None and bool(data["notification_late"]) != notification_late:
            continue
        items.append(data)
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/critical-findings/<finding_id>/impose-restriction")
def impose_restriction(finding_id):
    actor = authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    action = params.get_enum(body, "action", ("RESTRICT", "CLOSE"), required=True)
    authorized_by_id = params.get_string(body, "authorized_by_id", required=True)
    record = services.get_critical_finding(finding_id)
    services.get_personnel(authorized_by_id)
    if authorized_by_id != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if record["finding_status"] not in ("OPEN", "MITIGATED"):
        raise ApiError("ERR_FINDING_STATE_INVALID")
    if action == "RESTRICT" and record["restriction_action"] != "NONE":
        raise ApiError("ERR_FINDING_STATE_INVALID")
    if action == "CLOSE" and record["restriction_action"] not in ("NONE", "RESTRICT"):
        raise ApiError("ERR_FINDING_STATE_INVALID")
    inspection = store.inspections.get(record["source_inspection_id"])
    if inspection is not None and inspection["team_leader_id"] == authorized_by_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if action == "CLOSE" and record["severity"] != "IMMEDIATE":
        raise ApiError("ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE")

    record["restriction_action"] = action
    record["restriction_authorized_by_id"] = authorized_by_id
    record["restriction_imposed_at"] = db.now()
    db.touch(record)
    bridge = services.get_bridge(record["bridge_id"])
    services.settle_and_touch(bridge)
    if action == "CLOSE":
        services.cascade_bridge_closed(bridge)
    return response.object_response(serializers.critical_finding(record))


@bp.post("/critical-findings/<finding_id>/notify")
def notify(finding_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    tier = params.get_enum(body, "tier", TIERS, required=True)
    channel = params.get_enum(body, "channel", CHANNELS, required=True)
    recipient_label = params.get_string(body, "recipient_label", required=True)
    record = services.get_critical_finding(finding_id)
    if tier == "BRIDGE_OWNER":
        if record["finding_status"] == "RESOLVED":
            raise ApiError("ERR_FINDING_STATE_INVALID")
        if record["notification_status"] != "PENDING":
            raise ApiError("ERR_NOTIFICATION_SEQUENCE")
    else:
        if record["notification_status"] != "OWNER_NOTIFIED":
            raise ApiError("ERR_NOTIFICATION_SEQUENCE")

    sent_at = db.now()
    late = False
    if tier == "BRIDGE_OWNER":
        late = calc.is_late(sent_at, record["notification_due_at"])
    log = db.new_record(
        {
            "critical_finding_id": finding_id,
            "tier": tier,
            "channel": channel,
            "recipient_label": recipient_label,
            "sent_at": sent_at,
            "late": late,
        },
        common=False,
    )
    store.notification_logs[log["id"]] = log
    if tier == "BRIDGE_OWNER":
        record["notification_status"] = "OWNER_NOTIFIED"
        if late:
            record["notification_late"] = True
    else:
        record["notification_status"] = "FHWA_REPORTED"
    db.touch(record)
    return response.object_response(serializers.notification_log(log), 201)


@bp.get("/notification-logs/<log_id>")
def read_notification_log(log_id):
    authenticate_read()
    record = services.get_notification_log(log_id)
    return response.object_response(serializers.notification_log(record))


@bp.get("/notification-logs")
def list_notification_logs():
    authenticate_read()
    limit, offset = params.query_pagination()
    finding_id = params.query_string("critical_finding_id")
    tier = params.query_enum("tier", TIERS)
    channel = params.query_enum("channel", CHANNELS)
    late = params.query_bool("late")
    items = []
    for record in services.rows("notification_logs"):
        if finding_id is not None and record["critical_finding_id"] != finding_id:
            continue
        if tier is not None and record["tier"] != tier:
            continue
        if channel is not None and record["channel"] != channel:
            continue
        if late is not None and bool(record["late"]) != late:
            continue
        items.append(serializers.notification_log(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/critical-findings/<finding_id>/mitigate")
def mitigate(finding_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    mitigation_note = params.get_string(body, "mitigation_note", required=True)
    record = services.get_critical_finding(finding_id)
    if record["finding_status"] != "OPEN":
        raise ApiError("ERR_FINDING_STATE_INVALID")
    record["finding_status"] = "MITIGATED"
    record["mitigation_note"] = mitigation_note
    db.touch(record)
    return response.object_response(serializers.critical_finding(record))


@bp.post("/critical-findings/<finding_id>/resolve")
def resolve(finding_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    resolution_note = params.get_string(body, "resolution_note", required=True)
    record = services.get_critical_finding(finding_id)
    if record["finding_status"] not in ("OPEN", "MITIGATED"):
        raise ApiError("ERR_FINDING_STATE_INVALID")
    if record["notification_status"] not in ("OWNER_NOTIFIED", "FHWA_REPORTED"):
        raise ApiError("ERR_FINDING_STATE_INVALID")
    record["finding_status"] = "RESOLVED"
    record["resolution_note"] = resolution_note
    db.touch(record)
    bridge = services.get_bridge(record["bridge_id"])
    services.settle_and_touch(bridge)
    return response.object_response(serializers.critical_finding(record))
