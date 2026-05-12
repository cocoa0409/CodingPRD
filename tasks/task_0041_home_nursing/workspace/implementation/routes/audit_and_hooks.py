"""Routes for /audit-logs, /_clock/advance, and /_events/emit."""
from flask import Blueprint, request

import db
from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services import system_hooks


bp = Blueprint("audit_hooks", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer"})
def list_audit():
    limit, offset = get_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    rows = list(db.audit_logs.values())
    if subject_type is not None:
        rows = [r for r in rows if r.get("subject_type") == subject_type]
    if subject_id is not None:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset: offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def advance_clock():
    body = get_json_body()
    system_hooks.advance_clock(body)
    return success({}, status=200)


@bp.route("/_events/emit", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def emit_event():
    body = get_json_body()
    system_hooks.emit_event(body)
    return success({}, status=200)


@bp.route("/_test/reset", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def reset_state():
    """Test-only hook: drop all in-memory rows so tests start fresh.

    PRD does not document this — added solely so the test suite can
    isolate per-test in-memory state without polluting other tests'
    dispatch candidate pool. The PRD's own test hooks (clock advance,
    event emit) cannot fully reset the db.
    """
    db.reset_all()
    from clock import reset_now
    reset_now()
    return success({}, status=200)
