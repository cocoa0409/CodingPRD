from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import get_body, require_str, paginate, sorted_by_created
from serialize import public, public_list
from services import core

bp = Blueprint("violations", __name__)


def _owner_check(role, user_id, violation):
    if role == "AccountHolder" and violation.get("account_id") != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this violation")


@bp.post("/etc/violations")
def create_violation():
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    body = get_body()

    # Existence (priority 3)
    txid = body.get("toll_transaction_id")
    tx = None
    if isinstance(txid, str):
        tx = db.toll_transactions.get(txid)
        if tx is None:
            raise err(errors.ERR_NOT_FOUND, "Toll transaction not found")
    if tx is None:
        require_str(body, "toll_transaction_id")

    # Eligibility (priority 13): PRICED, UNSETTLED, PLATE read
    if not (tx["pricing_status"] == "PRICED" and tx["settlement_status"] == "UNSETTLED"
            and tx["read_method"] == "PLATE"):
        raise err(errors.ERR_NOT_VIOLATION_ELIGIBLE,
                  "Transaction is not a PRICED, UNSETTLED, PLATE read")

    account = db.accounts.get(tx.get("account_id")) if tx.get("account_id") else None

    penalty, fine_total = core.compute_fine(tx["toll_cents"], 1)
    v = {
        "toll_transaction_id": tx["id"],
        "account_id": tx.get("account_id"),
        "toll_due_cents": tx["toll_cents"],
        "penalty_cents": penalty,
        "fine_total_cents": fine_total,
        "escalation_tier": 1,
        "settlement_status": "ASSESSED",
        "dispute_reason": None,
    }
    init_common(v)
    db.violations[v["id"]] = v

    # Cascade: transaction -> IN_VIOLATION
    tx["settlement_status"] = "IN_VIOLATION"
    touch(tx)

    # Cascade: account -> DELINQUENT if ACTIVE; recompute outstanding fines
    if account is not None:
        core.recompute_outstanding_fines(account)
        core.make_delinquent_if_active(account)
    return success(public(v), status=201)


@bp.get("/etc/violations/<vid>")
def get_violation(vid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    v = db.violations.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Violation not found")
    _owner_check(role, user_id, v)
    return success(public(v))


@bp.get("/etc/violations")
def list_violations():
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    items = list(db.violations.values())
    account_id = request.args.get("account_id")
    txid = request.args.get("toll_transaction_id")
    if account_id is not None:
        items = [v for v in items if v.get("account_id") == account_id]
    if txid is not None:
        items = [v for v in items if v["toll_transaction_id"] == txid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/etc/violations/<vid>/contest")
def contest_violation(vid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    v = db.violations.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Violation not found")
    _owner_check(role, user_id, v)
    if v["settlement_status"] != "ASSESSED":
        raise err(errors.ERR_INVALID_STATE, "Violation is not ASSESSED")
    body = get_body()
    reason = require_str(body, "dispute_reason")
    v["dispute_reason"] = reason
    v["settlement_status"] = "CONTESTED"
    touch(v)
    return success(public(v))


@bp.post("/etc/violations/<vid>/accept-dispute")
def accept_dispute(vid):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    v = db.violations.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Violation not found")
    if v["settlement_status"] != "CONTESTED":
        raise err(errors.ERR_INVALID_STATE, "Violation is not CONTESTED")
    v["settlement_status"] = "DISMISSED"
    touch(v)
    # Cascade: linked tx IN_VIOLATION -> WRITTEN_OFF
    tx = db.toll_transactions.get(v["toll_transaction_id"])
    if tx is not None and tx["settlement_status"] == "IN_VIOLATION":
        tx["settlement_status"] = "WRITTEN_OFF"
        touch(tx)
    account = db.accounts.get(v.get("account_id")) if v.get("account_id") else None
    if account is not None:
        core.recompute_outstanding_fines(account)
        core.maybe_clear_delinquency(account)
    return success(public(v))


@bp.post("/etc/violations/<vid>/reject-dispute")
def reject_dispute(vid):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    v = db.violations.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Violation not found")
    if v["settlement_status"] != "CONTESTED":
        raise err(errors.ERR_INVALID_STATE, "Violation is not CONTESTED")
    v["settlement_status"] = "ASSESSED"
    v["escalation_tier"] += 1
    penalty, fine_total = core.compute_fine(v["toll_due_cents"], v["escalation_tier"])
    v["penalty_cents"] = penalty
    v["fine_total_cents"] = fine_total
    touch(v)
    account = db.accounts.get(v.get("account_id")) if v.get("account_id") else None
    if account is not None:
        core.recompute_outstanding_fines(account)
    return success(public(v))


@bp.post("/etc/violations/<vid>/pay")
def pay_violation(vid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder"})
    v = db.violations.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Violation not found")
    _owner_check(role, user_id, v)
    if v["settlement_status"] not in ("ASSESSED", "CONTESTED"):
        raise err(errors.ERR_INVALID_STATE, "Violation is not payable")
    account = db.accounts.get(v.get("account_id"))
    if account is None:
        raise err(errors.ERR_INVALID_STATE, "Violation has no owning account")
    # Sufficient balance (priority 15)
    if account["balance_cents"] < v["fine_total_cents"]:
        raise err(errors.ERR_INSUFFICIENT_BALANCE, "Insufficient balance to pay fine")

    core.apply_debit_and_reload(account, v["fine_total_cents"], "VIOLATION_SETTLE",
                                ref_violation_id=v["id"],
                                ref_transaction_id=v["toll_transaction_id"])
    v["settlement_status"] = "SETTLED"
    touch(v)
    # Cascade: linked tx IN_VIOLATION -> SETTLED
    tx = db.toll_transactions.get(v["toll_transaction_id"])
    if tx is not None and tx["settlement_status"] == "IN_VIOLATION":
        tx["settlement_status"] = "SETTLED"
        touch(tx)
    core.recompute_outstanding_fines(account)
    core.maybe_clear_delinquency(account)
    return success(public(v))
