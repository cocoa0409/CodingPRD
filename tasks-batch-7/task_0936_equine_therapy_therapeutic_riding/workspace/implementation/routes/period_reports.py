"""Period reports: the centre's accountability artefact (PRD §3.8)."""

from flask import Blueprint

from core import timeutil as T
from core.envelope import object_response
from core.errors import fail
from core.ladder import Field, endpoint, validate_body
from core.lookups import resource_or_404
from core.store import clock, new_row, touch
from domain import gates, reports

bp = Blueprint("period_reports", __name__)


@bp.post("/period-reports")
@endpoint(["ProgramAdmin"])
def create_report():
    def cross(payload):
        start = T.parse_date(payload.get("period_start")) \
            if isinstance(payload.get("period_start"), str) else None
        end = T.parse_date(payload.get("period_end")) \
            if isinstance(payload.get("period_end"), str) else None
        if start is not None and end is not None and end < start:
            fail("ERR_VALIDATION", "period_end must not precede period_start.")

    payload = validate_body([
        Field("period_start", "date", required=True),
        Field("period_end", "date", required=True),
    ], cross=cross)
    start = T.parse_date(payload["period_start"])
    end = T.parse_date(payload["period_end"])
    if gates.finalized_report_overlapping(start, end) is not None:      # gate 2
        fail("ERR_REPORT_FINALIZED",
             "The requested period overlaps a finalized report.")

    row = new_row("period_reports")
    row.update({
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "status": "DRAFT",
        "finalized_at": None,
        "amendment_count": 0,
        "amendment_net_cents": 0,
    })
    for key in reports.AGGREGATE_KEYS:
        row[key] = 0
    return object_response(reports.period_report(row), 201)


@bp.get("/period-reports/<report_id>")
@endpoint(["ProgramAdmin", "BillingClerk"])
def read_report(report_id):
    return object_response(reports.period_report(
        resource_or_404("period_reports", report_id)))


@bp.post("/period-reports/<report_id>/finalize")
@endpoint(["ProgramAdmin"])
def finalize_report(report_id):
    row = resource_or_404("period_reports", report_id)
    if row["status"] == "FINALIZED":                                    # gate 2
        fail("ERR_REPORT_FINALIZED", "That report is already finalized.")
    live = reports.aggregate(T.parse_date(row["period_start"]),
                             T.parse_date(row["period_end"]))
    for key in reports.AGGREGATE_KEYS:
        row[key] = live[key]
    row["status"] = "FINALIZED"
    row["finalized_at"] = clock.stamp()
    touch(row)
    return object_response(reports.period_report(row))
