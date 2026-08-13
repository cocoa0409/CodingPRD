"""EmergencyCall intake with dedup/recurrence classification (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from validate import (get_body, opt_enum, pagination_params, paginate,
                      req_bool, req_enum, req_str, sort_by_creation)

bp = Blueprint("calls", __name__)


def implied_priority(call):
    if call["symptoms_reported"]:
        return "P1"
    if call["odor_reported"] and call["location_context"] == "INSIDE_STRUCTURE":
        return "P2"
    if call["odor_reported"]:
        return "P3"
    return "P4"


def normalized_address(address_line, city, territory_id):
    return address_line.strip().upper() + "|" + city.strip().upper() + "|" + territory_id


@bp.route("/gas-ops/emergency-calls", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def intake_call(user_id, role):
    body = get_body()
    rec = domain.new_record(common_fields=False)
    rec.update({
        "caller_name": req_str(body, "caller_name"),
        "caller_phone": req_str(body, "caller_phone"),
        "address_line": req_str(body, "address_line"),
        "city": req_str(body, "city"),
        "territory_id": req_str(body, "territory_id"),
        "location_context": req_enum(body, "location_context", domain.LOCATION_CONTEXTS),
        "occupancy_type": opt_enum(body, "occupancy_type", domain.OCCUPANCY_TYPES, "SINGLE_FAMILY"),
        "odor_reported": req_bool(body, "odor_reported"),
        "symptoms_reported": req_bool(body, "symptoms_reported"),
        "hissing_reported": req_bool(body, "hissing_reported"),
        "received_at": clock.now(),
    })
    territory = db.territories.get(rec["territory_id"])
    if territory is None:
        raise ApiError("ERR_TERRITORY_NOT_FOUND", "Territory not found", 404)
    rec["implied_priority"] = implied_priority(rec)

    now = clock.now()
    key = normalized_address(rec["address_line"], rec["city"], rec["territory_id"])
    same_addr = [i for i in db.incidents.values() if i["normalized_address"] == key]

    # DUPLICATE: a non-terminal incident already exists at this address.
    live = [i for i in same_addr if i["lifecycle_status"] not in ("CLOSED", "MERGED")]
    if live:
        incident = max(live, key=lambda i: (i["created_at"], i["_seq"]))
        rec["classification"] = "DUPLICATE"
        rec["is_duplicate"] = True
        rec["incident_id"] = incident["id"]
        db.calls[rec["id"]] = rec
        if domain.PRIORITY_RANK[rec["implied_priority"]] > domain.PRIORITY_RANK[incident["priority"]]:
            # Auto-escalation (never lowers): raise priority, re-evaluate, notify, mark stale.
            incident["priority"] = rec["implied_priority"]
            domain.auto_priority_notify(incident)
            incident["severity_score"] = domain.severity_score(incident)
            if incident["severity_score"] >= 80:
                domain.auto_severity_notify(incident, "PUBLIC_ALERT")
            domain.bump(incident)
            domain.mark_reports_stale(incident)
        return response.success(domain.ser_call(rec), 201)

    # RECURRENCE: a CLOSED incident whose closure falls in the half-open window
    # [closed_at, closed_at + recurrence_window_hours); exactly at the end -> PRIMARY.
    window = timedelta(hours=territory["recurrence_window_hours"])
    recurrent = [i for i in same_addr
                 if i["lifecycle_status"] == "CLOSED" and i["closed_at"] is not None
                 and i["closed_at"] <= now < i["closed_at"] + window]
    if recurrent:
        incident = max(recurrent, key=lambda i: (i["closed_at"], i["_seq"]))
        old_start = incident["response_clock_started_at"]
        rec["classification"] = "RECURRENCE"
        rec["is_duplicate"] = False
        rec["incident_id"] = incident["id"]
        db.calls[rec["id"]] = rec
        _, _, adjusted = domain.elapsed(incident, now)
        incident["prior_segment_adjusted_seconds"] = adjusted
        incident["reopen_count"] += 1
        incident["lifecycle_status"] = "REOPENED"
        incident["response_clock_started_at"] = rec["received_at"]
        incident["first_arrival_at"] = None
        incident["make_safe_completed"] = False
        incident["entry_status"] = "NOT_REQUIRED"
        incident["closed_at"] = None
        domain.bump(incident)
        domain.mark_reports_stale(incident, extra_times=[old_start])
        return response.success(domain.ser_call(rec), 201)

    # PRIMARY: spawn a new incident.
    incident = domain.new_record(common_fields=True)
    incident.update({
        "territory_id": rec["territory_id"],
        "normalized_address": key,
        "occupancy_type": rec["occupancy_type"],
        "lifecycle_status": "NEW",
        "entry_status": "NOT_REQUIRED",
        "priority": rec["implied_priority"],
        "reopen_count": 0,
        "severity_score": 0,
        "response_clock_started_at": rec["received_at"],
        "first_arrival_at": None,
        "prior_segment_adjusted_seconds": 0,
        "make_safe_completed": False,
        "leak_confirmed": False,
        "auto_notification_created": False,
        "closed_at": None,
    })
    db.incidents[incident["id"]] = incident
    rec["classification"] = "PRIMARY"
    rec["is_duplicate"] = False
    rec["incident_id"] = incident["id"]
    db.calls[rec["id"]] = rec
    domain.auto_priority_notify(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_call(rec), 201)


@bp.route("/gas-ops/emergency-calls", methods=["GET"])
@require_roles("SystemAdmin", "Dispatcher", "Supervisor")
def list_calls(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.calls.values())
    incident_id = request.args.get("incident_id")
    territory_id = request.args.get("territory_id")
    if incident_id is not None:
        items = [c for c in items if c["incident_id"] == incident_id]
    if territory_id is not None:
        items = [c for c in items if c["territory_id"] == territory_id]
    page, total = paginate([domain.ser_call(c) for c in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/emergency-calls/<callId>", methods=["GET"])
@require_roles("SystemAdmin", "Dispatcher", "Supervisor")
def get_call(callId, user_id, role):
    rec = db.calls.get(callId)
    if rec is None:
        raise ApiError("ERR_CALL_NOT_FOUND", "Emergency call not found", 404)
    return response.success(domain.ser_call(rec), 200)
