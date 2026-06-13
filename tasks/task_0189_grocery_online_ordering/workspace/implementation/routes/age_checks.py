"""AgeCheck endpoints (PRD §3.7, §3.9)."""
from flask import Blueprint, request

import db
import calculations as calc
from errors import (
    err, ERR_ORDER_NOT_FOUND, ERR_SLOT_NOT_FOUND, ERR_VALIDATION,
    ApiError,
)
from middleware import get_user_context, require_role
import validate as V
from timeutil import parse_iso
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("age_checks", __name__)

_NOT_FOUND_AGE_CHECK = ("ERR_VALIDATION", 404)


@bp.route("/v1/age-checks", methods=["POST"])
def create_age_check():
    user_id, role = get_user_context()
    require_role(role, {"StoreOps"})  # PRD §4: StoreOps only
    body = V.get_body()
    order_id = V.require_str(body, "order_id")
    verifier_user_id = V.require_str(body, "verifier_user_id")
    verified_birth_date = V.require_str(body, "verified_birth_date")
    try:
        parse_iso(verified_birth_date)
    except ValueError:
        err(ERR_VALIDATION, "verified_birth_date must be an ISO 8601 date")
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        slot = db.slots.get(order["slot_id"])
        if slot is None:
            err(ERR_SLOT_NOT_FOUND, "Slot not found")
        # outcome by completed-birthday rule against slot.window_start (PRD §3.7)
        outcome = calc.age_check_outcome(verified_birth_date, slot["window_start"])
        age_check = {
            "order_id": order_id,
            "verifier_user_id": verifier_user_id,
            "verified_birth_date": verified_birth_date,
            "outcome": outcome,
        }
        db.stamp_create(age_check)
        db.age_checks[age_check["id"]] = age_check
        return object_response(public(age_check), 201)


@bp.route("/v1/age-checks", methods=["GET"])
def list_age_checks():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    limit, offset = get_pagination()
    order_id = request.args.get("order_id")
    with db.lock:
        records = list(db.age_checks.values())
        if order_id is not None:
            records = [a for a in records if a["order_id"] == order_id]
        if role == "Customer":
            owned = {o["id"] for o in db.orders.values() if o["customer_id"] == user_id}
            records = [a for a in records if a["order_id"] in owned]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/age-checks/<age_check_id>", methods=["GET"])
def get_age_check(age_check_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    with db.lock:
        age_check = db.age_checks.get(age_check_id)
        if age_check is None:
            raise ApiError(_NOT_FOUND_AGE_CHECK[0], _NOT_FOUND_AGE_CHECK[1], "Age check not found")
        return object_response(public(age_check))
