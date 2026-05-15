"""Audit routes: list audit events, run-internal sweep, respond-external."""

from flask import Blueprint, request, g

from db import DB, new_id, LOCK
from errors import ERR_VALIDATION, raise_error
from middleware import auth_required
from response import success_response, list_response
from services.common import get_json_body, require_fields, parse_pagination, paginate
from services.serializers import serialize_audit_event
from services.time_util import now_iso, now_dt
from services.audit import emit_audit

bp = Blueprint("audit", __name__)


@bp.get("/audit-events")
@auth_required(["LabManager"])
def list_audit_events():
    limit, offset = parse_pagination()
    rows = list(DB["audit_events"])
    event_type = request.args.get("event_type")
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    if subject_type:
        rows = [r for r in rows if r.get("subject_type") == subject_type]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize_audit_event(r) for r in page], total, limit, offset)


@bp.post("/_audit/run-internal")
@auth_required(["LabManager"])
def run_internal_audit():
    today_key = now_dt().strftime("%Y-%m-%d")
    with LOCK:
        # Idempotent within UTC date
        if today_key in DB["internal_audit_dates"]:
            # Return the previously-emitted event for today (no duplicate emit)
            for e in reversed(DB["audit_events"]):
                if e.get("event_type") == "INTERNAL_AUDIT_RUN":
                    if e.get("payload", {}).get("date") == today_key:
                        return success_response(serialize_audit_event(e), 200)
        DB["internal_audit_dates"].add(today_key)
        stats = {
            "date": today_key,
            "samples": len(DB["samples"]),
            "tasks": len(DB["tasks"]),
            "instruments": len(DB["instruments"]),
            "reports_issued": sum(1 for r in DB["reports"].values() if r.get("status") == "ISSUED"),
            "reports_archived": sum(1 for r in DB["reports"].values() if r.get("status") == "ARCHIVED"),
        }
        evt = emit_audit(
            "INTERNAL_AUDIT_RUN", "Lab", "lab",
            g.user_role, g.user_id, stats,
        )
    return success_response(serialize_audit_event(evt), 200)


@bp.post("/_audit/respond-external")
@auth_required(["LabManager"])
def respond_external():
    body = get_json_body()
    require_fields(body, ["inspection_id", "response_note"])
    inspection_id = body["inspection_id"]
    response_note = body["response_note"]
    if not isinstance(inspection_id, str) or not inspection_id:
        raise_error(ERR_VALIDATION, "inspection_id required")
    if not isinstance(response_note, str):
        raise_error(ERR_VALIDATION, "response_note required")
    with LOCK:
        evt = emit_audit(
            "EXTERNAL_INSPECTION_RESPONDED", "Inspection", inspection_id,
            g.user_role, g.user_id,
            {"inspection_id": inspection_id, "response_note": response_note},
        )
    return success_response(serialize_audit_event(evt), 200)
