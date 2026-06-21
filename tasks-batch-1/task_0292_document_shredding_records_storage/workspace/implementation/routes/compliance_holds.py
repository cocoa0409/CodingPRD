"""ComplianceHold endpoints (PRD §3.10)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, require_enum, as_str,
    get_account_or_404, get_hold_or_404,
)

bp = Blueprint("compliance_holds", __name__)

SUBJECT_TYPES = {"RETENTION_BOX", "SERVICE_ORDER"}
REASONS = {"LITIGATION_HOLD", "AUDIT_HOLD", "REGULATORY_FREEZE"}


@bp.post("/compliance-holds")
def create_hold():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    require_present(data, "account_id", "subject_type", "subject_id", "reason")
    account_id = as_str(data["account_id"], "account_id")
    get_account_or_404(account_id)
    require_enum(data["subject_type"], SUBJECT_TYPES, "subject_type")
    subject_type = data["subject_type"]
    subject_id = as_str(data["subject_id"], "subject_id")
    require_enum(data["reason"], REASONS, "reason")

    # Polymorphic subject must resolve under its subject_type (PRD §2.6).
    if subject_type == "RETENTION_BOX":
        if subject_id not in db.retention_boxes:
            raise err("ERR_NOT_FOUND", "Subject box not found")
    else:  # SERVICE_ORDER
        if subject_id not in db.service_orders:
            raise err("ERR_NOT_FOUND", "Subject order not found")

    hold = {
        "account_id": account_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": data["reason"],
        "status": "ACTIVE",
    }
    stamp_create(hold)
    db.compliance_holds[hold["id"]] = hold
    return object_response(serialize(hold), 201)


@bp.get("/compliance-holds/<hold_id>")
def get_hold(hold_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer", "AccountManager"})
    h = get_hold_or_404(hold_id)
    return object_response(serialize(h), 200)


@bp.get("/compliance-holds")
def list_holds():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer", "AccountManager"})
    items = list(db.compliance_holds.values())
    account_id = request.args.get("account_id")
    subject_id = request.args.get("subject_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [h for h in items if h["account_id"] == account_id]
    if subject_id is not None:
        items = [h for h in items if h["subject_id"] == subject_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(h) for h in page], limit, offset, total, 200)


@bp.post("/compliance-holds/<hold_id>/release")
def release_hold(hold_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    h = get_hold_or_404(hold_id)
    if h["status"] != "ACTIVE":
        raise err("ERR_HOLD_NOT_ACTIVE", "Hold is not ACTIVE")
    h["status"] = "RELEASED"
    touch(h)
    return object_response(serialize(h), 200)
