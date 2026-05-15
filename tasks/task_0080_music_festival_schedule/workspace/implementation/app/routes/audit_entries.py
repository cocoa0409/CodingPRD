"""Audit-entries read endpoint per PRD §3.7."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ApiError,
    DB,
    GLOBAL_LOCK,
    list_audit_for_festival,
    make_blueprint,
    paginate_list,
    require_audit_log_allowlist,
    resolve_festival,
    success_envelope,
)


bp = make_blueprint("audit_entries")


def _payload(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "festival_id": r.get("festival_id"),
        "actor_user_id": r.get("actor_user_id"),
        "actor_role": r.get("actor_role"),
        "event_category": r.get("event_category"),
        "subject_entity_type": r.get("subject_entity_type"),
        "subject_entity_id": r.get("subject_entity_id"),
        "from_state": r.get("from_state"),
        "to_state": r.get("to_state"),
        "payload_summary": r.get("payload_summary"),
        "created_at": r.get("created_at"),
    }


@bp.route("/festivals/<festival_id>/audit-entries", methods=["GET"])
def list_audit(festival_id: str):
    # The §2.1 audit-log allowlist is the finer-grained gate that
    # supersedes the standard role-permission check.  Per §1.4
    # priority 26, this error_id is the bespoke ERR_AUDIT_LOG_FORBIDDEN.
    require_audit_log_allowlist()
    with GLOBAL_LOCK:
        resolve_festival(festival_id)
        cat_f = request.args.get("event_category")
        subj_f = request.args.get("subject_entity_type")
        after_f = request.args.get("created_at_after")
        rows = list_audit_for_festival(
            festival_id,
            event_category=cat_f,
            subject_entity_type=subj_f,
            created_at_after=after_f,
        )
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
