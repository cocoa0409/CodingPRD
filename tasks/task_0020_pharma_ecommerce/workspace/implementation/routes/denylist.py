"""Prescriber denylist — append-only entries."""

from __future__ import annotations

from flask import Blueprint, request

from db import db, filter_by_platform, new_id, order_by_seq, platform_clock, serialize, serialize_list
from lookups import get_platform
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from validate import require_field, require_json

bp = Blueprint("denylist", __name__)


@bp.post("/pharma-platforms/<pid>/prescriber-denylist")
@require_roles("PlatformAdmin", "RegulatoryGateway")
def add_entry(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    license_no = require_field(body, "prescriber_license_no", kind=str)
    reason = require_field(body, "reason", kind=str)
    row = {
        "id": new_id(),
        "platform_id": pid,
        "prescriber_license_no": license_no,
        "reason": reason,
        "created_at": platform_clock(platform),
        "_seq": db.next_seq(),
    }
    db.prescriber_denylist[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/prescriber-denylist")
@require_roles("PlatformAdmin", "PrescriptionReviewer", "RegulatoryGateway")
def list_entries(pid: str):
    get_platform(pid)
    rows = order_by_seq(filter_by_platform(db.prescriber_denylist, pid))
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200
