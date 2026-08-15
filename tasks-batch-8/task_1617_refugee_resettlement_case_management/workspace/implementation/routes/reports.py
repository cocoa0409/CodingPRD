"""FederalReport endpoints: generate snapshot, submit, review."""

from flask import Blueprint

from db import store, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_REPORT_DOCUMENTATION_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES,
)
from helpers import body_dict, req_date, req_enum
from middleware import authenticate, authorize, AGENCY_DIRECTOR, FEDERAL_OFFICER
from response import success_object
from serializers import ser_report
from services import generate_report_snapshot, notes_of_case

bp = Blueprint("reports", __name__)

DECISIONS = {"ACCEPTED", "REJECTED"}


def get_report_or_404(report_id):
    r = store.federal_reports.get(report_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Federal report not found.")
    return r


@bp.post("/federal-reports")
def create_report():
    _uid, role = authenticate()
    authorize(role, {AGENCY_DIRECTOR})
    d = body_dict()
    # Priority 4: schema — half-open period must be correctly ordered
    period_start = req_date(d, "period_start")
    period_end = req_date(d, "period_end")
    if not period_end > period_start:
        raise ApiError(ERR_VALIDATION, 400, "period_end must be strictly after period_start.")
    # Priority 8: temporal — periods must not overlap any existing report of
    # any status (half-open intervals; flush adjacency allowed).
    for other in store.federal_reports.values():
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError(
                ERR_REPORT_PERIOD_OVERLAP,
                409,
                "Report period overlaps an existing federal report.",
            )
    snapshot, included_case_ids = generate_report_snapshot(period_start, period_end)
    report = {
        "id": new_id(),
        "period_start": period_start,
        "period_end": period_end,
        "cases_arrived_count": snapshot["cases_arrived_count"],
        "benchmarks_met_count": snapshot["benchmarks_met_count"],
        "benchmarks_met_on_time_count": snapshot["benchmarks_met_on_time_count"],
        "benchmarks_pending_count": snapshot["benchmarks_pending_count"],
        "benchmarks_waived_count": snapshot["benchmarks_waived_count"],
        "per_capita_allocation_cents": snapshot["per_capita_allocation_cents"],
        "status": "DRAFT",
        "revision_count": 0,
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        # Internal only (never serialized): the frozen set of covered cases.
        "_included_case_ids": included_case_ids,
    }
    stamp_new(report)
    store.federal_reports[report["id"]] = report
    return success_object(ser_report(report), 201)


@bp.get("/federal-reports/<report_id>")
def get_report(report_id):
    authenticate()
    return success_object(ser_report(get_report_or_404(report_id)))


@bp.post("/federal-reports/<report_id>/submit")
def submit_report(report_id):
    uid, role = authenticate()
    authorize(role, {AGENCY_DIRECTOR})
    report = get_report_or_404(report_id)
    # Priority 6: state — only DRAFT reports can be submitted
    if report["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT report can be submitted.")
    # Priority 11: documentation gate — every included case must have at
    # least one CaseNote.
    for cid in report["_included_case_ids"]:
        if not notes_of_case(cid):
            raise ApiError(
                ERR_REPORT_DOCUMENTATION_INCOMPLETE,
                422,
                "An included case has no case note.",
            )
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = uid
    touch(report)
    return success_object(ser_report(report), 200)


@bp.post("/federal-reports/<report_id>/review")
def review_report(report_id):
    uid, role = authenticate()
    authorize(role, {FEDERAL_OFFICER})
    report = get_report_or_404(report_id)
    d = body_dict()
    # Priority 4: schema (review_note, if present, is accepted but not stored —
    # the FederalReport entity carries no review_note field)
    decision = req_enum(d, "decision", DECISIONS)
    # Priority 6: state — only SUBMITTED reports can be reviewed
    if report["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUBMITTED report can be reviewed.")
    # Priority 11: segregation of duties on user identity
    if uid == report["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Reviewer must differ from the report's submitter.",
        )
    report["reviewed_by_user_id"] = uid
    if decision == "ACCEPTED":
        report["status"] = "ACCEPTED"
    else:
        # Revision loop: back to DRAFT, submitter cleared, revision_count + 1.
        report["status"] = "DRAFT"
        report["submitted_by_user_id"] = None
        report["revision_count"] += 1
    touch(report)
    return success_object(ser_report(report), 200)
