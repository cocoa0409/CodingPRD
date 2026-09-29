"""Margin-call issuance, cure and waiver (PRD 3.6)."""

from flask import Blueprint

from db import by_created_at, db
from errors import ApiError
from middleware import BORROWER, COLLATERAL_ANALYST, CREDIT_OFFICER, require_auth
from response import ok
from routes.common import filter_by, get_margin_call, list_response
from serializers import cure_payment_out, margin_call_out
from services import computed, cure
from services.constants import DEFAULT_CURE_DAYS, OPEN_CALL_STATUSES, TRIGGER_REASONS
from services.states import (
    create_margin_call,
    facility_level_call_amount,
    restrict_if_active,
    waive_call,
)
from validation import MISSING, body, reject_system_fields, v_enum, v_id, v_int, v_string

bp = Blueprint("margin_calls", __name__)


@bp.post("/margin-calls")
def create_call():
    user_id, _role = require_auth([CREDIT_OFFICER])
    data = body()

    # priority 5
    facility_id = v_id(data, "facility_id")
    facility = db.facilities.get(facility_id)
    if facility is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND",
                       "No such facility: %s" % facility_id)
    advance = None
    advance_id = data.get("advance_id")
    if advance_id is not None:
        advance_id = v_id(data, "advance_id")
        advance = db.advances.get(advance_id)
        if advance is None or advance["facility_id"] != facility["id"]:
            raise ApiError("ERR_ADVANCE_NOT_FOUND",
                           "No such advance on this facility: %s" % advance_id)

    # priority 7
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "updated_at": MISSING, "version": 1,
                                "status": "ISSUED", "cured_amount_cents": 0,
                                "issued_at": MISSING, "cure_deadline_at": MISSING,
                                "call_amount_cents": MISSING,
                                "issued_by_user_id": user_id,
                                "waived_by_user_id": None})
    trigger_reason = v_enum(data, "trigger_reason", TRIGGER_REASONS)
    cure_days = v_int(data, "cure_days", required=False, minimum=0,
                      default=DEFAULT_CURE_DAYS)

    if advance is not None:
        amount = computed.store_valuation(advance)["required_paydown_cents"]
    else:
        amount = facility_level_call_amount(facility["id"])
    # priority 33
    if amount <= 0:
        raise ApiError("ERR_MARGIN_CALL_AMOUNT_ZERO",
                       "The computed call amount is zero.")

    call = create_margin_call(facility, advance, trigger_reason, amount,
                              cure_days=cure_days, issued_by_user_id=user_id)
    restrict_if_active(facility)
    return ok(margin_call_out(call), 201)


@bp.get("/margin-calls/<call_id>")
def read_call(call_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    call = get_margin_call(call_id)
    return ok(margin_call_out(call))


@bp.post("/margin-calls/<call_id>/cure-payments")
def create_cure_payment(call_id):
    require_auth([BORROWER, COLLATERAL_ANALYST])
    call = get_margin_call(call_id)
    data = body()
    reject_system_fields(data, {"id": MISSING, "created_at": MISSING,
                                "applied_at": MISSING,
                                "applied_to_fees_cents": MISSING,
                                "applied_to_principal_cents": MISSING,
                                "principal_allocation": MISSING,
                                "margin_call_id": call["id"]})
    amount_cents = v_int(data, "amount_cents", exclusive_min=0)
    expected_version = v_int(data, "expected_margin_call_version", minimum=0)
    # priority 8
    if expected_version != call["version"]:
        raise ApiError("ERR_STALE_MARGIN_CALL_VERSION",
                       "The margin call version has moved on.")
    # priority 14
    if call["status"] not in OPEN_CALL_STATUSES:
        raise ApiError("ERR_MARGIN_CALL_NOT_OPEN",
                       "Only an ISSUED or PARTIALLY_CURED call accepts payment.")
    facility = db.facilities[call["facility_id"]]
    # priority 32
    ceiling = (computed.accrued_fee_balance(facility["id"])
               + cure.remaining_obligation(call))
    if amount_cents > ceiling:
        raise ApiError("ERR_CURE_PAYMENT_EXCEEDS_OBLIGATION",
                       "The payment exceeds the outstanding obligation.")

    payment = cure.apply_cure_payment(call, facility, amount_cents)
    return ok(cure_payment_out(payment), 201)


@bp.get("/margin-calls/<call_id>/cure-payments")
def list_cure_payments(call_id):
    require_auth([CREDIT_OFFICER, COLLATERAL_ANALYST, BORROWER])
    call = get_margin_call(call_id)
    rows = by_created_at([p for p in db.cure_payments.values()
                          if p["margin_call_id"] == call["id"]])
    return list_response(rows, cure_payment_out)


@bp.post("/margin-calls/<call_id>/waive")
def waive(call_id):
    user_id, _role = require_auth([CREDIT_OFFICER])
    call = get_margin_call(call_id)
    data = body()
    v_string(data, "reason", max_len=500)
    # priority 14
    if call["status"] not in OPEN_CALL_STATUSES:
        raise ApiError("ERR_MARGIN_CALL_NOT_OPEN",
                       "Only an ISSUED or PARTIALLY_CURED call may be waived.")
    # priority 46, skipped when the comparand is null
    if call["issued_by_user_id"] is not None \
            and call["issued_by_user_id"] == user_id:
        raise ApiError("ERR_DUAL_CONTROL_VIOLATION",
                       "A margin call may not be waived by the user who issued it.")
    facility = db.facilities[call["facility_id"]]
    waive_call(call, facility, user_id)
    return ok(margin_call_out(call))
