"""Investigator and training-record endpoints (PRD §3.3, §3.9)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_STATE, ERR_TRAINING_WINDOW_INVALID
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_assignment, pub_investigator, pub_training
from util import (
    apply_filters,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_int,
    require_state_codes,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("investigators", __name__)


@bp.post("/siu/investigators")
@require_roles("SIUManager")
def create_investigator(_user_id: str, _role: str):
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    badge_number = require_string(body, "badge_number")
    state_certifications = require_state_codes(body, "state_certifications")
    max_active_cases = require_int(body, "max_active_cases", minimum=1, maximum=20)
    investigator = {
        "full_name": full_name,
        "email": email,
        "badge_number": badge_number,
        "state_certifications": state_certifications,
        "max_active_cases": max_active_cases,
        "active_case_count": 0,
        "status": "ACTIVE",
        "training_current_through": None,
    }
    db.stamp_new(investigator)
    db.investigators[investigator["id"]] = investigator
    return success_object(pub_investigator(investigator), 201)


@bp.get("/siu/investigators/<investigatorId>")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def get_investigator(investigatorId: str, _user_id: str, _role: str):
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    return success_object(pub_investigator(investigator))


@bp.get("/siu/investigators")
@require_roles("SIUManager", "SIUComplianceOfficer")
def list_investigators(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.investigators.values()), ["status"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_investigator(i) for i in page], limit, offset, total)


@bp.get("/siu/investigators/<investigatorId>/assignments")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_investigator_assignments(investigatorId: str, _user_id: str, _role: str):
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    limit, offset = parse_pagination()
    items = sort_created(
        [a for a in db.assignments.values() if a.get("investigator_id") == investigator["id"]]
    )
    page, total = page_of(items, limit, offset)
    return success_list([pub_assignment(a) for a in page], limit, offset, total)


@bp.get("/siu/investigators/<investigatorId>/training-records")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_investigator_training(investigatorId: str, _user_id: str, _role: str):
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    limit, offset = parse_pagination()
    items = sort_created(
        [t for t in db.training_records.values() if t.get("investigator_id") == investigator["id"]]
    )
    page, total = page_of(items, limit, offset)
    return success_list([pub_training(t) for t in page], limit, offset, total)


@bp.get("/siu/training-records")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def list_training_records(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.training_records.values()), ["investigator_id", "course_code"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_training(t) for t in page], limit, offset, total)


@bp.get("/siu/training-records/<recordId>")
@require_roles("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")
def get_training_record(recordId: str, _user_id: str, _role: str):
    record = path_or_404(db.training_records, recordId, "TrainingRecord")
    return success_object(pub_training(record))


@bp.post("/siu/investigators/<investigatorId>/training-records")
@require_roles("SIUInvestigator", "SIUManager")
def create_training_record(investigatorId: str, _user_id: str, _role: str):
    body = get_json_body()
    course_code = require_string(body, "course_code")
    completed_at = require_ts(body, "completed_at")
    valid_until = require_ts(body, "valid_until")
    credit_hours = require_int(body, "credit_hours")
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    # Business rule (priority 19): valid_until > completed_at and credit_hours >= 1.
    if db.parse_instant(valid_until) <= db.parse_instant(completed_at) or credit_hours < 1:
        raise_err(
            ERR_TRAINING_WINDOW_INVALID,
            "valid_until must be later than completed_at and credit_hours >= 1",
        )
    record = {
        "investigator_id": investigator["id"],
        "course_code": course_code,
        "completed_at": completed_at,
        "valid_until": valid_until,
        "credit_hours": credit_hours,
    }
    db.stamp_new(record)
    db.training_records[record["id"]] = record
    # Recompute currency: latest valid_until across the investigator's records.
    best = None
    best_raw = None
    for row in db.training_records.values():
        if row.get("investigator_id") != investigator["id"]:
            continue
        parsed = db.parse_instant(row.get("valid_until"))
        if parsed is not None and (best is None or parsed > best):
            best = parsed
            best_raw = row.get("valid_until")
    investigator["training_current_through"] = best_raw
    db.touch(investigator)
    return success_object(pub_training(record), 201)


@bp.post("/siu/investigators/<investigatorId>/suspend")
@require_roles("SIUManager")
def suspend_investigator(investigatorId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    if investigator.get("status") != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Investigator must be ACTIVE to be suspended")
    investigator["status"] = "SUSPENDED"
    db.touch(investigator)
    return success_object(pub_investigator(investigator))


@bp.post("/siu/investigators/<investigatorId>/reinstate")
@require_roles("SIUManager")
def reinstate_investigator(investigatorId: str, _user_id: str, _role: str):
    get_json_body()
    investigator = path_or_404(db.investigators, investigatorId, "Investigator")
    if investigator.get("status") != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Investigator must be SUSPENDED to be reinstated")
    investigator["status"] = "ACTIVE"
    db.touch(investigator)
    return success_object(pub_investigator(investigator))
