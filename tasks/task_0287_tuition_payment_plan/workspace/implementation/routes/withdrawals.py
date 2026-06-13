"""Withdrawal routes (GET only) (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services.listing import paginate_and_render
from services.serialize import withdrawal_view

bp = Blueprint("withdrawals", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/withdrawals/<withdrawal_id>", methods=["GET"])
def get_withdrawal(withdrawal_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.withdrawals.get(withdrawal_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Withdrawal not found")
    return success(withdrawal_view(record), status=200)


@bp.route("/institutions/withdrawals", methods=["GET"])
def list_withdrawals():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    enrollment_id = request.args.get("enrollment_id")
    records = list(db.withdrawals.values())
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    return paginate_and_render(records, withdrawal_view)
