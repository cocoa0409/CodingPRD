"""Installment routes (GET only) (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services.listing import paginate_and_render
from services.serialize import installment_view

bp = Blueprint("installments", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/installments/<installment_id>", methods=["GET"])
def get_installment(installment_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.installments.get(installment_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Installment not found")
    return success(installment_view(record), status=200)


@bp.route("/institutions/installments", methods=["GET"])
def list_installments():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    records = list(db.installments.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, installment_view)
