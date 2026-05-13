"""Alert lifecycle endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles, auth_context
from response import object_response, array_response
from serializers import alert as ser_alert, response_action as ser_resp
from services import audit
from services.alerts import recompute_level
from validators import (
    get_pagination,
    paginate,
    require_dict,
    require_enum,
    require_str,
)


bp = Blueprint("alerts", __name__)


ACTION_KINDS = {"VENTILATION", "REFRIGERATION_ADJUSTMENT", "TRANSSHIPMENT", "INSPECTION"}


def _bump(alert):
    alert["updated_at"] = clock.now_iso()
    alert["version"] = alert.get("version", 0) + 1


@bp.get("/alerts/<alert_id>")
@require_roles(
    "SHIPPER", "CARRIER", "DRIVER", "DISPATCHER", "COMPLIANCE_OFFICER",
    "INSURANCE_ADJUSTER", "CONSIGNEE",
)
def get_alert(alert_id):
    a = db.alerts.get(alert_id)
    if a is None:
        err("ERR_NOT_FOUND", "Alert not found.")
    return object_response(ser_alert(a))


@bp.get("/alerts")
@require_roles("SHIPPER", "CARRIER", "DISPATCHER", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def list_alerts():
    limit, offset = get_pagination(request.args)
    rows = db.alerts.all()
    task_id = request.args.get("task_id")
    if task_id:
        rows = [a for a in rows if a["task_id"] == task_id]
    status = request.args.get("status")
    if status:
        rows = [a for a in rows if a["status"] == status]
    level = request.args.get("level")
    if level:
        rows = [a for a in rows if a["level"] == level]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [ser_alert(r) for r in page], limit=limit, offset=offset, total_count=total
    )


@bp.post("/alerts/<alert_id>/acknowledge")
@require_roles("DRIVER", "DISPATCHER")
def acknowledge(alert_id):
    with db.global_lock:
        a = db.alerts.get(alert_id)
        if a is None:
            err("ERR_NOT_FOUND", "Alert not found.")
        if a["status"] != "OPEN":
            err("ERR_INVALID_STATE", "Alert must be OPEN to acknowledge.")
        task = db.tasks.get(a["task_id"])
        if task is None:
            err("ERR_INVALID_STATE", "Parent task missing.")
        if task["status"] not in {"DISPATCHED", "IN_TRANSIT", "AT_STOP"}:
            err("ERR_INVALID_STATE", "Parent task not in an acknowledgeable state.")
        a["status"] = "ACKNOWLEDGED"
        _bump(a)
        user_id, role = auth_context()
        audit.log("ALERT", a["id"], "ACKNOWLEDGED", role, user_id)
    return object_response(ser_alert(a))


@bp.post("/alerts/<alert_id>/responses")
@require_roles("DRIVER", "DISPATCHER")
def record_response(alert_id):
    with db.global_lock:
        a = db.alerts.get(alert_id)
        if a is None:
            err("ERR_NOT_FOUND", "Alert not found.")
        if a["status"] not in {"ACKNOWLEDGED", "ESCALATED"}:
            err("ERR_INVALID_STATE", "Alert must be ACKNOWLEDGED or ESCALATED.")

        body = require_dict(request.get_json(silent=True) or {})
        action_kind = require_enum(body.get("action_kind"), ACTION_KINDS, field="action_kind")
        notes = body.get("notes")
        if notes is None:
            notes = ""
        else:
            notes = require_str(notes, field="notes", min_len=0, max_len=500)

        user_id, role = auth_context()
        now_iso = clock.now_iso()
        ra = {
            "id": new_id(),
            "alert_id": a["id"],
            "action_kind": action_kind,
            "executed_by_role": role,
            "notes": notes,
            "executed_at": now_iso,
            "created_at": now_iso,
        }
        db.responses.put(ra)
        prior = a["status"]
        a["status"] = "IN_RESPONSE"
        _bump(a)
        audit.log("ALERT", a["id"], "RESPONSE_RECORDED", role, user_id)
    return object_response(ser_resp(ra), status_code=201)


@bp.post("/alerts/<alert_id>/escalate")
@require_roles("DISPATCHER")
def escalate(alert_id):
    with db.global_lock:
        a = db.alerts.get(alert_id)
        if a is None:
            err("ERR_NOT_FOUND", "Alert not found.")
        if a["status"] != "IN_RESPONSE":
            err("ERR_INVALID_STATE", "Alert must be IN_RESPONSE to escalate.")
        a["status"] = "ESCALATED"
        existing = set(a.get("notified_channels", []))
        existing.add("CUSTOMER")
        order = ["DRIVER", "DISPATCH", "CUSTOMER"]
        a["notified_channels"] = [c for c in order if c in existing]
        _bump(a)
        user_id, role = auth_context()
        audit.log("ALERT", a["id"], "ESCALATED", role, user_id)
    return object_response(ser_alert(a))


@bp.post("/alerts/<alert_id>/resolve")
@require_roles("DISPATCHER")
def resolve(alert_id):
    with db.global_lock:
        a = db.alerts.get(alert_id)
        if a is None:
            err("ERR_NOT_FOUND", "Alert not found.")
        if a["status"] not in {"IN_RESPONSE", "ESCALATED"}:
            err("ERR_INVALID_STATE", "Alert must be IN_RESPONSE or ESCALATED to resolve.")
        task = db.tasks.get(a["task_id"])
        if task is None or task["status"] not in {"IN_TRANSIT", "AT_STOP", "DELIVERED"}:
            err("ERR_TASK_NOT_RESOLVABLE", "Parent task not in a resolvable state.")
        if not db.responses_for_alert(a["id"]):
            err("ERR_INVALID_STATE", "At least one ResponseAction is required to resolve.")
        a["resolved_at"] = clock.now_iso()
        # Final classification: recompute first so duration_seconds and peak are final
        recompute_level(a, task)
        a["status"] = "RESOLVED"
        _bump(a)
        user_id, role = auth_context()
        audit.log("ALERT", a["id"], "RESOLVED", role, user_id)
    return object_response(ser_alert(a))
