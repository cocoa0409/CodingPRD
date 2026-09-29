from flask import Blueprint

import calc
import derive
import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import clock_date, clock_iso, db, new_record, sorted_records, touch

bp = Blueprint("payments", __name__)

METHODS = ("CHECK", "ACH", "CARD")
READ_ROLES = ["CorpsDirector", "BusinessManager", "Member"]
LIST_ROLES = ["CorpsDirector", "BusinessManager"]


@bp.route("/tuition-payments", methods=["POST"])
@endpoint(["BusinessManager"])
def create_payment():
    body = v.get_body()
    plan_id = v.req_str(body, "payment_plan_id")
    amount = v.req_int(body, "amount_cents")
    received_raw, received_on = v.req_date(body, "received_on")
    method = v.req_enum(body, "method", METHODS)
    # Rung 6 -- a payment's amount_cents must be greater than 0.
    v.positive(amount > 0, "amount_cents must be greater than 0.")
    plan = find.plan(plan_id)
    # Rung 15 -- deliberately outranks the over-payment check at rung 57.
    if plan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_PLAN_NOT_ACCEPTING_PAYMENTS",
                       "This plan accepts no further money.")
    # Rung 44 -- the receipt date may not be later than the logical-clock date.
    if received_on > clock_date():
        raise ApiError("ERR_FUTURE_DATED_INPUT",
                       "received_on may not be later than the logical-clock date.")
    figures = derive.plan_figures(plan)
    late_fee_outstanding = plan["late_fee_accrued_cents"] - figures["late_fee_paid_cents"]
    principal_outstanding = plan["financed_total_cents"] - figures["principal_paid_cents"]
    # Rung 57 -- money, last.
    if amount > late_fee_outstanding + principal_outstanding:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The tender exceeds the plan's total outstanding obligation.")

    to_late_fee, to_principal = calc.payment_waterfall_allocation(
        amount, late_fee_outstanding, principal_outstanding)

    record = new_record()
    record.update({
        "payment_plan_id": plan_id,
        "amount_cents": amount,
        "received_on": received_raw,
        "method": method,
        "allocated_to_late_fee_cents": to_late_fee,
        "allocated_to_principal_cents": to_principal,
        "status": "POSTED",
        "reversal_reason": None,
        "reversed_at": None,
    })
    db.payments[record["id"]] = record
    # The tuition chain of PRD 2.9 runs on live definitions; only the plan's
    # own status re-evaluation can move a stored field.
    services.reevaluate_plan_after_payment(plan)
    return object_response(serialize.payment(record), 201)


@bp.route("/tuition-payments/<tuition_payment_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_payment(tuition_payment_id):
    return object_response(serialize.payment(find.payment(tuition_payment_id)))


@bp.route("/tuition-payments", methods=["GET"])
@endpoint(LIST_ROLES)
def list_payments():
    plan_id = v.arg_str("payment_plan_id")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.payments):
        if plan_id is not None and record["payment_plan_id"] != plan_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.payment)


@bp.route("/tuition-payments/<tuition_payment_id>/reverse", methods=["POST"])
@endpoint(["BusinessManager"])
def reverse_payment(tuition_payment_id):
    body = v.get_body()
    reason = v.req_str(body, "reversal_reason")
    payment = find.payment(tuition_payment_id)
    plan = db.plans.get(payment["payment_plan_id"])
    # Rung 16 -- POSTED payment on a plan that is not SUPERSEDED.
    if payment["status"] != "POSTED" or (plan is not None and plan["status"] == "SUPERSEDED"):
        raise ApiError("ERR_INVALID_PAYMENT_STATE",
                       "This payment may not be reversed.")
    payment["status"] = "REVERSED"
    payment["reversal_reason"] = reason
    payment["reversed_at"] = clock_iso()
    touch(payment)
    if plan is not None:
        services.reevaluate_plan_after_reversal(plan)
    return object_response(serialize.payment(payment))
