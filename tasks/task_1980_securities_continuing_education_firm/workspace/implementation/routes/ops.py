"""Ops surface: enforcement sweep, logical clock, audit evidence log."""

from flask import Blueprint, request

from db import store, clock_set
from middleware import require_roles, json_body, require_fields
from response import success, paginate
from services import by_seq, run_sweep
from util import parse_dt, fmt_dt, view

bp = Blueprint("ops", __name__)


@bp.post("/enforcement/sweep")
@require_roles("ComplianceOfficer")
def enforcement_sweep():
    counts = run_sweep()
    return success(counts)


@bp.post("/_clock/set_current_utc")
@require_roles("ComplianceOfficer")
def set_clock():
    body = json_body()
    require_fields(body, "to_iso8601")
    new_now = parse_dt(body["to_iso8601"], "to_iso8601")
    clock_set(new_now)
    return success({"current_utc": fmt_dt(new_now)})


@bp.get("/audit-events")
@require_roles("Auditor", "ComplianceOfficer")
def list_audit_events():
    items = by_seq(store.audit_events.values())
    for param in ("entity_type", "entity_id", "event_type"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page, pagination = paginate(items)
    return success([view(e) for e in page], is_list=True, pagination=pagination)
