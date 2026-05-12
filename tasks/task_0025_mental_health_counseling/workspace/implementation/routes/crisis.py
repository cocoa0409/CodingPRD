"""Crisis incident endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit
from services.cascades import crisis_handover_cascade
from services.risk import recompute_for_client
from services.validation import (
    get_body, require_str, optional_str, DETECTION_SOURCES, SEVERITIES,
)


bp = Blueprint("crisis", __name__)


def _public(i: dict) -> dict:
    return db.public(i)


@bp.route("/counseling/crisis-incidents", methods=["POST"])
@require_auth(roles={"Counselor"})
def create_incident():
    body = get_body()
    appointment_id = require_str(body, "appointment_id")
    detection_source = require_str(body, "detection_source")
    trigger_keyword = optional_str(body, "trigger_keyword")
    severity = body.get("severity", "MEDIUM")

    if detection_source not in DETECTION_SOURCES:
        raise err("ERR_VALIDATION", f"invalid detection_source: {detection_source}")
    if severity is not None and severity not in SEVERITIES:
        raise err("ERR_VALIDATION", f"invalid severity: {severity}")

    if detection_source == "KEYWORD_DETECTOR" and not trigger_keyword:
        raise err("ERR_TRIGGER_KEYWORD_MISSING",
                  "trigger_keyword required when detection_source=KEYWORD_DETECTOR")

    appt = db.appointments.get(appointment_id)
    if appt is None:
        raise err("ERR_REF_NOT_FOUND", f"appointment_id {appointment_id} not found")
    if appt["counselor_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Counselor may only escalate own appointment")

    inc = {
        "appointment_id": appointment_id,
        "client_id": appt["client_id"],
        "detection_source": detection_source,
        "trigger_keyword": trigger_keyword,
        "severity": severity or "MEDIUM",
        "status": "DETECTED",
        "assigned_responder_id": None,
        "handover_at": None,
        "emergency_notified_at": None,
        "follow_up_due_at": None,
        "follow_up_completed_at": None,
    }
    db.stamp_create(inc, common_fields=True)
    db.crisis_incidents[inc["id"]] = inc
    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="CRISIS_DETECTED",
        target_entity="CrisisIncident", target_id=inc["id"],
        payload_summary={"source": detection_source},
    )
    recompute_for_client(appt["client_id"])
    return success(_public(inc), 201)


@bp.route("/counseling/crisis-incidents/<id>/handover", methods=["POST"])
@require_auth(roles={"CrisisResponder"})
def handover(id):
    inc = db.crisis_incidents.get(id)
    if inc is None:
        raise err("ERR_NOT_FOUND", f"CrisisIncident {id} not found")
    if inc["status"] != "DETECTED":
        raise err("ERR_INVALID_STATE",
                  f"CrisisIncident status {inc['status']} cannot accept handover")

    body = get_body()
    severity = body.get("severity")
    if severity is not None and severity not in SEVERITIES:
        raise err("ERR_VALIDATION", f"invalid severity: {severity}")
    if severity is None:
        severity = inc.get("severity", "MEDIUM")

    cur = now()
    inc["status"] = "HANDED_OVER"
    inc["assigned_responder_id"] = g.user_id
    inc["handover_at"] = iso(cur)
    inc["follow_up_due_at"] = iso(cur + timedelta(hours=72))
    inc["severity"] = severity
    db.stamp_update(inc)

    crisis_handover_cascade(incident=inc, actor_role=g.user_role, actor_user_id=g.user_id)
    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="CRISIS_HANDOVER",
        target_entity="CrisisIncident", target_id=inc["id"],
        payload_summary={"severity": severity},
    )
    recompute_for_client(inc["client_id"])
    return success(_public(inc))


@bp.route("/counseling/crisis-incidents/<id>/notify-emergency", methods=["POST"])
@require_auth(roles={"CrisisResponder"})
def notify_emergency(id):
    inc = db.crisis_incidents.get(id)
    if inc is None:
        raise err("ERR_NOT_FOUND", f"CrisisIncident {id} not found")
    if inc["status"] != "HANDED_OVER":
        raise err("ERR_INVALID_STATE",
                  f"CrisisIncident status {inc['status']} not eligible for notify")
    if inc.get("severity") == "LOW":
        raise err("ERR_NOTIFY_NOT_REQUIRED",
                  "Notification not required at LOW severity")

    client = db.clients.get(inc["client_id"])
    if client is None or not client.get("emergency_contact_phone"):
        raise err("ERR_NO_EMERGENCY_CONTACT",
                  "Client has no emergency_contact_phone")

    cur = now()
    inc["status"] = "EMERGENCY_NOTIFIED"
    inc["emergency_notified_at"] = iso(cur)
    db.stamp_update(inc)

    audit.append(
        actor_role=g.user_role, actor_user_id=g.user_id,
        action="CRISIS_NOTIFY",
        target_entity="CrisisIncident", target_id=inc["id"],
        payload_summary={"phone_present": True},
    )
    return success(_public(inc))


@bp.route("/counseling/crisis-incidents/<id>/schedule-follow-up", methods=["POST"])
@require_auth(roles={"CrisisResponder"})
def schedule_follow_up(id):
    inc = db.crisis_incidents.get(id)
    if inc is None:
        raise err("ERR_NOT_FOUND", f"CrisisIncident {id} not found")
    if inc["status"] not in ("HANDED_OVER", "EMERGENCY_NOTIFIED"):
        raise err("ERR_INVALID_STATE",
                  f"CrisisIncident status {inc['status']} not eligible for schedule-follow-up")
    if inc["status"] == "HANDED_OVER" and inc.get("severity") != "LOW":
        raise err("ERR_INVALID_STATE",
                  "Must notify emergency before scheduling follow-up at MEDIUM/HIGH severity")

    body = get_body()
    fu_due = optional_str(body, "follow_up_due_at")
    if fu_due is not None:
        try:
            parse_iso(fu_due)
        except ValueError:
            raise err("ERR_VALIDATION", "follow_up_due_at must be ISO 8601")
        inc["follow_up_due_at"] = fu_due

    inc["status"] = "FOLLOW_UP_SCHEDULED"
    db.stamp_update(inc)
    return success(_public(inc))


@bp.route("/counseling/crisis-incidents/<id>/resolve", methods=["POST"])
@require_auth(roles={"CrisisResponder"})
def resolve(id):
    inc = db.crisis_incidents.get(id)
    if inc is None:
        raise err("ERR_NOT_FOUND", f"CrisisIncident {id} not found")
    if inc["status"] != "FOLLOW_UP_SCHEDULED":
        raise err("ERR_INVALID_STATE",
                  f"CrisisIncident status {inc['status']} not eligible for resolve")

    body = get_body()
    fu_completed = require_str(body, "follow_up_completed_at")
    try:
        fu_dt = parse_iso(fu_completed)
    except ValueError:
        raise err("ERR_VALIDATION", "follow_up_completed_at must be ISO 8601")
    if fu_dt > now():
        raise err("ERR_VALIDATION", "follow_up_completed_at must be <= now()")

    inc["status"] = "RESOLVED"
    inc["follow_up_completed_at"] = fu_completed
    db.stamp_update(inc)

    recompute_for_client(inc["client_id"])
    return success(_public(inc))


@bp.route("/counseling/crisis-incidents", methods=["GET"])
@require_auth(roles={"Counselor", "CrisisResponder", "PlatformAdmin"})
def list_incidents():
    limit, offset = get_pagination()
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    severity = request.args.get("severity")

    items = list(db.crisis_incidents.values())
    if g.user_role == "Counselor":
        # Only incidents for appointments owned by counselor
        items = [
            i for i in items
            if (db.appointments.get(i["appointment_id"]) is not None
                and db.appointments[i["appointment_id"]]["counselor_id"] == g.user_id)
        ]
    if client_id:
        items = [i for i in items if i["client_id"] == client_id]
    if status:
        items = [i for i in items if i["status"] == status]
    if severity:
        items = [i for i in items if i["severity"] == severity]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(i) for i in page], limit, offset, total)
