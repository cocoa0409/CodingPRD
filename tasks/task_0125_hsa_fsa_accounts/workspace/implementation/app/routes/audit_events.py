"""AuditEvent retrieval endpoint."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..errors import ApiError
from ..helpers import serialize_audit_event
from ..responses import build_list_envelope, paginate, parse_pagination
from ..services.audit import reconcile_plan_year
from ..store import store


bp = Blueprint("audit_events", __name__)


@bp.route("/accounts/<account_id>/audit-events", methods=["GET"])
@require_auth(["Auditor", "PlanAdministrator"])
def list_audit_events(account_id: str):
    a = store.accounts.get(account_id)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Account not found.")

    limit, offset = parse_pagination()
    f_plan_year = request.args.get("plan_year_id")
    f_event_type = request.args.get("event_type")

    rows = [e for e in store.audit_events if e.get("account_id") == a["id"]]
    if f_plan_year is not None:
        rows = [r for r in rows if r.get("plan_year_id") == f_plan_year]
    if f_event_type is not None:
        rows = [r for r in rows if r["event_type"] == f_event_type]

    # Reconciliation invariant — compute over plan years in scope of this query.
    plan_year_ids = set()
    if f_plan_year is not None:
        plan_year_ids.add(f_plan_year)
    else:
        for e in store.audit_events:
            if e.get("account_id") == a["id"] and e.get("plan_year_id"):
                plan_year_ids.add(e["plan_year_id"])

    for pid in plan_year_ids:
        if pid not in store.plan_years:
            continue
        if not reconcile_plan_year(pid):
            raise ApiError(
                "ERR_AUDIT_TRAIL_INCONSISTENT",
                "Audit-trail ledger does not reconcile against plan-year counters.",
            )

    # Sort by (occurred_at, id) ascending — append order per PRD §2.3.
    rows.sort(key=lambda r: (r["occurred_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return jsonify(build_list_envelope(
        [serialize_audit_event(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
