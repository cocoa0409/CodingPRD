"""Payout batch and payment routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import payout as svc

bp = Blueprint("payouts", __name__)


@bp.route("/payout-batches", methods=["POST"])
def create():
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.generate_payout_batch(body)
    return success_response(data, status_code=201)


@bp.route("/payout-batches/<batch_id>/execute", methods=["POST"])
def execute(batch_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.execute_batch(batch_id, body)
    return success_response(data)


@bp.route("/payout-batches/<batch_id>", methods=["GET"])
def get(batch_id):
    require_role("PlatformAdmin", "FinanceOps")
    data = svc.get_batch(batch_id)
    return success_response(data)


@bp.route("/payout-batches/<batch_id>/payments", methods=["GET"])
def list_payments(batch_id):
    require_role("PlatformAdmin", "FinanceOps")
    items, total, limit, offset = svc.list_payments(batch_id, request.args)
    return list_response(items, total, limit, offset)


@bp.route("/payments/<payment_id>/retry", methods=["POST"])
def retry(payment_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.retry_payment(payment_id, body)
    return success_response(data)


@bp.route("/payments/<payment_id>/abandon", methods=["POST"])
def abandon(payment_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.abandon_payment(payment_id, body)
    return success_response(data)
