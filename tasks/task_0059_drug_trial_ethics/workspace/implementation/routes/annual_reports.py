from __future__ import annotations

"""Annual report endpoints."""

from flask import Blueprint, g, request

import db
from clock import parse_iso
from errors import (
    ERR_FIELD_VALIDATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    raise_error,
)
from middleware import ensure_owns_application, require_role
from response import success_array, success_object
from serializers import serialize_annual_report
import services_state as svc
from validation import (
    get_json_body,
    get_pagination,
    require_datetime,
    require_enum,
    require_int,
    sort_default,
)


bp = Blueprint("annual_reports", __name__)


REPORT_KINDS = {"ANNUAL_PROGRESS", "PROTOCOL_AMENDMENT", "FINAL_REPORT"}


# ---------------------------------------------------------------------------
# POST /ethics/applications/{aid}/annual-reports
# ---------------------------------------------------------------------------
@bp.post("/ethics/applications/<aid>/annual-reports")
def create_annual_report(aid):
    require_role({"Applicant"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    ensure_owns_application(app)

    body = get_json_body()
    report_period_start = require_datetime(body, "report_period_start")
    report_period_end = require_datetime(body, "report_period_end")
    report_kind = require_enum(body, "report_kind", REPORT_KINDS)
    serious = require_int(body, "serious_adverse_event_count", min_value=0)
    total = require_int(body, "total_adverse_event_count", min_value=0)
    enrollment = require_int(body, "enrollment_count", min_value=0)
    if serious > total:
        raise_error(ERR_FIELD_VALIDATION,
                    "serious_adverse_event_count must be <= total_adverse_event_count")

    with db.lock:
        if app["status"] not in ("APPROVED", "APPROVED_WITH_MOD"):
            raise_error(ERR_INVALID_STATE,
                        f"Application must be APPROVED or APPROVED_WITH_MOD (got '{app['status']}')")

        flag = svc.compute_safety_alert_flag(serious, total, enrollment)
        ar = svc.new_versioned({
            "application_id": aid,
            "report_period_start": report_period_start,
            "report_period_end": report_period_end,
            "report_kind": report_kind,
            "serious_adverse_event_count": serious,
            "total_adverse_event_count": total,
            "enrollment_count": enrollment,
            "outcome": None,
            "safety_alert_flag": flag,
            "status": "SUBMITTED",
        })
        db.annual_reports[ar["id"]] = ar
    return success_object(serialize_annual_report(ar), 201)


# ---------------------------------------------------------------------------
# GET /ethics/applications/{aid}/annual-reports
# ---------------------------------------------------------------------------
@bp.get("/ethics/applications/<aid>/annual-reports")
def list_annual_reports(aid):
    require_role({"Applicant", "Secretary", "Chairperson", "CommitteeMember", "RegulatoryWatcher"})
    app = db.applications.get(aid)
    if not app:
        raise_error(ERR_NOT_FOUND, f"Application {aid} not found")
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "Applicant may not read other applications' reports")

    limit, offset = get_pagination()
    kind_f = request.args.get("report_kind")
    rows = [r for r in db.annual_reports.values() if r["application_id"] == aid]
    if kind_f:
        rows = [r for r in rows if r["report_kind"] == kind_f]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_annual_report(r) for r in page],
                         limit=limit, offset=offset, total_count=total)
