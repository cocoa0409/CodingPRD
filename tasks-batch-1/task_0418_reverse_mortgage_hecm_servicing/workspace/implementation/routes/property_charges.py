"""PropertyChargePayment endpoints (§3.8)."""
import re

from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common, ledger
from services.clock import parse_ymd

bp = Blueprint("property_charges", __name__)

CHARGE_TYPES = {"PROPERTY_TAX", "HAZARD_INSURANCE"}
READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _windows_overlap(s1, e1, s2, e2):
    # half-open [start,end): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@bp.route("/property-charge-payments", methods=["POST"])
def create_payment():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "lesa_set_aside_id", "charge_type",
                                 "coverage_start", "coverage_end", "amount_cents"])
    # existence: loan then lesa (left to right)
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    lesa = db.lesa_set_asides.get(body["lesa_set_aside_id"])
    if lesa is None:
        raise errors.err(errors.ERR_NOT_FOUND, "LesaSetAside not found")
    # body well-formedness
    common.require_enum(body, "charge_type", CHARGE_TYPES)
    cs = body["coverage_start"]
    ce = body["coverage_end"]
    if not isinstance(cs, str) or not _DATE_RE.match(cs):
        raise errors.err(errors.ERR_INVALID_REQUEST, "coverage_start must be YYYY-MM-DD")
    if not isinstance(ce, str) or not _DATE_RE.match(ce):
        raise errors.err(errors.ERR_INVALID_REQUEST, "coverage_end must be YYYY-MM-DD")
    amount = common.require_positive_int(body, "amount_cents")

    # business rule order (PRD §3.8):
    # 1) LESA must be FUNDED and belong to the same loan
    if lesa["loan_id"] != loan["id"] or lesa["status"] != "FUNDED":
        raise errors.err(errors.ERR_LESA_EXHAUSTED, "LESA exhausted or belongs to a different loan")
    # 2) coverage window must not overlap an existing POSTED payment of same charge_type on same loan
    s1 = parse_ymd(cs)
    e1 = parse_ymd(ce)
    for p in db.property_charge_payments.values():
        if p["loan_id"] != loan["id"]:
            continue
        if p["charge_type"] != body["charge_type"]:
            continue
        if p["status"] != "POSTED":
            continue
        s2 = parse_ymd(p["coverage_start"])
        e2 = parse_ymd(p["coverage_end"])
        if _windows_overlap(s1, e1, s2, e2):
            raise errors.err(errors.ERR_COVERAGE_WINDOW_OVERLAP, "Coverage window overlaps an existing payment")
    # 3) amount may not overdraw the pool
    if amount > lesa["remaining_cents"]:
        raise errors.err(errors.ERR_LESA_OVERDRAW, "Amount exceeds remaining LESA pool")

    rec = {
        "loan_id": loan["id"],
        "lesa_set_aside_id": lesa["id"],
        "charge_type": body["charge_type"],
        "coverage_start": cs,
        "coverage_end": ce,
        "amount_cents": amount,
        "status": "POSTED",
    }
    db.stamp_create(rec)
    db.property_charge_payments[rec["id"]] = rec

    # move money out of pool and onto the loan
    lesa["drawn_cents"] += amount
    lesa["remaining_cents"] = lesa["initial_amount_cents"] - lesa["drawn_cents"]
    if lesa["remaining_cents"] == 0:
        lesa["status"] = "EXHAUSTED"
    db.touch(lesa)
    loan["principal_balance_cents"] += amount
    ledger.post_entry(loan, "LESA_DRAW", amount, source_ref_id=rec["id"])
    db.touch(loan)
    return success(public(rec), status=201)


@bp.route("/property-charge-payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.property_charge_payments.get(payment_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "PropertyChargePayment not found")
    return success(public(rec))


@bp.route("/property-charge-payments", methods=["GET"])
def list_payments():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.property_charge_payments.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    lesa_id = request.args.get("lesa_set_aside_id")
    if lesa_id is not None:
        rows = [r for r in rows if r["lesa_set_aside_id"] == lesa_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/property-charge-payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.property_charge_payments.get(payment_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "PropertyChargePayment not found")
    if rec["status"] != "POSTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Payment not in POSTED state")
    lesa = db.lesa_set_asides.get(rec["lesa_set_aside_id"])
    loan = db.loans.get(rec["loan_id"])
    amount = rec["amount_cents"]
    if lesa is not None:
        lesa["drawn_cents"] -= amount
        lesa["remaining_cents"] = lesa["initial_amount_cents"] - lesa["drawn_cents"]
        lesa["status"] = "FUNDED"
        db.touch(lesa)
    if loan is not None:
        loan["principal_balance_cents"] -= amount
        ledger.post_entry(loan, "REVERSAL", -amount, source_ref_id=rec["id"])
        db.touch(loan)
    rec["status"] = "REVERSED"
    db.touch(rec)
    return success(public(rec))
