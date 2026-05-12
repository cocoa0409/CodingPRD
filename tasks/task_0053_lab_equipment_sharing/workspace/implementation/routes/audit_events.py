"""Audit event listing."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_events", __name__)


@bp.get("/audit-events")
@require_auth(roles={"PlatformAdmin", "LabOwner"})
def list_audit_events():
    limit, offset = get_pagination()
    subject_type_f = request.args.get("subject_type")
    subject_id_f = request.args.get("subject_id")
    actor_user_id_f = request.args.get("actor_user_id")
    items = []
    for ev in db.audit_events.values():
        if subject_type_f and ev["subject_type"] != subject_type_f:
            continue
        if subject_id_f and ev["subject_id"] != subject_id_f:
            continue
        if actor_user_id_f and ev["actor_user_id"] != actor_user_id_f:
            continue
        items.append(ev)
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([db.public(x) for x in page], limit, offset, total)
