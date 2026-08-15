"""Accounts: create, close, clear-review-hold (PRD §3.2)."""
from flask import Blueprint, request

import store
from auth import (
    ALL_ROLES,
    authenticate,
    authorize,
    check_list_enrollment_param,
    check_ownership,
    scope_list,
)
from errors import (
    ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    raise_err,
)
from services import account_out, guard_enrollment_mutable
from util import body_json, bump, get_or_404, list_response, new_record, opt_nullable_int, req_str, success_object

bp = Blueprint("accounts", __name__)


@bp.route("/treasury/accounts", methods=["POST"])
def create_account():
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body = body_json()
    enrollment_id = req_str(body, "enrollment_id")
    account_number = req_str(body, "account_number")
    if not account_number.isdigit() or not (6 <= len(account_number) <= 17):
        raise_err(ERR_INVALID_REQUEST, "account_number must be 6-17 digits")
    threshold_present, threshold = opt_nullable_int(body, "payment_review_threshold_cents")
    if threshold_present and threshold is not None and threshold < 0:
        raise_err(ERR_INVALID_REQUEST, "payment_review_threshold_cents must be non-negative or null")
    enr = get_or_404(store.enrollments, enrollment_id, "TreasuryEnrollment")
    guard_enrollment_mutable(enr)
    duplicate = any(
        a["enrollment_id"] == enr["id"] and a["account_number"] == account_number
        for a in store.accounts.values()
    )
    if duplicate:
        raise_err(ERR_INVALID_REQUEST, "account_number must be unique within the enrollment")
    rec = new_record()
    rec.update({
        "enrollment_id": enr["id"],
        "account_number": account_number,
        "payment_review_threshold_cents": threshold if threshold_present else None,
        "status": "ACTIVE",
        "cumulative_paid_cents": 0,
        "cumulative_reversed_cents": 0,
        "net_settled_cents": 0,
    })
    store.accounts[rec["id"]] = rec
    return success_object(account_out(rec), 201)


@bp.route("/treasury/accounts/<aid>", methods=["GET"])
def get_account(aid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.accounts, aid, "Account")
    check_ownership(user, rec["enrollment_id"])
    return success_object(account_out(rec), 200)


@bp.route("/treasury/accounts", methods=["GET"])
def list_accounts():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.accounts.values(), user, lambda a: a["enrollment_id"])
    if enr_filter is not None:
        records = [a for a in records if a["enrollment_id"] == enr_filter]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, account_out)


@bp.route("/treasury/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body_json()
    rec = get_or_404(store.accounts, aid, "Account")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] == "CLOSED":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Account is already CLOSED")
    open_excs = any(
        e["account_id"] == rec["id"] and e["status"] == "OPEN"
        for e in store.exceptions.values()
    )
    if open_excs:
        raise_err(ERR_ACCOUNT_HAS_OPEN_EXCEPTIONS, "Account has OPEN exceptions")
    rec["status"] = "CLOSED"
    bump(rec)
    return success_object(account_out(rec), 200)


@bp.route("/treasury/accounts/<aid>/clear-review-hold", methods=["POST"])
def clear_review_hold(aid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankOps"])
    body_json()
    rec = get_or_404(store.accounts, aid, "Account")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "REVIEW_HOLD":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Account is not in REVIEW_HOLD")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(account_out(rec), 200)
