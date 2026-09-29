"""Periodic call reports and the reporting-calendar dimension (§3.5)."""

import re
from datetime import datetime, timezone

from flask import Blueprint

import calculations as calc
from db import base_row, days, db, now, serialize, set_dt
from errors import ApiError
from middleware import authorize
from response import created
from routes.common import get_jurisdiction, get_licensee, get_license
from routes.state_licenses import _require_not_terminal
from services import engine
from validators import bad, get_body, v_int, v_str

bp = Blueprint("call_reports", __name__)

PERIOD_RE = re.compile(r"^(\d{4})(Q[1-4]|FY)$")


@bp.post("/call-reports")
def file_call_report():
    authorize("LicensingManager")
    body = get_body()
    state_license_id = v_str(body, "state_license_id")
    period_label = v_str(body, "period_label")
    volume = v_int(body, "transmission_volume_cents", minimum=0)
    transactions = v_int(body, "transaction_count", minimum=0)
    match = PERIOD_RE.match(period_label)
    if not match:
        bad("period_label must be <YYYY>Q<1-4> or <YYYY>FY")

    license_row = get_license(state_license_id)
    licensee = get_licensee(license_row["licensee_id"])
    jurisdiction = get_jurisdiction(license_row["jurisdiction_id"])

    _require_not_terminal(license_row)

    suffix = match.group(2)
    expected_suffixes = ("Q1", "Q2", "Q3", "Q4") if jurisdiction[
        "call_report_frequency"
    ] == "QUARTERLY" else ("FY",)
    if suffix not in expected_suffixes:
        raise ApiError(
            "ERR_DUPLICATE_CALL_REPORT",
            "period_label %s does not match the %s cadence of this jurisdiction"
            % (period_label, jurisdiction["call_report_frequency"]),
        )
    for existing in engine.call_reports_of(state_license_id):
        if existing["period_label"] == period_label:
            raise ApiError(
                "ERR_DUPLICATE_CALL_REPORT",
                "A call report for %s has already been filed" % period_label,
            )

    year, month, day = calc.period_end_parts(period_label)
    period_end = datetime(year, month, day, tzinfo=timezone.utc)

    row = base_row()
    row.update(
        {
            "state_license_id": state_license_id,
            "period_label": period_label,
            "transmission_volume_cents": volume,
            "transaction_count": transactions,
            "assessment_fee_cents": calc.call_report_assessment_fee(
                volume, jurisdiction["assessment_rate_bps"]
            ),
        }
    )
    set_dt(row, "period_end", period_end)
    set_dt(row, "due_at", period_end + days(calc.CALL_REPORT_DUE_DAYS))
    set_dt(row, "filed_at", now())
    row["status"] = None
    db.call_reports[row["id"]] = row

    engine.apply_call_report(license_row, row, jurisdiction, licensee)
    return created(serialize(row))
