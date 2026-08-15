"""Audit trail read endpoints."""
from flask import Blueprint, request

from db import store
from middleware import authenticate, pagination_params
from response import ok, ok_list
from serializers import serialize_audit_event
from services.audit import verify_chain

bp = Blueprint("audit", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]


@bp.get("/audit-events/verify-chain")
def verify_audit_chain():
    authenticate(["SystemAdmin", "BSAOfficer", "Examiner"])
    chain_valid, events_checked = verify_chain()
    return ok({"chain_valid": chain_valid, "events_checked": events_checked})


@bp.get("/audit-events")
def list_audit_events():
    authenticate(ALL_ROLES)
    items = list(store.audit_events)
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    actor_id = request.args.get("actor_id")
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]
    if actor_id is not None:
        items = [e for e in items if e["actor_id"] == actor_id]
    # Append-only ledger: creation order is sequence_no order (equivalent to
    # created_at ASC under a forward-moving logical clock, and still correct
    # if a test drives the clock backward).
    items.sort(key=lambda e: e["sequence_no"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serialize_audit_event(e) for e in page], limit, offset, total)
