"""Append-only audit log read endpoints (list, get)."""

from flask import Blueprint, request

from errors import err
from db import db
from middleware import require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
import serializers

bp = Blueprint("audit_entries", __name__)


@bp.route("/audit-entries", methods=["GET"])
def list_audit_entries():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.audit_entries)
    onboarding_id = request.args.get("onboarding_id")
    if onboarding_id is not None:
        records = [r for r in records if r.get("onboarding_id") == onboarding_id]
    return paginate_and_respond(records, limit, offset, serializers.audit_entry)


@bp.route("/audit-entries/<entry_id>", methods=["GET"])
def get_audit_entry(entry_id):
    require_read_role()
    entry = db.audit_entries.get(entry_id)
    if entry is None:
        raise err("ERR_NOT_FOUND", "AuditEntry not found")
    return object_response(serializers.audit_entry(entry))
