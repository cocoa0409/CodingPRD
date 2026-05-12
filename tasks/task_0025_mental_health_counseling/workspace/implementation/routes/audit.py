"""Audit log endpoint."""
from flask import Blueprint, g, request

import db
from clock import parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_log", __name__)


def _public(e: dict) -> dict:
    return db.public(e)


@bp.route("/counseling/audit-log", methods=["GET"])
@require_auth(roles={"PlatformAdmin"})
def list_audit():
    limit, offset = get_pagination()
    action = request.args.get("action")
    target_entity = request.args.get("target_entity")
    actor_role = request.args.get("actor_role")
    from_s = request.args.get("from")
    to_s = request.args.get("to")

    items = list(db.audit_log.values())
    if action:
        items = [e for e in items if e["action"] == action]
    if target_entity:
        items = [e for e in items if e["target_entity"] == target_entity]
    if actor_role:
        items = [e for e in items if e["actor_role"] == actor_role]
    if from_s:
        try:
            from_dt = parse_iso(from_s)
        except ValueError:
            raise err("ERR_VALIDATION", "from must be ISO 8601")
        items = [e for e in items if parse_iso(e["created_at"]) >= from_dt]
    if to_s:
        try:
            to_dt = parse_iso(to_s)
        except ValueError:
            raise err("ERR_VALIDATION", "to must be ISO 8601")
        items = [e for e in items if parse_iso(e["created_at"]) < to_dt]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(e) for e in page], limit, offset, total)
