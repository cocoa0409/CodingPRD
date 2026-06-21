"""Installment endpoints: get/list (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (
    authenticate, require_role, require_borrower_owns, require_merchant_owns,
)
from response import success
from services import engine
from services.engine import serialize_installment
from routes.common import (
    parse_pagination, paginate, require_installment,
)

bp = Blueprint("installments", __name__)


@bp.route("/installments/<installment_id>", methods=["GET"])
def get_installment(installment_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    inst = require_installment(installment_id)
    loan = db.loans.get(inst["loan_id"])
    if loan is not None:
        require_borrower_owns(role, uid, loan["borrower_id"])
        require_merchant_owns(role, uid, loan["merchant_id"])
    return success(serialize_installment(inst), status=200)


@bp.route("/installments", methods=["GET"])
def list_installments():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")

    rows = list(db.installments.values())
    if loan_filter is not None:
        rows = [i for i in rows if i["loan_id"] == loan_filter]
    if role == "Borrower":
        rows = [i for i in rows
                if (db.loans.get(i["loan_id"]) or {}).get("borrower_id") == uid]
    elif role == "Merchant":
        rows = [i for i in rows
                if (db.loans.get(i["loan_id"]) or {}).get("merchant_id") == uid]

    # Installments are ordered by sequence_no ASC (PRD §2.3 documented exception).
    rows.sort(key=lambda i: (i["sequence_no"], i["_seq"]))
    page, meta = paginate(rows, limit, offset)
    return success([serialize_installment(i) for i in page],
                   status=200, pagination=meta)
