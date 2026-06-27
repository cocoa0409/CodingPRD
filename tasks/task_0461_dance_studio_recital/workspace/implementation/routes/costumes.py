"""Costume / CostumeOrder routes (PRD 3.6)."""
from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (SIZE_CODES, clock_date, lookup, optional_int, paginate,
                     parse_date, require_enum, require_fields, require_int,
                     require_str, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from services.billing import add_fee_line, open_invoice_for, remove_fee_or_credit
from views import public, public_list

bp = Blueprint("costumes", __name__)

OCCUPIED = {"CONFIRMED", "WAITLIST_PROMOTED"}


@bp.route("/sections/<sid>/costumes", methods=["POST"])
def create_costume(sid):
    authenticate({"StudioAdmin"})
    sec = lookup(db.sections, sid)
    body = get_json()
    require_fields(body, ["name", "unit_price_cents", "size_window_close_date"])
    name = require_str(body, "name")
    unit_price = require_int(body, "unit_price_cents", lo=0)
    close_date = parse_date(body, "size_window_close_date")
    rush = optional_int(body, "rush_surcharge_cents", default=0, lo=0)
    costume = {
        "id": new_id(),
        "section_id": sec["id"],
        "name": name,
        "unit_price_cents": unit_price,
        "size_window_close_date": body["size_window_close_date"],
        "rush_surcharge_cents": rush,
        "status": "SIZING_OPEN",
        **common_fields(),
    }
    db.costumes[costume["id"]] = costume
    return success(public(costume), status=201)


@bp.route("/sections/<sid>/costumes", methods=["GET"])
def list_costumes(sid):
    authenticate({"StudioAdmin", "Parent"})
    sec = lookup(db.sections, sid)
    items = [c for c in db.costumes.values() if c["section_id"] == sec["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/costumes/<cid>", methods=["GET"])
def get_costume(cid):
    authenticate({"StudioAdmin", "Parent"})
    costume = lookup(db.costumes, cid)
    return success(public(costume), status=200)


def _pinned_price(costume):
    """Rush surcharge applies only when clock date is STRICTLY after the close date."""
    close_date = parse_date(costume, "size_window_close_date")
    if clock_date() > close_date:
        return costume["unit_price_cents"] + costume["rush_surcharge_cents"]
    return costume["unit_price_cents"]


@bp.route("/costumes/<cid>/submit-order", methods=["POST"])
def submit_order(cid):
    authenticate({"StudioAdmin"})
    costume = lookup(db.costumes, cid)
    if costume["status"] != "SIZING_OPEN":
        raise err("ERR_INVALID_STATE", "Costume is not SIZING_OPEN.")
    drafts = [o for o in db.costume_orders.values()
              if o["costume_id"] == costume["id"] and o["status"] == "DRAFT"]
    drafts.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for order in drafts:
        enr = db.enrollments.get(order["enrollment_id"])
        if enr is None or enr["placement_status"] not in OCCUPIED:
            raise err("ERR_NOT_ENROLLED_IN_SECTION",
                      "Order's enrollment is not confirmed in the section.")
    # Pin prices, submit, fold fees.
    for order in drafts:
        enr = db.enrollments.get(order["enrollment_id"])
        price = _pinned_price(costume)
        order["price_cents"] = price
        order["status"] = "SUBMITTED"
        touch(order)
        add_fee_line(enr["family_id"], price)
    costume["status"] = "ORDERED"
    touch(costume)
    return success(public(costume), status=200)


@bp.route("/costume-orders", methods=["POST"])
def create_costume_order():
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    body = get_json()
    require_fields(body, ["costume_id", "enrollment_id", "size_code"])
    costume = lookup(db.costumes, body["costume_id"])
    enr = lookup(db.enrollments, body["enrollment_id"])
    require_owner(role, user_id, enr["family_id"])
    size_code = require_enum(body, "size_code", SIZE_CODES)
    # The cited enrollment must be CONFIRMED/WAITLIST_PROMOTED in the costume's section.
    if enr["section_id"] != costume["section_id"] or enr["placement_status"] not in OCCUPIED:
        raise err("ERR_NOT_ENROLLED_IN_SECTION",
                  "Enrollment is not confirmed in the costume's section.")
    order = {
        "id": new_id(),
        "costume_id": costume["id"],
        "enrollment_id": enr["id"],
        "size_code": size_code,
        "price_cents": 0,
        "status": "DRAFT",
        **common_fields(),
    }
    db.costume_orders[order["id"]] = order
    return success(public(order), status=201)


@bp.route("/costume-orders/<oid>", methods=["GET"])
def get_costume_order(oid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    order = lookup(db.costume_orders, oid)
    enr = db.enrollments.get(order["enrollment_id"])
    if enr is not None:
        require_owner(role, user_id, enr["family_id"])
    return success(public(order), status=200)


@bp.route("/costume-orders", methods=["GET"])
def list_costume_orders():
    authenticate({"StudioAdmin", "Parent"})
    items = list(db.costume_orders.values())
    for key in ("costume_id", "enrollment_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/costume-orders/<oid>/cancel", methods=["POST"])
def cancel_costume_order(oid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    order = lookup(db.costume_orders, oid)
    enr = db.enrollments.get(order["enrollment_id"])
    owning_family = enr["family_id"] if enr else None
    require_owner(role, user_id, owning_family)

    if order["status"] == "DRAFT":
        order["status"] = "CANCELLED"
        touch(order)
    elif order["status"] == "SUBMITTED":
        # SUBMITTED is cancellable only by a StudioAdmin (compensation).
        if role != "StudioAdmin":
            raise err("ERR_FORBIDDEN_ROLE", "Only an admin may cancel a submitted order.")
        if owning_family is not None:
            remove_fee_or_credit(owning_family, order["price_cents"])
        order["status"] = "CANCELLED"
        touch(order)
    else:
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled.")
    return success(public(order), status=200)
