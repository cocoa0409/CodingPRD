"""ComplianceItem endpoints & remediation state machine (PRD §3.9)."""

import hashlib
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404
from util import body, require_enum, require_iso_date, require_str, pagination, paginate

bp = Blueprint("compliance", __name__)

READ_ROLES = {"ComplianceOfficer", "Advisor", "BillingAdmin"}
SUBJECT_TYPES = {"CLIENT", "ACCOUNT", "HOUSEHOLD"}
OBLIGATION_TYPES = {"REG_BI_DISCLOSURE", "FORM_ADV_DELIVERY", "IPS_ARCHIVE", "FEE_DISCLOSURE"}
ACTIONS = {"SATISFY", "FLAG_REMEDIATION", "REOPEN", "ARCHIVE"}


def serialize(c):
    return {
        "id": c["id"],
        "subject_type": c["subject_type"],
        "subject_id": c["subject_id"],
        "obligation_type": c["obligation_type"],
        "due_date": c["due_date"],
        "archive_hash": c["archive_hash"],
        "remediation_round": c["remediation_round"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def make_item(subject_type, subject_id, obligation_type, due_date):
    """Create a compliance item (system-spawned or manual). status=OPEN."""
    c = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "obligation_type": obligation_type,
        "due_date": due_date,
        "archive_hash": None,
        "remediation_round": 0,
        "status": "OPEN",
    }
    stamp_new(c)
    db.compliance_items[c["id"]] = c
    return c


@bp.route("/compliance-items", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    data = body()
    subject_type = require_enum(data, "subject_type", SUBJECT_TYPES)
    subject_id = require_str(data, "subject_id")
    obligation_type = require_enum(data, "obligation_type", OBLIGATION_TYPES)
    due_date = require_iso_date(data, "due_date")
    c = make_item(subject_type, subject_id, obligation_type, due_date)
    return created(serialize(c))


@bp.route("/compliance-items/<cid>", methods=["GET"])
def read(cid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    c = get_or_404(db.compliance_items, cid)
    return ok(serialize(c))


@bp.route("/compliance-items", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    subject_id = request.args.get("subject_id")
    status = request.args.get("status")
    items = list(db.compliance_items.values())
    if subject_id is not None:
        items = [x for x in items if x["subject_id"] == subject_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/compliance-items/<cid>/state", methods=["POST"])
def state(cid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    c = get_or_404(db.compliance_items, cid)
    data = body()
    action = require_enum(data, "action", ACTIONS)
    from datetime import date as _date
    today = db.clock_date()

    if action == "SATISFY":
        if c["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "SATISFY requires OPEN")
        due = _date.fromisoformat(c["due_date"]) if c["due_date"] else None
        if due is not None and today > due:
            raise err("ERR_COMPLIANCE_NOT_DUE", "Cannot satisfy a lapsed obligation")
        c["status"] = "SATISFIED"

    elif action == "FLAG_REMEDIATION":
        if c["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "FLAG_REMEDIATION requires OPEN")
        due = _date.fromisoformat(c["due_date"]) if c["due_date"] else None
        if due is None or today <= due:
            raise err("ERR_COMPLIANCE_NOT_DUE", "Only an overdue item may enter remediation")
        c["status"] = "REMEDIATION"

    elif action == "REOPEN":
        if c["status"] != "REMEDIATION":
            raise err("ERR_INVALID_STATE", "REOPEN requires REMEDIATION")
        c["remediation_round"] += 1
        new_due = today + timedelta(days=30)
        c["due_date"] = new_due.isoformat()
        c["status"] = "OPEN"

    elif action == "ARCHIVE":
        if c["status"] != "SATISFIED":
            raise err("ERR_INVALID_STATE", "ARCHIVE requires SATISFIED")
        raw = "|".join([
            str(c["subject_type"]), str(c["subject_id"]),
            str(c["obligation_type"]), str(c["created_at"]),
        ])
        c["archive_hash"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        c["status"] = "ARCHIVED"

    touch(c)
    return ok(serialize(c))
