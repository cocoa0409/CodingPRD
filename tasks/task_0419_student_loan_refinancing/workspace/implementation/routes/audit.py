"""Audit-event listing (PRD §3.12).

Append-only records read back filtered by subject_type and subject_id.
"""
from flask import Blueprint, request

import db
import serialize
from auth import authorize
from response import array_response
from store_helpers import sorted_by_created, paginate
from validate import parse_pagination

bp = Blueprint("audit", __name__)


@bp.route("/audit-events", methods=["GET"])
def list_audit_events():
    authorize(("GET", "/audit-events"))
    limit, offset = parse_pagination()
    f_subject_type = request.args.get("subject_type")
    f_subject_id = request.args.get("subject_id")
    records = list(db.audit_events)
    if f_subject_type is not None:
        records = [r for r in records if r["subject_type"] == f_subject_type]
    if f_subject_id is not None:
        records = [r for r in records if r["subject_id"] == f_subject_id]
    records = sorted_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serialize.audit_event(r) for r in page], limit, offset, total)
