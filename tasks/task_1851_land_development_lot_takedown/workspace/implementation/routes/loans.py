"""DevelopmentLoan endpoints (PRD 3.6): one open loan per parcel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_LOAN_ALREADY_EXISTS,
    ERR_LOAN_INVALID_STATE,
    ERR_PARCEL_NOT_ACQUIRED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from validate import check_body_fk_exists, get_body, req_int, req_str, require_path

bp = Blueprint("loans", __name__)


@bp.post("/development-loans")
def create_loan():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence
    check_body_fk_exists("parcels", body, "parcel_id")
    # Priority 4: shape
    parcel_id = req_str(body, "parcel_id")
    commitment = req_int(body, "commitment_amount_cents", minimum=1)
    floor_bp = req_int(body, "release_price_floor_bp", minimum=1, maximum=10000)
    # Priority 9: one open loan per parcel; a PAID_OFF loan does not block a successor
    for other in db["loans"].values():
        if other["parcel_id"] == parcel_id and other["status"] in ("DRAFT", "ACTIVE"):
            raise_error(ERR_LOAN_ALREADY_EXISTS,
                        "a loan for this parcel already exists in DRAFT or ACTIVE")
    rec = new_record("loans", {
        "parcel_id": parcel_id,
        "commitment_amount_cents": commitment,
        "release_price_floor_bp": floor_bp,
        "outstanding_balance_cents": 0,
        "total_drawn_cents": 0,
        "total_release_paid_cents": 0,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/development-loans")
def list_loans():
    return list_response("loans", {
        "parcel_id": request.args.get("parcel_id"),
        "status": request.args.get("status"),
    })


@bp.get("/development-loans/<rid>")
def get_loan(rid):
    return get_one("loans", rid)


@bp.post("/development-loans/<rid>/activate")
def activate_loan(rid):
    authorized(["DeveloperOperator"])
    loan = require_path("loans", rid)
    if loan["status"] != "DRAFT":
        raise_error(ERR_LOAN_INVALID_STATE, "activate requires DRAFT")
    # Priority 10 (referential)
    parcel = db["parcels"].get(loan["parcel_id"])
    if parcel is None or parcel["status"] != "ACQUIRED":
        raise_error(ERR_PARCEL_NOT_ACQUIRED, "loan activation requires parcel ACQUIRED")
    loan["status"] = "ACTIVE"
    touch(loan)
    return success_object(public(loan))
