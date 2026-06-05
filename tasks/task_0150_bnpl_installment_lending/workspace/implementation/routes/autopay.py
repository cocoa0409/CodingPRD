"""AutopayMandate endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_role, require_borrower_owns
from response import success
from services import engine
from services.engine import stamp_new, touch, serialize_mandate
from routes.common import (
    get_json_body, parse_pagination, paginate, sort_by_created,
    require_loan, require_mandate,
)

bp = Blueprint("autopay", __name__)


@bp.route("/autopay-mandates", methods=["POST"])
def create_mandate():
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    body = get_json_body()

    loan_id = body.get("loan_id")
    if not loan_id or not isinstance(loan_id, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'loan_id'.")
    loan = require_loan(loan_id)
    require_borrower_owns(role, uid, loan["borrower_id"])

    # State: autopay is enabled on an ACTIVE loan.
    if loan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Autopay can only be enabled on an ACTIVE loan.")

    # Uniqueness (priority 6): at most one mandate per loan.
    for m in db.autopay_mandates.values():
        if m["loan_id"] == loan_id:
            raise err("ERR_DUPLICATE", "An autopay mandate already exists for this loan.")

    mandate = {
        "loan_id": loan_id,
        "borrower_id": loan["borrower_id"],
        "status": "ENABLED",
    }
    stamp_new(mandate)
    db.autopay_mandates[mandate["id"]] = mandate
    return success(serialize_mandate(mandate), status=201)


@bp.route("/autopay-mandates/<mandate_id>", methods=["GET"])
def get_mandate(mandate_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower"})
    m = require_mandate(mandate_id)
    require_borrower_owns(role, uid, m["borrower_id"])
    return success(serialize_mandate(m), status=200)


@bp.route("/autopay-mandates", methods=["GET"])
def list_mandates():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower"})
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")
    borrower_filter = request.args.get("borrower_id")

    rows = list(db.autopay_mandates.values())
    if loan_filter is not None:
        rows = [m for m in rows if m["loan_id"] == loan_filter]
    if borrower_filter is not None:
        rows = [m for m in rows if m["borrower_id"] == borrower_filter]
    if role == "Borrower":
        rows = [m for m in rows if m["borrower_id"] == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_mandate(m) for m in page],
                   status=200, pagination=meta)


@bp.route("/autopay-mandates/<mandate_id>/disable", methods=["POST"])
def disable_mandate(mandate_id):
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    m = require_mandate(mandate_id)
    require_borrower_owns(role, uid, m["borrower_id"])

    m["status"] = "DISABLED"
    touch(m)
    return success(serialize_mandate(m), status=200)
