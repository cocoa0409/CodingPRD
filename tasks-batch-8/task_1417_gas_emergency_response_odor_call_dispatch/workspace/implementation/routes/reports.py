"""RegulatoryReport endpoints: generate / list / get / submit / accept / reject /
regenerate. Snapshot math per the regulatory_compliance_snapshot calculation."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import check_report_read_scope, load_report
from validate import (get_body, pagination_params, paginate, req_str,
                      sort_by_creation)

bp = Blueprint("reports", __name__)

READ_ROLES = ("SystemAdmin", "Dispatcher", "Supervisor", "Regulator")


def compute_snapshot(territory_id, period_start, period_end, now):
    """Pinned order: (1) recompute pauses/elapsed per candidate, (2) breach verdicts
    against current-priority thresholds, (3) aggregate counts and rates."""
    candidates = [i for i in db.incidents.values()
                  if i["territory_id"] == territory_id
                  and i["lifecycle_status"] != "MERGED"
                  and period_start <= i["response_clock_started_at"] < period_end]
    stats = {p: {"total": 0, "determined": 0, "compliant_raw": 0, "compliant_adjusted": 0}
             for p in domain.PRIORITIES}
    determined_count = 0
    compliant_raw = 0
    compliant_adjusted = 0
    for inc in candidates:
        raw, _, adjusted = domain.elapsed(inc, now)
        threshold_seconds = domain.threshold_minutes(inc) * 60
        bucket = stats[inc["priority"]]
        bucket["total"] += 1
        # Determined: arrival recorded, or adjusted elapsed past threshold (an OPEN
        # pause is virtually closed at generation time by domain.elapsed(now)).
        if inc["first_arrival_at"] is None and adjusted <= threshold_seconds:
            continue  # pending
        determined_count += 1
        bucket["determined"] += 1
        if raw <= threshold_seconds:
            compliant_raw += 1
            bucket["compliant_raw"] += 1
        if adjusted <= threshold_seconds:
            compliant_adjusted += 1
            bucket["compliant_adjusted"] += 1

    def rate(count):
        if determined_count == 0:
            return None
        return float((Decimal(count) / Decimal(determined_count)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP))

    return {
        "incident_count": len(candidates),
        "determined_count": determined_count,
        "pending_count": len(candidates) - determined_count,
        "compliant_count_raw": compliant_raw,
        "compliant_count_adjusted": compliant_adjusted,
        "compliance_rate_raw": rate(compliant_raw),
        "compliance_rate_adjusted": rate(compliant_adjusted),
        "stats": stats,
    }


@bp.route("/gas-ops/regulatory-reports", methods=["POST"])
@require_roles("Supervisor")
def generate(user_id, role):
    body = get_body()
    territory_id = req_str(body, "territory_id")
    period_start = clock.parse_dt(body.get("period_start"))
    period_end = clock.parse_dt(body.get("period_end"))
    if territory_id not in db.territories:
        raise ApiError("ERR_TERRITORY_NOT_FOUND", "Territory not found", 404)
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_TIME_RANGE",
                       "period_end must be strictly after period_start", 400)
    now = clock.now()
    rec = domain.new_record(common_fields=True)
    rec.update({
        "territory_id": territory_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "generated_at": now,
        "submitted_at": None,
        "needs_regeneration": False,
        "regeneration_count": 0,
        "reject_reason": None,
    })
    rec.update(compute_snapshot(territory_id, period_start, period_end, now))
    db.reports[rec["id"]] = rec
    return response.success(domain.ser_report(rec), 201)


@bp.route("/gas-ops/regulatory-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.reports.values())
    territory_id = request.args.get("territory_id")
    status = request.args.get("status")
    if territory_id is not None:
        items = [r for r in items if r["territory_id"] == territory_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if role == "Regulator":
        items = [r for r in items if r["status"] != "DRAFT"]
    page, total = paginate([domain.ser_report(r) for r in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/regulatory-reports/<reportId>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_report(reportId, user_id, role):
    report = load_report(reportId)
    check_report_read_scope(report, role)
    return response.success(domain.ser_report(report), 200)


@bp.route("/gas-ops/regulatory-reports/<reportId>/submit", methods=["POST"])
@require_roles("Supervisor")
def submit(reportId, user_id, role):
    report = load_report(reportId)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", "Submit requires a DRAFT report", 409)
    if report["needs_regeneration"]:
        raise ApiError("ERR_REPORT_NOT_DRAFT",
                       "Report is stale: covered incidents changed after generation; "
                       "regenerate before submitting", 409)
    report["status"] = "SUBMITTED"
    report["submitted_at"] = clock.now()
    domain.bump(report)
    return response.success(domain.ser_report(report), 200)


@bp.route("/gas-ops/regulatory-reports/<reportId>/accept", methods=["POST"])
@require_roles("Regulator")
def accept(reportId, user_id, role):
    report = load_report(reportId)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Accept requires a SUBMITTED report", 409)
    report["status"] = "ACCEPTED"
    domain.bump(report)
    return response.success(domain.ser_report(report), 200)


@bp.route("/gas-ops/regulatory-reports/<reportId>/reject", methods=["POST"])
@require_roles("Regulator")
def reject(reportId, user_id, role):
    report = load_report(reportId)
    reason = req_str(get_body(), "reason")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Reject requires a SUBMITTED report", 409)
    report["status"] = "REJECTED"
    report["reject_reason"] = reason
    domain.bump(report)
    return response.success(domain.ser_report(report), 200)


@bp.route("/gas-ops/regulatory-reports/<reportId>/regenerate", methods=["POST"])
@require_roles("Supervisor")
def regenerate(reportId, user_id, role):
    report = load_report(reportId)
    if report["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Regenerate requires a DRAFT or REJECTED report", 409)
    now = clock.now()
    report.update(compute_snapshot(report["territory_id"], report["period_start"],
                                   report["period_end"], now))
    report["generated_at"] = now
    report["needs_regeneration"] = False
    report["regeneration_count"] += 1
    report["status"] = "DRAFT"
    domain.bump(report)
    return response.success(domain.ser_report(report), 200)
