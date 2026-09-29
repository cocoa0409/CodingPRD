"""Uptime reporting: the provisional operator view and the final federal view
(PRD §3.7)."""
from flask import Blueprint

import calc
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id
from response import array_response, object_response, paginate

bp = Blueprint("uptime_reports", __name__)

PROGRAM_OUTCOMES = ("ACCEPT", "RETURN")


def _write_figures(report, figures, methodology):
    report["eligible_port_count"] = figures["eligible_port_count"]
    report["total_port_minutes"] = figures["total_port_minutes"]
    report["excluded_minutes"] = figures["excluded_minutes"]
    report["billable_downtime_minutes"] = figures["billable_downtime_minutes"]
    report["uptime_pct"] = figures["uptime_pct"]
    report["methodology"] = methodology


@bp.post("/uptime-reports")
@endpoint("NetworkOperator")
def declare_period():
    body = validation.json_body()
    raw_station_id = validation.fk(body, "station_id")
    station = lookup.station(raw_station_id) if raw_station_id is not None else None
    validation.as_string(body, "station_id")
    period_start = validation.as_datetime(body, "period_start")
    period_end = validation.as_datetime(body, "period_end")

    if not period_end > period_start:
        raise err("ERR_REPORTING_PERIOD_INVALID",
                  "period_end must be strictly after period_start.")
    if calc.floor_minutes_between(period_start, period_end) < calc.MIN_REPORTING_PERIOD_MINUTES:
        raise err("ERR_REPORTING_PERIOD_INVALID",
                  "The reporting period must span at least seven days.")
    if period_end > clock.now():
        raise err("ERR_REPORTING_PERIOD_NOT_ELAPSED",
                  "period_end may not be later than the current logical clock reading.")

    for existing in db.reports_of_station(station["id"]):
        # closed-closed intervals: an adjacent period IS an overlap
        if period_start <= existing["period_end"] and existing["period_start"] <= period_end:
            raise err("ERR_REPORTING_PERIOD_OVERLAP",
                      "The period overlaps an existing reporting period on this station.")

    row = db.base_record()
    row.update({
        "station_id": station["id"],
        "period_start": period_start,
        "period_end": period_end,
        "methodology": None,
        "eligible_port_count": None,
        "total_port_minutes": None,
        "excluded_minutes": None,
        "billable_downtime_minutes": None,
        "uptime_pct": None,
        "state": "DRAFT",
        "finalized_by_user_id": None,
        "claim_count": 0,
        "returned_count": 0,
    })
    db.reports[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.uptime_report(row), 201)


@bp.get("/uptime-reports/<uptime_report_id>")
@endpoint()
def get_report(uptime_report_id):
    return object_response(serialize.uptime_report(lookup.uptime_report(uptime_report_id)))


@bp.get("/uptime-reports/<uptime_report_id>/reimbursement-claims")
@endpoint()
def list_claims_of_report(uptime_report_id):
    report = lookup.uptime_report(uptime_report_id)
    limit, offset = validation.pagination()
    rows = db.claims_of_report(report["id"])
    rows = validation.apply_filters(rows, validation.filters("state"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.reimbursement_claim(r) for r in page],
                          limit, offset, total)


@bp.post("/uptime-reports/<uptime_report_id>/compute-provisional")
@endpoint("NetworkOperator")
def compute_provisional(uptime_report_id):
    report = lookup.uptime_report(uptime_report_id)
    if report["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT report may be computed provisionally.")

    station = db.stations.get(report["station_id"])
    if not calc.station_is_serviceable(station):
        raise err("ERR_INVALID_STATE", "The station must be OPERATIONAL or SUSPENDED.")

    figures = calc.uptime_figures(report, "PROVISIONAL")
    if figures["total_port_minutes"] <= 0:
        raise err("ERR_NO_REPORTABLE_PORT_MINUTES",
                  "The reporting period has no port-minute exposure.")

    _write_figures(report, figures, "PROVISIONAL")
    report["state"] = "PROVISIONAL"
    db.touch(report)
    return object_response(serialize.uptime_report(report))


@bp.post("/uptime-reports/<uptime_report_id>/finalize")
@endpoint("ComplianceAuditor")
def finalize(uptime_report_id):
    report = lookup.uptime_report(uptime_report_id)
    if report["state"] != "PROVISIONAL":
        raise err("ERR_INVALID_STATE", "Only a PROVISIONAL report may be finalized.")

    for outage in calc.attributed_outages(report):
        if outage["state"] == "EXCLUSION_REVIEW":
            raise err("ERR_EXCLUSION_REVIEW_PENDING",
                      "An outage attributed to this period is awaiting exclusion adjudication.")

    figures = calc.uptime_figures(report, "FINAL")
    if figures["denominator"] <= 0:
        raise err("ERR_NO_REPORTABLE_PORT_MINUTES",
                  "The reporting period has no reportable port minutes.")

    _write_figures(report, figures, "FINAL")
    report["state"] = "FINAL"
    report["finalized_by_user_id"] = current_user_id()
    db.touch(report)
    return object_response(serialize.uptime_report(report))


@bp.post("/uptime-reports/<uptime_report_id>/submit")
@endpoint("NetworkOperator")
def submit(uptime_report_id):
    report = lookup.uptime_report(uptime_report_id)
    if report["state"] != "FINAL":
        raise err("ERR_INVALID_STATE", "Only a FINAL report may be submitted.")
    report["state"] = "SUBMITTED"
    db.touch(report)
    return object_response(serialize.uptime_report(report))


@bp.post("/uptime-reports/<uptime_report_id>/program-review")
@endpoint("ProgramAdministrator")
def program_review(uptime_report_id):
    report = lookup.uptime_report(uptime_report_id)
    body = validation.json_body()
    outcome = validation.as_enum(body, "outcome", PROGRAM_OUTCOMES)

    if report["state"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED report may be reviewed.")

    if outcome == "ACCEPT":
        report["state"] = "ACCEPTED"
    else:
        report["state"] = "PROVISIONAL"
        report["returned_count"] = report["returned_count"] + 1
        report["finalized_by_user_id"] = None
    db.touch(report)
    return object_response(serialize.uptime_report(report))
