"""Charge routes (PRD §3.3, §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import validate, calc, domain
from services.listing import paginate_and_render
from services.serialize import charge_view

bp = Blueprint("charges", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


def _scheduled_installments(enrollment_id):
    return [i for i in domain.installments_of(enrollment_id)
            if i["status"] == "SCHEDULED"]


@bp.route("/institutions/charges", methods=["POST"])
def create_charge():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    enrollment_id = validate.require_string(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    kind = validate.require_enum(body, "kind", ("TUITION", "FEE", "HOUSING"))
    amount_cents = validate.require_positive_amount(body, "amount_cents")

    # PRD §3.8: posting a charge for a student on hold is rejected.
    student = db.students[enrollment["student_id"]]
    if student["has_active_hold"]:
        raise err("ERR_STUDENT_ON_HOLD", "Student is on hold")

    # On an ACTIVE enrollment the delta must re-spread; guard the no-scheduled
    # case BEFORE committing the charge so the operation is atomic (PRD §3.5).
    if enrollment["status"] == "ACTIVE" and len(_scheduled_installments(enrollment_id)) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")

    old_net = enrollment["net_after_aid_cents"]

    charge = db.stamp_new({
        "institution_id": enrollment["institution_id"],
        "enrollment_id": enrollment_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "POSTED",
    })
    db.charges[charge["id"]] = charge

    domain.recompute_gross_and_aid(enrollment)
    new_net = enrollment["net_after_aid_cents"]

    if enrollment["status"] == "ACTIVE":
        _respread(enrollment, new_net - old_net)
    db.touch(enrollment)

    return success(charge_view(charge), status=201)


@bp.route("/institutions/charges/<charge_id>", methods=["GET"])
def get_charge(charge_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.charges.get(charge_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Charge not found")
    return success(charge_view(record), status=200)


@bp.route("/institutions/charges", methods=["GET"])
def list_charges():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    records = list(db.charges.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, charge_view)


@bp.route("/institutions/charges/<charge_id>/reverse", methods=["POST"])
def reverse_charge(charge_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    charge = db.charges.get(charge_id)
    if charge is None:
        raise err("ERR_NOT_FOUND", "Charge not found")
    if charge["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Charge must be POSTED to reverse")

    enrollment = db.enrollments[charge["enrollment_id"]]
    if enrollment["status"] not in ("PENDING", "ACTIVE"):
        raise err("ERR_ENROLLMENT_NOT_ACTIVE",
                  "Enrollment must be PENDING or ACTIVE")

    # Guard the no-scheduled case before committing (PRD §3.5, atomic).
    if enrollment["status"] == "ACTIVE" and len(_scheduled_installments(enrollment["id"])) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")

    old_net = enrollment["net_after_aid_cents"]
    charge["status"] = "REVERSED"
    db.touch(charge)

    domain.recompute_gross_and_aid(enrollment)
    new_net = enrollment["net_after_aid_cents"]

    if enrollment["status"] == "ACTIVE":
        _respread(enrollment, new_net - old_net)
    db.touch(enrollment)

    return success(charge_view(charge), status=200)


def _respread(enrollment, delta):
    scheduled = _scheduled_installments(enrollment["id"])
    if len(scheduled) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")
    calc.respread_delta(delta, scheduled)
    for inst in scheduled:
        db.touch(inst)
    domain.recompute_scheduled_balance(enrollment)
