"""Exception queue: reads, customer decisions, bank deadline extension (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_list_enrollment_param, check_ownership, scope_list
from errors import (
    ERR_DECISION_DEADLINE_PASSED,
    ERR_EXCEPTION_ALREADY_EXTENDED,
    ERR_EXCEPTION_NOT_OPEN,
    ERR_INVALID_REQUEST,
    ERR_SOD_UPLOAD_DECISION_CONFLICT,
    raise_err,
)
from services import exception_out, guard_enrollment_active, guard_enrollment_mutable, resolve_exception_decision
from util import body_json, bump, get_or_404, list_response, req_datetime, req_enum, success_object

bp = Blueprint("exceptions", __name__)


@bp.route("/treasury/exceptions/<eid>", methods=["GET"])
def get_exception(eid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.exceptions, eid, "ExceptionItem")
    check_ownership(user, rec["enrollment_id"])
    return success_object(exception_out(rec), 200)


@bp.route("/treasury/exceptions", methods=["GET"])
def list_exceptions():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.exceptions.values(), user, lambda e: e["enrollment_id"])
    if enr_filter is not None:
        records = [e for e in records if e["enrollment_id"] == enr_filter]
    for param in ("account_id", "presented_item_id", "issued_check_id",
                  "fee_entry_id", "decided_by_user_id", "status", "reason"):
        v = request.args.get(param)
        if v is not None:
            records = [e for e in records if str(e.get(param)) == v]
    return list_response(records, exception_out)


@bp.route("/treasury/exceptions/<eid>/decision", methods=["POST"])
def decide_exception(eid):
    uid, role, user = authenticate()
    authorize(role, user, ["CustomerManager", "CustomerDecisionMaker"])
    exc = store.exceptions.get(eid)
    if exc is not None:
        check_ownership(user, exc["enrollment_id"])
    body = body_json()
    decision = req_enum(body, "decision", ["PAY", "RETURN"])
    if exc is None:
        get_or_404(store.exceptions, eid, "ExceptionItem")
    enr = store.enrollments[exc["enrollment_id"]]
    guard_enrollment_active(enr)
    if exc["status"] != "OPEN":
        raise_err(ERR_EXCEPTION_NOT_OPEN, "Exception is not OPEN")
    if clock.now() > exc["decision_deadline_at"]:
        raise_err(ERR_DECISION_DEADLINE_PASSED, "Decision deadline has passed")
    # segregation of duties: the issue-file uploader may not decision (§2.8)
    if exc["issued_check_id"] is not None:
        check = store.checks.get(exc["issued_check_id"])
        upload = store.uploads.get(check["issue_file_id"]) if check else None
        if upload is not None and upload["uploaded_by_user_id"] == uid:
            raise_err(
                ERR_SOD_UPLOAD_DECISION_CONFLICT,
                "The issue-file uploader may not decision this exception",
            )
    resolve_exception_decision(exc, decision, uid)
    return success_object(exception_out(exc), 200)


@bp.route("/treasury/exceptions/<eid>/extend-deadline", methods=["POST"])
def extend_deadline(eid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body = body_json()
    new_deadline = req_datetime(body, "new_deadline_at")
    exc = get_or_404(store.exceptions, eid, "ExceptionItem")
    enr = store.enrollments[exc["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if exc["status"] != "OPEN":
        raise_err(ERR_EXCEPTION_NOT_OPEN, "Exception is not OPEN")
    if exc["extended_once"]:
        raise_err(ERR_EXCEPTION_ALREADY_EXTENDED, "Deadline was already extended once")
    now = clock.now()
    if now > exc["decision_deadline_at"]:
        raise_err(ERR_DECISION_DEADLINE_PASSED, "Decision deadline has passed")
    # shape-layer window: (current deadline, current deadline + 24h]
    if not (exc["decision_deadline_at"] < new_deadline <= exc["decision_deadline_at"] + timedelta(hours=24)):
        raise_err(
            ERR_INVALID_REQUEST,
            "new_deadline_at must be within (current deadline, current deadline + 24h]",
        )
    exc["decision_deadline_at"] = new_deadline
    exc["extended_once"] = True
    bump(exc)
    return success_object(exception_out(exc), 200)
