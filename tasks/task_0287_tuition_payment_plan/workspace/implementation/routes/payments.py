"""Payment routes (PRD §3.6)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import validate, domain
from services.listing import paginate_and_render
from services.serialize import payment_view

bp = Blueprint("payments", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/payments", methods=["POST"])
def create_payment():
    user_id, role = get_user_context()
    require_role(role, ("Bursar", "Student"))
    body = validate.get_body()

    enrollment_id = validate.require_string(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    # Student ownership: the enrollment's student_id must equal X-User-ID (PRD §2.1).
    if role == "Student" and enrollment["student_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Student does not own this enrollment")

    purpose = validate.require_enum(body, "purpose",
                                    ("DOWN_PAYMENT", "INSTALLMENT", "AUTOPAY"))
    amount_cents = validate.require_positive_amount(body, "amount_cents")

    installment_id = body.get("installment_id")
    if purpose in ("INSTALLMENT", "AUTOPAY"):
        if not isinstance(installment_id, str) or installment_id.strip() == "":
            raise err("ERR_INVALID_REQUEST",
                      "installment_id is required for installment payments")
        installment = db.installments.get(installment_id)
        if installment is None:
            raise err("ERR_NOT_FOUND", "Installment not found")
        if installment["enrollment_id"] != enrollment_id:
            raise err("ERR_NOT_FOUND", "Installment does not belong to enrollment")
    else:
        # DOWN_PAYMENT: installment_id is omitted.
        installment_id = None

    payment = db.stamp_new({
        "institution_id": enrollment["institution_id"],
        "enrollment_id": enrollment_id,
        "installment_id": installment_id,
        "purpose": purpose,
        "amount_cents": amount_cents,
        "status": "PENDING",
    })
    db.payments[payment["id"]] = payment
    return success(payment_view(payment), status=201)


@bp.route("/institutions/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.payments.get(payment_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Payment not found")
    return success(payment_view(record), status=200)


@bp.route("/institutions/payments", methods=["GET"])
def list_payments():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    installment_id = request.args.get("installment_id")
    status = request.args.get("status")
    records = list(db.payments.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if installment_id is not None:
        records = [r for r in records if r["installment_id"] == installment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, payment_view)


@bp.route("/institutions/payments/<payment_id>/settle", methods=["POST"])
def settle_payment(payment_id):
    _, role = get_user_context()
    require_role(role, ("Bursar",))
    payment = db.payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "Payment not found")

    if payment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Payment must be PENDING to settle")

    enrollment = db.enrollments[payment["enrollment_id"]]
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Parent enrollment is not ACTIVE")

    if payment["purpose"] == "DOWN_PAYMENT":
        if enrollment.get("down_payment_collected"):
            raise err("ERR_DOWN_PAYMENT_ALREADY_PAID",
                      "Down payment already collected")
        payment["status"] = "SETTLED"
        db.touch(payment)
        enrollment["down_payment_collected"] = True
        domain.recompute_paid_principal(enrollment)
        db.touch(enrollment)
        domain.maybe_complete(enrollment)
    else:  # INSTALLMENT or AUTOPAY
        installment = db.installments.get(payment["installment_id"])
        if installment is None or installment["enrollment_id"] != enrollment["id"]:
            raise err("ERR_NOT_FOUND", "Installment not found")
        if installment["status"] not in ("SCHEDULED", "OVERDUE"):
            raise err("ERR_INSTALLMENT_NOT_PAYABLE",
                      "Targeted installment is not payable")

        payment["status"] = "SETTLED"
        db.touch(payment)

        was_overdue = installment["status"] == "OVERDUE"
        installment["paid_amount_cents"] += payment["amount_cents"]
        db.touch(installment)

        if installment["paid_amount_cents"] >= installment["amount_cents"]:
            installment["status"] = "PAID"
            db.touch(installment)
            if was_overdue:
                enrollment["delinquent_installment_count"] -= 1
            domain.recompute_scheduled_balance(enrollment)
            domain.recompute_paid_principal(enrollment)
            db.touch(enrollment)
            if was_overdue:
                # Re-evaluate delinquency (may release a hold).
                domain.delinquency_evaluation(enrollment)
            domain.maybe_complete(enrollment)
        else:
            domain.recompute_scheduled_balance(enrollment)
            domain.recompute_paid_principal(enrollment)
            db.touch(enrollment)

    return success(payment_view(payment), status=200)


@bp.route("/institutions/payments/<payment_id>/fail", methods=["POST"])
def fail_payment(payment_id):
    _, role = get_user_context()
    require_role(role, ("Bursar",))
    payment = db.payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "Payment not found")
    if payment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Payment must be PENDING to fail")
    payment["status"] = "FAILED"
    db.touch(payment)
    return success(payment_view(payment), status=200)
