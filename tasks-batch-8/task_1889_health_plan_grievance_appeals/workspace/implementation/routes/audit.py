"""Audit universe snapshot and compliance-summary endpoints (PRD section 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import calc
import db
import errors
from auth import require_roles
from envelope import (paginate, parse_bool_param, parse_pagination,
                      success_list, success_object)
from serializers import audit_record_out
from services import get_or_404
from validate import get_body, req_str

bp = Blueprint("audit", __name__)

VIEW_ROLES = {"PlatformAdmin", "ComplianceOfficer"}


def _valid_period(value):
    return isinstance(value, str) and db.PERIOD_RE.match(value) is not None


def _rate(numerator, denominator):
    if denominator == 0:
        return 0.0
    return float((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP))


@bp.route("/appeals/audit-universe/snapshot", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def snapshot(_user_id, _role):
    body = get_body()
    report_period = req_str(body, "report_period")
    if not _valid_period(report_period):
        raise errors.validation("report_period must be in YYYY-MM form")
    universe = calc.cases_decided_in_period(report_period)
    # Atomicity: reject the whole run if any pair was already captured
    for case in universe:
        for rec in db.audit_records.values():
            if rec["report_period"] == report_period and rec["case_id"] == case["id"]:
                raise errors.duplicate_snapshot()
    now = db.clock_now()
    created = 0
    for case in universe:
        rec = db.make_append_only()
        rec.update({
            "report_period": report_period,
            "case_id": case["id"],
            "case_kind": case["case_kind"],
            "priority_track": case["priority_track"],
            "resolution_timely": calc.case_resolution_timely(case),
            "effectuation_timely": calc.case_effectuation_timely(case),
            "snapshot_at": now,
        })
        db.audit_records[rec["id"]] = rec
        created += 1
    return success_object({"report_period": report_period,
                           "rows_created": created}, status=201)


@bp.route("/appeals/audit-universe/compliance-summary", methods=["GET"])
@require_roles(VIEW_ROLES)
def compliance_summary(_user_id, _role):
    report_period = request.args.get("report_period")
    if report_period is None:
        raise errors.validation("missing required parameter: report_period")
    if not _valid_period(report_period):
        raise errors.validation("report_period must be in YYYY-MM form")
    universe = calc.cases_decided_in_period(report_period)
    total = len(universe)
    timely = 0
    intake_delay = 0
    reviewer_late = 0
    eff_required = 0
    eff_timely = 0
    for case in universe:
        if calc.case_resolution_timely(case):
            timely += 1
        elif calc.case_ack_late(case):
            # Late solely because acknowledgement ran past the 24h window:
            # attributed to INTAKE_DELAY and excluded from reviewer lateness.
            intake_delay += 1
        else:
            reviewer_late += 1
        eff_flag = calc.case_effectuation_timely(case)
        if eff_flag is not None:
            eff_required += 1
            if eff_flag:
                eff_timely += 1
    return success_object({
        "report_period": report_period,
        "total_cases": total,
        "resolution_timely_count": timely + intake_delay,
        "resolution_timely_rate": _rate(timely + intake_delay, total),
        "intake_delay_count": intake_delay,
        "reviewer_late_count": reviewer_late,
        "effectuation_timely_rate": _rate(eff_timely, eff_required),
    })


@bp.route("/appeals/audit-universe/<rid>", methods=["GET"])
@require_roles(VIEW_ROLES)
def get_audit_record(rid, _user_id, _role):
    return success_object(audit_record_out(
        get_or_404(db.audit_records, rid, "audit universe record")))


@bp.route("/appeals/audit-universe", methods=["GET"])
@require_roles(VIEW_ROLES)
def list_audit_records(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.audit_records.values())
    report_period = request.args.get("report_period")
    if report_period is not None:
        rows = [r for r in rows if r["report_period"] == report_period]
    case_id = request.args.get("case_id")
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    case_kind = request.args.get("case_kind")
    if case_kind is not None:
        rows = [r for r in rows if r["case_kind"] == case_kind]
    priority_track = request.args.get("priority_track")
    if priority_track is not None:
        rows = [r for r in rows if r["priority_track"] == priority_track]
    resolution_timely = parse_bool_param(request.args, "resolution_timely")
    if resolution_timely is not None:
        rows = [r for r in rows if r["resolution_timely"] == resolution_timely]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([audit_record_out(r) for r in page], total, limit, offset)
