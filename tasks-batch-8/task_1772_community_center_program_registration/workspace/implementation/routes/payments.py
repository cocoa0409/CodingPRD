"""PaymentTransaction endpoints (PRD 3.7)."""
from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize
from errors import raise_err
from util import get_or_404, list_response, serialize, success_object

bp = Blueprint("payments", __name__)

FIELDS = [
    "id",
    "registration_id",
    "type",
    "amount_cents",
    "method",
    "status",
    "created_at",
    "updated_at",
    "version",
]

READ_ROLES = ["HouseholdManager", "FrontDeskStaff", "ProgramCoordinator", "FinanceOfficer"]


def payment_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/payments", methods=["GET"])
def list_payments():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    registration_id = request.args.get("registration_id")
    records = list(store.payments.values())
    if registration_id is not None:
        records = [r for r in records if r["registration_id"] == registration_id]
    # Default sort created_at ASC (chronological): a CHARGE precedes its REFUND.
    return list_response(records, payment_out)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    rec = get_or_404(store.payments, payment_id, "PaymentTransaction")
    return success_object(payment_out(rec), 200)


@bp.route("/payments/<payment_id>/approve-refund", methods=["POST"])
def approve_refund(payment_id):
    _, role = authenticate()
    authorize(role, ["FinanceOfficer"])
    rec = get_or_404(store.payments, payment_id, "PaymentTransaction")
    if not (rec["type"] == "REFUND" and rec["status"] == "PENDING"):
        raise_err("ERR_REFUND_NOT_PENDING", "Only a PENDING REFUND transaction can be approved")
    services.approve_refund(rec)
    return success_object(payment_out(rec), 200)
