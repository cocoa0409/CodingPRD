"""Employment authorizations (CPT/OPT) and employment periods (PRD §3.5)."""

from datetime import date, timedelta

from flask import Blueprint, request

import db
import services
from db import clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_AUTH_INVALID_STATE,
    ERR_AUTH_WINDOW_INVALID,
    ERR_EMPLOYMENT_PERIOD_OVERLAP,
    ERR_I20_NOT_ISSUED,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OPT_WINDOW_CLOSED,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RESOURCE_NOT_OWNED,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, opt_date, opt_str,
    req_date, req_enum, req_int, req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import employment_authorization_out, employment_period_out

bp = Blueprint("employment", __name__)

AUTH_TYPES = ("CPT", "OPT_PRE", "OPT_POST")
AUTH_ACTIONS = ("RECOMMEND", "REVISE", "FILE", "ADJUDICATE", "CANCEL")
ADJUDICATE_OUTCOMES = ("APPROVED", "DENIED")


def _check_auth_scope(user_id, role, auth):
    if role == "Student" and auth["student_id"] != user_id:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only act on their own authorizations")


# ---------------------------------------------------------------------------
# Employment authorizations
# ---------------------------------------------------------------------------

@bp.route("/sevis/employment-authorizations", methods=["POST"])
def create_authorization():
    require_roles(STAFF_ROLES)
    data = body()
    student_id = req_str(data, "student_id")
    auth_type = req_enum(data, "auth_type", AUTH_TYPES)
    employer_name = opt_str(data, "employer_name")
    hours_per_week = req_int(data, "hours_per_week", min_value=1)
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    if parse_date(end_date) <= parse_date(start_date):
        raise_error(ERR_INVALID_REQUEST, "end_date must be later than start_date")
    if auth_type == "CPT" and not employer_name:
        raise_error(ERR_INVALID_REQUEST, "employer_name is required for CPT")
    student = get_student_or_404(student_id)
    auth = {
        "id": new_id(),
        "student_id": student["id"],
        "auth_type": auth_type,
        "employer_name": employer_name,
        "hours_per_week": hours_per_week,
        "start_date": start_date,
        "end_date": end_date,
        "uscis_receipt_number": None,
        "status": "DRAFT",
    }
    stamp_new(auth)
    db.employment_authorizations[auth["id"]] = auth
    return success_object(employment_authorization_out(auth), 201)


@bp.route("/sevis/employment-authorizations", methods=["GET"])
def list_authorizations():
    user_id, role = require_roles(ALL_ROLES)
    student_filter = request.args.get("student_id")
    if role == "Student":
        if student_filter is not None and student_filter != user_id:
            raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only list their own resources")
        student_filter = user_id
    filters = {
        "student_id": student_filter,
        "auth_type": request.args.get("auth_type"),
        "status": request.args.get("status"),
    }
    return list_response(
        list(db.employment_authorizations.values()), employment_authorization_out, filters
    )


@bp.route("/sevis/employment-authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    user_id, role = require_roles(ALL_ROLES)
    auth = get_or_404(db.employment_authorizations, aid, "EmploymentAuthorization")
    _check_auth_scope(user_id, role, auth)
    return success_object(employment_authorization_out(auth), 200)


@bp.route("/sevis/employment-authorizations/<aid>/transition", methods=["POST"])
def transition_authorization(aid):
    user_id, role = require_roles(ALL_ROLES)
    auth = get_or_404(db.employment_authorizations, aid, "EmploymentAuthorization")
    data = body()
    action = req_enum(data, "action", AUTH_ACTIONS)

    # Action-specific role rule (priority 2): FILE is a Student-only action;
    # the other actions are staff-only.
    if action == "FILE":
        if role != "Student":
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "FILE is a Student action")
    else:
        if role not in STAFF_ROLES:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "This action requires a DSO or PDSO")
    if role == "Student":
        _check_auth_scope(user_id, role, auth)

    record = services.record_of_student(auth["student_id"])

    if action == "RECOMMEND":
        if auth["status"] != "DRAFT":
            raise_error(ERR_AUTH_INVALID_STATE, "Authorization must be DRAFT to recommend")
        if record is None or record["status"] != "ACTIVE":
            raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be ACTIVE to recommend employment")
        if not services.issued_forms_of_student(auth["student_id"]):
            raise_error(ERR_I20_NOT_ISSUED, "An ISSUED I-20 is required to recommend employment")
        program_end = parse_date(record["program_end_date"])
        if auth["auth_type"] in ("CPT", "OPT_PRE"):
            if parse_date(auth["end_date"]) > program_end:
                raise_error(ERR_AUTH_WINDOW_INVALID, "CPT/OPT_PRE end_date must be on or before program_end_date")
        else:  # OPT_POST
            start = parse_date(auth["start_date"])
            if not (program_end + timedelta(days=1) <= start
                    <= program_end + timedelta(days=services.OPT_POST_START_WINDOW_DAYS)):
                raise_error(ERR_OPT_WINDOW_CLOSED, "OPT_POST start_date must fall within [program_end_date + 1 day, program_end_date + 60 days]")
        auth["status"] = "RECOMMENDED"

    elif action == "REVISE":
        if auth["status"] != "RECOMMENDED":
            raise_error(ERR_AUTH_INVALID_STATE, "Authorization must be RECOMMENDED to revise")
        auth["status"] = "DRAFT"

    elif action == "FILE":
        receipt = req_str(data, "uscis_receipt_number")
        if auth["status"] != "RECOMMENDED":
            raise_error(ERR_AUTH_INVALID_STATE, "Authorization must be RECOMMENDED to file")
        if auth["auth_type"] not in ("OPT_PRE", "OPT_POST"):
            raise_error(ERR_AUTH_INVALID_STATE, "Only OPT authorizations are filed with USCIS")
        program_end = parse_date(record["program_end_date"])
        today = clock_date()
        if not (program_end - timedelta(days=services.OPT_FILE_BEFORE_DAYS) <= today
                <= program_end + timedelta(days=services.OPT_FILE_AFTER_DAYS)):
            raise_error(ERR_OPT_WINDOW_CLOSED, "OPT filing window is [program_end_date - 90 days, program_end_date + 60 days]")
        auth["uscis_receipt_number"] = receipt
        auth["status"] = "FILED"

    elif action == "ADJUDICATE":
        outcome = req_enum(data, "outcome", ADJUDICATE_OUTCOMES)
        if auth["auth_type"] == "CPT":
            # CPT adjudicates directly from RECOMMENDED, APPROVED only.
            if auth["status"] != "RECOMMENDED" or outcome != "APPROVED":
                raise_error(ERR_AUTH_INVALID_STATE, "CPT adjudicates from RECOMMENDED with outcome APPROVED")
            auth["status"] = "APPROVED"
        else:
            # OPT must pass through FILED.
            if auth["status"] != "FILED":
                raise_error(ERR_AUTH_INVALID_STATE, "OPT authorizations must be FILED before adjudication")
            auth["status"] = "APPROVED" if outcome == "APPROVED" else "DENIED"

    else:  # CANCEL
        if auth["status"] not in ("DRAFT", "RECOMMENDED"):
            raise_error(ERR_AUTH_INVALID_STATE, "Only DRAFT or RECOMMENDED authorizations can be cancelled")
        auth["status"] = "CANCELLED"

    touch(auth)
    return success_object(employment_authorization_out(auth), 200)


# ---------------------------------------------------------------------------
# Employment periods (day-coverage non-overlap; adjacency permitted)
# ---------------------------------------------------------------------------

@bp.route("/sevis/employment-authorizations/<aid>/employment-periods", methods=["POST"])
def create_employment_period(aid):
    user_id, role = require_roles(ALL_ROLES)
    auth = get_or_404(db.employment_authorizations, aid, "EmploymentAuthorization")
    _check_auth_scope(user_id, role, auth)
    data = body()
    employer_name = req_str(data, "employer_name")
    start_date = req_date(data, "start_date")
    end_date = opt_date(data, "end_date")
    hours_per_week = req_int(data, "hours_per_week", min_value=1)
    new_start = parse_date(start_date)
    new_end = parse_date(end_date) if end_date is not None else None
    if new_end is not None and new_end < new_start:
        raise_error(ERR_INVALID_REQUEST, "end_date must be on or after start_date")
    if auth["status"] != "APPROVED":
        raise_error(ERR_AUTH_INVALID_STATE, "Employment periods are reported under an APPROVED authorization")
    far_future = date.max
    for existing in services.periods_of_authorization(auth["id"]):
        ex_start = parse_date(existing["start_date"])
        ex_end = parse_date(existing["end_date"]) if existing["end_date"] else far_future
        # Day-coverage semantics: any shared calendar day is an overlap;
        # zero-gap adjacency (start == prior end + 1 day) is permitted.
        if new_start <= ex_end and ex_start <= (new_end if new_end is not None else far_future):
            raise_error(ERR_EMPLOYMENT_PERIOD_OVERLAP, "Employment period shares a calendar day with an existing period")
    period = {
        "id": new_id(),
        "authorization_id": auth["id"],
        "employer_name": employer_name,
        "start_date": start_date,
        "end_date": end_date,
        "hours_per_week": hours_per_week,
    }
    before = services.unemployment_counters(auth)
    stamp_new(period)
    db.employment_periods[period["id"]] = period
    after = services.unemployment_counters(auth)
    if after != before:
        touch(auth)
    services.recompute_posture(auth["student_id"])
    return success_object(employment_period_out(period), 201)


@bp.route("/sevis/employment-authorizations/<aid>/employment-periods", methods=["GET"])
def list_employment_periods(aid):
    user_id, role = require_roles(ALL_ROLES)
    auth = get_or_404(db.employment_authorizations, aid, "EmploymentAuthorization")
    _check_auth_scope(user_id, role, auth)
    items = services.periods_of_authorization(auth["id"])
    return list_response(items, employment_period_out)


@bp.route("/sevis/employment-periods/<pid>", methods=["DELETE"])
def delete_employment_period(pid):
    require_roles(STAFF_ROLES)
    period = get_or_404(db.employment_periods, pid, "EmploymentPeriod")
    auth = db.employment_authorizations.get(period["authorization_id"])
    before = services.unemployment_counters(auth) if auth is not None else None
    del db.employment_periods[pid]
    if auth is not None:
        after = services.unemployment_counters(auth)
        if after != before:
            touch(auth)
        services.recompute_posture(auth["student_id"])
    return "", 204
