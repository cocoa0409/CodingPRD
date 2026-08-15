"""Revenue reports."""

from db import store, new_id, next_seq, now_str, today, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NO_COVERING_AGREEMENT,
    ERR_REPORT_PERIOD_NOT_ELAPSED,
    ERR_DUPLICATE_REPORT,
    ERR_DISPUTE_ROUND_LIMIT,
    ERR_STALE_REPORT_VERSION,
)
from middleware import (
    caller,
    require_roles,
    body,
    ROLE_PLATFORM_ADMIN,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
    ROLE_DISTRIBUTOR_PARTNER,
)
from response import created, ok, paginate
from serializers import ser_report
from services.core import get_or_404, MAX_DISPUTE_ROUNDS
from services.selector import compute_report_figures
from util import req_str, parse_month, month_last_day, is_int
from flask import Blueprint, request

bp = Blueprint("reports", __name__)

REPORT_READ_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
    ROLE_DISTRIBUTOR_PARTNER,
]


def _resolve_covering_agreement(channel_id, platform_id, first_day, last_day):
    """An agreement in ACTIVE, SUSPENDED, or TERMINATED whose closed effective
    window covers the whole period month and which carries a locked rate
    snapshot."""
    covering = []
    for a in store.distribution_agreements.values():
        if a["channel_id"] != channel_id or a["platform_id"] != platform_id:
            continue
        if a["agreement_status"] not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
            continue
        if a["locked_tier_threshold_cents"] is None:
            continue
        if a["_eff_start"] <= first_day and last_day <= a["_eff_end"]:
            covering.append(a)
    if not covering:
        return None
    covering.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return covering[-1]


def _period_elapsed(report):
    y, m = map(int, report["period_month"].split("-"))
    if today() <= month_last_day(y, m):
        raise_err(
            ERR_REPORT_PERIOD_NOT_ELAPSED,
            "The report period must be fully elapsed",
        )


@bp.route("/v1/revenue-reports", methods=["POST"])
def create_report():
    user_id, role = caller()
    b = body()
    channel_id = req_str(b, "channel_id")
    platform_id = req_str(b, "platform_id")
    period_month = req_str(b, "period_month")
    parsed = parse_month(period_month)
    if parsed is None:
        raise_err(ERR_INVALID_REQUEST, "period_month must be in YYYY-MM form")
    require_roles(role, [ROLE_FINANCE_ANALYST])
    if channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    if platform_id not in store.distributor_platforms:
        raise_err(ERR_REFERENCE_NOT_FOUND, "platform_id does not reference an existing platform")
    # Tier 9: covering agreement with a locked snapshot.
    y, m = parsed
    first_day = month_last_day(y, m).replace(day=1)
    last_day = month_last_day(y, m)
    agreement = _resolve_covering_agreement(channel_id, platform_id, first_day, last_day)
    if agreement is None:
        raise_err(ERR_NO_COVERING_AGREEMENT, "No covering agreement with a locked rate snapshot")
    # Tier 11: period fully elapsed (current logical date strictly after the
    # period's last day).
    if today() <= last_day:
        raise_err(ERR_REPORT_PERIOD_NOT_ELAPSED, "The report period must be fully elapsed")
    # Tier 12: one report per (channel, platform, period).
    for r in store.revenue_reports.values():
        if (
            r["channel_id"] == channel_id
            and r["platform_id"] == platform_id
            and r["period_month"] == period_month
        ):
            raise_err(ERR_DUPLICATE_REPORT, "A report already exists for (channel, platform, period)")
    ts = now_str()
    rec = {
        "id": new_id(),
        "channel_id": channel_id,
        "platform_id": platform_id,
        "agreement_id": agreement["id"],
        "period_month": period_month,
        "report_status": "DRAFT",
        "calculation_variant": None,
        "gross_revenue_cents": None,
        "platform_share_cents": None,
        "net_revenue_cents": None,
        "dispute_round": 0,
        "generated_by_user_id": user_id,
        "finalized_by_user_id": None,
        "dispute_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    store.revenue_reports[rec["id"]] = rec
    return created(ser_report(rec))


@bp.route("/v1/revenue-reports", methods=["GET"])
def list_reports():
    user_id, role = caller()
    require_roles(role, REPORT_READ_ROLES)
    recs = list(store.revenue_reports.values())
    if role == ROLE_DISTRIBUTOR_PARTNER:
        recs = [r for r in recs if r["platform_id"] == user_id]
    fc = request.args.get("channel_id")
    fp = request.args.get("platform_id")
    fa = request.args.get("agreement_id")
    fs = request.args.get("report_status")
    fpm = request.args.get("period_month")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fp is not None:
        recs = [r for r in recs if r["platform_id"] == fp]
    if fa is not None:
        recs = [r for r in recs if r["agreement_id"] == fa]
    if fs is not None:
        recs = [r for r in recs if r["report_status"] == fs]
    if fpm is not None:
        recs = [r for r in recs if r["period_month"] == fpm]
    return paginate(recs, ser_report)


@bp.route("/v1/revenue-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    user_id, role = caller()
    require_roles(role, REPORT_READ_ROLES)
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    if role == ROLE_DISTRIBUTOR_PARTNER and rec["platform_id"] != user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Partners may only read their own platform's reports")
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/generate-provisional", methods=["POST"])
def generate_provisional(report_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_FINANCE_ANALYST])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    if rec["report_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT report can generate provisional figures")
    _period_elapsed(rec)
    compute_report_figures(rec, "PROVISIONAL")
    rec["report_status"] = "PROVISIONAL"
    touch(rec)
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/recompute", methods=["POST"])
def recompute_report(report_id):
    _, role = caller()
    b = body()
    expected = b.get("expected_report_version")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_report_version is required and must be an integer")
    require_roles(role, [ROLE_FINANCE_ANALYST])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    if rec["report_status"] not in ("DRAFT", "PROVISIONAL"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Recompute is allowed only while DRAFT or PROVISIONAL")
    if expected != rec["version"]:
        raise_err(ERR_STALE_REPORT_VERSION, "expected_report_version does not match the report's current version")
    compute_report_figures(rec, "PROVISIONAL")
    rec["report_status"] = "PROVISIONAL"
    touch(rec)
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/finalize", methods=["POST"])
def finalize_report(report_id):
    user_id, role = caller()
    body()
    require_roles(role, [ROLE_FINANCE_CONTROLLER])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    # Tier 6: segregation of duties.
    if user_id == rec["generated_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "A controller must not finalize a report they generated")
    if rec["report_status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PROVISIONAL report can be finalized")
    _period_elapsed(rec)
    compute_report_figures(rec, "FINAL")
    rec["report_status"] = "FINALIZED"
    rec["finalized_by_user_id"] = user_id
    touch(rec)
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/dispute", methods=["POST"])
def dispute_report(report_id):
    user_id, role = caller()
    b = body()
    reason = req_str(b, "dispute_reason")
    require_roles(role, [ROLE_DISTRIBUTOR_PARTNER])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    # Tier 5: ownership scope.
    if rec["platform_id"] != user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Partners may only dispute their own platform's reports")
    if rec["report_status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FINALIZED report can be disputed")
    if rec["dispute_round"] >= MAX_DISPUTE_ROUNDS:
        raise_err(ERR_DISPUTE_ROUND_LIMIT, "The dispute-round ceiling has been reached")
    rec["report_status"] = "DISPUTED"
    rec["dispute_reason"] = reason
    touch(rec)
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/refinalize", methods=["POST"])
def refinalize_report(report_id):
    user_id, role = caller()
    body()
    require_roles(role, [ROLE_FINANCE_CONTROLLER])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    if user_id == rec["generated_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "A controller must not refinalize a report they generated")
    if rec["report_status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DISPUTED report can be refinalized")
    compute_report_figures(rec, "FINAL")
    rec["report_status"] = "FINALIZED"
    rec["finalized_by_user_id"] = user_id
    rec["dispute_round"] += 1
    touch(rec)
    return ok(ser_report(rec))


@bp.route("/v1/revenue-reports/<report_id>/settle", methods=["POST"])
def settle_report(report_id):
    user_id, role = caller()
    body()
    require_roles(role, [ROLE_FINANCE_CONTROLLER])
    rec = get_or_404(store.revenue_reports, report_id, "RevenueReport")
    if user_id == rec["generated_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "A controller must not settle a report they generated")
    if rec["report_status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a FINALIZED report can be settled")
    rec["report_status"] = "SETTLED"
    touch(rec)
    return ok(ser_report(rec))
