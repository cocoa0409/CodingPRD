"""Enrollment endpoints (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint

import db
import services
from common import (
    stamp_create, touch, serialize, serialize_list, sort_by_created,
    require_str, get_or_404,
)
from datehelpers import parse_dt
from errors import (
    APIError,
    ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_APPLICATION_NOT_APPROVED, ERR_COVERAGE_OVERLAP,
)
from middleware import authenticate, get_json_body, parse_pagination, paginate
from response import ok_object, ok_array

bp = Blueprint("enrollments", __name__)


@bp.post("/enrollments")
def create_enrollment():
    authenticate(["CaseWorker"])
    body = get_json_body()

    household_id = require_str(body, "household_id")
    application_id = require_str(body, "application_id")
    coverage_start = require_str(body, "coverage_start")
    coverage_end = require_str(body, "coverage_end")
    redetermination_due = require_str(body, "redetermination_due")

    # Existence (priority 3): body FKs left-to-right.
    if household_id not in db.households:
        raise APIError(ERR_NOT_FOUND, 404, "Household not found")
    if application_id not in db.applications:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")

    rec = {
        "household_id": household_id,
        "application_id": application_id,
        "coverage_status": "PENDING",
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "redetermination_due": redetermination_due,
        "member_months": 0,
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    rec = get_or_404(db.enrollments, eid, "Enrollment")
    return ok_object(serialize(rec), 200)


@bp.get("/enrollments")
def list_enrollments():
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    from flask import request
    limit, offset = parse_pagination()
    household_id = request.args.get("household_id")
    application_id = request.args.get("application_id")
    items = list(db.enrollments.values())
    if household_id is not None:
        items = [e for e in items if e["household_id"] == household_id]
    if application_id is not None:
        items = [e for e in items if e["application_id"] == application_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


def _closed_intervals_intersect(s1, e1, s2, e2) -> bool:
    """[s1,e1] and [s2,e2] closed intervals intersect."""
    return s1 <= e2 and s2 <= e1


@bp.post("/enrollments/<eid>/activate")
def activate_enrollment(eid):
    authenticate(["CaseWorker"])
    enr = get_or_404(db.enrollments, eid, "Enrollment")

    # priority 6: must be PENDING.
    if enr["coverage_status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not PENDING")
    # priority 9: linked application must be APPROVED.
    app = db.applications.get(enr["application_id"])
    if app is None or app["review_status"] != "APPROVED":
        raise APIError(ERR_APPLICATION_NOT_APPROVED, 409, "Linked application is not APPROVED")
    # priority 10: closed-interval coverage overlap with ACTIVE/IN_REDETERMINATION
    # enrollments of the same household.
    s1 = parse_dt(enr["coverage_start"])
    e1 = parse_dt(enr["coverage_end"])
    for other in db.enrollments.values():
        if other["id"] == eid:
            continue
        if other["household_id"] != enr["household_id"]:
            continue
        if other["coverage_status"] not in ("ACTIVE", "IN_REDETERMINATION"):
            continue
        s2 = parse_dt(other["coverage_start"])
        e2 = parse_dt(other["coverage_end"])
        if _closed_intervals_intersect(s1, e1, s2, e2):
            raise APIError(ERR_COVERAGE_OVERLAP, 409, "Coverage interval overlaps another active enrollment")

    hh = db.households[enr["household_id"]]
    enr["coverage_status"] = "ACTIVE"
    enr["member_months"] = hh["household_size"] * 12
    touch(enr)
    services.credit_ledger(hh, enr["member_months"])
    return ok_object(serialize(enr), 200)
