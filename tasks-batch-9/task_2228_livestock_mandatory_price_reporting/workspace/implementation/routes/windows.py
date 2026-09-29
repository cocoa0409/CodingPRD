"""Reporting windows (PRD §3.3)."""

from flask import Blueprint

import clock
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_PENDING_SUBMISSIONS_EXIST,
    ERR_WINDOW_NOT_OPEN,
    ERR_WINDOW_PERIOD_NOT_ENDED,
    ERR_WINDOW_PERIOD_OVERLAP,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPORTER_AGENT,
    roles,
)
from numeric import money

bp = Blueprint("windows", __name__)

READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
)

PENDING_STATUSES = ("SUBMITTED", "RESUBMITTED")


@bp.post("/reporting-windows")
@roles(ROLE_PROGRAM_ADMIN)
def create_window():
    payload = V.body()
    species = V.get_enum(payload, "species", V.SPECIES)
    report_class = V.get_enum(payload, "report_class", V.REPORT_CLASSES)
    frequency = V.get_enum(payload, "frequency", V.FREQUENCIES)
    period_start_raw, period_start = V.get_datetime(payload, "period_start")
    period_end_raw, period_end = V.get_datetime(payload, "period_end")
    deadline_raw, deadline = V.get_datetime(payload, "submission_deadline_utc")
    correction_raw, correction = V.get_datetime(payload, "correction_deadline_utc")
    release_raw, release = V.get_datetime(payload, "publication_release_utc")
    min_reporter_count = V.get_int(payload, "min_reporter_count", required=False, minimum=1, default=3)
    max_share = V.get_decimal(
        payload,
        "max_single_reporter_share_pct",
        required=False,
        minimum="0.01",
        maximum="100.00",
        default=money("70.00"),
    )
    min_reported_head = V.get_int(
        payload, "min_reported_head", required=False, minimum=0, default=2000
    )

    if not period_start < period_end:
        raise V.bad("period_start must be strictly earlier than period_end.")
    if deadline > correction:
        raise V.bad("submission_deadline_utc must be no later than correction_deadline_utc.")
    if correction > release:
        raise V.bad("correction_deadline_utc must be no later than publication_release_utc.")

    for other in db.reporting_windows.values():
        if (
            other["species"] != species
            or other["report_class"] != report_class
            or other["frequency"] != frequency
        ):
            continue
        if period_start < other["_period_end"] and other["_period_start"] < period_end:
            raise ApiError(
                ERR_WINDOW_PERIOD_OVERLAP,
                "The proposed period intersects an existing window for the same species, "
                "report class and frequency.",
            )

    rec = db.insert(
        db.reporting_windows,
        {
            "species": species,
            "report_class": report_class,
            "frequency": frequency,
            "period_start": period_start_raw,
            "_period_start": period_start,
            "period_end": period_end_raw,
            "_period_end": period_end,
            "submission_deadline_utc": deadline_raw,
            "_submission_deadline_utc": deadline,
            "correction_deadline_utc": correction_raw,
            "_correction_deadline_utc": correction,
            "publication_release_utc": release_raw,
            "_publication_release_utc": release,
            "min_reporter_count": min_reporter_count,
            "max_single_reporter_share_pct": money(max_share),
            "min_reported_head": min_reported_head,
            "status": "OPEN",
            "accepted_submission_count": 0,
            "total_head_reported": 0,
        },
    )
    return response.object_response(serializers.reporting_window(rec), 201)


@bp.post("/reporting-windows/<window_id>/lock")
@roles(ROLE_PROGRAM_ADMIN)
def lock_window(window_id):
    rec = lookup.reporting_window(window_id)

    if rec["status"] != "OPEN":
        raise ApiError(
            ERR_WINDOW_NOT_OPEN,
            "Only an OPEN window may be locked; this window is %s." % rec["status"],
        )

    if clock.now() < rec["_period_end"]:
        raise ApiError(
            ERR_WINDOW_PERIOD_NOT_ENDED,
            "The covered trade period has not ended yet.",
        )

    pending = any(
        s["reporting_window_id"] == rec["id"] and s["status"] in PENDING_STATUSES
        for s in db.submissions.values()
    )
    if pending:
        raise ApiError(
            ERR_PENDING_SUBMISSIONS_EXIST,
            "Submissions of this window are still awaiting review.",
        )

    rec["status"] = "LOCKED"
    db.touch(rec)
    return response.object_response(serializers.reporting_window(rec))


@bp.get("/reporting-windows/<window_id>")
@roles(*READ_ROLES)
def get_window(window_id):
    rec = lookup.reporting_window(window_id)
    return response.object_response(serializers.reporting_window(rec))


@bp.get("/reporting-windows")
@roles(*READ_ROLES)
def list_windows():
    limit, offset = V.pagination()
    species = V.query_str("species")
    report_class = V.query_str("report_class")
    frequency = V.query_str("frequency")
    status = V.query_str("status")

    records = db.ordered(db.reporting_windows.values())
    if species is not None:
        records = [r for r in records if r["species"] == species]
    if report_class is not None:
        records = [r for r in records if r["report_class"] == report_class]
    if frequency is not None:
        records = [r for r in records if r["frequency"] == frequency]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.reporting_window(r) for r in page], limit, offset, total
    )
