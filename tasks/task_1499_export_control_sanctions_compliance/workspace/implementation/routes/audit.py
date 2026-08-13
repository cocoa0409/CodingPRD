"""Audit record listing (recordkeeping query) and retention purge."""

from flask import Blueprint, request

import db
from middleware import auth, page_params, filtered_sorted
from response import ok, list_response
from services.audit import purge_expired

bp = Blueprint("audit", __name__)


@bp.get("/compliance/audit-records")
def list_audit_records():
    auth()
    filters = {
        "entity_type": request.args.get("entity_type"),
        "entity_id": request.args.get("entity_id"),
        "event_type": request.args.get("event_type"),
    }
    items = filtered_sorted(db.AUDIT_RECORDS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/audit-records/purge")
def purge_audit_records():
    auth("ComplianceDirector")
    purged = purge_expired()
    return ok({"purged_count": purged}, "object", 200)
