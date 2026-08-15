"""Fee ledger reads, waiver (authority-capped), reinstatement (PRD §3.7)."""
from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize, check_list_enrollment_param, check_ownership, scope_list
from errors import (
    ERR_FEE_ENTRY_NOT_WAIVABLE,
    ERR_WAIVER_EXCEEDS_AUTHORITY,
    raise_err,
)
from services import WAIVER_AUTHORITY_CAP_CENTS, fee_out, guard_enrollment_mutable
from util import body_json, bump, get_or_404, list_response, req_str, success_object

bp = Blueprint("fee_entries", __name__)

WAIVABLE_TYPES = ("EXCEPTION_FEE", "RETURN_FEE", "MINIMUM_TOPUP")


@bp.route("/treasury/fee-entries/<fid>", methods=["GET"])
def get_fee(fid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.fees, fid, "FeeLedgerEntry")
    check_ownership(user, rec["enrollment_id"])
    return success_object(fee_out(rec), 200)


@bp.route("/treasury/fee-entries", methods=["GET"])
def list_fees():
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    enr_filter = check_list_enrollment_param(user)
    records = scope_list(store.fees.values(), user, lambda f: f["enrollment_id"])
    if enr_filter is not None:
        records = [f for f in records if f["enrollment_id"] == enr_filter]
    for param in ("period", "exception_id", "status", "fee_type"):
        v = request.args.get(param)
        if v is not None:
            records = [f for f in records if str(f.get(param)) == v]
    return list_response(records, fee_out)


@bp.route("/treasury/fee-entries/<fid>/waive", methods=["POST"])
def waive_fee(fid):
    uid, role, _user = authenticate()
    authorize(role, _user, ["BankOps", "BankTreasuryManager"])
    body = body_json()
    reason = req_str(body, "reason", non_empty=False)
    rec = get_or_404(store.fees, fid, "FeeLedgerEntry")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    # waivability first (state), authority cap last (fiscal) — PRD §2.10
    if rec["fee_type"] not in WAIVABLE_TYPES or rec["status"] not in ("ACCRUED", "BILLED"):
        raise_err(ERR_FEE_ENTRY_NOT_WAIVABLE, "Entry is not waivable")
    if role == "BankOps" and rec["amount_cents"] > WAIVER_AUTHORITY_CAP_CENTS:
        raise_err(ERR_WAIVER_EXCEEDS_AUTHORITY, "BankOps waiver authority is capped at 1000 cents")
    rec["waived_from_status"] = rec["status"]
    rec["status"] = "WAIVED"
    rec["waived_by"] = uid
    rec["waiver_reason"] = reason
    bump(rec)
    return success_object(fee_out(rec), 200)


@bp.route("/treasury/fee-entries/<fid>/reinstate", methods=["POST"])
def reinstate_fee(fid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body_json()
    rec = get_or_404(store.fees, fid, "FeeLedgerEntry")
    enr = store.enrollments[rec["enrollment_id"]]
    guard_enrollment_mutable(enr)
    if rec["status"] != "WAIVED":
        raise_err(ERR_FEE_ENTRY_NOT_WAIVABLE, "Only a WAIVED entry can be reinstated")
    rec["status"] = rec["waived_from_status"]
    rec["waived_from_status"] = None
    rec["waived_by"] = None
    rec["waiver_reason"] = None
    bump(rec)
    return success_object(fee_out(rec), 200)
