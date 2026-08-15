"""Payment run endpoints: read, approve, pay, void."""

from flask import Blueprint, request
from db import payment_runs, photographers, now_iso
from errors import (
    ApiError, ERR_PAYMENT_RUN_NOT_FOUND, ERR_INVALID_STATE,
)
from response import success_object
from middleware import get_auth, require_role
from serializers import serialize_payment_run

bp = Blueprint("payment_runs", __name__)


@bp.route("/payment-runs/<prid>", methods=["GET"])
def get_payment_run(prid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin"})

    pr = payment_runs.get(prid)
    if pr is None:
        raise ApiError(ERR_PAYMENT_RUN_NOT_FOUND, f"Payment run {prid} not found", 404)
    return success_object(serialize_payment_run(pr))


@bp.route("/payment-runs/<prid>/approve", methods=["POST"])
def approve_payment_run(prid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin"})

    pr = payment_runs.get(prid)
    if pr is None:
        raise ApiError(ERR_PAYMENT_RUN_NOT_FOUND, f"Payment run {prid} not found", 404)

    if pr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot approve payment run in status {pr['status']}", 409)

    pr["status"] = "APPROVED"
    pr["updated_at"] = now_iso()
    pr["version"] += 1
    return success_object(serialize_payment_run(pr))


@bp.route("/payment-runs/<prid>/pay", methods=["POST"])
def pay_payment_run(prid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin"})

    pr = payment_runs.get(prid)
    if pr is None:
        raise ApiError(ERR_PAYMENT_RUN_NOT_FOUND, f"Payment run {prid} not found", 404)

    if pr["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot pay payment run in status {pr['status']}", 409)

    now = now_iso()
    pr["status"] = "PAID"
    pr["paid_at"] = now
    pr["updated_at"] = now
    pr["version"] += 1

    # Credit paid_out_cents
    photog = photographers.get(pr["photographer_id"])
    if photog:
        photog["paid_out_cents"] += pr["total_cents"]
        photog["updated_at"] = now
        photog["version"] += 1

    return success_object(serialize_payment_run(pr))


@bp.route("/payment-runs/<prid>/void", methods=["POST"])
def void_payment_run(prid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin"})

    pr = payment_runs.get(prid)
    if pr is None:
        raise ApiError(ERR_PAYMENT_RUN_NOT_FOUND, f"Payment run {prid} not found", 404)

    if pr["status"] not in ("DRAFT", "APPROVED", "PAID"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot void payment run in status {pr['status']}", 409)

    old_status = pr["status"]
    now = now_iso()
    pr["status"] = "VOIDED"
    pr["updated_at"] = now
    pr["version"] += 1

    # Compensation: PAID -> VOIDED debits paid_out_cents
    if old_status == "PAID":
        photog = photographers.get(pr["photographer_id"])
        if photog:
            photog["paid_out_cents"] -= pr["total_cents"]
            photog["updated_at"] = now
            photog["version"] += 1

    return success_object(serialize_payment_run(pr))
