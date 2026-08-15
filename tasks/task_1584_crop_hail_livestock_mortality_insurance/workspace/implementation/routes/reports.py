"""Acreage and head report endpoints (PRD 3.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_REPORT_BEFORE_COVERAGE,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy, resolve_unit
from serializers import acreage_report_view, head_report_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_enum, require_int,
    parse_pagination, paginate, sort_created, dt, ceil_whole_days,
)

bp = Blueprint("reports", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")

ACREAGE_FIELDS = {"report_kind", "reported_acres"}
HEAD_FIELDS = {"report_kind", "reported_head_count"}


def _check_reportable(policy: dict, unit: dict, expected_kind: str, now_dt) -> None:
    if unit["unit_kind"] != expected_kind:
        raise_err(ERR_INVALID_REQUEST,
                  f"This report family does not apply to a {unit['unit_kind']} unit")
    if policy["lifecycle_state"] not in ("BOUND", "ACTIVE"):
        raise_err(ERR_INVALID_STATE,
                  "Reports are accepted only while the policy is BOUND or ACTIVE")
    if now_dt < dt(policy["effective_date"]):
        raise_err(ERR_REPORT_BEFORE_COVERAGE,
                  "Report submitted before the policy's effective date")


def _apply_first_report_transition(unit: dict, is_timely: bool, now: str) -> None:
    if unit["status"] != "PENDING_REPORT":
        return
    unit["status"] = "REPORTED" if is_timely else "LAPSED_REPORT"
    db.touch(unit, now)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units/<unitId>/acreage-reports",
          methods=["POST"])
@require_roles("Policyholder")
def create_acreage_report(carrierId: str, policyId: str, unitId: str,
                          _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    unit = resolve_unit(policy["id"], unitId)
    body = get_json_body()
    reject_unknown_fields(body, ACREAGE_FIELDS)
    report_kind = require_enum(body, "report_kind", {"PLANTING", "HARVEST"})
    reported_acres = require_int(body, "reported_acres", minimum=0)

    now = carrier["current_utc"]
    now_dt = dt(now)
    _check_reportable(policy, unit, "CROP_HAIL", now_dt)

    deadline_raw = (
        policy["acreage_report_deadline"] if report_kind == "PLANTING"
        else policy["harvest_report_deadline"]
    )
    if now_dt <= dt(deadline_raw):
        is_timely, lateness_days, reduction = True, 0, 0
    else:
        is_timely = False
        lateness_days = ceil_whole_days(now_dt - dt(deadline_raw))
        reduction = min(100, lateness_days * 5)

    report = db.stamp_new({
        "coverage_unit_id": unit["id"],
        "report_kind": report_kind,
        "reported_acres": reported_acres,
        "submitted_at": now,
        "is_timely": is_timely,
        "lateness_days": lateness_days,
        "coverage_reduction_pct": reduction,
    }, now)
    db.acreage_reports[report["id"]] = report
    _apply_first_report_transition(unit, is_timely, now)
    return success_object(acreage_report_view(report), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units/<unitId>/acreage-reports",
          methods=["GET"])
@require_roles(*ALL_ROLES)
def list_acreage_reports(carrierId: str, policyId: str, unitId: str,
                         _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    unit = resolve_unit(policy["id"], unitId)
    items = [r for r in db.acreage_reports.values()
             if r["coverage_unit_id"] == unit["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([acreage_report_view(r) for r in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units/<unitId>/head-reports",
          methods=["POST"])
@require_roles("Policyholder")
def create_head_report(carrierId: str, policyId: str, unitId: str,
                       _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    unit = resolve_unit(policy["id"], unitId)
    body = get_json_body()
    reject_unknown_fields(body, HEAD_FIELDS)
    report_kind = require_enum(body, "report_kind", {"INITIAL", "INTERIM", "FINAL"})
    reported_head_count = require_int(body, "reported_head_count", minimum=0)

    now = carrier["current_utc"]
    now_dt = dt(now)
    _check_reportable(policy, unit, "LIVESTOCK_MORTALITY", now_dt)

    if report_kind == "INITIAL":
        deadline_raw = policy["head_report_deadline"]
        if now_dt <= dt(deadline_raw):
            is_timely, lateness_days, reduction = True, 0, 0
        else:
            is_timely = False
            lateness_days = ceil_whole_days(now_dt - dt(deadline_raw))
            reduction = min(100, lateness_days * 5)
    else:
        # INTERIM/FINAL are always timely and never reduce coverage (PRD 3.5).
        is_timely, lateness_days, reduction = True, 0, 0

    report = db.stamp_new({
        "coverage_unit_id": unit["id"],
        "report_kind": report_kind,
        "reported_head_count": reported_head_count,
        "submitted_at": now,
        "is_timely": is_timely,
        "lateness_days": lateness_days,
        "coverage_reduction_pct": reduction,
    }, now)
    db.head_reports[report["id"]] = report
    _apply_first_report_transition(unit, is_timely, now)
    return success_object(head_report_view(report), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units/<unitId>/head-reports",
          methods=["GET"])
@require_roles(*ALL_ROLES)
def list_head_reports(carrierId: str, policyId: str, unitId: str,
                      _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    unit = resolve_unit(policy["id"], unitId)
    items = [r for r in db.head_reports.values()
             if r["coverage_unit_id"] == unit["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([head_report_view(r) for r in page], limit, offset, total)
