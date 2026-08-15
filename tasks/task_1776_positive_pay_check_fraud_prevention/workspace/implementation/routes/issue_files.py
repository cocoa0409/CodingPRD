"""Issued-check file intake (PRD §3.3) and IssuedCheck reads/void."""
from datetime import datetime

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
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_CHECK_NOT_VOIDABLE,
    ERR_IDEMPOTENCY_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_TIER_FORBIDS_ISSUE_FILES,
    raise_err,
)
from services import (
    canonical_rows_hash,
    check_enrollment_id,
    check_out,
    guard_enrollment_active,
    upload_out,
    validate_issue_row,
)
from util import body_json, bump, get_or_404, list_response, new_record, req_str, success_object

bp = Blueprint("issue_files", __name__)


@bp.route("/treasury/issue-files", methods=["POST"])
def upload_issue_file():
    uid, role, user = authenticate()
    authorize(role, user, ["CustomerAdmin", "CustomerManager"])
    body = body_json()
    enrollment_id = req_str(body, "enrollment_id")
    account_id = req_str(body, "account_id")
    file_reference = req_str(body, "file_reference")
    rows = body.get("rows")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise_err(ERR_INVALID_REQUEST, "rows must be an array of row objects")

    enr = get_or_404(store.enrollments, enrollment_id, "TreasuryEnrollment")
    acct = get_or_404(store.accounts, account_id, "Account")
    check_ownership(user, enr["id"])
    # whole-file gates, outermost state first (PRD §2.10)
    guard_enrollment_active(enr)
    if acct["enrollment_id"] != enr["id"] or acct["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Account must belong to the enrollment and be ACTIVE")
    if enr["tier"] == "REVERSE_POSITIVE_PAY":
        raise_err(ERR_TIER_FORBIDS_ISSUE_FILES, "REVERSE_POSITIVE_PAY enrollments submit no issue files")

    # idempotent replay on (enrollment_id, file_reference)
    payload_hash = canonical_rows_hash(rows)
    for prior in store.uploads.values():
        if prior["enrollment_id"] == enr["id"] and prior["file_reference"] == file_reference:
            if prior["payload_hash"] == payload_hash:
                return success_object(upload_out(prior), 201)
            raise_err(ERR_IDEMPOTENCY_CONFLICT, "file_reference already used with a different payload")

    row_errors = []
    accepted = []
    seen_in_file = set()
    for idx, row in enumerate(rows):
        reason = validate_issue_row(row, acct["id"], seen_in_file)
        if reason is not None:
            row_errors.append({
                "row_index": idx,
                "check_number": row.get("check_number") if isinstance(row, dict) else None,
                "reason": reason,
            })
            continue
        seen_in_file.add(row["check_number"])
        accepted.append(row)

    created_checks = []
    for row in accepted:
        chk = new_record()
        chk.update({
            "account_id": acct["id"],
            "issue_file_id": None,  # linked after the upload record exists
            "check_number": row["check_number"],
            "amount_cents": row["amount_cents"],
            "payee_name": row["payee_name"],
            "issue_date": datetime.strptime(row["issue_date"].strip(), "%Y-%m-%d").date(),
            "status": "REGISTERED",
            "consumed_by_item_id": None,
        })
        created_checks.append(chk)

    rec = new_record()
    rec.update({
        "enrollment_id": enr["id"],
        "account_id": acct["id"],
        "uploaded_by_user_id": uid,
        "file_reference": file_reference,
        "payload_hash": payload_hash,
        "row_count": len(rows),
        "accepted_row_count": len(created_checks),
        "rejected_row_count": len(row_errors),
        "row_errors": row_errors,
        "status": (
            "ACCEPTED" if len(created_checks) == len(rows)
            else "PARTIALLY_ACCEPTED" if created_checks
            else "REJECTED"
        ),
    })
    store.uploads[rec["id"]] = rec
    for chk in created_checks:
        chk["issue_file_id"] = rec["id"]
        store.checks[chk["id"]] = chk
    return success_object(upload_out(rec), 201)


@bp.route("/treasury/issue-files/<fid>", methods=["GET"])
def get_upload(fid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.uploads, fid, "IssueFileUpload")
    check_ownership(user, rec["enrollment_id"])
    return success_object(upload_out(rec), 200)


@bp.route("/treasury/issue-files", methods=["GET"])
def list_uploads():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.uploads.values(), user, lambda f: f["enrollment_id"])
    if enr_filter is not None:
        records = [f for f in records if f["enrollment_id"] == enr_filter]
    for param in ("account_id", "uploaded_by_user_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [f for f in records if f.get(param) == v]
    return list_response(records, upload_out)


@bp.route("/treasury/issued-checks/<cid>", methods=["GET"])
def get_check(cid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.checks, cid, "IssuedCheck")
    check_ownership(user, check_enrollment_id(rec))
    return success_object(check_out(rec), 200)


@bp.route("/treasury/issued-checks", methods=["GET"])
def list_checks():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    records = scope_list(store.checks.values(), user, check_enrollment_id)
    for param in ("account_id", "issue_file_id", "consumed_by_item_id", "status", "check_number"):
        v = request.args.get(param)
        if v is not None:
            records = [c for c in records if str(c.get(param)) == v]
    return list_response(records, check_out)


@bp.route("/treasury/issued-checks/<cid>/void", methods=["POST"])
def void_check(cid):
    _, role, user = authenticate()
    authorize(role, user, ["CustomerAdmin", "CustomerManager"])
    body_json()
    rec = store.checks.get(cid)
    if rec is not None:
        check_ownership(user, check_enrollment_id(rec))
    if rec is None:
        get_or_404(store.checks, cid, "IssuedCheck")
    enr = store.enrollments[store.accounts[rec["account_id"]]["enrollment_id"]]
    guard_enrollment_active(enr)
    if rec["status"] != "REGISTERED":
        raise_err(ERR_CHECK_NOT_VOIDABLE, "Only a REGISTERED check can be voided")
    rec["status"] = "VOIDED"
    bump(rec)
    return success_object(check_out(rec), 200)
