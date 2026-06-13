"""LateFee routes (PRD §3.7)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import domain
from services.listing import paginate_and_render
from services.serialize import late_fee_view

bp = Blueprint("late_fees", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/late-fees/<late_fee_id>", methods=["GET"])
def get_late_fee(late_fee_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.late_fees.get(late_fee_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Late fee not found")
    return success(late_fee_view(record), status=200)


@bp.route("/institutions/late-fees", methods=["GET"])
def list_late_fees():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    installment_id = request.args.get("installment_id")
    status = request.args.get("status")
    records = list(db.late_fees.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if installment_id is not None:
        records = [r for r in records if r["installment_id"] == installment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, late_fee_view)


@bp.route("/institutions/late-fees/<late_fee_id>/waive", methods=["POST"])
def waive_late_fee(late_fee_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    late_fee = db.late_fees.get(late_fee_id)
    if late_fee is None:
        raise err("ERR_NOT_FOUND", "Late fee not found")
    if late_fee["status"] != "ASSESSED":
        raise err("ERR_INVALID_STATE", "Late fee must be ASSESSED to waive")

    late_fee["status"] = "WAIVED"
    db.touch(late_fee)

    enrollment = db.enrollments[late_fee["enrollment_id"]]
    domain.recompute_late_fee_balance(enrollment)
    db.touch(enrollment)

    return success(late_fee_view(late_fee), status=200)
