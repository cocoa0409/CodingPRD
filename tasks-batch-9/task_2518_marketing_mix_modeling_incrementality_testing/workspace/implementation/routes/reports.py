"""Reconciliation reports (PRD section 3.9)."""

from flask import Blueprint, request

import db as store
from db import base_row, db
from errors import ApiError
from lookup import must, must_field
from middleware import ANALYTICS_LEAD, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.market import require_posture_not_frozen
from services.reconcile import build_reconciliation
from validation import date_style, field_array, field_date, get_body, invalid

bp = Blueprint("reports", __name__)


def _parse_platform_lines(body):
    raw_lines = field_array(body, "platform_lines", min_items=1)
    lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise invalid("Each platform_lines entry must be an object.")
        if "channel_id" not in entry or entry["channel_id"] is None:
            raise invalid("Each platform_lines entry needs a channel_id.")
        if "platform_revenue_cents" not in entry or entry["platform_revenue_cents"] is None:
            raise invalid("Each platform_lines entry needs a platform_revenue_cents.")
        channel_id = entry["channel_id"]
        amount = entry["platform_revenue_cents"]
        if not isinstance(channel_id, str) or channel_id.strip() == "":
            raise invalid("platform_lines channel_id must be an identifier string.")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise invalid("platform_lines platform_revenue_cents must be an integer.")
        if isinstance(amount, float):
            if not float(amount).is_integer():
                raise invalid("platform_lines platform_revenue_cents must be an integer.")
            amount = int(amount)
        lines.append({"channel_id": channel_id, "platform_revenue_cents": amount})
    return lines


@bp.post("/mmm/reconciliation-reports")
def create_report():
    authenticate((ANALYTICS_LEAD,))
    body = get_body()
    start_raw, start = field_date(body, "reporting_period_start")
    end_raw, end = field_date(body, "reporting_period_end")
    if end <= start:
        raise invalid("reporting_period_end must be strictly after reporting_period_start.")
    lines = _parse_platform_lines(body)

    run = must_field("model_runs", body, "model_run_id")
    for line in lines:
        must("media_channels", line["channel_id"])

    if run["calibration_status"] not in ("NOT_REQUIRED", "CALIBRATED"):
        raise ApiError("ERR_CALIBRATION_STALE",
                       "The model run's calibration status is %s." % run["calibration_status"])
    require_posture_not_frozen(db.markets[run["market_id"]])

    figures = build_reconciliation(run, lines)

    for existing in store.reports_of_run(run["id"]):
        if existing["_reporting_period_start"] == start:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A report already exists for that run and reporting period start.")

    row = base_row("reconciliation_reports")
    row.update({
        "model_run_id": run["id"],
        "reporting_period_start": start_raw,
        "reporting_period_end": end_raw,
        "platform_lines": lines,
        "variance_lines": figures["variance_lines"],
        "platform_reported_revenue_cents": figures["platform_reported_revenue_cents"],
        "model_attributed_revenue_cents": figures["model_attributed_revenue_cents"],
        "total_variance_cents": figures["total_variance_cents"],
        "weighted_variance_pct": figures["weighted_variance_pct"],
        "attribution_gap_flag": figures["attribution_gap_flag"],
        "basis": figures["basis"],
        "status": "CURRENT",
        "_reporting_period_start": start,
        "_reporting_period_end": end,
        "_date_style": date_style(start_raw),
    })
    db.add("reconciliation_reports", row)
    return created(row)


@bp.get("/mmm/reconciliation-reports")
def list_reports():
    authenticate(READ_ROLES)
    rows = db.all("reconciliation_reports")
    for param in ("model_run_id", "status", "attribution_gap_flag", "basis"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(ordering.sort_rows("reconciliation_reports", rows), request.args)


@bp.get("/mmm/reconciliation-reports/<report_id>")
def get_report(report_id):
    authenticate(READ_ROLES)
    return ok(must("reconciliation_reports", report_id))
