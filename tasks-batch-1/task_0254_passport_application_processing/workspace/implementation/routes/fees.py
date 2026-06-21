"""Fee assessments: read, list, pay."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PAYMENT_AMOUNT_MISMATCH,
)
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    touch,
)

bp = Blueprint("fees", __name__)


def _fee_or_404(rid: str) -> dict:
    rec = db.fee_assessments.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "FeeAssessment not found")
    return rec


@bp.route("/fee-assessments/<rid>", methods=["GET"])
def get_fee(rid):
    require_auth(["Applicant", "Adjudicator"])
    rec = _fee_or_404(rid)
    return ok_object(serialize(rec), 200)


@bp.route("/fee-assessments", methods=["GET"])
def list_fees():
    require_auth(["Applicant", "Adjudicator", "AcceptanceAgent"])
    limit, offset = parse_pagination()
    items = list(db.fee_assessments.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [f for f in items if f["application_id"] == application_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.route("/fee-assessments/<rid>/pay", methods=["POST"])
def pay_fee(rid):
    require_auth(["Applicant"])
    fee = _fee_or_404(rid)
    body = get_body()
    if "amount_tendered_cents" not in body or body.get("amount_tendered_cents") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: amount_tendered_cents")
    amount = body["amount_tendered_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_tendered_cents must be an integer")

    # 5 / 6 transition definedness & terminality
    if fee["payment_status"] == "REFUNDED":
        raise APIError(ERR_ALREADY_TERMINAL, 409, "FeeAssessment is REFUNDED (terminal)")
    if fee["payment_status"] != "UNPAID":
        raise APIError(ERR_INVALID_STATE, 409, "Payment requires status UNPAID")

    # 15 exact payment amount
    if amount != fee["total_due_cents"]:
        raise APIError(ERR_PAYMENT_AMOUNT_MISMATCH, 422, "amount_tendered_cents must equal total_due_cents")

    fee["payment_status"] = "PAID"
    fee["amount_paid_cents"] = fee["total_due_cents"]
    touch(fee)

    app_rec = db.applications.get(fee["application_id"])
    if app_rec is not None:
        applicant = db.applicants.get(app_rec["applicant_id"])
        if applicant is not None:
            applicant["total_fees_paid_cents"] += fee["total_due_cents"]
            touch(applicant)

    return ok_object(serialize(fee), 200)
