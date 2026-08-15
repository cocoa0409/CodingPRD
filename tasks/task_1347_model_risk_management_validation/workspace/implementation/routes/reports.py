"""Board & regulatory reporting endpoints: create (snapshot), list, get, submit."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import BUSINESS_ROLES, require_roles
from response import success, success_list
from serializers import report_json
from services import risk, workflow
from utils import new_id
from validate import get_body, pagination_params, v_dt, v_enum

bp = Blueprint("reports", __name__)


def get_report_or_404(report_id):
    r = store.reports.get(report_id)
    if r is None:
        raise ApiError(
            "ERR_NOT_FOUND", 404, "Regulatory report '%s' does not exist" % report_id
        )
    return r


@bp.post("/mrm/regulatory-reports")
def create_report():
    body = get_body()
    report_type = v_enum(body, "report_type", ("BOARD_QUARTERLY", "REGULATOR_ANNUAL"))
    period_start = v_dt(body, "period_start")
    period_end = v_dt(body, "period_end")
    aggregation_method = v_enum(
        body, "aggregation_method", ("EQUAL_WEIGHTED", "EXPOSURE_WEIGHTED")
    )
    if period_end <= period_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "period_end must be strictly after period_start",
        )
    require_roles("RegulatoryReporter")
    with store.lock:
        now = store.now()
        # Snapshot input set: created on or before period_end, not RETIRED.
        input_set = [
            m
            for m in store.models.values()
            if m["created_at"] <= period_end
            and m["status"] in ("REGISTERED", "APPROVED_FOR_USE", "SUSPENDED")
        ]
        model_ids = {m["id"] for m in input_set}
        open_findings = [
            f
            for f in store.findings.values()
            if f["model_id"] in model_ids and f["status"] in risk.OPEN_FINDING_STATES
        ]
        metric_ids = {
            mt["id"] for mt in store.metrics.values() if mt["model_id"] in model_ids
        }
        breach_count = sum(
            1
            for b in store.breach_events.values()
            if b["metric_id"] in metric_ids and b["status"] == "OPEN"
        )
        report = {
            "id": new_id(),
            "report_type": report_type,
            "period_start": period_start,
            "period_end": period_end,
            "aggregation_method": aggregation_method,
            "status": "DRAFT",
            "total_models": len(input_set),
            "tier_1_count": sum(1 for m in input_set if m["risk_tier"] == "TIER_1"),
            "open_findings_total": len(open_findings),
            "open_critical_count": sum(
                1 for f in open_findings if f["severity"] == "CRITICAL"
            ),
            "breach_event_count": breach_count,
            "overdue_validation_count": sum(
                1 for m in input_set if m["validation_due_at"] < now
            ),
            "inventory_risk_index": risk.inventory_risk_index(
                input_set, aggregation_method
            ),
            "submitted_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.reports[report["id"]] = report
        return success(report_json(report), 201)


@bp.get("/mrm/regulatory-reports")
def list_reports():
    require_roles(*BUSINESS_ROLES)
    limit, offset = pagination_params()
    f_type = request.args.get("report_type")
    f_status = request.args.get("status")
    with store.lock:
        items = sorted(store.reports.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if f_type is not None:
            items = [r for r in items if r["report_type"] == f_type]
        if f_status is not None:
            items = [r for r in items if r["status"] == f_status]
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([report_json(r) for r in page], limit, offset, total)


@bp.get("/mrm/regulatory-reports/<report_id>")
def get_report(report_id):
    require_roles(*BUSINESS_ROLES)
    with store.lock:
        return success(report_json(get_report_or_404(report_id)))


@bp.post("/mrm/regulatory-reports/<report_id>/submit")
def submit_report(report_id):
    require_roles("RegulatoryReporter")
    with store.lock:
        report = get_report_or_404(report_id)
        if report["status"] != "DRAFT":
            raise ApiError(
                "ERR_REPORT_ALREADY_SUBMITTED",
                409,
                "Report has already been submitted",
            )
        # CLOSED-interval overlap within the same report_type against SUBMITTED
        # reports: adjacency IS a conflict.
        for other in store.reports.values():
            if (
                other["id"] != report["id"]
                and other["report_type"] == report["report_type"]
                and other["status"] == "SUBMITTED"
                and other["period_start"] <= report["period_end"]
                and report["period_start"] <= other["period_end"]
            ):
                raise ApiError(
                    "ERR_REPORT_PERIOD_OVERLAP",
                    409,
                    "Report period overlaps a SUBMITTED report of the same type",
                )
        report["status"] = "SUBMITTED"
        report["submitted_at"] = store.now()
        workflow.mutate(report)
        return success(report_json(report))
