"""Offer lifecycle endpoints (PRD 3.2)."""

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from middleware import ALL_ROLES
from services import calc, domain

bp = Blueprint("offers", __name__)

OFFER_SPEC = {
    "manufacturer_id": {"type": "string", "required": True, "min_len": 1},
    "offer_code": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 24,
        "offer_code": True,
    },
    "face_value_cents": {"type": "integer", "required": True, "min": 1, "max": 100000},
    "handling_fee_cents": {"type": "integer", "required": True, "min": 0, "max": 1000},
    "expiration_date": {"type": "date", "required": True},
    "redemption_instructions": {
        "type": "string",
        "required": True,
        "min_len": 1,
        "max_len": 500,
    },
    "barcode_family": {
        "type": "enum",
        "required": True,
        "values": ["GS1_DATABAR", "UPC_A_WITH_EXT5"],
    },
    "max_redemptions": {
        "type": "integer",
        "required": True,
        "min": 1,
        "max": 100000000,
    },
    "purchase_requirement_units": {"type": "integer", "min": 1, "max": 24, "default": 1},
    "redemption_grace_days": {"type": "integer", "min": 0, "max": 365, "default": 30},
    "digital_enabled": {"type": "boolean", "default": False},
    "clip_validity_days": {"type": "integer", "min": 1, "max": 365, "default": 60},
}

CLEARABLE = ("ACTIVE", "EXPIRED")


@bp.route("/offers", methods=["POST"])
def create_offer():
    ctx = mw.authenticate(["Manufacturer", "ClearinghouseAdmin"])
    values = validate.parse(mw.body(), OFFER_SPEC)
    manufacturer = mw.fetch(
        "manufacturers", values["manufacturer_id"], "ERR_MANUFACTURER_NOT_FOUND"
    )
    mw.own_manufacturer(ctx, manufacturer["id"])
    if manufacturer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Issuing manufacturer is suspended")
    for existing in db.db.offers.values():
        if (
            existing["manufacturer_id"] == manufacturer["id"]
            and existing["offer_code"] == values["offer_code"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_OFFER_CODE",
                "Offer code already used by this manufacturer",
            )
    row = db.base_row()
    row.update(
        {
            "manufacturer_id": manufacturer["id"],
            "offer_code": values["offer_code"],
            "face_value_cents": values["face_value_cents"],
            "handling_fee_cents": values["handling_fee_cents"],
            "purchase_requirement_units": values["purchase_requirement_units"],
            "expiration_date": values["expiration_date"],
            "redemption_grace_days": values["redemption_grace_days"],
            "redemption_instructions": values["redemption_instructions"],
            "barcode_family": values["barcode_family"],
            "barcode_payload": None,
            "max_redemptions": values["max_redemptions"],
            "accepted_redemption_count": 0,
            "digital_enabled": values["digital_enabled"],
            "clip_validity_days": values["clip_validity_days"],
            "status": "DRAFT",
            "withdrawn_reason": None,
        }
    )
    db.db.offers[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/offers/<oid>", methods=["GET"])
def get_offer(oid):
    ctx = mw.authenticate(ALL_ROLES)
    row = mw.fetch("offers", oid, "ERR_OFFER_NOT_FOUND")
    mw.own_manufacturer(ctx, row["manufacturer_id"])
    return response.object_response(row)


@bp.route("/offers", methods=["GET"])
def list_offers():
    mw.authenticate(ALL_ROLES)
    limit, offset = mw.pagination()
    manufacturer_id = mw.str_arg("manufacturer_id")
    status = mw.str_arg("status")
    digital = mw.bool_arg("digital_enabled")
    rows = [
        o
        for o in db.db.offers.values()
        if (manufacturer_id is None or o["manufacturer_id"] == manufacturer_id)
        and (status is None or o["status"] == status)
        and (digital is None or o["digital_enabled"] == digital)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/offers/<oid>/register", methods=["POST"])
def register_offer(oid):
    ctx = mw.authenticate(["Manufacturer", "ClearinghouseAdmin"])
    offer = mw.fetch("offers", oid, "ERR_OFFER_NOT_FOUND")
    mw.own_manufacturer(ctx, offer["manufacturer_id"])
    validate.require_no_body(mw.body())
    if offer["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a DRAFT offer can be registered"
        )
    manufacturer = db.db.manufacturers[offer["manufacturer_id"]]
    if manufacturer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Issuing manufacturer is suspended")
    offer["status"] = "REGISTERED"
    offer["barcode_payload"] = calc.barcode_payload(offer, manufacturer)
    touch(offer)
    return response.object_response(offer)


@bp.route("/offers/<oid>/activate", methods=["POST"])
def activate_offer(oid):
    mw.authenticate(["ClearinghouseAdmin"])
    offer = mw.fetch("offers", oid, "ERR_OFFER_NOT_FOUND")
    validate.require_no_body(mw.body())
    if offer["status"] != "REGISTERED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "Only a REGISTERED offer can be activated"
        )
    manufacturer = db.db.manufacturers[offer["manufacturer_id"]]
    if manufacturer["status"] == "SUSPENDED":
        raise ApiError("ERR_MANUFACTURER_SUSPENDED", "Issuing manufacturer is suspended")
    if db.parse_date(offer["expiration_date"]) < db.today():
        raise ApiError("ERR_OFFER_EXPIRED", "Offer expiration date has already passed")
    offer["status"] = "ACTIVE"
    touch(offer)
    return response.object_response(offer)


@bp.route("/offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    ctx = mw.authenticate(["Manufacturer", "ClearinghouseAdmin"])
    offer = mw.fetch("offers", oid, "ERR_OFFER_NOT_FOUND")
    mw.own_manufacturer(ctx, offer["manufacturer_id"])
    values = validate.parse(
        mw.body(),
        {
            "withdrawn_reason": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 200,
            }
        },
    )
    if offer["status"] not in ("REGISTERED", "ACTIVE", "EXPIRED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An offer in %s cannot be withdrawn" % offer["status"],
        )
    domain.withdraw_offer(offer, values["withdrawn_reason"])
    return response.object_response(offer)
