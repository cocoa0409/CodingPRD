"""ReminderRule and ReminderEvent endpoints."""

from flask import Blueprint, g

from db import LOCK
from middleware import require_roles
from response import success_object, success_array
from services import reminders as svc
from services.serializers import serialize_reminder_rule, serialize_reminder_event
from ._helpers import parse_pagination, get_json_body


bp = Blueprint("reminders", __name__)


@bp.route("/contracts/<cid>/reminder-rules", methods=["POST"])
@require_roles("ContractInitiator")
def post_reminder_rule(cid):
    body = get_json_body()
    with LOCK:
        r = svc.create_reminder_rule(cid, body)
    return success_object(serialize_reminder_rule(r), 201)


@bp.route("/reminder-rules/<rid>", methods=["PATCH"])
@require_roles("ContractInitiator")
def patch_reminder_rule(rid):
    body = get_json_body()
    with LOCK:
        r = svc.patch_reminder_rule(rid, body)
    return success_object(serialize_reminder_rule(r))


@bp.route("/reminder-rules/<rid>/fire", methods=["POST"])
@require_roles("ContractInitiator", "SystemSweeper")
def fire_reminder_rule(rid):
    body = get_json_body()
    with LOCK:
        e = svc.fire_reminder(rid, body, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_reminder_event(e), 201)


@bp.route("/contracts/<cid>/reminder-events", methods=["GET"])
@require_roles("ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def list_reminder_events(cid):
    limit, offset = parse_pagination()
    with LOCK:
        rows, total = svc.list_reminder_events(cid, limit, offset)
        data = [serialize_reminder_event(r) for r in rows]
    return success_array(data, limit, offset, total)
