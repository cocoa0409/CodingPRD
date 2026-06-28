"""Payment endpoints + billing-dimension advances (PRD §3.7)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services import calc
from services.common import (
    get_json_body, require_fields, require_int, require_enum, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg, optional_enum,
)

bp = Blueprint("payments", __name__)

KINDS = {"DEPOSIT", "INSTALLMENT"}
PAYMENT_STATUSES = {"CAPTURED", "REFUNDED"}
RW_ROLES = {"Registrar", "Parent"}


@bp.route("/payments", methods=["POST"])
def create_payment():
    _, role = get_auth()
    require_role(role, {"Registrar", "Parent"})
    body = get_json_body()
    require_fields(body, ["enrollment_id", "kind", "amount_cents"])

    enrollment_id = body["enrollment_id"]
    if not isinstance(enrollment_id, str):
        raise errors.invalid_request("enrollment_id must be a string.")
    kind = require_enum(body, "kind", KINDS)
    amount_cents = require_int(body, "amount_cents", minimum=1)

    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise errors.not_found("enrollment_id does not exist.")

    # Deposit fiscal rule (priority 14): DEPOSIT amount must equal deposit_cents
    # and may be posted only while billing_status == DEPOSIT_DUE.
    if kind == "DEPOSIT":
        if enr["billing_status"] != "DEPOSIT_DUE" or amount_cents != enr["deposit_cents"]:
            raise errors.deposit_amount_mismatch()

    payment = new_common_fields()
    payment.update({
        "enrollment_id": enrollment_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "CAPTURED",
        "captured_at": db.clock.now_iso(),
    })
    db.payments[payment["id"]] = payment

    # Recompute paid_to_date and advance billing dimension as warranted.
    enr["paid_to_date_cents"] = calc.compute_paid_to_date(enrollment_id)
    if (
        kind == "DEPOSIT"
        and enr["billing_status"] == "DEPOSIT_DUE"
        and amount_cents == enr["deposit_cents"]
    ):
        enr["billing_status"] = "ACTIVE"
    elif kind == "INSTALLMENT" and enr["billing_status"] == "PAST_DUE":
        enr["billing_status"] = "ACTIVE"
    touch(enr)

    return object_response(serialize(payment), 201)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_auth()
    require_role(role, RW_ROLES)
    payment = db.payments.get(payment_id)
    if payment is None:
        raise errors.not_found("Payment not found.")
    return object_response(serialize(payment), 200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    _, role = get_auth()
    require_role(role, RW_ROLES)
    limit, offset = parse_pagination()
    enrollment_id = str_arg("enrollment_id")
    status = optional_enum(str_arg("status"), PAYMENT_STATUSES, "status")
    kind = optional_enum(str_arg("kind"), KINDS, "kind")

    records = list(db.payments.values())
    if enrollment_id is not None:
        records = [p for p in records if p["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    if kind is not None:
        records = [p for p in records if p["kind"] == kind]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)
