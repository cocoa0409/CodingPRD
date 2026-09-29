"""Bank credit records posted from the statement (PRD section 3.7)."""
from flask import Blueprint

import db
import domain
import response
import serializers
import validation
from auth import endpoint
from errors import bad_request
from routes.common import list_collection

bp = Blueprint("bank", __name__)

CREDIT_TYPES = ("PROVISIONAL", "FINAL", "ADJUSTMENT")
BANK_READ_ROLES = ["TreasuryAnalyst", "CashOfficeClerk", "StoreManager"]


@bp.post("/cash-ops/bank-credit-records")
@endpoint(["TreasuryAnalyst"])
def create_bank_credit_record():
    data = validation.body()
    store_id = validation.req_str(data, "store_id")
    credit_type = validation.req_enum(data, "credit_type", CREDIT_TYPES)
    if credit_type == "ADJUSTMENT":
        amount_cents = validation.req_int(data, "amount_cents", minimum=None)
    else:
        amount_cents = validation.req_int(data, "amount_cents", minimum=1)
    value_date = validation.req_date(data, "value_date")
    bank_reference = validation.req_str(data, "bank_reference")
    deposit_id = validation.opt_str(data, "deposit_id")
    store = domain.get_store(store_id)
    deposit = None
    if deposit_id is not None:
        deposit = domain.get_deposit(deposit_id)
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "deposit_id": deposit["id"] if deposit is not None else None,
            "credit_type": credit_type,
            "amount_cents": amount_cents,
            "value_date": value_date,
            "bank_reference": bank_reference,
            "match_state": "UNMATCHED",
        }
    )
    db.bank_credit_records[record["id"]] = record
    return response.object_response(serializers.bank_credit_record(record), 201)


@bp.get("/cash-ops/bank-credit-records/<record_id>")
@endpoint(BANK_READ_ROLES)
def read_bank_credit_record(record_id):
    record = domain.get_credit_record(record_id)
    return response.object_response(serializers.bank_credit_record(record))


@bp.get("/cash-ops/bank-credit-records")
@endpoint(BANK_READ_ROLES)
def list_bank_credit_records():
    return list_collection(
        db.bank_credit_records,
        [
            ("store_id", "store_id"),
            ("deposit_id", "deposit_id"),
            ("credit_type", "credit_type"),
            ("match_state", "match_state"),
        ],
        serializers.bank_credit_record,
    )
