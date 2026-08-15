"""Inspection scheduling, completion, scoring, and CA spawning (PRD §3.5)."""
from datetime import timedelta

import db
from errors import (ApiError, ERR_INSPECTION_STATE, ERR_INVALID_WINDOW,
                    ERR_INSPECTOR_SCHEDULE_CONFLICT, ERR_INVALID_REQUEST,
                    forbidden_ownership)
from services.common import touch, refresh_posture, CA_DUE_DAYS


def validate_inspection_body(body):
    """Priority 2 well-formedness for POST /ehs/inspections: required fields
    present and parseable (window ordering is priority 16, checked in
    create_inspection after FK existence)."""
    from services.common import require_fields, require_string, require_datetime
    require_fields(body, ["lab_id", "inspector_id", "scheduled_start", "scheduled_end"])
    require_string(body, "inspector_id")
    require_datetime(body, "scheduled_start")
    require_datetime(body, "scheduled_end")


def create_inspection(lab, body):
    from services.common import require_string, require_datetime
    inspector_id = require_string(body, "inspector_id")
    start = require_datetime(body, "scheduled_start")
    end = require_datetime(body, "scheduled_end")
    if not (end > start):
        raise ApiError(ERR_INVALID_WINDOW,
                       "scheduled_end must be strictly after scheduled_start", 400)
    # Half-open overlap per inspector: overlap iff new_start < existing_end AND
    # existing_start < new_end; touching endpoints allowed.
    for other in db.inspections.values():
        if other["inspector_id"] != inspector_id or other["status"] != "SCHEDULED":
            continue
        if start < other["scheduled_end"] and other["scheduled_start"] < end:
            raise ApiError(ERR_INSPECTOR_SCHEDULE_CONFLICT,
                           "Inspector already has a SCHEDULED inspection overlapping this window", 409)
    insp = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "inspector_id": inspector_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "findings": None,
        "score_weighted": None,
        "score_flat": None,
        "outcome": None,
        "completed_by_inspector_id": None,
        "completed_at": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.inspections[insp["id"]] = insp
    return insp


def complete_inspection(insp, lab, user_id, findings):
    if user_id != insp["inspector_id"]:
        raise forbidden_ownership("Only the assigned inspector may complete this inspection")
    if insp["status"] != "SCHEDULED":
        raise ApiError(ERR_INSPECTION_STATE,
                       "Inspection must be SCHEDULED to complete", 409)

    # inspection_scoring (integer arithmetic; PASS boundary inclusive at 70).
    majors = sum(1 for f in findings if f["severity"] == "MAJOR")
    minors = sum(1 for f in findings if f["severity"] == "MINOR")
    score_weighted = 100 - 20 * majors - 5 * minors
    score_flat = 100 - 10 * len(findings)
    outcome = "PASS" if score_weighted >= 70 else "FAIL"

    now = db.now()
    insp["status"] = "COMPLETED"
    insp["findings"] = findings
    insp["score_weighted"] = score_weighted
    insp["score_flat"] = score_flat
    insp["outcome"] = outcome
    insp["completed_by_inspector_id"] = user_id
    insp["completed_at"] = now
    touch(insp)

    # One CorrectiveAction (OPEN) per finding; due completed_at + 14d / +30d.
    for f in findings:
        ca = {
            "id": db.new_id(),
            "inspection_id": insp["id"],
            "lab_id": lab["id"],
            "description": f["description"],
            "severity": f["severity"],
            "status": "OPEN",
            "due_date": now + timedelta(days=CA_DUE_DAYS[f["severity"]]),
            "resolution_note": None,
            "verified_by": None,
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.corrective_actions[ca["id"]] = ca

    # Posture recompute; FAIL with >= 1 MAJOR forces FROZEN (rule 3), and the
    # transition into FROZEN cascades ACTIVE registrations -> SUSPENDED.
    refresh_posture(lab)
    return insp


def validate_findings(body):
    """Priority 2: findings must be an array of {severity, description}."""
    findings = body.get("findings")
    if findings is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: findings", 400)
    if not isinstance(findings, list):
        raise ApiError(ERR_INVALID_REQUEST, "findings must be an array", 400)
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each finding must be an object", 400)
        if f.get("severity") not in ("MAJOR", "MINOR"):
            raise ApiError(ERR_INVALID_REQUEST,
                           "finding severity must be MAJOR or MINOR", 400)
        if not isinstance(f.get("description"), str) or f.get("description") == "":
            raise ApiError(ERR_INVALID_REQUEST,
                           "finding description must be a non-empty string", 400)
    return [{"severity": f["severity"], "description": f["description"]} for f in findings]
