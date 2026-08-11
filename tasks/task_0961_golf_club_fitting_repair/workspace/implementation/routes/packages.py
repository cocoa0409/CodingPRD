"""Lesson package endpoints."""
from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination, parse_iso
from services.common import new_entity, get_package, get_customer, check_ownership
from services.serializers import serialize_lesson_package

bp = Blueprint("packages", __name__)

READ_ROLES = {"ShopManager", "Instructor", "Customer"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/lesson-packages")
def create_package():
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    customer_id = data.get("customer_id")
    total_credits = data.get("total_credits")
    price_cents = data.get("price_cents")
    expires_raw = data.get("expires_at")
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise_err("ERR_VALIDATION", "customer_id is required")
    if not isinstance(total_credits, int) or isinstance(total_credits, bool) or total_credits < 1:
        raise_err("ERR_VALIDATION", "total_credits must be an integer >= 1")
    if not isinstance(price_cents, int) or isinstance(price_cents, bool):
        raise_err("ERR_VALIDATION", "price_cents must be an integer")
    try:
        expires_at = parse_iso(expires_raw)
    except (ValueError, TypeError):
        raise_err("ERR_VALIDATION", "expires_at must be an ISO8601 timestamp")
    get_customer(customer_id)
    p = new_entity()
    p.update({
        "customer_id": customer_id,
        "total_credits": total_credits,
        "credits_used": 0,
        "price_cents": price_cents,
        "expires_at": expires_at,
        "status": "ACTIVE",
    })
    db.lesson_packages[p["id"]] = p
    return success_response(serialize_lesson_package(p), status=201)


@bp.get("/lesson-packages/<pid>")
def read_package(pid):
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    p = get_package(pid)
    check_ownership(p, user_id, role)
    return success_response(serialize_lesson_package(p))


@bp.get("/lesson-packages")
def list_packages():
    user_id, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.lesson_packages.values())
    if role == "Customer":
        items = [p for p in items if p["customer_id"] == user_id]
    val = request.args.get("customer_id")
    if val is not None:
        items = [p for p in items if p["customer_id"] == val]
    items.sort(key=lambda p: p["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_lesson_package(p) for p in page],
        response_type="array", pagination=pagination,
    )
