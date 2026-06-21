"""Appeal endpoints (PRD §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import services
from common import (
    stamp_create, touch, serialize, serialize_list, sort_by_created,
    require_str, require_int, require_enum, optional_bool, get_or_404,
)
from errors import (
    APIError,
    ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_NOT_TERMINATED,
)
from middleware import authenticate, get_json_body, parse_pagination, paginate, current_user_id
from response import ok_object, ok_array

bp = Blueprint("appeals", __name__)

RULE_TARGETS = {"UPHELD", "OVERTURNED"}


@bp.post("/appeals")
def file_appeal():
    authenticate(["Applicant"])
    body = get_json_body()

    enrollment_id = require_str(body, "enrollment_id")
    redetermination_id = require_str(body, "redetermination_id")
    aid_paid_pending = optional_bool(body, "aid_paid_pending", False)
    expected_enrollment_version = require_int(body, "expected_enrollment_version")

    # priority 3: existence of body FKs left-to-right.
    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Enrollment not found")
    redet = db.redeterminations.get(redetermination_id)
    if redet is None:
        raise APIError(ERR_NOT_FOUND, 404, "Redetermination not found")

    # priority 5: OCC on parent Enrollment.version.
    if expected_enrollment_version != enr["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_enrollment_version is stale")

    rec = {
        "enrollment_id": enrollment_id,
        "redetermination_id": redetermination_id,
        "appeal_status": "FILED",
        "adjudicator_id": None,
        "aid_paid_pending": aid_paid_pending,
    }
    stamp_create(rec)
    db.appeals[rec["id"]] = rec

    # Cascade: linked Redetermination TERMINATED -> PENDING_APPEAL.
    if redet["redet_status"] == "TERMINATED":
        redet["redet_status"] = "PENDING_APPEAL"
        touch(redet)
    # Increment parent Enrollment.version by one.
    touch(enr)
    return ok_object(serialize(rec), 201)


@bp.get("/appeals/<apid>")
def get_appeal(apid):
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    rec = get_or_404(db.appeals, apid, "Appeal")
    return ok_object(serialize(rec), 200)


@bp.get("/appeals")
def list_appeals():
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    redetermination_id = request.args.get("redetermination_id")
    items = list(db.appeals.values())
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    if redetermination_id is not None:
        items = [a for a in items if a["redetermination_id"] == redetermination_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/appeals/<apid>/schedule")
def schedule(apid):
    authenticate(["HearingOfficer"])
    rec = get_or_404(db.appeals, apid, "Appeal")
    if rec["appeal_status"] != "FILED":
        raise APIError(ERR_INVALID_STATE, 409, "Appeal is not FILED")
    rec["appeal_status"] = "HEARING_SCHEDULED"
    touch(rec)
    return ok_object(serialize(rec), 200)


def _underlying_caseworker_id(appeal: dict):
    """assigned_caseworker_id of the application underlying this appeal's
    enrollment (the determination's caseworker), for segregation of duties."""
    enr = db.enrollments.get(appeal["enrollment_id"])
    if enr is None:
        return None
    app = db.applications.get(enr["application_id"])
    if app is None:
        return None
    return app.get("assigned_caseworker_id")


@bp.post("/appeals/<apid>/hear")
def hear(apid):
    authenticate(["HearingOfficer"])
    rec = get_or_404(db.appeals, apid, "Appeal")
    if rec["appeal_status"] != "HEARING_SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appeal is not HEARING_SCHEDULED")
    # priority 8: segregation of duties.
    officer = current_user_id()
    caseworker = _underlying_caseworker_id(rec)
    if caseworker is not None and officer == caseworker:
        raise APIError(ERR_SEGREGATION_OF_DUTIES, 409, "Hearing officer must differ from the assigned caseworker")
    rec["appeal_status"] = "HEARD"
    rec["adjudicator_id"] = officer
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/appeals/<apid>/rule")
def rule(apid):
    authenticate(["HearingOfficer"])
    rec = get_or_404(db.appeals, apid, "Appeal")
    body = get_json_body()
    target = require_enum(body, "target_status", RULE_TARGETS)

    if rec["appeal_status"] != "HEARD":
        raise APIError(ERR_INVALID_STATE, 409, "Appeal is not HEARD")

    enr = db.enrollments.get(rec["enrollment_id"])
    if target == "UPHELD":
        rec["appeal_status"] = "UPHELD"
        touch(rec)
    else:  # OVERTURNED
        # priority 16: linked enrollment must be TERMINATED.
        if enr is None or enr["coverage_status"] != "TERMINATED":
            raise APIError(ERR_NOT_TERMINATED, 409, "Linked enrollment is not TERMINATED")
        rec["appeal_status"] = "OVERTURNED"
        touch(rec)
        # Cascade: Enrollment TERMINATED -> ACTIVE (re-credit ledger).
        enr["coverage_status"] = "ACTIVE"
        touch(enr)
        hh = db.households[enr["household_id"]]
        services.credit_ledger(hh, enr["member_months"])
    return ok_object(serialize(rec), 200)


@bp.post("/appeals/<apid>/withdraw")
def withdraw(apid):
    authenticate(["Applicant"])
    rec = get_or_404(db.appeals, apid, "Appeal")
    if rec["appeal_status"] not in ("FILED", "HEARING_SCHEDULED"):
        raise APIError(ERR_INVALID_STATE, 409, "Appeal cannot be withdrawn from its current state")
    rec["appeal_status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(serialize(rec), 200)
