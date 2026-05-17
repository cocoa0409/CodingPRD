"""Disbursement routes."""
from __future__ import annotations

from flask import Blueprint, request

from db import store
from errors import (
    err_insufficient_escrow,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from services.loan_engine import bump
from services.serializers import disbursement_view
from utils import new_uuid, parse_iso

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("disbursements", __name__)

_ALLOWED_TYPES = {"PROPERTY_TAX", "HAZARD_INSURANCE", "SURPLUS_REFUND"}


@bp.post("/loans/<lid>/disbursements")
@require_auth(["Servicer"])
def create_disbursement(lid):
    loan = get_loan_or_404(lid)
    body = get_json()
    d_type = body.get("type")
    if d_type not in _ALLOWED_TYPES:
        raise err_invalid_state("Invalid disbursement type.")
    sd_raw = body.get("scheduled_date")
    if sd_raw is None:
        raise err_invalid_state("scheduled_date required")
    try:
        scheduled_date = parse_iso(sd_raw)
    except Exception:
        raise err_invalid_state("Invalid scheduled_date")
    amount = get_int(body, "amount_cents")
    if amount is None or amount <= 0:
        raise err_invalid_state("amount_cents must be > 0")

    now = store.now()
    did = new_uuid()
    record = {
        "id": did,
        "loan_id": lid,
        "type": d_type,
        "scheduled_date": scheduled_date,
        "amount_cents": amount,
        "status": "SCHEDULED",
        "paid_at": None,
        "failure_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.disbursements[did] = record
    return success(disbursement_view(record), 201)


@bp.post("/loans/<lid>/disbursements/<did>/retry")
@require_auth(["Servicer"])
def retry_disbursement(lid, did):
    loan = get_loan_or_404(lid)
    d = store.disbursements.get(did)
    if d is None or d["loan_id"] != lid:
        raise err_resource_not_found("Disbursement not found under loan.")
    if d["status"] != "FAILED":
        raise err_invalid_state("Only FAILED disbursements can be retried.")
    if loan["escrow_balance_cents"] < d["amount_cents"]:
        raise err_insufficient_escrow()
    now = store.now()
    d["status"] = "PAID"
    d["paid_at"] = now
    d["failure_reason"] = None
    loan["escrow_balance_cents"] -= d["amount_cents"]
    bump(d, now)
    bump(loan, now)
    return success(disbursement_view(d), 200)


@bp.post("/loans/<lid>/disbursements/<did>/cancel")
@require_auth(["Servicer"])
def cancel_disbursement(lid, did):
    loan = get_loan_or_404(lid)
    d = store.disbursements.get(did)
    if d is None or d["loan_id"] != lid:
        raise err_resource_not_found("Disbursement not found under loan.")
    if d["status"] != "SCHEDULED":
        raise err_invalid_state("Only SCHEDULED disbursements can be canceled.")
    now = store.now()
    d["status"] = "CANCELED"
    bump(d, now)
    return success(disbursement_view(d), 200)


@bp.get("/loans/<lid>/disbursements")
@require_auth(["Servicer", "Borrower", "PlatformAdmin"])
def list_disbursements(lid):
    loan = get_loan_or_404(lid)
    enforce_borrower_owns_loan(loan)
    limit, offset = parse_pagination()
    items = [d for d in store.disbursements.values() if d["loan_id"] == lid]
    status = request.args.get("status")
    d_type = request.args.get("type")
    if status:
        items = [d for d in items if d["status"] == status]
    if d_type:
        items = [d for d in items if d["type"] == d_type]
    items = sort_by_created_at(items)
    page = paginate(items, limit, offset)
    return list_success([disbursement_view(d) for d in page], limit, offset, len(items), 200)
