"""Compliance report endpoints."""

from flask import Blueprint, request

from clock import clock, parse_iso8601
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response
from serializers import compliance_report as ser_cr
from validators import require_dict, require_enum, require_iso


bp = Blueprint("compliance_reports", __name__)


DOMAINS = {"FOOD", "PHARMACEUTICAL", "BIOLOGICAL"}


def _bump(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


@bp.post("/compliance-reports")
@require_roles("COMPLIANCE_OFFICER")
def create_report():
    body = require_dict(request.get_json(silent=True) or {})
    domain = require_enum(body.get("regulatory_domain"), DOMAINS, field="regulatory_domain")
    require_iso(body.get("period_start"), field="period_start")
    require_iso(body.get("period_end"), field="period_end")
    ps = parse_iso8601(body["period_start"])
    pe = parse_iso8601(body["period_end"])
    if not (pe > ps):
        err("ERR_VALIDATION", "period_end must be > period_start.")
    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "regulatory_domain": domain,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "task_count": 0,
        "alert_count": 0,
        "critical_alert_count": 0,
        "status": "DRAFT",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.reports.put(row)
    return object_response(ser_cr(row), status_code=201)


@bp.post("/compliance-reports/<report_id>/generate")
@require_roles("COMPLIANCE_OFFICER")
def generate(report_id):
    row = db.reports.get(report_id)
    if row is None:
        err("ERR_NOT_FOUND", "ComplianceReport not found.")
    if row["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Report must be DRAFT to generate.")
    ps = parse_iso8601(row["period_start"])
    pe = parse_iso8601(row["period_end"])
    # in-period tasks of matching cargo_type
    tasks_in_period = []
    for t in db.tasks.all():
        if t["cargo_type"] != row["regulatory_domain"]:
            continue
        planned = parse_iso8601(t["planned_start_at"])
        if planned >= ps and planned < pe:
            tasks_in_period.append(t)
    task_ids = {t["id"] for t in tasks_in_period}
    alerts_in_period = []
    for a in db.alerts.all():
        if a["task_id"] not in task_ids:
            continue
        opened = parse_iso8601(a["opened_at"])
        if opened is None:
            continue
        if opened >= ps and opened < pe:
            alerts_in_period.append(a)
    critical_count = sum(1 for a in alerts_in_period if a["level"] == "CRITICAL")
    row["task_count"] = len(tasks_in_period)
    row["alert_count"] = len(alerts_in_period)
    row["critical_alert_count"] = critical_count
    row["status"] = "GENERATED"
    _bump(row)
    return object_response(ser_cr(row))


@bp.post("/compliance-reports/<report_id>/submit")
@require_roles("COMPLIANCE_OFFICER")
def submit(report_id):
    row = db.reports.get(report_id)
    if row is None:
        err("ERR_NOT_FOUND", "ComplianceReport not found.")
    if row["status"] != "GENERATED":
        err("ERR_INVALID_STATE", "Report must be GENERATED to submit.")
    row["status"] = "SUBMITTED"
    _bump(row)
    return object_response(ser_cr(row))


@bp.post("/compliance-reports/<report_id>/acknowledge")
@require_roles("COMPLIANCE_OFFICER")
def acknowledge(report_id):
    row = db.reports.get(report_id)
    if row is None:
        err("ERR_NOT_FOUND", "ComplianceReport not found.")
    if row["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Report must be SUBMITTED to acknowledge.")
    row["status"] = "ACKNOWLEDGED"
    _bump(row)
    return object_response(ser_cr(row))


@bp.get("/compliance-reports/<report_id>")
@require_roles("COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def get_report(report_id):
    row = db.reports.get(report_id)
    if row is None:
        err("ERR_NOT_FOUND", "ComplianceReport not found.")
    return object_response(ser_cr(row))
