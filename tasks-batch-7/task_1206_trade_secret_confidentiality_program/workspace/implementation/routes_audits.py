"""CleanDeskAudit routes (PRD §3.9)."""

from flask import Blueprint, request
from datetime import timedelta

from db import (
    all_rows,
    by_id,
    created_asc,
    fmt_ts,
    new_record,
    parse_dt,
    serialize,
    touch,
)
from errors import (
    err_audit_window_conflict,
    err_date_order,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import actor, body, require_field, require_roles, require_str
from response import ok_list, ok_object, paginate
from services import AUDIT_BUFFER_DAYS, lapse_measure
from db import db

bp = Blueprint("audits", __name__)

AUDIT_STATUSES = ("SCHEDULED", "CONDUCTED", "REPORTED", "REMEDIATING", "CLOSED", "CANCELLED")
AUDIT_NON_TERMINAL = ("SCHEDULED", "CONDUCTED", "REPORTED", "REMEDIATING")


@bp.post("/api/clean-desk-audits")
def create_audit():
    _uid, role = actor()
    require_roles(role, "SecurityOfficer")
    data = body()
    department = require_str(data, "department")
    start_raw = require_field(data, "window_start")
    end_raw = require_field(data, "window_end")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise err_invalid_request("window_start / window_end must be ISO 8601 timestamps")
    if end_dt <= start_dt:
        raise err_date_order("window_end must be strictly after window_start")
    # Temporal buffer: the department's non-terminal audits require a 7-day
    # buffer; windows expanded by the buffer must not overlap (PRD §3.9).
    buf = timedelta(days=AUDIT_BUFFER_DAYS)
    for other in all_rows("clean_desk_audits"):
        if other["department"] != department:
            continue
        if other["status"] not in AUDIT_NON_TERMINAL:
            continue
        if start_dt < other["_window_end_dt"] + buf and other["_window_start_dt"] < end_dt + buf:
            raise err_audit_window_conflict()
    rec = new_record(
        "clean_desk_audits",
        {
            "department": department,
            "window_start": start_raw if isinstance(start_raw, str) else fmt_ts(start_dt),
            "window_end": end_raw if isinstance(end_raw, str) else fmt_ts(end_dt),
            "_window_start_dt": start_dt,
            "_window_end_dt": end_dt,
            "findings_count": None,
            "critical_findings": None,
            "resolved_critical_count": None,
            "status": "SCHEDULED",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/clean-desk-audits")
def list_audits():
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    filters = [(f, request.args[f]) for f in ("department", "status") if f in request.args]
    rows = []
    for r in created_asc(all_rows("clean_desk_audits")):
        if all(r.get(k) == v for k, v in filters):
            rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


@bp.get("/api/clean-desk-audits/<rid>")
def get_audit(rid):
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    a = by_id("clean_desk_audits", rid)
    if a is None:
        raise err_not_found("clean-desk audit not found")
    return ok_object(serialize(a))


@bp.post("/api/clean-desk-audits/<rid>/state")
def audit_state(rid):
    _uid, role = actor()
    require_roles(role, "SecurityOfficer")
    a = by_id("clean_desk_audits", rid)
    if a is None:
        raise err_not_found("clean-desk audit not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in AUDIT_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(AUDIT_STATUSES)}")
    cur = a["status"]

    if to_status == "CONDUCTED":
        if cur != "SCHEDULED":
            raise err_invalid_state(f"Cannot move audit from {cur} to CONDUCTED")
        findings = data.get("findings_count")
        critical = data.get("critical_findings")
        if (
            not isinstance(findings, int)
            or isinstance(findings, bool)
            or not isinstance(critical, int)
            or isinstance(critical, bool)
        ):
            raise err_invalid_request("findings_count and critical_findings must be integers")
        if not (findings >= critical >= 0):
            raise err_invalid_request("findings_count >= critical_findings >= 0 required")
        a["findings_count"] = findings
        a["critical_findings"] = critical
        a["status"] = "CONDUCTED"
        touch(a)
        # Critical findings lapse the linked measures (created_at ASC); each
        # lapse recomputes its asset's posture, and a drop to DEFICIENT returns
        # that asset's UNDER_REVIEW disclosures (§3.9).
        if critical > 0:
            linked = data.get("linked_measure_ids") or []
            if not isinstance(linked, list):
                raise err_invalid_request("linked_measure_ids must be an array")
            targets = created_asc(
                [
                    m
                    for m in all_rows("measures")
                    if m["id"] in linked and m["status"] in ("IMPLEMENTED", "VERIFIED")
                ]
            )
            for m in targets:
                lapse_measure(m)
    elif to_status == "REPORTED":
        if cur != "CONDUCTED":
            raise err_invalid_state(f"Cannot move audit from {cur} to REPORTED")
        a["status"] = "REPORTED"
        touch(a)
    elif to_status == "REMEDIATING":
        if cur != "REPORTED":
            raise err_invalid_state(f"Cannot move audit from {cur} to REMEDIATING")
        if not (a["critical_findings"] or 0) > 0:
            raise err_invalid_state("Non-critical audits close directly")
        a["status"] = "REMEDIATING"
        touch(a)
    elif to_status == "CLOSED":
        if cur == "REPORTED":
            if (a["critical_findings"] or 0) != 0:
                raise err_invalid_state("Critical findings require remediation")
            a["status"] = "CLOSED"
            touch(a)
        elif cur == "REMEDIATING":
            resolved = data.get("resolved_critical_count")
            if not isinstance(resolved, int) or isinstance(resolved, bool):
                raise err_invalid_request("resolved_critical_count must be an integer")
            if resolved != a["critical_findings"]:
                raise err_invalid_state("resolved_critical_count must equal critical_findings")
            a["resolved_critical_count"] = resolved
            a["status"] = "CLOSED"
            touch(a)
        else:
            raise err_invalid_state(f"Cannot move audit from {cur} to CLOSED")
    elif to_status == "CANCELLED":
        if cur != "SCHEDULED":
            raise err_invalid_state(f"Cannot move audit from {cur} to CANCELLED")
        a["status"] = "CANCELLED"
        touch(a)
    return ok_object(serialize(a))
