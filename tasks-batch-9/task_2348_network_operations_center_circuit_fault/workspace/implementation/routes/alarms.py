"""Alarm ingestion, correlation and clearing (PRD 3.3)."""

from flask import Blueprint

import db
import derive
import lookup
from consts import ALARM_TYPES, CORRELATION_STATES, RAW_SEVERITIES
from db import base_record, now, rows
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send, send_list
from valid import body, q_enum, q_string, req_enum, req_ts

bp = Blueprint("alarms", __name__)

INGEST_ROLES = ("NocAnalyst", "NocShiftLead", "PlatformAdmin")
READ_ROLES = ("NocAnalyst", "NocShiftLead", "VendorManager", "PlatformAdmin")


@bp.post("/alarms")
def ingest_alarm():
    authenticate(INGEST_ROLES)
    payload = body()
    source_circuit = body_ref(payload, "source_circuit_id", lookup.circuit)
    source_device = body_ref(payload, "source_device_id", lookup.device)
    alarm_type = req_enum(payload, "alarm_type", ALARM_TYPES)
    raw_severity = req_enum(payload, "raw_severity", RAW_SEVERITIES)
    raised_at = req_ts(payload, "raised_at")
    if raised_at > now():
        fail("ERR_TIMESTAMP_RANGE_INVALID")
    if (source_circuit is None) == (source_device is None):
        fail("ERR_ALARM_SOURCE_INVALID")

    alarm = base_record(versioned=False)
    alarm.update(
        {
            "source_circuit_id": source_circuit["id"] if source_circuit else None,
            "source_device_id": source_device["id"] if source_device else None,
            "alarm_type": alarm_type,
            "raw_severity": raw_severity,
            "raised_at": raised_at,
            "correlation_state": "ROOT",
            "correlation_parent_alarm_id": None,
            "incident_id": None,
            "cleared_at": None,
        }
    )

    maintenance_suppressed = (
        source_circuit is not None
        and source_circuit["monitoring_state"] == "MAINTENANCE_SUPPRESSED"
    )
    parent = None
    if maintenance_suppressed:
        alarm["correlation_state"] = "SUPPRESSED"
    else:
        parent = derive.choose_correlation_parent(alarm)
        if parent is not None:
            alarm["correlation_state"] = "SUPPRESSED"
            alarm["correlation_parent_alarm_id"] = parent["id"]

    db.db.alarms[alarm["id"]] = alarm

    if maintenance_suppressed:
        return send(alarm, 201)

    if parent is not None:
        derive.attach_suppressed_alarm(alarm, parent)
        return send(alarm, 201)

    circuit_ids = [source_circuit["id"]] if source_circuit else []
    device_ids = [source_device["id"]] if source_device else []
    derive.cascade_health(circuit_ids, device_ids)
    derive.attach_or_open_incident(alarm, derive.anchor_circuit_id(alarm))
    return send(alarm, 201)


@bp.post("/alarms/<id>/clear")
def clear_alarm(id):
    authenticate(INGEST_ROLES)
    alarm = lookup.alarm(id)
    payload = body()
    cleared_at = req_ts(payload, "cleared_at")
    if cleared_at < alarm["raised_at"] or cleared_at > now():
        fail("ERR_TIMESTAMP_RANGE_INVALID")
    if alarm["cleared_at"] is not None:
        fail("ERR_ALARM_ALREADY_CLEARED")

    was_root = alarm["correlation_state"] == "ROOT"
    alarm["cleared_at"] = cleared_at
    alarm["correlation_state"] = "CLEARED"

    if not was_root:
        return send(alarm)

    children = [
        child
        for child in rows(db.db.alarms)
        if child["correlation_parent_alarm_id"] == alarm["id"]
        and child["cleared_at"] is None
        and child["correlation_state"] == "SUPPRESSED"
    ]
    children.sort(key=lambda a: (a["raised_at"], a["_seq"]))

    promoted = None
    if children:
        promoted = children[0]
        promoted["correlation_state"] = "ROOT"
        promoted["correlation_parent_alarm_id"] = None
        for child in children[1:]:
            child["correlation_parent_alarm_id"] = promoted["id"]

    circuit_ids = set()
    device_ids = set()
    for record in (alarm, promoted):
        if record is None:
            continue
        if record["source_circuit_id"]:
            circuit_ids.add(record["source_circuit_id"])
        if record["source_device_id"]:
            device_ids.add(record["source_device_id"])

    derive.cascade_health(circuit_ids, device_ids)

    if promoted is not None:
        derive.attach_or_open_incident(promoted, derive.anchor_circuit_id(promoted))
    return send(alarm)


@bp.get("/alarms/<id>")
def get_alarm(id):
    authenticate(READ_ROLES)
    return send(lookup.alarm(id))


@bp.get("/alarms")
def list_alarms():
    authenticate(READ_ROLES)
    source_circuit_id = q_string("source_circuit_id")
    source_device_id = q_string("source_device_id")
    correlation_parent_alarm_id = q_string("correlation_parent_alarm_id")
    incident_id = q_string("incident_id")
    correlation_state = q_enum("correlation_state", CORRELATION_STATES)
    alarm_type = q_enum("alarm_type", ALARM_TYPES)
    result = []
    for alarm in rows(db.db.alarms):
        if source_circuit_id and alarm["source_circuit_id"] != source_circuit_id:
            continue
        if source_device_id and alarm["source_device_id"] != source_device_id:
            continue
        if (
            correlation_parent_alarm_id
            and alarm["correlation_parent_alarm_id"] != correlation_parent_alarm_id
        ):
            continue
        if incident_id and alarm["incident_id"] != incident_id:
            continue
        if correlation_state and alarm["correlation_state"] != correlation_state:
            continue
        if alarm_type and alarm["alarm_type"] != alarm_type:
            continue
        result.append(alarm)
    return send_list(result)
