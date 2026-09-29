"""Curing document exceptions on a custodian receipt (PRD 3.5)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import COLLATERAL_ANALYST, CUSTODIAN, mismatch, require_auth
from response import ok
from routes.common import get_receipt
from serializers import receipt_out
from services import computed
from services.constants import EXCEPTION_CODES
from validation import MISSING, body, reject_system_fields, v_enum_array
from services.states import close_calls, reevaluate_restricted

bp = Blueprint("receipts", __name__)


@bp.post("/receipts/<receipt_id>/cure")
def cure_receipt(receipt_id):
    user_id, role = require_auth([CUSTODIAN, COLLATERAL_ANALYST])
    receipt = get_receipt(receipt_id)
    # priority 4
    if role == CUSTODIAN and receipt["custodian_id"] != user_id:
        mismatch()
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING,
                                "status": receipt["status"],
                                "exception_codes": list(receipt["exception_codes"]),
                                "document_types": list(receipt["document_types"])})
    cured = v_enum_array(data, "cured_exception_codes", EXCEPTION_CODES)

    # priority 12
    if receipt["status"] != "EXCEPTION":
        raise ApiError("ERR_CUSTODY_INVALID_STATE",
                       "Only an EXCEPTION receipt may be cured.")

    advance = db.advances[receipt["advance_id"]]
    facility = db.facilities[advance["facility_id"]]

    union = list(receipt["cured_exception_codes"])
    for code in cured:
        if code not in union:
            union.append(code)
    receipt["cured_exception_codes"] = union
    complete = all(code in union for code in receipt["exception_codes"])

    if complete:
        receipt["status"] = "CURED"
        touch(receipt)
        if advance["custody_status"] == "RECEIVED_EXCEPTION":
            advance["custody_status"] = "EXCEPTION_CURED"
            touch(advance)
        result = computed.store_valuation(advance)
        if result["required_paydown_cents"] == 0:
            if close_calls(advance["id"], "CUSTODY_EXCEPTION"):
                reevaluate_restricted(facility)
    else:
        touch(receipt)
    return ok(receipt_out(receipt))
