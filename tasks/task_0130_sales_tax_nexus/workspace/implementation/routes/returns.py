"""TaxReturn + RemittancePayment endpoints (§3.9-3.10).

Implements the branching fork-join return state machine with the
segregation-of-duties control, the nexus-registration precondition, the
acceptance sweep + tax_due computation, and the OCC-guarded remittance.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_INTERVAL, ERR_RETURN_PERIOD_OVERLAP, ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_NEXUS_NOT_REGISTERED, ERR_AMOUNT_MISMATCH,
    ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import require, get_identity
from response import object_response, array_response
from services import common, serializers, nexus

bp = Blueprint("returns", __name__)

READ_ROLES = ["Seller", "PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor"]
NON_REJECTED = {"DRAFT", "ACCEPTED", "FILED", "REMITTED"}


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _periods_collide_closed(a_start, a_end, b_start, b_end):
    """Closed-interval intersection OR touching; adjacency forbidden."""
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# TaxReturn CRUD
# ---------------------------------------------------------------------------
@bp.post("/tax-returns")
@require("TaxPreparer")
def create_return():
    user_id, _role = get_identity()
    body = common.get_body()
    seller_id = common.require_str(body, "seller_id")
    jurisdiction_id = common.require_str(body, "jurisdiction_id")

    common.resolve_fk(db.sellers, seller_id, "seller_id")
    common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")

    period_start = common.parse_dt(body, "period_start")
    period_end = common.parse_dt(body, "period_end")

    if not (period_end > period_start):
        raise APIError(ERR_INVALID_INTERVAL, "period_end must be strictly after period_start")

    # Closed-interval overlap against non-REJECTED returns (priority 9).
    for r in db.tax_returns.values():
        if r["seller_id"] != seller_id or r["jurisdiction_id"] != jurisdiction_id:
            continue
        if r["status"] not in NON_REJECTED:
            continue
        if _periods_collide_closed(period_start, period_end, r["period_start"], r["period_end"]):
            raise APIError(ERR_RETURN_PERIOD_OVERLAP, "overlapping or touching return period")

    rec = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "period_start": period_start,
        "period_end": period_end,
        "prepared_by": user_id,
        "approved_by": None,
        "tax_due": 0,
        "status": "DRAFT",
    }
    common.stamp_create(rec)
    db.tax_returns[rec["id"]] = rec
    return object_response(serializers.tax_return(rec), 201)


@bp.get("/tax-returns/<rec_id>")
@require(*READ_ROLES)
def get_return(rec_id):
    rec = common.get_or_404(db.tax_returns, rec_id, "tax return")
    return object_response(serializers.tax_return(rec))


@bp.get("/tax-returns")
@require(*READ_ROLES)
def list_returns():
    records = list(db.tax_returns.values())
    a = request.args
    if a.get("seller_id") is not None:
        records = [r for r in records if r["seller_id"] == a.get("seller_id")]
    if a.get("jurisdiction_id") is not None:
        records = [r for r in records if r["jurisdiction_id"] == a.get("jurisdiction_id")]
    if a.get("status") is not None:
        records = [r for r in records if r["status"] == a.get("status")]
    items, limit, offset, total = common.paginate(records, serializers.tax_return)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@bp.post("/tax-returns/<rec_id>/accept")
@require("TaxApprover")
def accept_return(rec_id):
    user_id, _role = get_identity()
    rec = common.get_or_404(db.tax_returns, rec_id, "tax return")

    # State (priority 10) -> SoD (priority 11) -> nexus precondition (priority 12).
    if rec["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "return must be DRAFT to accept")
    if user_id == rec["prepared_by"]:
        raise APIError(ERR_SEGREGATION_OF_DUTIES, "approver must differ from preparer")
    profile = nexus.find_profile(rec["seller_id"], rec["jurisdiction_id"])
    if profile is None or profile["nexus_status"] != "REGISTERED":
        raise APIError(ERR_NEXUS_NOT_REGISTERED, "seller's nexus profile is not REGISTERED")

    _sweep_and_compute(rec)
    rec["approved_by"] = user_id
    rec["status"] = "ACCEPTED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "TaxReturn", rec["id"], "ACCEPT_RETURN")
    return object_response(serializers.tax_return(rec))


def _sweep_and_compute(rec):
    seller_id = rec["seller_id"]
    jurisdiction_id = rec["jurisdiction_id"]
    p_start = rec["period_start"]
    p_end = rec["period_end"]

    sales_tax = Decimal("0")
    # Sweep SETTLED, SELLER-responsible transactions whose nexus accrued to this
    # jurisdiction, created_at in [period_start, period_end).
    for txn in db.transactions.values():
        if txn["seller_id"] != seller_id:
            continue
        if txn["settlement_status"] != "SETTLED":
            continue
        if txn["remittance_responsibility"] != "SELLER":
            continue
        if txn.get("_sourced_state_id") != jurisdiction_id:
            continue
        if not (p_start <= txn["created_at"] < p_end):
            continue
        txn["tax_return_id"] = rec["id"]
        common.touch(txn)
        sales_tax += Decimal(str(txn["tax_collected"]))

    use_tax = Decimal("0")
    for acc in db.use_tax_accruals.values():
        if acc["seller_id"] != seller_id or acc["jurisdiction_id"] != jurisdiction_id:
            continue
        if acc["status"] != "ACCRUED":
            continue
        if not (p_start <= acc["created_at"] < p_end):
            continue
        acc["tax_return_id"] = rec["id"]
        acc["status"] = "INCLUDED_IN_RETURN"
        common.touch(acc)
        use_tax += Decimal(str(acc["accrued_use_tax"]))

    rec["tax_due"] = float(_round2(sales_tax + use_tax))


@bp.post("/tax-returns/<rec_id>/reject")
@require("TaxApprover")
def reject_return(rec_id):
    user_id, _role = get_identity()
    rec = common.get_or_404(db.tax_returns, rec_id, "tax return")
    if rec["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "return must be DRAFT to reject")
    if user_id == rec["prepared_by"]:
        raise APIError(ERR_SEGREGATION_OF_DUTIES, "approver must differ from preparer")
    rec["status"] = "REJECTED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "TaxReturn", rec["id"], "REJECT_RETURN")
    return object_response(serializers.tax_return(rec))


@bp.post("/tax-returns/<rec_id>/reopen")
@require("TaxPreparer")
def reopen_return(rec_id):
    rec = common.get_or_404(db.tax_returns, rec_id, "tax return")
    if rec["status"] != "REJECTED":
        raise APIError(ERR_INVALID_STATE, "return must be REJECTED to reopen")
    rec["status"] = "DRAFT"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "TaxReturn", rec["id"], "REOPEN_RETURN")
    return object_response(serializers.tax_return(rec))


@bp.post("/tax-returns/<rec_id>/file")
@require("TaxApprover")
def file_return(rec_id):
    rec = common.get_or_404(db.tax_returns, rec_id, "tax return")
    if rec["status"] != "ACCEPTED":
        raise APIError(ERR_INVALID_STATE, "return must be ACCEPTED to file")
    rec["status"] = "FILED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "TaxReturn", rec["id"], "FILE_RETURN")
    return object_response(serializers.tax_return(rec))


# ---------------------------------------------------------------------------
# RemittancePayment
# ---------------------------------------------------------------------------
@bp.post("/remittance-payments")
@require("TaxApprover")
def create_remittance():
    body = common.get_body()
    tax_return_id = common.require_str(body, "tax_return_id")
    amount = common.require_number(body, "amount", minimum=0, exclusive_min=True)
    # expected_tax_return_version is required for the OCC check.
    if "expected_tax_return_version" not in body or body["expected_tax_return_version"] is None:
        raise APIError(ERR_INVALID_REQUEST, "missing required field: expected_tax_return_version")
    expected_version = body["expected_tax_return_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise APIError(ERR_INVALID_REQUEST, "expected_tax_return_version must be an integer")

    rec = common.resolve_fk(db.tax_returns, tax_return_id, "tax_return_id")

    # State (priority 10) -> OCC (priority 16) -> amount match (priority 15).
    if rec["status"] != "FILED":
        raise APIError(ERR_INVALID_STATE, "return must be FILED to remit")
    if expected_version != rec["version"]:
        raise APIError(ERR_STALE_VERSION, "expected_tax_return_version does not match current version")
    if Decimal(str(amount)) != Decimal(str(rec["tax_due"])):
        raise APIError(ERR_AMOUNT_MISMATCH, "amount must equal the return's tax_due exactly")

    payment = {
        "tax_return_id": tax_return_id,
        "amount": amount,
        "status": "APPLIED",
    }
    common.stamp_create(payment)
    db.remittance_payments[payment["id"]] = payment

    rec["status"] = "REMITTED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "TaxReturn", rec["id"], "REMIT_RETURN")
    return object_response(serializers.remittance_payment(payment), 201)


@bp.get("/remittance-payments/<rec_id>")
@require(*READ_ROLES)
def get_remittance(rec_id):
    rec = common.get_or_404(db.remittance_payments, rec_id, "remittance payment")
    return object_response(serializers.remittance_payment(rec))


@bp.get("/remittance-payments")
@require(*READ_ROLES)
def list_remittances():
    records = list(db.remittance_payments.values())
    trid = request.args.get("tax_return_id")
    if trid is not None:
        records = [r for r in records if r["tax_return_id"] == trid]
    items, limit, offset, total = common.paginate(records, serializers.remittance_payment)
    return array_response(items, limit, offset, total)
