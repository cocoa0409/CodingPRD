"""FinancialAid routes (PRD §3.3, §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import validate, calc, domain
from services.listing import paginate_and_render
from services.serialize import aid_view

bp = Blueprint("aids", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


def _scheduled_installments(enrollment_id):
    return [i for i in domain.installments_of(enrollment_id)
            if i["status"] == "SCHEDULED"]


def _respread(enrollment, delta):
    scheduled = _scheduled_installments(enrollment["id"])
    if len(scheduled) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")
    calc.respread_delta(delta, scheduled)
    for inst in scheduled:
        db.touch(inst)
    domain.recompute_scheduled_balance(enrollment)


@bp.route("/institutions/aids", methods=["POST"])
def create_aid():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    enrollment_id = validate.require_string(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found")

    source = validate.require_enum(body, "source", ("GRANT", "SCHOLARSHIP", "LOAN"))
    amount_cents = validate.require_positive_amount(body, "amount_cents")

    if enrollment["status"] == "ACTIVE" and len(_scheduled_installments(enrollment_id)) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")

    old_net = enrollment["net_after_aid_cents"]

    aid = db.stamp_new({
        "institution_id": enrollment["institution_id"],
        "enrollment_id": enrollment_id,
        "source": source,
        "amount_cents": amount_cents,
        "status": "APPLIED",
    })
    db.aids[aid["id"]] = aid

    domain.recompute_gross_and_aid(enrollment)
    new_net = enrollment["net_after_aid_cents"]

    if enrollment["status"] == "ACTIVE":
        _respread(enrollment, new_net - old_net)
    db.touch(enrollment)

    return success(aid_view(aid), status=201)


@bp.route("/institutions/aids/<aid_id>", methods=["GET"])
def get_aid(aid_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.aids.get(aid_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Aid record not found")
    return success(aid_view(record), status=200)


@bp.route("/institutions/aids", methods=["GET"])
def list_aids():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    records = list(db.aids.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, aid_view)


@bp.route("/institutions/aids/<aid_id>/cancel", methods=["POST"])
def cancel_aid(aid_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    aid = db.aids.get(aid_id)
    if aid is None:
        raise err("ERR_NOT_FOUND", "Aid record not found")
    if aid["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Aid must be APPLIED to cancel")

    enrollment = db.enrollments[aid["enrollment_id"]]
    if enrollment["status"] not in ("PENDING", "ACTIVE"):
        raise err("ERR_ENROLLMENT_NOT_ACTIVE",
                  "Enrollment must be PENDING or ACTIVE")

    if enrollment["status"] == "ACTIVE" and len(_scheduled_installments(enrollment["id"])) == 0:
        raise err("ERR_NO_SCHEDULED_INSTALLMENTS",
                  "No scheduled installments to absorb the delta")

    old_net = enrollment["net_after_aid_cents"]
    aid["status"] = "CANCELLED"
    db.touch(aid)

    domain.recompute_gross_and_aid(enrollment)
    new_net = enrollment["net_after_aid_cents"]

    if enrollment["status"] == "ACTIVE":
        _respread(enrollment, new_net - old_net)
    db.touch(enrollment)

    return success(aid_view(aid), status=200)
