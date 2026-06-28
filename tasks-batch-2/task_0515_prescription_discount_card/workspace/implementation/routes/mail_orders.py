"""MailOrderFulfillment endpoints (PRD §3.10, §3.12)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, calculations

bp = Blueprint("mail_orders", __name__)

READ_ROLES = ["Member", "PlatformAdmin", "PharmacyOperator"]


@bp.route("/mail-orders", methods=["POST"])
def create_mail_order():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    discount_card_id = common.req_str(body, "discount_card_id")
    pharmacy_id = common.req_str(body, "pharmacy_id")
    member_id = common.req_str(body, "member_id")
    quantity = common.req_int(body, "quantity")
    ship_to_state = common.req_str(body, "ship_to_state")
    common.validate_state_code(ship_to_state, "ship_to_state")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): card, pharmacy, member (left-to-right per body)
    card = common.must_exist(db.discount_cards, discount_card_id, "DiscountCard")
    pharmacy = common.must_exist(db.pharmacies, pharmacy_id, "Pharmacy")
    member = common.must_exist(db.members, member_id, "Member")

    drug = db.drugs[card["drug_id"]]

    # controlled substance (priority 7): for controlled drug, member.state_code must equal ship_to_state
    if drug.get("is_controlled", False):
        if member["state_code"] != ship_to_state:
            raise errors.ApiError(errors.ERR_CONTROLLED_SUBSTANCE_BLOCKED, 422,
                                  "Controlled substance mail-order blocked: state mismatch.")

    # mail-order pharmacy (priority 13)
    if not pharmacy.get("is_mail_order", False):
        raise errors.ApiError(errors.ERR_NOT_MAIL_ORDER_PHARMACY, 422,
                              "Pharmacy is not a mail-order pharmacy.")

    # quantity bounds (priority 16): [1, 3]
    if quantity < 1 or quantity > 3:
        raise errors.ApiError(errors.ERR_QUANTITY_OUT_OF_RANGE, 422,
                              "Mail-order quantity must be between 1 and 3.")

    # compute total_cents
    quote = calculations.resolve_quote(pharmacy_id, card["drug_id"])
    if quote is None:
        raise errors.validation("No active price quote for the mail-order pharmacy/drug.")
    bprice = calculations.basis_price(quote, card["pricing_basis"])
    total = quantity * bprice + pharmacy["dispense_fee_cents"]

    rec = {
        "discount_card_id": discount_card_id,
        "pharmacy_id": pharmacy_id,
        "member_id": member_id,
        "quantity": quantity,
        "ship_to_state": ship_to_state,
        "total_cents": total,
        "status": "PLACED",
    }
    db.stamp_create(rec, common_fields=True)
    db.mail_orders[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/mail-orders/<oid>", methods=["GET"])
def get_mail_order(oid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.mail_orders, oid, "MailOrderFulfillment")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/mail-orders", methods=["GET"])
def list_mail_orders():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    member_id = request.args.get("member_id")
    discount_card_id = request.args.get("discount_card_id")
    pharmacy_id = request.args.get("pharmacy_id")
    items = list(db.mail_orders.values())
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if discount_card_id is not None:
        items = [o for o in items if o["discount_card_id"] == discount_card_id]
    if pharmacy_id is not None:
        items = [o for o in items if o["pharmacy_id"] == pharmacy_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/mail-orders/<oid>/ship", methods=["POST"])
def ship_mail_order(oid):
    middleware.require_auth(["PharmacyOperator"])
    rec = common.must_exist(db.mail_orders, oid, "MailOrderFulfillment")
    if rec["status"] != "PLACED":
        raise errors.invalid_state("Mail order is not PLACED.")
    pharmacy = db.pharmacies.get(rec["pharmacy_id"])
    if pharmacy is None:
        raise errors.not_found("Pharmacy not found.")
    if pharmacy["status"] != "ACTIVE":
        raise errors.invalid_state("Pharmacy is not ACTIVE.")
    rec["status"] = "SHIPPED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/mail-orders/<oid>/deliver", methods=["POST"])
def deliver_mail_order(oid):
    middleware.require_auth(["PharmacyOperator"])
    rec = common.must_exist(db.mail_orders, oid, "MailOrderFulfillment")
    if rec["status"] != "SHIPPED":
        raise errors.invalid_state("Mail order is not SHIPPED.")
    rec["status"] = "DELIVERED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/mail-orders/<oid>/cancel", methods=["POST"])
def cancel_mail_order(oid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    middleware.require_owner(user_id, role, member_id)
    rec = common.must_exist(db.mail_orders, oid, "MailOrderFulfillment")
    common.must_exist(db.members, member_id, "Member")
    middleware.require_owner(user_id, role, rec["member_id"])
    if rec["status"] != "PLACED":
        raise errors.invalid_state("Mail order is not PLACED.")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
