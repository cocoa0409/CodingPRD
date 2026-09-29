"""Outcome reporting, monitoring site visits and closure (PRD 3.9)."""

from flask import Blueprint

from auth import (ALL_ROLES, authenticate, get_report, get_request,
                  ownership_violation, require_agency_self)
from envelope import created, filter_str, ok, paginate
from errors import ApiError
from store import (base_entity, date_of, db, now_iso, plus_days, q2,
                   sort_created_asc, touch)
from validators import body, get_date, get_int, get_money, get_number, get_str

from services import aggregates, calc

bp = Blueprint("reports", __name__)

BUFFER_STATUSES = (
    "SITE_VISIT_SCHEDULED",
    "SITE_VISIT_COMPLETED",
    "REVISION_REQUESTED",
    "ACCEPTED",
)


def _report_request(report):
    return db.requests[report["request_id"]]


def _report_agency(report):
    return db.agencies[_report_request(report)["agency_id"]]


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@bp.get("/outcome-reports/<report_id>")
def read_report(report_id):
    authenticate(ALL_ROLES)
    return ok(get_report(report_id))


@bp.get("/outcome-reports")
def list_reports():
    authenticate(ALL_ROLES)
    rows = list(db.reports.values())
    request_id = filter_str("request_id")
    panelist_id = filter_str("site_visit_panelist_id")
    status = filter_str("status")
    if request_id is not None:
        rows = [r for r in rows if r["request_id"] == request_id]
    if panelist_id is not None:
        rows = [r for r in rows if r["site_visit_panelist_id"] == panelist_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created_asc(rows))


# --------------------------------------------------------------------------- #
# filing
# --------------------------------------------------------------------------- #


@bp.post("/allocation-requests/<request_id>/outcome-reports")
def file_report(request_id):
    role, user_id = authenticate(("UnitedFundAdmin", "AgencyRepresentative"))
    data = body()
    period_end = get_date(data, "reporting_period_end")
    persons_served = get_int(data, "persons_served", minimum=0)
    metric_name = get_str(data, "outcome_metric_name", min_len=1, max_len=120)
    metric_value = get_number(data, "outcome_metric_value", minimum=0)
    funds_expended = get_money(data, "funds_expended", minimum=0)

    req = get_request(request_id)
    if role == "AgencyRepresentative":
        require_agency_self(user_id, req["agency_id"])
    if req["status"] != "AWARDED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    row = base_entity()
    row.update({
        "request_id": request_id,
        "reporting_period_end": period_end.isoformat(),
        "persons_served": persons_served,
        "outcome_metric_name": metric_name,
        "outcome_metric_value": metric_value,
        "funds_expended": q2(funds_expended),
        "status": "SUBMITTED",
        "revision_round_count": 0,
        "site_visit_panelist_id": None,
        "site_visit_window_start": None,
        "site_visit_window_end": None,
        "site_visit_findings": None,
        "expenditure_variance_pct": calc.expenditure_variance(
            funds_expended, req["total_award"]
        ),
        "submitted_at": now_iso(),
    })
    db.reports[row["id"]] = row

    req["status"] = "REPORTING"
    touch("request", req)
    aggregates.recompute_agency_delinquency(db.agencies[req["agency_id"]])
    return created(row)


# --------------------------------------------------------------------------- #
# monitoring site visits
# --------------------------------------------------------------------------- #


@bp.post("/outcome-reports/<report_id>/site-visit")
def schedule_site_visit(report_id):
    role, user_id = authenticate(("VolunteerPanelist",))
    data = body()
    window_start = get_date(data, "site_visit_window_start")
    window_end = get_date(data, "site_visit_window_end")

    report = get_report(report_id)
    req = _report_request(report)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    # PRD 3.9 enumerates these four checks explicitly: segregation of duties,
    # then the seat, then window sanity, then spacing.
    for score in aggregates.request_scores(report["request_id"]):
        if score["panelist_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if aggregates.assignment_for(req["cycle_id"], user_id) is None:
        raise ApiError("ERR_PANELIST_NOT_ASSIGNED")

    submitted_date = date_of(report["submitted_at"])
    latest = plus_days(submitted_date, calc.SITE_VISIT_MAX_LEAD_DAYS)
    if window_start < submitted_date:
        raise ApiError("ERR_SITE_VISIT_WINDOW_INVALID")
    if window_end < window_start:
        raise ApiError("ERR_SITE_VISIT_WINDOW_INVALID")
    if window_end > latest:
        raise ApiError("ERR_SITE_VISIT_WINDOW_INVALID")

    buffer_days = calc.SITE_VISIT_BUFFER_DAYS
    for other in db.reports.values():
        if other["id"] == report_id:
            continue
        if other["site_visit_panelist_id"] != user_id:
            continue
        if other["status"] not in BUFFER_STATUSES:
            continue
        if other["site_visit_window_start"] is None:
            continue
        other_start = date_of(other["site_visit_window_start"])
        other_end = date_of(other["site_visit_window_end"])
        if (window_start <= plus_days(other_end, buffer_days)
                and other_start <= plus_days(window_end, buffer_days)):
            raise ApiError("ERR_SITE_VISIT_BUFFER_CONFLICT")

    report["site_visit_panelist_id"] = user_id
    report["site_visit_window_start"] = window_start.isoformat()
    report["site_visit_window_end"] = window_end.isoformat()
    report["status"] = "SITE_VISIT_SCHEDULED"
    touch("report", report)
    aggregates.recompute_panelist_counters(db.panelists[user_id])
    return ok(report)


@bp.post("/outcome-reports/<report_id>/site-visit/complete")
def complete_site_visit(report_id):
    role, user_id = authenticate(("VolunteerPanelist",))
    data = body()
    findings = get_str(data, "site_visit_findings", min_len=1)

    report = get_report(report_id)
    # Gate 6 is only evaluable once a visit has been scheduled; an unscheduled
    # report carries a null site_visit_panelist_id and falls through to gate 21.
    if (report["site_visit_panelist_id"] is not None
            and report["site_visit_panelist_id"] != user_id):
        ownership_violation()
    if report["status"] != "SITE_VISIT_SCHEDULED":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    report["site_visit_findings"] = findings
    report["status"] = "SITE_VISIT_COMPLETED"
    touch("report", report)
    return ok(report)


# --------------------------------------------------------------------------- #
# disposition
# --------------------------------------------------------------------------- #


@bp.post("/outcome-reports/<report_id>/accept")
def accept_report(report_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    body()
    report = get_report(report_id)
    if report["status"] != "SITE_VISIT_COMPLETED":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    report["status"] = "ACCEPTED"
    touch("report", report)
    req = _report_request(report)
    if req["status"] == "REPORTING":
        req["status"] = "CLOSED_SATISFIED"
        touch("request", req)
    aggregates.recompute_agency_delinquency(db.agencies[req["agency_id"]])
    return ok(report)


@bp.post("/outcome-reports/<report_id>/request-revision")
def request_revision(report_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    data = body()
    get_str(data, "revision_note", min_len=1)

    report = get_report(report_id)
    if report["status"] != "SITE_VISIT_COMPLETED":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if report["revision_round_count"] >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    report["status"] = "REVISION_REQUESTED"
    report["revision_round_count"] += 1
    touch("report", report)
    return ok(report)


@bp.post("/outcome-reports/<report_id>/resubmit")
def resubmit_report(report_id):
    role, user_id = authenticate(("UnitedFundAdmin", "AgencyRepresentative"))
    data = body()
    persons_served = get_int(data, "persons_served", minimum=0)
    metric_value = get_number(data, "outcome_metric_value", minimum=0)
    funds_expended = get_money(data, "funds_expended", minimum=0)

    report = get_report(report_id)
    req = _report_request(report)
    if role == "AgencyRepresentative":
        require_agency_self(user_id, req["agency_id"])
    if report["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    report["persons_served"] = persons_served
    report["outcome_metric_value"] = metric_value
    report["funds_expended"] = q2(funds_expended)
    # PRD 3.9 clears only the findings; the historic window and its panelist
    # deliberately stay on the record so the buffer rule still sees them.
    report["site_visit_findings"] = None
    report["expenditure_variance_pct"] = calc.expenditure_variance(
        funds_expended, req["total_award"]
    )
    report["submitted_at"] = now_iso()
    report["status"] = "SUBMITTED"
    touch("report", report)
    return ok(report)
