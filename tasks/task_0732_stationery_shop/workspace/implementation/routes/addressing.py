"""Addressing job endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("addressing", __name__)


@bp.route("/orders/<oid>/addressing-jobs", methods=["POST"])
def create_addressing_job(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer", "ShopAdmin"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    body = util.get_body()
    job_type = util.get_enum(body, "job_type", ["ADDRESSING", "ASSEMBLY"])
    quantity = util.get_int(body, "quantity")
    scheduled_date = util.get_iso_date(body, "scheduled_date")
    unit_price_cents = util.get_int(body, "unit_price_cents")
    if quantity < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "quantity must be >= 1")
    if unit_price_cents <= 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "unit_price_cents must be > 0")

    if o["status"] in ("CANCELLED", "DELIVERED", "SHIPPED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] not in ("CART", "DEPOSIT_PENDING"):
        errors.raise_error(errors.ERR_INVALID_STATE, "addressing jobs may only be added in CART or DEPOSIT_PENDING")

    a = models.make_common({
        "order_id": o["id"],
        "job_type": job_type,
        "quantity": quantity,
        "scheduled_date": scheduled_date,
        "unit_price_cents": unit_price_cents,
        "status": "SCHEDULED",
    })
    db.addressing_jobs[a["id"]] = a
    # Adding the first job flips the 3-day addressing adder
    services.recompute_expected_lead_days(o)
    models.bump(o)
    return resp.created(a)


@bp.route("/orders/<oid>/addressing-jobs", methods=["GET"])
def list_order_addressing_jobs(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    limit, offset = util.get_pagination()
    items = [a for a in db.addressing_jobs.values() if a["order_id"] == oid]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


@bp.route("/addressing-jobs/<aid>", methods=["GET"])
def get_addressing_job(aid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    a = models.get_addressing_job(aid)
    if role == "Customer":
        o = db.orders.get(a["order_id"])
        if not o or o["customer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not your addressing job")
    return resp.ok(a)
