from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import require_int, require_string, optional_bool, parse_pagination
from response import success_object, success_list
from errors import ApiError
from db import db, touch, CLOCK, add_days
from services.serialize import serialize
from services.core import recompute_landlord_totals
from services.sweeps import GRACE_DAYS, WAIVER_AUTHORITY_CENTS

bp = Blueprint("installments", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}


def _landlord_id_for(inst):
    lease = db.leases.get(inst["lease_id"])
    return lease["landlord_id"] if lease else None


@bp.route("/installments/<installmentId>", methods=["GET"])
def get_installment(installmentId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.installments.get(installmentId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Installment {installmentId} not found")
    return success_object(serialize("installment", rec))


@bp.route("/installments", methods=["GET"])
def list_installments():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.installments.values(),
                   key=lambda r: (r["due_date"], r["created_at"]))
    lease_q = request.args.get("lease_id")
    if lease_q is not None:
        items = [r for r in items if r["lease_id"] == lease_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("installment", r) for r in page], limit, offset, total)


@bp.route("/installments/<installmentId>/record_payment", methods=["POST"])
def record_payment(installmentId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=1)

    rec = db.installments.get(installmentId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Installment {installmentId} not found")
    if rec["status"] not in ("OPEN", "LATE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Installment in state {rec['status']} cannot receive payment")

    outstanding = rec["amount_cents"] + rec.get("late_fee_cents", 0) - rec.get("paid_cents", 0)
    if amount > outstanding:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 409,
                       "Payment exceeds outstanding balance")

    rec["paid_cents"] = rec.get("paid_cents", 0) + amount
    rec["last_payment_at"] = CLOCK.get()
    rec["paid_recorded_by"] = user_id
    if rec["paid_cents"] >= rec["amount_cents"] + rec.get("late_fee_cents", 0):
        rec["status"] = "PAID"
    touch(rec)
    lid = _landlord_id_for(rec)
    if lid:
        recompute_landlord_totals(lid)
    return success_object(serialize("installment", rec))


@bp.route("/installments/<installmentId>/reverse_payment", methods=["POST"])
def reverse_payment(installmentId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.installments.get(installmentId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Installment {installmentId} not found")
    if rec["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Installment in state {rec['status']} cannot be reversed")
    if rec.get("paid_recorded_by") == user_id:
        raise ApiError("ERR_DUTY_SEGREGATION_VIOLATION", 403,
                       "Reverser must differ from the manager who recorded the payment")

    rec["paid_cents"] = 0
    rec["paid_recorded_by"] = None
    # reopen to OPEN, or LATE if past grace
    if CLOCK.get() > add_days(rec["due_date"], GRACE_DAYS):
        rec["status"] = "LATE"
    else:
        rec["status"] = "OPEN"
    touch(rec)
    lid = _landlord_id_for(rec)
    if lid:
        recompute_landlord_totals(lid)
    return success_object(serialize("installment", rec))


@bp.route("/installments/<installmentId>/waive", methods=["POST"])
def waive_installment(installmentId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    require_string(body, "reason")
    landlord_consent = optional_bool(body, "landlord_consent", default=False)

    rec = db.installments.get(installmentId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Installment {installmentId} not found")
    if rec["status"] not in ("OPEN", "LATE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Installment in state {rec['status']} cannot be waived")

    outstanding = rec["amount_cents"] + rec.get("late_fee_cents", 0) - rec.get("paid_cents", 0)
    if outstanding > WAIVER_AUTHORITY_CENTS and not landlord_consent:
        raise ApiError("ERR_WAIVER_EXCEEDS_AUTHORITY", 409,
                       "Waiver exceeds manager authority without landlord consent")

    rec["status"] = "WAIVED"
    touch(rec)
    lid = _landlord_id_for(rec)
    if lid:
        recompute_landlord_totals(lid)
    return success_object(serialize("installment", rec))
