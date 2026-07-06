"""Escalation routes (PRD §3.6). Creation is via POST /va/calls/{callId}/escalate."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_OWNER,
                        ROLE_RECEPTIONIST)
from common import paginate, public, touch
from services.lookups import find_or_404

bp = Blueprint("escalations", __name__)


@bp.route("/va/escalations/<escalation_id>", methods=["GET"])
def get_escalation(escalation_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_OWNER})
    rec = find_or_404(db.escalations, escalation_id)
    return success_object(serializers.escalation(public(rec)), 200)


@bp.route("/va/escalations", methods=["GET"])
def list_escalations():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_OWNER})
    records = list(db.escalations.values())
    call_id = request.args.get("call_id")
    escalated_to = request.args.get("escalated_to_receptionist_id")
    status = request.args.get("status")
    if call_id is not None:
        records = [r for r in records if r["call_id"] == call_id]
    if escalated_to is not None:
        records = [r for r in records if r["escalated_to_receptionist_id"] == escalated_to]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records)
    return success_array([serializers.escalation(public(r)) for r in page], meta, 200)


@bp.route("/va/escalations/<escalation_id>/resolve", methods=["POST"])
def resolve_escalation(escalation_id):
    _, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    rec = find_or_404(db.escalations, escalation_id)
    # QUEUED or ASSIGNED -> RESOLVED (PRD §3.6).
    if rec["status"] not in ("QUEUED", "ASSIGNED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Escalation is not QUEUED or ASSIGNED")
    rec["status"] = "RESOLVED"
    touch(rec)
    return success_object(serializers.escalation(public(rec)), 200)
