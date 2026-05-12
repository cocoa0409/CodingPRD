"""AuditLog read-only endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db
from middleware import require_roles
from response import list_response
from services.common import paginate, parse_iso8601_utc, parse_pagination
from services.lookup import get_community

bp = Blueprint("audit_logs", __name__)


@bp.get("/communities/<community_id>/audit-logs")
@require_roles("CommunityAdmin")
def list_audit_logs(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    action = request.args.get("action")
    subject_kind = request.args.get("subject_kind")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    from_utc = parse_iso8601_utc(from_raw) if from_raw else None
    to_utc = parse_iso8601_utc(to_raw) if to_raw else None

    # AuditLog entries are global; filter by checking subject linkage in this community.
    items = []
    for entry in db.audit_logs.values():
        # Filter by subject's community where possible
        sk = entry.get("subject_kind")
        sid = entry.get("subject_id")
        belongs = False
        if sk == "DISPOSAL":
            d = db.disposals.get(sid)
            belongs = bool(d and d.get("community_id") == community_id)
        elif sk == "VIOLATION":
            v = db.violations.get(sid)
            belongs = bool(v and v.get("community_id") == community_id)
        elif sk == "POINT_RULE":
            r = db.point_rules.get(sid)
            belongs = bool(r and r.get("community_id") == community_id)
        elif sk == "RANKING_PERIOD":
            p = db.ranking_periods.get(sid)
            belongs = bool(p and p.get("community_id") == community_id)
        elif sk == "HOUSEHOLD":
            h = db.households.get(sid)
            belongs = bool(h and h.get("community_id") == community_id)
        if not belongs:
            continue
        if action is not None and entry["action"] != action:
            continue
        if subject_kind is not None and entry["subject_kind"] != subject_kind:
            continue
        t = parse_iso8601_utc(entry["created_at"])
        if from_utc is not None and t < from_utc:
            continue
        if to_utc is not None and t >= to_utc:
            continue
        items.append(entry)
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
