"""Committee reports: draft, finalize (frozen metrics), present (PRD §3.9)."""

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_INVALID_REPORT_PERIOD,
                    ERR_REPORT_PERIOD_OVERLAP, invalid_state)
from middleware import (auth_context, get_body, get_or_404, req_dt, req_enum,
                        require_roles)
from response import paginate, success_object
from serializers import created_sorted, report_to_api
from services.audit import append_audit
from services.calculations import compliance_index, sla_compliance_pct

bp = Blueprint("committee_reports", __name__)

COMMITTEES = ("BOARD_RISK_COMMITTEE", "AUDIT_COMMITTEE",
              "EXECUTIVE_COMPLIANCE_COMMITTEE")


@bp.post("/compliance/committee-reports")
def create_report():
    user_id, role = auth_context()
    require_roles(role, ("BoardSecretary",))
    body = get_body()
    committee_name = req_enum(body, "committee_name", COMMITTEES)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")

    # Priority 6: end strictly after start.
    if not period_end > period_start:
        raise ApiError(ERR_INVALID_REPORT_PERIOD, 422,
                       "period_end <= period_start")

    # Priority 7: half-open [start, end) windows of the same committee never
    # overlap; adjacency (start == other end) is allowed.
    for other in store.reports.values():
        if other["committee_name"] != committee_name:
            continue
        if other["period_start"] < period_end and period_start < other["period_end"]:
            raise ApiError(ERR_REPORT_PERIOD_OVERLAP, 409,
                           "Report window overlaps an existing report of the "
                           "same committee")

    report = stamp_new({
        "id": new_id(),
        "committee_name": committee_name,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "metrics": None,
        "finalized_at": None,
    })
    store.reports[report["id"]] = report
    append_audit(user_id, role, "POST /compliance/committee-reports",
                 "CommitteeReport", report["id"])
    return success_object(report_to_api(report), status=201)


@bp.get("/compliance/committee-reports")
def list_reports():
    auth_context()
    items = created_sorted(store.reports.values())
    for param in ("committee_name", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    return paginate(items, report_to_api)


@bp.get("/compliance/committee-reports/<report_id>")
def get_report(report_id):
    auth_context()
    report = get_or_404(store.reports, report_id, "committee report")
    return success_object(report_to_api(report))


def _compute_metrics(report):
    """Five-key snapshot at the finalize clock (PRD §3.9)."""
    c1 = sum(
        1 for p in store.plans.values()
        if p["execution_status"] != "VERIFIED" and p["deadline_posture"] == "OVERDUE")
    c2 = sum(
        1 for c in store.regulatory_changes.values()
        if c["status"] == "PENDING_TRIAGE" and c["created_at"] < report["period_end"])
    c3 = sum(
        1 for e in store.escalations.values()
        if e["status"] in ("OPEN", "ACKNOWLEDGED"))
    index = compliance_index(c1, c2, c3)

    start, end = report["period_start"], report["period_end"]
    in_window = [
        a for a in store.assessments.values()
        if a["submitted_at"] is not None and start <= a["submitted_at"] < end
    ]
    on_time = sum(1 for a in in_window if not a["sla_breached"])
    sla = sla_compliance_pct(on_time, len(in_window))

    return {
        "overdue_plan_count": c1,
        "pending_triage_count": c2,
        "open_escalation_count": c3,
        "compliance_index": float(index),
        "sla_compliance_pct": float(sla),
    }


@bp.post("/compliance/committee-reports/<report_id>/finalize")
def finalize_report(report_id):
    user_id, role = auth_context()
    require_roles(role, ("BoardSecretary",))
    report = get_or_404(store.reports, report_id, "committee report")
    if report["status"] != "DRAFT":
        raise invalid_state("finalize requires status DRAFT")
    report["metrics"] = _compute_metrics(report)
    report["finalized_at"] = now_clock()
    report["status"] = "FINALIZED"
    touch(report)
    append_audit(user_id, role, "POST /compliance/committee-reports/{id}/finalize",
                 "CommitteeReport", report["id"])
    return success_object(report_to_api(report))


@bp.post("/compliance/committee-reports/<report_id>/present")
def present_report(report_id):
    user_id, role = auth_context()
    require_roles(role, ("BoardSecretary",))
    report = get_or_404(store.reports, report_id, "committee report")
    if report["status"] != "FINALIZED":
        raise invalid_state("present requires status FINALIZED")
    report["status"] = "PRESENTED"
    touch(report)
    append_audit(user_id, role, "POST /compliance/committee-reports/{id}/present",
                 "CommitteeReport", report["id"])
    return success_object(report_to_api(report))
