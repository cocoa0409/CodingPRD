"""Disbursements."""

from flask import Blueprint, request

from auth import any_role, require_roles
from domain import (
    advance_sync,
    check_advance_cap,
    new_advance,
    post_ledger,
    replay,
)
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOAN_NOT_ACTIVE,
    ERR_ON_HOLD,
    ERR_PAYEE_NOT_VERIFIED,
    ERR_RELEASE_EARLY,
    ERR_SOD,
    ERR_STALE_VERSION,
    not_found,
)
from routes_core import get_account_or_404
from serializers import advance_out, disbursement_out, tax_record_out
from store import store
from util import bump, fmt_date, new_record, now_ts, ok, ok_list, parse_date, today
from validate import body, fk_exists, positive_amount, req_date

bp = Blueprint("disbursements", __name__)


def get_disbursement_or_404(did):
    d = store.disbursements.get(did)
    if d is None:
        raise not_found("Disbursement not found")
    return d


@bp.post("/servicing/escrow-accounts/<aid>/disbursements")
def create_disbursement(aid):
    uid, _ = require_roles("DisbursementProcessor")
    account = get_account_or_404(aid)
    data = body()
    li = fk_exists(store.line_items, data.get("line_item_id"), "line_item_id")
    payee = fk_exists(store.payees, data.get("payee_id"), "payee_id")
    if not isinstance(data.get("amount_cents"), int) or isinstance(data.get("amount_cents"), bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents is required and must be an integer")
    due = req_date(data, "due_date")
    rel = req_date(data, "scheduled_release_date")
    if li is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "line_item_id is required")
    if payee is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "payee_id is required")
    if li["escrow_account_id"] != aid:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "line_item does not belong to this escrow account")
    if li["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Line item is not ACTIVE")
    if payee["verification_status"] != "VERIFIED":
        raise ApiError(ERR_PAYEE_NOT_VERIFIED, 409, "Payee is not VERIFIED")
    amount = positive_amount(data["amount_cents"])
    d = new_record({
        "escrow_account_id": aid,
        "line_item_id": li["id"],
        "payee_id": payee["id"],
        "amount_cents": amount,
        "due_date": due,
        "scheduled_release_date": rel,
        "status": "SCHEDULED",
        "scheduled_by_user_id": uid,
        "released_by_user_id": None,
        "released_at": None,
        "cleared_at": None,
        "returned_at": None,
        "late_release": False,
        "ledger_entry_id": None,
    })
    store.disbursements[d["id"]] = d
    return ok(disbursement_out(d), 201)


@bp.get("/servicing/escrow-accounts/<aid>/disbursements")
def list_disbursements(aid):
    any_role()
    get_account_or_404(aid)
    rows = [d for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"])
            if d["escrow_account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([disbursement_out(r) for r in rows])


@bp.get("/servicing/disbursements/<did>")
def get_disbursement(did):
    any_role()
    return ok(disbursement_out(get_disbursement_or_404(did)))


@bp.patch("/servicing/disbursements/<did>")
def patch_disbursement(did):
    require_roles("DisbursementProcessor")
    d = get_disbursement_or_404(did)
    data = body()
    # shape on provided fields
    if "amount_cents" in data and data["amount_cents"] is not None:
        v = data["amount_cents"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer")
    if "due_date" in data and data["due_date"] is not None:
        if parse_date(data["due_date"]) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "due_date must be an ISO date")
    if "scheduled_release_date" in data and data["scheduled_release_date"] is not None:
        if parse_date(data["scheduled_release_date"]) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "scheduled_release_date must be an ISO date")
    expected = data.get("expected_disbursement_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_disbursement_version is required")
    # OCC (priority 7)
    if expected != d["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale disbursement version")
    if d["status"] in ("CLEARED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only SCHEDULED disbursements can be patched")
    if data.get("amount_cents") is not None:
        d["amount_cents"] = positive_amount(data["amount_cents"])
    if data.get("due_date") is not None:
        d["due_date"] = data["due_date"]
    if data.get("scheduled_release_date") is not None:
        d["scheduled_release_date"] = data["scheduled_release_date"]
    bump(d)
    return ok(disbursement_out(d))


@bp.post("/servicing/disbursements/<did>/release")
def release_disbursement(did):
    uid, _ = require_roles("DisbursementProcessor")
    d = get_disbursement_or_404(did)
    if d["status"] in ("CLEARED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Disbursement is not SCHEDULED")
    account = store.accounts.get(d["escrow_account_id"])
    if account is None or account["account_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Escrow account is not ACTIVE")
    if account["hold_status"] != "NONE":
        raise ApiError(ERR_ON_HOLD, 409, "Escrow account is on compliance hold")
    loan = store.loans.get(account["loan_id"])
    if loan is None or loan["status"] != "ACTIVE":
        raise ApiError(ERR_LOAN_NOT_ACTIVE, 409, "Loan is not ACTIVE")
    if uid == d["scheduled_by_user_id"]:
        raise ApiError(ERR_SOD, 409, "Releaser must differ from scheduler")
    now_date = today()
    if now_date < parse_date(d["scheduled_release_date"]):
        raise ApiError(ERR_RELEASE_EARLY, 409, "Release before scheduled_release_date")
    payee = store.payees.get(d["payee_id"])
    if payee is None or payee["verification_status"] != "VERIFIED":
        raise ApiError(ERR_PAYEE_NOT_VERIFIED, 409, "Payee is not VERIFIED")

    pre_balance = account["balance_cents"]
    shortfall = d["amount_cents"] - max(pre_balance, 0)
    if shortfall > 0:
        check_advance_cap(account["id"], shortfall)

    entry = post_ledger(account, "DISBURSEMENT", -d["amount_cents"],
                        fmt_date(now_date), "Disbursement", d["id"])
    if shortfall > 0:
        adv = new_advance(account, "DISBURSEMENT_SHORTFALL", shortfall, d["id"])
        post_ledger(account, "ADVANCE_ISSUED", shortfall, fmt_date(now_date),
                    "EscrowAdvance", adv["id"])
    replay(account)
    d["late_release"] = now_date > parse_date(d["due_date"])
    d["released_by_user_id"] = uid
    d["released_at"] = now_ts()
    d["ledger_entry_id"] = entry["id"]
    d["status"] = "RELEASED"
    bump(d)
    bump(account)
    return ok(disbursement_out(d))


@bp.post("/servicing/disbursements/<did>/cancel")
def cancel_disbursement(did):
    require_roles("DisbursementProcessor")
    d = get_disbursement_or_404(did)
    if d["status"] in ("CLEARED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] not in ("SCHEDULED", "BLOCKED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only SCHEDULED or BLOCKED disbursements can be cancelled")
    d["status"] = "CANCELLED"
    bump(d)
    return ok(disbursement_out(d))


@bp.post("/servicing/disbursements/<did>/mark-cleared")
def mark_cleared(did):
    require_roles("DisbursementProcessor")
    d = get_disbursement_or_404(did)
    if d["status"] in ("CLEARED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, 409, "Disbursement is not RELEASED")
    d["status"] = "CLEARED"
    d["cleared_at"] = now_ts()
    bump(d)
    return ok(disbursement_out(d))


@bp.post("/servicing/disbursements/<did>/mark-returned")
def mark_returned(did):
    require_roles("DisbursementProcessor")
    d = get_disbursement_or_404(did)
    if d["status"] in ("CLEARED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "RELEASED":
        raise ApiError(ERR_INVALID_STATE, 409, "Disbursement is not RELEASED")
    account = store.accounts.get(d["escrow_account_id"])
    now_date = fmt_date(today())
    post_ledger(account, "DISBURSEMENT_RETURN", d["amount_cents"], now_date,
                "Disbursement", d["id"])
    # Reduce the advance tied to this disbursement, if any is still open
    linked = [a for a in store.advances.values()
              if a.get("disbursement_id") == d["id"]
              and a["status"] in ("OUTSTANDING", "RECOVERING")]
    for a in sorted(linked, key=lambda r: r["_seq"]):
        reduction = min(a["outstanding_cents"], d["amount_cents"])
        if reduction <= 0:
            continue
        post_ledger(account, "ADVANCE_RECOVERY", -reduction, now_date,
                    "EscrowAdvance", a["id"])
        a["recovered_cents"] += reduction
        advance_sync(a)
        bump(a)
        break
    replay(account)
    d["status"] = "RETURNED"
    d["returned_at"] = now_ts()
    bump(d)
    bump(account)
    return ok(disbursement_out(d))


@bp.get("/servicing/disbursements/<did>/tax-monitoring-records")
def disbursement_tax_records(did):
    any_role()
    d = get_disbursement_or_404(did)
    rows = [r for r in sorted(store.tax_records.values(), key=lambda x: x["_seq"])
            if r["paid_via_disbursement_id"] == d["id"]]
    return ok_list([tax_record_out(r) for r in rows])


@bp.get("/servicing/disbursements/<did>/advances")
def disbursement_advances(did):
    any_role()
    d = get_disbursement_or_404(did)
    rows = [a for a in sorted(store.advances.values(), key=lambda x: x["_seq"])
            if a.get("disbursement_id") == d["id"]]
    return ok_list([advance_out(r) for r in rows])


@bp.get("/servicing/escrow-line-items/<liid>/disbursements")
def line_item_disbursements(liid):
    any_role()
    if liid not in store.line_items:
        raise not_found("EscrowLineItem not found")
    rows = [d for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"])
            if d["line_item_id"] == liid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([disbursement_out(r) for r in rows])
