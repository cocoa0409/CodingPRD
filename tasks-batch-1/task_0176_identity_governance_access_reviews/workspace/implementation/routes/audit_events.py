"""Audit evidence routes (PRD §3.9).

Append-only, immutable records (id + created_at only). Read as a global
filterable collection or scoped to a subject identity (see identities).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role
from response import object_response, array_response
from services.common import (
    serialize, parse_pagination, paginate, filter_enum_param,
)

bp = Blueprint("audit_events", __name__)

READ_ROLES = {"AccessManager", "AccessApprover", "CampaignAdmin", "Certifier"}
EVENT_TYPES = {
    "GRANT_ACTIVATED", "GRANT_REVOKED", "REQUEST_APPROVED", "REQUEST_REJECTED",
    "IDENTITY_DISABLED", "ITEM_CERTIFIED", "ORPHAN_DETECTED",
}


@bp.route("/audit-events/<id>", methods=["GET"])
def get_audit_event(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.audit_events.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Audit event not found")
        return object_response(serialize(record), 200)


@bp.route("/audit-events", methods=["GET"])
def list_audit_events():
    require_role(READ_ROLES)
    subject_identity_id = request.args.get("subject_identity_id")
    event_type = filter_enum_param(request.args, "event_type", EVENT_TYPES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.audit_events.values())
        if subject_identity_id is not None:
            records = [a for a in records
                       if a["subject_identity_id"] == subject_identity_id]
        if event_type is not None:
            records = [a for a in records if a["event_type"] == event_type]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
