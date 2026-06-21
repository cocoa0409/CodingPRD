"""Consignment and ConditionReport endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, require_number,
    require_enum, public, list_collection,
)
from services import lookup, cascade

bp = Blueprint("consignments", __name__)

ALL_ROLES = {"AuctionAdmin", "Seller", "Buyer", "Arbitrator"}


# ===== Consignment ==========================================================
@bp.route("/auction/consignments", methods=["POST"])
def create_consignment():
    user_id, role = get_auth()
    require_role(role, {"AuctionAdmin", "Seller"})
    body = get_body()
    sale_id = require_str(body, "sale_id")
    seller_id = require_str(body, "seller_id")
    vin = require_str(body, "vin")
    if len(vin) != 17:
        raise ApiError("ERR_VALIDATION", "vin must be 17 characters.")
    title_status = require_enum(body, "title_status", ("ABSENT", "ON_HAND"),
                               default="ABSENT", required=False)

    with db.lock:
        # ownership (priority 3): Seller may only consign under own seller_id
        if role == "Seller" and seller_id != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Seller may only consign own vehicles.")
        # existence (priority 4): body FKs
        lookup.get_sale(sale_id)
        lookup.get_seller(seller_id)
        # uniqueness of vin per sale
        for c in db.consignments.values():
            if c["sale_id"] == sale_id and c["vin"] == vin:
                raise ApiError("ERR_DUPLICATE_VIN", "VIN already consigned in this sale.")
        rec = base_record()
        rec.update({
            "sale_id": sale_id,
            "seller_id": seller_id,
            "vin": vin,
            "reserve_price_cents": 0,
            "floor_price_cents": 0,
            "title_status": title_status,
            "expected_proceeds_cents": 0,
            "status": "SUBMITTED",
        })
        db.consignments[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/consignments", methods=["GET"])
def list_consignments():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    filters = {
        "sale_id": request.args.get("sale_id"),
        "seller_id": request.args.get("seller_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.consignments, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/consignments/<consignment_id>", methods=["GET"])
def get_consignment(consignment_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        c = lookup.get_consignment(consignment_id)
        return success_object(public(c))


@bp.route("/auction/consignments/<consignment_id>/catalog", methods=["POST"])
def catalog_consignment(consignment_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    reserve = require_int(body, "reserve_price_cents", minimum=0)
    floor = require_int(body, "floor_price_cents", minimum=0)
    with db.lock:
        c = lookup.get_consignment(consignment_id)
        if c["status"] != "SUBMITTED":
            raise ApiError("ERR_CONSIGNMENT_NOT_SUBMITTED", "Consignment not SUBMITTED.")
        if cascade.condition_report_for(c["id"]) is None:
            raise ApiError("ERR_CONDITION_REPORT_MISSING", "No condition report.")
        if floor > reserve:
            raise ApiError("ERR_FLOOR_ABOVE_RESERVE", "Floor above reserve.")
        c["reserve_price_cents"] = reserve
        c["floor_price_cents"] = floor
        c["status"] = "CATALOGED"
        touch(c)
        return success_object(public(c))


@bp.route("/auction/consignments/<consignment_id>/withdraw", methods=["POST"])
def withdraw_consignment(consignment_id):
    user_id, role = get_auth()
    require_role(role, {"AuctionAdmin", "Seller"})
    with db.lock:
        c = lookup.get_consignment(consignment_id)
        # ownership (priority 3)
        if role == "Seller" and c["seller_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning seller.")
        if c["status"] not in ("SUBMITTED", "CATALOGED"):
            raise ApiError("ERR_CONSIGNMENT_NOT_WITHDRAWABLE", "Consignment not withdrawable.")
        c["status"] = "WITHDRAWN"
        touch(c)
        return success_object(public(c))


# ===== ConditionReport ======================================================
@bp.route("/auction/condition-reports", methods=["POST"])
def create_condition_report():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    consignment_id = require_str(body, "consignment_id")
    grade = require_number(body, "grade", minimum=0.0, maximum=5.0)
    odometer = require_int(body, "odometer_miles", minimum=0)
    announcements = body.get("announcements", [])
    if announcements is None:
        announcements = []
    if not isinstance(announcements, list):
        raise ApiError("ERR_VALIDATION", "announcements must be an array.")

    with db.lock:
        lookup.get_consignment(consignment_id)
        as_is = (grade < 3.0) or (len(announcements) > 0)
        rec = base_record()
        rec.update({
            "consignment_id": consignment_id,
            "grade": grade,
            "odometer_miles": odometer,
            "announcements": announcements,
            "as_is": as_is,
        })
        db.condition_reports[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/condition-reports", methods=["GET"])
def list_condition_reports():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    filters = {"consignment_id": request.args.get("consignment_id")}
    items, limit, offset, total = list_collection(db.condition_reports, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/condition-reports/<cr_id>", methods=["GET"])
def get_condition_report(cr_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        cr = lookup.get_condition_report(cr_id)
        return success_object(public(cr))
