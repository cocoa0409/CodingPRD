from flask import Blueprint, request
from db import db, new_common_fields, touch, fmt_ts, now
from errors import err
from middleware import get_caller, require_role
from response import object_response, array_response, parse_pagination, paginate
from validate import body, require_str, require_enum, require_int
import lookups
from services import calculations as calc

subrogation_bp = Blueprint("subrogation", __name__)


def _renter_id_for_case(case):
    claim = lookups.claim_for_subrogation_case(case)
    return lookups.renter_id_for_claim(claim)


def _check_case_ownership(caller, case):
    if caller.role == "Renter" and _renter_id_for_case(case) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this subrogation case.")


@subrogation_bp.get("/subrogation-cases/<case_id>")
def get_subrogation_case(case_id):
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer", "PlatformAdmin", "Renter"})
    case = lookups.get_subrogation_case(case_id)
    _check_case_ownership(caller, case)
    return object_response(case)


@subrogation_bp.post("/subrogation-cases/<case_id>/transition")
def subrogation_case_transition(case_id):
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer"})
    b = body()
    action = require_enum(b, "action", {"SEND_DEMAND", "WRITE_OFF"})

    case = lookups.get_subrogation_case(case_id)

    if action == "SEND_DEMAND":
        if case["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Subrogation case is not OPEN.")
        case["status"] = "DEMAND_SENT"
        case["demand_sent_at"] = fmt_ts(now())
    else:
        if case["status"] != "DEMAND_SENT":
            raise err("ERR_INVALID_STATE", "Subrogation case is not DEMAND_SENT.")
        case["status"] = "WRITTEN_OFF"

    touch(case)
    return object_response(case)


@subrogation_bp.post("/subrogation-cases/<case_id>/recovery-payments")
def record_recovery_payment(case_id):
    caller = get_caller()
    require_role(caller, {"Renter"})
    b = body()
    body_case_id = require_str(b, "subrogation_case_id")
    amount_cents = require_int(b, "amount_cents", positive=True)

    case = lookups.get_subrogation_case(case_id)
    if body_case_id != case_id:
        lookups.get_subrogation_case(body_case_id)

    if _renter_id_for_case(case) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this subrogation case.")

    if case["status"] != "DEMAND_SENT":
        raise err("ERR_INVALID_STATE", "Subrogation case is not DEMAND_SENT.")

    if amount_cents > case["outstanding_balance_cents"]:
        raise err("ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE", "Payment exceeds outstanding balance.")

    payment = {
        **new_common_fields(),
        "subrogation_case_id": case["id"],
        "amount_cents": amount_cents,
        "status": "SUCCEEDED",
        "paid_at": fmt_ts(now()),
        "reversed_at": None,
    }
    db.recovery_payments[payment["id"]] = payment

    payments = lookups.recovery_payments_for_case(case["id"])
    case["outstanding_balance_cents"] = calc.subrogation_outstanding_balance(
        case["original_demand_amount_cents"], payments
    )
    if case["outstanding_balance_cents"] == 0:
        case["status"] = "PAID_IN_FULL"
    touch(case)

    return object_response(payment, 201)


@subrogation_bp.get("/subrogation-cases/<case_id>/recovery-payments")
def list_recovery_payments(case_id):
    caller = get_caller()
    require_role(caller, {"Renter", "ComplianceOfficer", "PlatformAdmin"})
    case = lookups.get_subrogation_case(case_id)
    _check_case_ownership(caller, case)

    limit, offset = parse_pagination(request.args)
    items = lookups.recovery_payments_for_case(case["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)
