"""The authorized repair network and warranty registrations (PRD 3.9)."""

import re

from flask import Blueprint, request

import auth
import calc
import store
import validate as v
from constants import (AUTHORIZATION_LEVELS, SHOP_STATUSES, WARRANTY_STATUSES)
from envelope import object_response, paginate
from errors import ApiError
from serialize import shop_view, warranty_view
from store import ORDERS, SHOPS, WARRANTIES, new_record, touch

bp = Blueprint("service", __name__)

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _shop(shop_id):
    return v.fetch(SHOPS, shop_id, "ERR_REPAIR_SHOP_NOT_FOUND")


def _registration(registration_id):
    return v.fetch(WARRANTIES, registration_id,
                   "ERR_WARRANTY_REGISTRATION_NOT_FOUND")


@bp.post("/repair-shops")
def create_shop():
    auth.require(auth.SERVICE_NETWORK_MANAGER)
    body = v.body()
    shop_code = v.get_str(body, "shop_code", min_len=1, max_len=64)
    shop_name = v.get_str(body, "shop_name", min_len=1, max_len=80)
    country = v.get_str(body, "country_code", min_len=2, max_len=2)
    if not COUNTRY_RE.match(country):
        v.bad("country_code must be two uppercase letters")
    v.unique_code(SHOPS, "shop_code", shop_code)
    rec = new_record(SHOPS, {
        "shop_code": shop_code,
        "shop_name": shop_name,
        "country_code": country,
        "authorization_level": "NONE",
        "status": "APPLIED",
    })
    return object_response(shop_view(rec), 201)


@bp.get("/repair-shops/<shop_id>")
def read_shop(shop_id):
    user_id, role = auth.require(auth.STAFF_ROLES, auth.AUTHORIZED_SHOP)
    if role == auth.AUTHORIZED_SHOP and user_id != shop_id:
        raise ApiError("ERR_SHOP_IDENTITY_MISMATCH",
                       "a shop may read only its own row")
    return object_response(shop_view(_shop(shop_id)))


@bp.get("/repair-shops")
def list_shops():
    auth.require_staff()
    rows = v.apply_filters(list(SHOPS.values()), [
        ("country_code", v.filter_value("country_code")),
        ("status", v.filter_enum("status", SHOP_STATUSES)),
        ("authorization_level", v.filter_enum("authorization_level",
                                             AUTHORIZATION_LEVELS)),
    ])
    rows.sort(key=lambda r: (r["shop_code"], r["created_at"], r["_seq"]))
    return paginate(rows, shop_view)


@bp.post("/repair-shops/<shop_id>/authorize")
def authorize_shop(shop_id):
    auth.require(auth.SERVICE_NETWORK_MANAGER)
    body = v.body()
    level = v.get_enum(body, "authorization_level", AUTHORIZATION_LEVELS)
    if level == "NONE":
        v.bad("authorization_level must grant something")
    shop = _shop(shop_id)
    if shop["status"] not in ("APPLIED", "SUSPENDED"):
        raise ApiError("ERR_SHOP_STATE_INVALID",
                       "the shop is not awaiting authorization")
    shop["status"] = "AUTHORIZED"
    shop["authorization_level"] = level
    touch(shop)
    return object_response(shop_view(shop))


@bp.post("/repair-shops/<shop_id>/suspend")
def suspend_shop(shop_id):
    auth.require(auth.SERVICE_NETWORK_MANAGER)
    body = v.body()
    v.get_str(body, "reason", required=False)
    shop = _shop(shop_id)
    if shop["status"] != "AUTHORIZED":
        raise ApiError("ERR_SHOP_STATE_INVALID",
                       "only an AUTHORIZED shop may be suspended")
    shop["status"] = "SUSPENDED"
    shop["authorization_level"] = "NONE"
    touch(shop)
    return object_response(shop_view(shop))


@bp.post("/warranty-registrations")
def create_registration():
    user_id, role = auth.require(auth.SERVICE_NETWORK_MANAGER,
                                 auth.AUTHORIZED_SHOP)
    body = v.body()
    if role == auth.AUTHORIZED_SHOP:
        named = body.get("registering_shop_id")
        if not isinstance(named, str) or named != user_id:
            raise ApiError("ERR_SHOP_IDENTITY_MISMATCH",
                           "a shop may register only in its own name")
    order_id = v.get_id(body, "build_order_id")
    shop_id = v.get_id(body, "registering_shop_id")
    serial = v.get_str(body, "serial_number", min_len=1, max_len=32)
    owner_email = v.get_str(body, "owner_email", min_len=1)
    if owner_email.count("@") != 1:
        v.bad("owner_email must contain exactly one @ character")
    purchase_date = v.get_ts(body, "purchase_date")
    order = v.fetch(ORDERS, order_id, "ERR_BUILD_ORDER_NOT_FOUND")
    shop = v.fetch(SHOPS, shop_id, "ERR_REPAIR_SHOP_NOT_FOUND")
    active = [r for r in WARRANTIES.values()
              if r["build_order_id"] == order["id"] and r["status"] == "ACTIVE"]
    if active:
        raise ApiError("ERR_WARRANTY_ALREADY_REGISTERED",
                       "the instrument already carries an active registration")
    if shop["status"] != "AUTHORIZED":
        raise ApiError("ERR_SHOP_NOT_AUTHORIZED",
                       "the registering shop is not authorized")
    if order["serial_number"] is None or serial != order["serial_number"]:
        raise ApiError("ERR_SERIAL_MISMATCH",
                       "the serial does not match the named instrument")
    months = calc.coverage_months(order)
    rec = new_record(WARRANTIES, {
        "build_order_id": order["id"],
        "registering_shop_id": shop["id"],
        "serial_number": serial,
        "owner_email": owner_email,
        "purchase_date": purchase_date,
        "coverage_months": months,
        "coverage_ends_at": store.add_months(
            purchase_date.replace(hour=0, minute=0, second=0, microsecond=0),
            months),
        "status": "ACTIVE",
    })
    return object_response(warranty_view(rec), 201)


@bp.get("/warranty-registrations/<registration_id>")
def read_registration(registration_id):
    user_id, role = auth.require(auth.STAFF_ROLES, auth.AUTHORIZED_SHOP)
    rec = _registration(registration_id)
    if role == auth.AUTHORIZED_SHOP and rec["registering_shop_id"] != user_id:
        raise ApiError("ERR_SHOP_IDENTITY_MISMATCH",
                       "a shop may read only its own registrations")
    return object_response(warranty_view(rec))


@bp.get("/warranty-registrations")
def list_registrations():
    user_id, role = auth.require(auth.STAFF_ROLES, auth.AUTHORIZED_SHOP)
    if role == auth.AUTHORIZED_SHOP:
        if request.args.get("registering_shop_id") != user_id:
            raise ApiError("ERR_SHOP_IDENTITY_MISMATCH",
                           "a shop must filter the list to itself")
    rows = v.apply_filters(list(WARRANTIES.values()), [
        ("build_order_id", v.filter_value("build_order_id")),
        ("registering_shop_id", v.filter_value("registering_shop_id")),
        ("status", v.filter_enum("status", WARRANTY_STATUSES)),
    ])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows, warranty_view)


@bp.post("/warranty-registrations/<registration_id>/void")
def void_registration(registration_id):
    auth.require(auth.SERVICE_NETWORK_MANAGER)
    body = v.body()
    v.get_str(body, "reason", required=False)
    rec = _registration(registration_id)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_WARRANTY_STATE_INVALID",
                       "only an ACTIVE registration may be voided")
    rec["status"] = "VOID"
    touch(rec)
    # warranty_claim_count is a read-time mirror over ACTIVE registrations, so
    # voiding decrements it without writing to the shop row.
    return object_response(warranty_view(rec))
