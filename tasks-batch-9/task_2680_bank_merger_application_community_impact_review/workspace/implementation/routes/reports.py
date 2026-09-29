"""Quarterly commitment performance reports, review and reopen (PRD 3.12)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, now_str, serialize, set_fields
from errors import ApiError
from helpers import ensure_application_filer, fetch, fetch_fk, list_and_respond
from middleware import (
    ALL_ROLES,
    ROLE_FILER,
    ROLE_MONITOR,
    actor_id,
    get_body,
    present,
    req_int,
    req_str,
    require_roles,
)
from response import object_response
from routes.plans import CATEGORIES

reports_bp = Blueprint("reports", __name__)


def _plan_application(plan):
    application = db.applications.get(plan["application_id"])
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the plan's application is unknown")
    return application


def _parse_achieved(body):
    if not present(body, "achieved_by_category"):
        raise ApiError("ERR_INVALID_REQUEST", "achieved_by_category is required")
    achieved = body["achieved_by_category"]
    if not isinstance(achieved, dict) or not achieved:
        raise ApiError(
            "ERR_INVALID_REQUEST", "achieved_by_category must be a non-empty object"
        )
    parsed = {}
    for category, amount in achieved.items():
        if category not in CATEGORIES:
            raise ApiError(
                "ERR_INVALID_REQUEST", "achieved_by_category names an undeclared category"
            )
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ApiError(
                "ERR_INVALID_REQUEST", "achieved_by_category values must be integers"
            )
        if amount < 0:
            raise ApiError(
                "ERR_INVALID_REQUEST", "achieved_by_category values must be at least 0"
            )
        parsed[category] = amount
    return parsed


def _apply_caps(plan, achieved):
    """Credit is capped per category against the line item's remaining headroom."""
    items = {i["category"]: i for i in aggregates.plan_line_items(plan["id"])}
    applied_by_category = {}
    credited = 0
    excess = 0
    for category, amount in achieved.items():
        item = items.get(category)
        if item is None:
            headroom = 0
        else:
            headroom = int(item["committed_usd"]) - int(item["credited_usd"])
            if headroom < 0:
                headroom = 0
        applied = amount if amount < headroom else headroom
        applied_by_category[category] = applied
        credited += applied
        excess += amount - applied
    return credited, excess, applied_by_category


@reports_bp.post("/performance-reports")
@require_roles(ROLE_FILER)
def create_report():
    body = get_body(required=True)
    plan_id = req_str(body, "plan_id")
    period_label = req_str(body, "period_label", min_len=4, max_len=16)
    period_index = req_int(body, "period_index", minimum=1)
    achieved = _parse_achieved(body)

    plan = fetch_fk("plans", plan_id)
    application = _plan_application(plan)
    ensure_application_filer(application)

    if plan["status"] != "EXECUTED":
        raise ApiError(
            "ERR_BENEFITS_PLAN_NOT_EXECUTED",
            "reports may only be filed against an EXECUTED plan",
        )
    for existing in aggregates.plan_reports(plan["id"]):
        if existing["period_label"] == period_label:
            raise ApiError(
                "ERR_DUPLICATE_REPORT_PERIOD", "this period_label is already reported"
            )
    if period_index != int(plan["filed_report_count"]) + 1:
        raise ApiError(
            "ERR_REPORT_PERIOD_OUT_OF_SEQUENCE",
            "period_index must be %s" % (int(plan["filed_report_count"]) + 1),
        )

    credited, excess, applied_by_category = _apply_caps(plan, achieved)
    basis = plan["measurement_basis"]
    quarterly_target = int(plan["quarterly_target_total_usd"])

    prior = 0
    for report in aggregates.plan_reports(plan["id"]):
        if int(report["period_index"]) <= period_index and report["status"] in (
            "ACCEPTED",
            "DEFICIENT",
        ):
            prior += int(report["credited_usd"])
    annual_pct = calc.fulfillment_annual(credited, quarterly_target)
    cumulative_pct = calc.fulfillment_cumulative(
        prior + credited, quarterly_target, period_index
    )
    if basis == "ANNUAL_PRO_RATA":
        fulfillment_pct, alternate_pct = annual_pct, cumulative_pct
    else:
        fulfillment_pct, alternate_pct = cumulative_pct, annual_pct

    record = new_record(
        {
            "plan_id": plan["id"],
            "period_label": period_label,
            "period_index": period_index,
            "achieved_by_category": dict(achieved),
            "credited_usd": credited,
            "excess_uncredited_usd": excess,
            "measurement_basis": basis,
            "fulfillment_pct": fulfillment_pct,
            "alternate_fulfillment_pct": alternate_pct,
            "filed_at": now_str(),
            "reviewed_at": None,
            "reviewed_by_user_id": None,
            "status": "FILED",
        }
    )
    record["_applied_by_category"] = applied_by_category
    record["_breached_condition_ids"] = []
    record["_prev_consecutive"] = None
    db.reports[record["id"]] = record
    return object_response(serialize(record), 201)


@reports_bp.get("/performance-reports/<record_id>")
@require_roles(*ALL_ROLES)
def get_report(record_id):
    return object_response(serialize(fetch("reports", record_id)))


@reports_bp.get("/performance-reports")
@require_roles(*ALL_ROLES)
def list_reports():
    return list_and_respond("reports", ("plan_id", "status"))


@reports_bp.post("/performance-reports/<record_id>/review")
@require_roles(ROLE_MONITOR)
def review_report(record_id):
    report = fetch("reports", record_id)
    get_body(required=False)
    plan = db.plans.get(report["plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "the report's plan is unknown")

    if report["status"] != "FILED":
        raise ApiError("ERR_INVALID_REPORT_STATE", "only a FILED report can be reviewed")
    if plan["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_PLAN_STATE", "the plan is not EXECUTED")

    accepted = (
        calc.Decimal(str(report["fulfillment_pct"])) >= calc.DEFICIENCY_THRESHOLD_PCT
    )

    # apply the credits, capped per line item at that item's commitment
    items = {i["category"]: i for i in aggregates.plan_line_items(plan["id"])}
    applied_now = {}
    for category, amount in (report.get("_applied_by_category") or {}).items():
        item = items.get(category)
        if item is None or amount <= 0:
            continue
        headroom = int(item["committed_usd"]) - int(item["credited_usd"])
        if headroom < 0:
            headroom = 0
        applied = amount if amount < headroom else headroom
        if applied <= 0:
            continue
        set_fields(item, credited_usd=int(item["credited_usd"]) + applied)
        applied_now[category] = applied
    report["_applied_at_review"] = applied_now
    report["_prev_consecutive"] = int(plan["consecutive_deficient_periods"])

    credited = int(report["credited_usd"])
    consecutive = int(plan["consecutive_deficient_periods"])
    consecutive = 0 if accepted else consecutive + 1
    set_fields(
        plan,
        credited_to_date_usd=int(plan["credited_to_date_usd"]) + credited,
        remaining_commitment_usd=int(plan["remaining_commitment_usd"]) - credited,
        filed_report_count=int(plan["filed_report_count"]) + 1,
        consecutive_deficient_periods=consecutive,
        compliance_status=calc.compliance_status_for(consecutive),
    )
    set_fields(
        report,
        status="ACCEPTED" if accepted else "DEFICIENT",
        reviewed_at=now_str(),
        reviewed_by_user_id=actor_id(),
    )

    breached_ids = []
    if not accepted and consecutive >= calc.CONSECUTIVE_DEFICIENT_BREACH:
        application = db.applications.get(plan["application_id"])
        decision = (
            aggregates.application_decision(plan["application_id"])
            if application is not None
            else None
        )
        if decision is not None:
            for condition in aggregates.decision_conditions(decision["id"]):
                if (
                    condition["condition_type"] == "COMMUNITY_BENEFITS"
                    and condition["timing"] == "POST_CLOSING"
                    and condition["status"] == "OPEN"
                ):
                    set_fields(condition, status="BREACHED")
                    breached_ids.append(condition["id"])
        if application is not None and breached_ids:
            set_fields(application, post_closing_monitoring_status="ESCALATED")
    report["_breached_condition_ids"] = breached_ids
    return object_response(serialize(report))


@reports_bp.post("/performance-reports/<record_id>/reopen")
@require_roles(ROLE_MONITOR)
def reopen_report(record_id):
    report = fetch("reports", record_id)
    get_body(required=False)
    plan = db.plans.get(report["plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "the report's plan is unknown")

    if report["status"] not in ("ACCEPTED", "DEFICIENT"):
        raise ApiError("ERR_INVALID_REPORT_STATE", "only a reviewed report can be reopened")
    for other in aggregates.plan_reports(plan["id"]):
        if int(other["period_index"]) > int(report["period_index"]) and other["status"] in (
            "ACCEPTED",
            "DEFICIENT",
        ):
            raise ApiError(
                "ERR_INVALID_REPORT_STATE",
                "a later report of this plan has already been reviewed",
            )

    was_deficient = report["status"] == "DEFICIENT"
    items = {i["category"]: i for i in aggregates.plan_line_items(plan["id"])}
    for category, amount in (report.get("_applied_at_review") or {}).items():
        item = items.get(category)
        if item is None or amount <= 0:
            continue
        set_fields(item, credited_usd=int(item["credited_usd"]) - int(amount))

    credited = int(report["credited_usd"])
    previous = report.get("_prev_consecutive")
    if previous is None:
        previous = max(int(plan["consecutive_deficient_periods"]) - 1, 0) if was_deficient else 0
    set_fields(
        plan,
        credited_to_date_usd=int(plan["credited_to_date_usd"]) - credited,
        remaining_commitment_usd=int(plan["remaining_commitment_usd"]) + credited,
        filed_report_count=max(int(plan["filed_report_count"]) - 1, 0),
        consecutive_deficient_periods=int(previous),
        compliance_status=calc.compliance_status_for(int(previous)),
    )
    set_fields(report, status="FILED", reviewed_at=None, reviewed_by_user_id=None)
    report["_applied_at_review"] = {}

    application = db.applications.get(plan["application_id"])
    if int(previous) < calc.CONSECUTIVE_DEFICIENT_BREACH:
        for condition_id in list(report.get("_breached_condition_ids") or []):
            condition = db.conditions.get(condition_id)
            if condition is not None and condition["status"] == "BREACHED":
                set_fields(condition, status="OPEN")
        report["_breached_condition_ids"] = []
        if application is not None:
            decision = aggregates.application_decision(plan["application_id"])
            still_breached = (
                any(
                    c["status"] == "BREACHED"
                    for c in aggregates.decision_conditions(decision["id"])
                )
                if decision is not None
                else False
            )
            if not still_breached and application["post_closing_monitoring_status"] == "ESCALATED":
                set_fields(application, post_closing_monitoring_status="MONITORING")
    return object_response(serialize(report))
