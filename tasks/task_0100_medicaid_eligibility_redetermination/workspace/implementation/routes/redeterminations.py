"""Redetermination endpoints (PRD §3.8).

Open-redetermination validation order (endpoint-specific, after the universal
auth/RBAC/existence/well-formedness gates):
  5    OCC: expected_enrollment_version vs Enrollment.version -> ERR_STALE_VERSION (412)
  5.5  Enrollment already IN_REDETERMINATION -> ERR_REDETERMINATION_IN_PROGRESS (409)
  6    Any other non-ACTIVE state -> ERR_INVALID_STATE (409)
  11   Window overlap with a prior redetermination -> ERR_REDETERMINATION_WINDOW_OVERLAP (409)
"""
from __future__ import annotations

from flask import Blueprint, request

import db
import services
from common import (
    stamp_create, touch, serialize, serialize_list, sort_by_created,
    require_str, require_int, require_enum, get_or_404,
)
from datehelpers import parse_dt
from errors import (
    APIError,
    ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_INVALID_STATE,
    ERR_REDETERMINATION_IN_PROGRESS, ERR_REDETERMINATION_WINDOW_OVERLAP,
    ERR_DETERMINATION_INELIGIBLE, ERR_CONTINUOUS_COVERAGE_LOCK,
)
from middleware import authenticate, get_json_body, parse_pagination, paginate
from response import ok_object, ok_array

bp = Blueprint("redeterminations", __name__)

FINALIZE_TARGETS = {"RENEWED", "TERMINATED"}


def _half_open_intersect(o1, c1, o2, c2) -> bool:
    """[o1,c1) and [o2,c2) half-open windows intersect."""
    return o1 < c2 and o2 < c1


@bp.post("/redeterminations")
def create_redetermination():
    authenticate(["CaseWorker"])
    body = get_json_body()

    enrollment_id = require_str(body, "enrollment_id")
    window_open = require_str(body, "window_open")
    window_close = require_str(body, "window_close")
    new_determination_id = require_str(body, "new_determination_id")
    expected_enrollment_version = require_int(body, "expected_enrollment_version")

    # priority 3: existence of body FKs left-to-right.
    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Enrollment not found")
    if new_determination_id not in db.determinations:
        raise APIError(ERR_NOT_FOUND, 404, "EligibilityDetermination not found")

    # priority 5: OCC on parent Enrollment.version.
    if expected_enrollment_version != enr["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_enrollment_version is stale")

    # priority 5.5: endpoint-specific in-progress check wins over generic state.
    if enr["coverage_status"] == "IN_REDETERMINATION":
        raise APIError(ERR_REDETERMINATION_IN_PROGRESS, 409, "A redetermination is already in progress")
    # priority 6: any other non-ACTIVE state -> generic invalid state.
    if enr["coverage_status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not ACTIVE")

    # priority 11: window overlap with ANY prior redetermination for this
    # enrollment (including terminal RENEWED ones).
    o1 = parse_dt(window_open)
    c1 = parse_dt(window_close)
    for other in db.redeterminations.values():
        if other["enrollment_id"] != enrollment_id:
            continue
        o2 = parse_dt(other["window_open"])
        c2 = parse_dt(other["window_close"])
        if _half_open_intersect(o1, c1, o2, c2):
            raise APIError(ERR_REDETERMINATION_WINDOW_OVERLAP, 409, "Redetermination window overlaps a prior window")

    rec = {
        "enrollment_id": enrollment_id,
        "redet_status": "INITIATED",
        "window_open": window_open,
        "window_close": window_close,
        "info_request_count": 0,
        "new_determination_id": new_determination_id,
    }
    stamp_create(rec)
    db.redeterminations[rec["id"]] = rec

    # Cascade: Enrollment ACTIVE -> IN_REDETERMINATION; bump version.
    enr["coverage_status"] = "IN_REDETERMINATION"
    touch(enr)
    return ok_object(serialize(rec), 201)


@bp.get("/redeterminations/<rid>")
def get_redetermination(rid):
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    rec = get_or_404(db.redeterminations, rid, "Redetermination")
    return ok_object(serialize(rec), 200)


@bp.get("/redeterminations")
def list_redeterminations():
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    new_determination_id = request.args.get("new_determination_id")
    items = list(db.redeterminations.values())
    if enrollment_id is not None:
        items = [r for r in items if r["enrollment_id"] == enrollment_id]
    if new_determination_id is not None:
        items = [r for r in items if r["new_determination_id"] == new_determination_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/redeterminations/<rid>/request-info")
def request_info(rid):
    authenticate(["CaseWorker"])
    rec = get_or_404(db.redeterminations, rid, "Redetermination")
    # INITIATED -> INFO_REQUESTED, or INFO_REQUESTED self-loop.
    if rec["redet_status"] not in ("INITIATED", "INFO_REQUESTED"):
        raise APIError(ERR_INVALID_STATE, 409, "Redetermination cannot request info from its current state")
    rec["redet_status"] = "INFO_REQUESTED"
    rec["info_request_count"] = rec.get("info_request_count", 0) + 1
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/redeterminations/<rid>/finalize")
def finalize(rid):
    authenticate(["CaseWorker"])
    rec = get_or_404(db.redeterminations, rid, "Redetermination")
    body = get_json_body()
    target = require_enum(body, "target_status", FINALIZE_TARGETS)

    # priority 6: finalize is defined from INITIATED or INFO_REQUESTED.
    if rec["redet_status"] not in ("INITIATED", "INFO_REQUESTED"):
        raise APIError(ERR_INVALID_STATE, 409, "Redetermination is not in a finalizable state")

    det = db.determinations.get(rec["new_determination_id"])
    enr = db.enrollments.get(rec["enrollment_id"])

    if target == "RENEWED":
        # priority 15: linked determination must be ELIGIBLE.
        if det is None or det["decision"] != "ELIGIBLE":
            raise APIError(ERR_DETERMINATION_INELIGIBLE, 409, "Linked determination is not ELIGIBLE")
        rec["redet_status"] = "RENEWED"
        touch(rec)
        # Cascade: Enrollment IN_REDETERMINATION -> ACTIVE (no ledger change).
        if enr is not None and enr["coverage_status"] == "IN_REDETERMINATION":
            enr["coverage_status"] = "ACTIVE"
            touch(enr)
    else:  # TERMINATED
        # priority 15: linked determination must be INELIGIBLE.
        if det is None or det["decision"] != "INELIGIBLE":
            raise APIError(ERR_DETERMINATION_INELIGIBLE, 409, "Linked determination is not INELIGIBLE")
        # priority 7: continuous-coverage freeze blocks termination.
        hh = db.households.get(enr["household_id"]) if enr is not None else None
        state_rule = db.state_rules.get(hh["state_code"]) if hh is not None else None
        if state_rule is not None and state_rule.get("continuous_coverage_active"):
            raise APIError(ERR_CONTINUOUS_COVERAGE_LOCK, 409, "Terminations are frozen by the continuous-coverage directive")
        rec["redet_status"] = "TERMINATED"
        touch(rec)
        # Cascade: Enrollment IN_REDETERMINATION -> TERMINATED (debit ledger).
        if enr is not None and enr["coverage_status"] == "IN_REDETERMINATION":
            enr["coverage_status"] = "TERMINATED"
            touch(enr)
            services.debit_ledger(hh, enr["member_months"])
    return ok_object(serialize(rec), 200)
