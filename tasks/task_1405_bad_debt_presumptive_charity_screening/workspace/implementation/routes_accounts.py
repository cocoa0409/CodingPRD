"""SelfPayAccount endpoints: register, list, get (PRD 3.1)."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, not_found
from middleware import (
    ALL_ROLES,
    ROLE_COLLECTOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    DEFAULT_RESERVE_METHODOLOGY,
    recompute_aging_on_read,
    serialize_account,
    bucket_for_days,
)
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_date,
    req_int,
    req_str,
    today,
)

bp = Blueprint("accounts", __name__)


def get_account_or_404(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        raise not_found("account not found")
    return account


@bp.post("/self-pay/accounts")
def create_account():
    authenticate([ROLE_COLLECTOR, ROLE_OFFICER])
    b = get_body()
    patient_mrn = req_str(b, "patient_mrn")
    patient_name = req_str(b, "patient_name")
    original_balance_cents = req_int(b, "original_balance_cents")
    if original_balance_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "original_balance_cents must be > 0", 400)
    guarantor_liability_date = req_date(b, "guarantor_liability_date")

    rec = base_record()
    gl = __import__("datetime").date.fromisoformat(guarantor_liability_date)
    rec.update({
        "patient_mrn": patient_mrn,
        "patient_name": patient_name,
        "original_balance_cents": original_balance_cents,
        "current_balance_cents": original_balance_cents,
        "guarantor_liability_date": guarantor_liability_date,
        "aging_bucket": bucket_for_days((today() - gl).days),
        "aging_bucket_entered_at": now_iso(),
        "credit_reporting_status": "NOT_REPORTED",
        "status": "OPEN",
        "status_reason": None,
        # running totals (PRD 2.8)
        "charity_writeoff_total_cents": 0,
        "bad_debt_writeoff_total_cents": 0,
        "recovery_total_cents": 0,
        # internal: reserve methodology (DIRECT default; no PATCH surface
        # is declared, so the ALLOWANCE variant is unreachable)
        "_reserve_methodology": DEFAULT_RESERVE_METHODOLOGY,
    })
    db.accounts[rec["id"]] = rec
    return ok_object(serialize_account(rec), 201)


@bp.get("/self-pay/accounts")
def list_accounts():
    authenticate(ALL_ROLES)
    status_f = request.args.get("status")
    bucket_f = request.args.get("aging_bucket")
    credit_f = request.args.get("credit_reporting_status")
    items = list(db.accounts.values())
    for a in items:
        recompute_aging_on_read(a)
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if bucket_f is not None:
        items = [a for a in items if a["aging_bucket"] == bucket_f]
    if credit_f is not None:
        items = [a for a in items if a["credit_reporting_status"] == credit_f]
    page, meta = paginate(items)
    return ok_list([serialize_account(a) for a in page], meta)


@bp.get("/self-pay/accounts/<account_id>")
def get_account(account_id):
    authenticate(ALL_ROLES)
    account = get_account_or_404(account_id)
    recompute_aging_on_read(account)
    return ok_object(serialize_account(account))
