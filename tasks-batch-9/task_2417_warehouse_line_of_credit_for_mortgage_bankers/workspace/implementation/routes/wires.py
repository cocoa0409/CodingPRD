"""The wire-fraud control at the heart of the funding path (PRD 3.3)."""

from flask import Blueprint

from db import db, touch
from errors import ApiError
from middleware import COLLATERAL_ANALYST, WIRE_OPERATOR, require_auth
from response import ok
from routes.common import get_wire
from serializers import wire_out
from validation import MISSING, body, reject_system_fields, v_enum, v_string

bp = Blueprint("wires", __name__)

DECISIONS = ("VERIFY", "BLOCK")


@bp.post("/wire-instructions/<wire_id>/decision")
def decide_wire(wire_id):
    user_id, _role = require_auth([COLLATERAL_ANALYST, WIRE_OPERATOR])
    wire = get_wire(wire_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING,
                                "status": wire["status"],
                                "amount_cents": wire["amount_cents"],
                                "decided_by_user_id": wire["decided_by_user_id"]})
    decision = v_enum(data, "decision", DECISIONS)
    callback_reference = None
    block_reason = None
    if decision == "VERIFY":
        callback_reference = v_string(data, "callback_reference", max_len=200)
    else:
        block_reason = v_string(data, "block_reason", required=False, max_len=100,
                                default="OPERATOR_BLOCK")
        # an operator-initiated block requires that reason to be OPERATOR_BLOCK
        if block_reason != "OPERATOR_BLOCK":
            raise ApiError("ERR_VALIDATION",
                           "An operator block must carry a block_reason of "
                           "OPERATOR_BLOCK.")

    # priority 13
    if wire["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_WIRE_INSTRUCTION_NOT_PENDING",
                       "A wire instruction is decided exactly once.")

    advance = db.advances[wire["advance_id"]]
    facility = db.facilities[advance["facility_id"]]

    if decision == "VERIFY":
        # priority 20; the comparison is not applied to a block
        if wire["payee_account_last4"] != facility["settlement_account_last4"]:
            raise ApiError("ERR_PAYEE_ACCOUNT_MISMATCH",
                           "The wire payee account does not match the facility "
                           "settlement account.")
        wire["status"] = "VERIFIED"
        wire["callback_reference"] = callback_reference
        wire["decided_by_user_id"] = user_id
        touch(wire)
        return ok(wire_out(wire))

    wire["status"] = "BLOCKED"
    wire["block_reason"] = block_reason
    wire["decided_by_user_id"] = user_id
    touch(wire)
    if advance["funding_status"] == "REQUESTED":
        advance["funding_status"] = "REJECTED"
        advance["rejected_reason"] = "WIRE_BLOCKED"
        touch(advance)
    return ok(wire_out(wire))
