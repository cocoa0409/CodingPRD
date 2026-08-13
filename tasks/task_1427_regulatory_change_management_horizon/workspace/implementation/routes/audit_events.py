"""Audit trail browsing and chain verification (PRD §2.9)."""

from flask import Blueprint, request

from db import store
from middleware import auth_context, require_roles
from response import paginate, success_object
from serializers import audit_event_to_api
from services.audit import verify_chain

bp = Blueprint("audit_events", __name__)


@bp.get("/compliance/audit-events")
def list_audit_events():
    auth_context()
    # Replay order: sequence_number ASC (append order).
    items = sorted(store.audit_events, key=lambda e: e["sequence_number"])
    for param in ("entity_type", "entity_id", "actor_user_id"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    return paginate(items, audit_event_to_api)


@bp.get("/compliance/audit-events/verify")
def verify_audit_events():
    _, role = auth_context()
    require_roles(role, ("PlatformAdmin",))
    chain_valid, events_checked = verify_chain()
    return success_object({
        "chain_valid": chain_valid,
        "events_checked": events_checked,
    })
