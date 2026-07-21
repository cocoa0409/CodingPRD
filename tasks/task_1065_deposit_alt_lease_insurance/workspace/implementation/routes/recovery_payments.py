from flask import Blueprint
from db import touch, fmt_ts, now
from errors import err
from middleware import get_caller, require_role
from response import object_response
import lookups
from services import calculations as calc

recovery_payments_bp = Blueprint("recovery_payments", __name__)


@recovery_payments_bp.post("/recovery-payments/<payment_id>/reverse")
def reverse_recovery_payment(payment_id):
    caller = get_caller()
    require_role(caller, {"PlatformAdmin"})

    payment = lookups.get_recovery_payment(payment_id)
    if payment["status"] != "SUCCEEDED":
        raise err("ERR_INVALID_STATE", "Recovery payment is not SUCCEEDED.")

    payment["status"] = "REVERSED"
    payment["reversed_at"] = fmt_ts(now())
    touch(payment)

    case = lookups.subrogation_case_for_recovery_payment(payment)
    payments = lookups.recovery_payments_for_case(case["id"])
    case["outstanding_balance_cents"] = calc.subrogation_outstanding_balance(
        case["original_demand_amount_cents"], payments
    )
    if case["status"] == "PAID_IN_FULL":
        case["status"] = "DEMAND_SENT"
    touch(case)

    return object_response(payment)
