"""Uptime reporting, holdback penalties and amendments."""
from flask import Blueprint

import derive
import serializers as ser
from auth import actor, require_station_owner
from constants import REPORT_STATUSES
from envelope import created, listing, ok
from errors import raise_error
from helpers import get_agreement, get_report, get_station
from store import base_row, db, sort_created, touch
from validate import (
    bad,
    f_dt,
    f_int,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
)

bp = Blueprint("uptime", __name__)


@bp.get("/uptime-reports/<report_id>")
def read_report(report_id):
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    return ok(ser.uptime_report(get_report(report_id)))


@bp.get("/uptime-reports")
def list_reports():
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    limit, offset = pagination()
    station_id = q_str("station_id")
    agreement_id = q_str("funding_agreement_id")
    amended_from = q_str("amended_from_report_id")
    status = q_enum("status", REPORT_STATUSES)
    rows = sort_created(list(db.uptime_reports.values()))
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if agreement_id is not None:
        rows = [r for r in rows if r["funding_agreement_id"] == agreement_id]
    if amended_from is not None:
        rows = [r for r in rows if r["amended_from_report_id"] == amended_from]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return listing([ser.uptime_report(r) for r in page], limit, offset, len(rows))


def _final_period_conflict(station_id, period_start, period_end, exclude_id=None):
    for other in derive.reports_of_station(station_id):
        if other["id"] == exclude_id or other["status"] != "FINAL":
            continue
        if other["period_start"] < period_end and period_start < other["period_end"]:
            return True
    return False


def _build_report(station, agreement, period_start, period_end, raw, amended_from):
    row = base_row()
    figures = derive.uptime_figures(station, agreement, period_start, period_end,
                                    station["nozzle_count"])
    row.update({
        "station_id": station["id"],
        "funding_agreement_id": agreement["id"],
        "amended_from_report_id": amended_from,
        "period_start": period_start,
        "period_end": period_end,
        "nozzle_count_snapshot": station["nozzle_count"],
        "downtime_nozzle_minutes": figures["downtime_nozzle_minutes"],
        "full_outage_minutes": figures["full_outage_minutes"],
        "uptime_pct_nozzle_weighted": figures["uptime_pct_nozzle_weighted"],
        "uptime_pct_station_level": figures["uptime_pct_station_level"],
        "uptime_pct": figures["uptime_pct"],
        "shortfall_points": figures["shortfall_points"],
        "penalty_cents": 0,
        "status": "DRAFT",
        "amend_reason": None,
        "_raw": raw,
    })
    db.uptime_reports[row["id"]] = row
    return row


@bp.post("/uptime-reports")
def draft_report():
    user_id, role = actor("ComplianceAdmin", "StationOperator")
    body = json_body()
    raw_station = body.get("station_id")
    if isinstance(raw_station, str) and raw_station.strip():
        require_station_owner(role, user_id, raw_station)

    station_id = f_str(body, "station_id")
    agreement_id = f_str(body, "funding_agreement_id")
    period_start, raw_start = f_dt(body, "period_start")
    period_end, raw_end = f_dt(body, "period_end")
    expected_version = f_int(body, "expected_funding_agreement_version")
    if period_end <= period_start:
        bad("Field 'period_end' must be strictly after 'period_start'.")

    station = get_station(station_id)
    agreement = get_agreement(agreement_id)

    if expected_version != agreement["version"]:
        raise_error("ERR_STALE_AGREEMENT_VERSION")

    if _final_period_conflict(station["id"], period_start, period_end):
        raise_error("ERR_REPORT_PERIOD_OVERLAP")
    if agreement["id"] != station["funding_agreement_id"]:
        raise_error("ERR_AGREEMENT_MISMATCH")

    row = _build_report(station, agreement, period_start, period_end,
                        {"period_start": raw_start, "period_end": raw_end}, None)
    touch(agreement)
    return created(ser.uptime_report(row))


@bp.post("/uptime-reports/<report_id>/finalize")
def finalize_report(report_id):
    actor("ComplianceAdmin")
    report = get_report(report_id)
    if report["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if _final_period_conflict(report["station_id"], report["period_start"],
                              report["period_end"], exclude_id=report["id"]):
        raise_error("ERR_REPORT_PERIOD_OVERLAP")

    agreement = db.funding_agreements[report["funding_agreement_id"]]
    report["penalty_cents"] = derive.funding_penalty(report, agreement)
    report["status"] = "FINAL"
    touch(report)
    touch(agreement)
    return ok(ser.uptime_report(report))


@bp.post("/uptime-reports/<report_id>/amend")
def amend_report(report_id):
    actor("ComplianceAdmin")
    cited = get_report(report_id)
    body = json_body()
    period_start, raw_start = f_dt(body, "period_start")
    period_end, raw_end = f_dt(body, "period_end")
    amend_reason = f_str(body, "amend_reason")
    if period_end <= period_start:
        bad("Field 'period_end' must be strictly after 'period_start'.")

    if cited["status"] != "FINAL":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[cited["station_id"]]
    agreement = db.funding_agreements[cited["funding_agreement_id"]]

    cited["status"] = "AMENDED"
    cited["amend_reason"] = amend_reason
    touch(cited)

    replacement = _build_report(station, agreement, period_start, period_end,
                                {"period_start": raw_start, "period_end": raw_end},
                                cited["id"])
    touch(agreement)
    return created(ser.uptime_report(replacement))
