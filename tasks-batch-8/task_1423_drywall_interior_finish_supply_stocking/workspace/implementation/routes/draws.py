"""DrawRequest and Payment endpoints."""
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OVERPAYMENT,
    ERR_DRAW_HAS_PAYMENTS, ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    require_enum, new_common_fields, touch,
)
from db import new_id, now_iso

bp = Blueprint("draws", __name__)


def _get_draw_or_404(did):
    d = db.draw_requests.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, "DrawRequest not found", 404)
    return d


@bp.route("/supply/draw-requests/<did>", methods=["GET"])
def get_draw(did):
    require_roles("CreditManager", "AccountsReceivableUser", "EstimatorUser")
    return success(_get_draw_or_404(did))


@bp.route("/supply/draw-requests", methods=["GET"])
def list_draws():
    require_roles("CreditManager", "AccountsReceivableUser", "EstimatorUser")
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    order_id = request.args.get("stocking_order_id")
    items = list(db.draw_requests.values())
    if project_id is not None:
        items = [d for d in items if d["project_id"] == project_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if order_id is not None:
        items = [d for d in items if d["stocking_order_id"] == order_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/draw-requests/<did>/payments", methods=["POST"])
def apply_payment(did):
    require_roles("AccountsReceivableUser")
    draw = _get_draw_or_404(did)
    b = body()
    require_fields(b, "amount_cents", "method", "received_at")
    amount = require_int(b, "amount_cents", min_val=1)
    method = require_enum(b, "method", {"ACH", "CHECK", "CARD"})
    received_at = require_str(b, "received_at")
    if draw["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError(ERR_INVALID_STATE, "Draw is not accepting payments", 409)
    remaining = draw["requested_cents"] - draw["paid_cents"]
    if amount > remaining:
        raise ApiError(ERR_OVERPAYMENT, "Payment exceeds draw remaining balance", 422)

    payment = {
        "id": new_id(),
        "created_at": now_iso(),
        "draw_request_id": did,
        "amount_cents": amount,
        "method": method,
        "received_at": received_at,
    }
    db.payments[payment["id"]] = payment

    draw["paid_cents"] = draw["paid_cents"] + amount
    if draw["paid_cents"] == draw["requested_cents"]:
        draw["status"] = "PAID"
    else:
        draw["status"] = "PARTIALLY_PAID"
    touch(draw)

    # Decrement account AR
    project = db.projects.get(draw["project_id"])
    if project:
        account = db.contractor_accounts.get(project["account_id"])
        if account:
            account["ar_outstanding_cents"] = account["ar_outstanding_cents"] - amount
            touch(account)

    return success(payment, status=201)


@bp.route("/supply/draw-requests/<did>/payments", methods=["GET"])
def list_payments(did):
    require_roles("CreditManager", "AccountsReceivableUser")
    _get_draw_or_404(did)
    limit, offset = parse_pagination()
    items = [p for p in db.payments.values() if p["draw_request_id"] == did]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/draw-requests/<did>/void", methods=["POST"])
def void_draw(did):
    require_roles("CreditManager")
    draw = _get_draw_or_404(did)
    if draw["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "Draw must be ISSUED to void", 409)
    if draw["paid_cents"] != 0:
        raise ApiError(ERR_DRAW_HAS_PAYMENTS, "Cannot void a draw with payments applied", 409)
    draw["status"] = "VOIDED"
    touch(draw)
    project = db.projects.get(draw["project_id"])
    if project:
        account = db.contractor_accounts.get(project["account_id"])
        if account:
            account["ar_outstanding_cents"] = account["ar_outstanding_cents"] - draw["requested_cents"]
            touch(account)
    return success(draw)
