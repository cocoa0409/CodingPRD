"""Annual-fee endpoints."""
from flask import Blueprint, request, g

import db
from middleware import require_roles
from response import success, success_list
from services import annual_fee_logic, serializers
from services.common import check_version, get_or_404
from utils import get_pagination, paginate

bp = Blueprint("annual_fees", __name__)


@bp.route("/ip-rights/<right_id>/annual-fees", methods=["POST"])
@require_roles("FinanceManager", "IPManager")
def schedule_fee(right_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        right = get_or_404(db.ip_rights, right_id)
        fee = annual_fee_logic.schedule_annual_fee(right, body, g.user_role, g.user_id)
    return success(serializers.serialize_annual_fee(fee), 201)


@bp.route("/annual-fees", methods=["GET"])
@require_roles("FinanceManager", "IPManager", "Admin")
def list_annual_fees():
    limit, offset = get_pagination(request.args)
    ip_right_id = request.args.get("ip_right_id")
    status = request.args.get("status")
    due_before = request.args.get("due_before")
    items = list(db.annual_fees.values())
    if ip_right_id:
        items = [f for f in items if f["ip_right_id"] == ip_right_id]
    if status:
        items = [f for f in items if f["status"] == status]
    if due_before:
        due_before_dt = db.parse_iso(due_before)
        if due_before_dt:
            items = [f for f in items if db.parse_iso(f["due_date"]) and
                     db.parse_iso(f["due_date"]) < due_before_dt]
    items.sort(key=lambda f: f["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_annual_fee(f) for f in window]
    return success_list(data, limit, offset, total)


@bp.route("/annual-fees/<fee_id>/pay", methods=["POST"])
@require_roles("FinanceManager")
def pay_fee(fee_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        fee = get_or_404(db.annual_fees, fee_id)
        check_version(fee, body)
        annual_fee_logic.pay_fee(fee, g.user_role, g.user_id, via_external=False)
    return success(serializers.serialize_annual_fee(fee))
