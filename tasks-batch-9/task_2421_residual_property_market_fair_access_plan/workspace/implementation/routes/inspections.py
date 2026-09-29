"""Inspection completion and the improvement-requirement lifecycle (PRD 3.5)."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail, invalid
from middleware import own, require
from response import ok
from routes.common import matches, page
from services import inspection as inspection_svc
from services.constants import (
    COMPLETION_RESULTS,
    REQUIREMENT_CODES,
    REQUIREMENT_SEVERITIES,
    REQUIREMENT_STATUSES,
    REQUIREMENT_WINDOW_DAYS,
)
from util import add_days
from validate import (
    body,
    filter_enum,
    opt_string,
    pagination,
    present,
    req_enum,
    req_score,
    req_string,
    store_instant,
)

bp = Blueprint("inspections", __name__)


def _requirement_entries(data):
    """Validate the optional requirements array of {code, severity} entries."""
    if not present(data, "requirements"):
        return []
    raw = data["requirements"]
    if not isinstance(raw, list):
        invalid("Field 'requirements' must be an array")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            invalid("Each entry of 'requirements' must be an object")
        entries.append((
            req_enum(item, "code", REQUIREMENT_CODES),
            req_enum(item, "severity", REQUIREMENT_SEVERITIES),
        ))
    return entries


def _owning_application(requirement):
    inspection = db.inspections.get(requirement["inspection_id"])
    if inspection is None:
        return None
    return db.applications.get(inspection["application_id"])


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    require("Underwriter", "Inspector", "Producer", "PlanAdmin")
    return ok(lookup.inspection(inspection_id))


@bp.post("/inspections/<inspection_id>/completion")
def complete_inspection(inspection_id):
    caller = require("Inspector")
    data = body()
    observed_condition_score = req_score(data, "observed_condition_score")
    result = req_enum(data, "result", COMPLETION_RESULTS)
    entries = _requirement_entries(data)

    if result == "PASS" and entries:
        invalid("A PASS result may not carry improvement requirements")
    if result == "PASS_WITH_CONDITIONS" and not entries:
        invalid("A PASS_WITH_CONDITIONS result requires at least one requirement")

    inspection = lookup.inspection(inspection_id)
    if inspection["result"] != "PENDING":
        fail("ERR_INSPECTION_ALREADY_COMPLETED",
             "Inspection is already %s" % inspection["result"])

    now = db.now()
    inspection["inspector_user_id"] = caller.user_id
    inspection["completed_at"] = store_instant(now)
    inspection["observed_condition_score"] = observed_condition_score
    inspection["result"] = result

    application = db.applications.get(inspection["application_id"])

    if result == "PASS_WITH_CONDITIONS":
        due_at = store_instant(add_days(now, REQUIREMENT_WINDOW_DAYS))
        for code, severity in entries:
            requirement = new_record({
                "inspection_id": inspection["id"],
                "code": code,
                "severity": severity,
                "status": "OPEN",
                "due_at": due_at,
                "evidence_reference": None,
                "cleared_at": None,
                "waiver_reason": None,
            })
            db.requirements[requirement["id"]] = requirement
        inspection["open_requirement_count"] = len(entries)
        inspection["cleared_major_count"] = 0

    touch(inspection)

    if application is not None:
        if result == "PASS":
            inspection_svc.approve_to_bind(application)
        elif result == "PASS_WITH_CONDITIONS":
            application["status"] = "IMPROVEMENTS_REQUIRED"
            touch(application)
        else:
            application["status"] = "DECLINED"
            application["decline_reason"] = "INSPECTION_FAILED"
            touch(application)

    return ok(inspection)


@bp.get("/inspections/<inspection_id>/requirements")
def list_requirements(inspection_id):
    require("Underwriter", "Inspector", "Producer", "PlanAdmin")
    limit, offset = pagination()
    status = filter_enum("status", REQUIREMENT_STATUSES)
    inspection = lookup.inspection(inspection_id)
    rows = [r for r in db.requirements.values()
            if r["inspection_id"] == inspection["id"]
            and matches(r, {"status": status})]
    return page(rows, limit, offset)


@bp.post("/improvement-requirements/<requirement_id>/evidence")
def submit_evidence(requirement_id):
    caller = require("Producer")
    data = body()
    evidence_reference = req_string(data, "evidence_reference")

    requirement = lookup.requirement(requirement_id)
    application = _owning_application(requirement)
    own(application is not None and application["producer_id"] == caller.user_id,
        "Requirement belongs to another producer's application")

    if requirement["status"] != "OPEN":
        fail("ERR_REQUIREMENT_STATE_INVALID",
             "Requirement status %s does not accept evidence" % requirement["status"])

    requirement["evidence_reference"] = evidence_reference
    requirement["status"] = "EVIDENCE_SUBMITTED"
    touch(requirement)
    # open_requirement_count is deliberately left unchanged.
    return ok(requirement)


@bp.post("/improvement-requirements/<requirement_id>/clearance")
def clear_requirement(requirement_id):
    require("Inspector")
    data = body()
    opt_string(data, "note")

    requirement = lookup.requirement(requirement_id)
    if requirement["status"] != "EVIDENCE_SUBMITTED":
        fail("ERR_REQUIREMENT_STATE_INVALID",
             "Requirement status %s cannot be cleared" % requirement["status"])

    requirement["status"] = "CLEARED"
    requirement["cleared_at"] = store_instant(db.now())
    touch(requirement)

    inspection_svc.cascade_after_requirement_closed(requirement)
    return ok(requirement)


@bp.post("/improvement-requirements/<requirement_id>/waiver")
def waive_requirement(requirement_id):
    caller = require("Underwriter")
    data = body()
    reason = req_string(data, "reason")

    requirement = lookup.requirement(requirement_id)
    if requirement["status"] not in ("OPEN", "EVIDENCE_SUBMITTED"):
        fail("ERR_REQUIREMENT_STATE_INVALID",
             "Requirement status %s cannot be waived" % requirement["status"])

    inspection = db.inspections.get(requirement["inspection_id"])
    if inspection is not None and inspection["inspector_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The inspector who raised the requirement may not waive it")

    if requirement["severity"] != "MINOR":
        fail("ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE",
             "A MAJOR requirement must be physically remediated")

    requirement["status"] = "WAIVED"
    requirement["waiver_reason"] = reason
    requirement["cleared_at"] = store_instant(db.now())
    touch(requirement)

    inspection_svc.cascade_after_requirement_closed(requirement)
    return ok(requirement)
