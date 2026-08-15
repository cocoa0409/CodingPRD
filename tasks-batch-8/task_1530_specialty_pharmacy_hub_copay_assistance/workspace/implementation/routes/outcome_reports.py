"""Outcome reports: create (OCC-guarded), submit."""

from datetime import date

from flask import Blueprint

from db import store, new_id, now_iso, _parse_iso_datetime
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_INVALID_TRANSITION,
    ERR_ALREADY_TERMINAL,
    ERR_STALE_VERSION,
    ERR_REPORT_PERIOD_CLOSED,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, req_date, req_int,
    get_enrollment_or_404, get_report_or_404,
    pagination_params, paginate, touch,
)
from services.calc import (
    serialize_report, reports_for_enrollment, shipments_for_enrollment,
    aes_for_enrollment, compute_pdc_for_report,
)

bp = Blueprint("outcome_reports", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test on dates."""
    return a_start < b_end and b_start < a_end


@bp.post("/hub/enrollments/<eid>/outcome-reports")
def create_report(eid):
    user_id, _ = require_roles("CaseManager")
    e = get_enrollment_or_404(eid)
    data = body()
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    expected_version = req_int(data, "expected_enrollment_version")

    # Body schema: period_end strictly after period_start.
    if period_end <= period_start:
        raise ApiError(ERR_VALIDATION,
                       "period_end must be after period_start.", 400)

    # State validity: terminal enrollment rejects child-mutating ops.
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        # DISCONTINUED is explicitly a *permitted* state for report
        # creation per PRD 3.8 ("ACTIVE or DISCONTINUED"), so only
        # DENIED_CLOSED is rejected here. DENIED_CLOSED is terminal
        # and rejects child-mutating operations.
        if e["status"] == "DENIED_CLOSED":
            raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                           "Enrollment is terminal.", 409)
    if e["status"] not in ("ACTIVE", "DISCONTINUED"):
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Outcome report creation requires enrollment in "
                       "ACTIVE or DISCONTINUED.", 409)

    # OCC check.
    if expected_version != e["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_enrollment_version does not match the "
                       "enrollment's current version.", 412)

    # Domain constraint: period must not overlap a SUBMITTED report.
    existing = reports_for_enrollment(eid)
    for r in existing:
        if r["status"] != "SUBMITTED":
            continue
        if _overlaps(period_start, period_end,
                     date.fromisoformat(r["period_start"]),
                     date.fromisoformat(r["period_end"])):
            raise ApiError(ERR_REPORT_PERIOD_CLOSED,
                           "Period overlaps a submitted outcome report.", 422)

    # Compute metrics over the half-open period.
    fills_delivered = 0
    total_assistance = 0
    for s in shipments_for_enrollment(eid):
        if s["status"] != "DELIVERED":
            continue
        dd = date.fromisoformat(s["delivered_date"])
        if period_start <= dd < period_end:
            fills_delivered += 1
            total_assistance += s["assistance_pay_cents"] or 0

    ae_count = 0
    for ae in aes_for_enrollment(eid):
        if ae["status"] not in ("REPORTED", "ACKNOWLEDGED"):
            continue
        aware_date = _parse_iso_datetime(ae["awareness_at"]).date()
        if period_start <= aware_date < period_end:
            ae_count += 1

    pdc_pct = compute_pdc_for_report(e, period_end)

    ts = now_iso()
    report = {
        "id": new_id(),
        "enrollment_id": eid,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "created_by_user_id": user_id,
        "status": "DRAFT",
        "fills_delivered_count": fills_delivered,
        "adverse_event_count": ae_count,
        "total_assistance_cents": total_assistance,
        "pdc_pct": pdc_pct,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.outcome_reports[report["id"]] = report

    # Supersede overlapping DRAFTs.
    for r in existing:
        if r["status"] != "DRAFT":
            continue
        if _overlaps(period_start, period_end,
                     date.fromisoformat(r["period_start"]),
                     date.fromisoformat(r["period_end"])):
            r["status"] = "SUPERSEDED"
            touch(r)

    # Successful create increments enrollment.version by 1.
    touch(e)

    return success_object(serialize_report(report), 201)


@bp.get("/hub/enrollments/<eid>/outcome-reports")
def list_reports(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(reports_for_enrollment(eid), limit, offset)
    return success_array([serialize_report(r) for r in page],
                         limit, offset, total, 200)


@bp.post("/hub/outcome-reports/<rid>/submit")
def submit_report(rid):
    require_roles("CaseManager")
    r = get_report_or_404(rid)
    if r["status"] in ("SUBMITTED", "SUPERSEDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "Outcome report is terminal.", 409)
    if r["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Submit requires a DRAFT report.", 409)
    r["status"] = "SUBMITTED"
    touch(r)
    return success_object(serialize_report(r), 200)
