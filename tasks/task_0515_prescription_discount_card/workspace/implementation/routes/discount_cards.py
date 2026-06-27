"""DiscountCard endpoints (PRD §3.6)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, calculations

bp = Blueprint("discount_cards", __name__)

READ_ROLES = ["Member", "PlatformAdmin", "PharmacyOperator"]


@bp.route("/discount-cards", methods=["POST"])
def create_card():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    comparison_id = common.req_str(body, "comparison_id")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): member then comparison
    member = common.must_exist(db.members, member_id, "Member")
    comparison = common.must_exist(db.comparisons, comparison_id, "PriceComparison")

    # state (priority 5 / business): comparison must be RESOLVED with selected pharmacy
    if comparison["status"] != "RESOLVED" or comparison.get("selected_pharmacy_id") is None:
        raise errors.ApiError(errors.ERR_COMPARISON_NOT_RESOLVED, 409,
                              "Comparison is not RESOLVED.")

    drug_id = comparison["drug_id"]
    pharmacy_id = comparison["selected_pharmacy_id"]
    drug = db.drugs[drug_id]

    creds = calculations.coupon_credentials(member, drug)

    rec = {
        "member_id": member_id,
        "drug_id": drug_id,
        "comparison_id": comparison_id,
        "pharmacy_id": pharmacy_id,
        "bin": creds["bin"],
        "pcn": creds["pcn"],
        "group_code": creds["group_code"],
        "member_code": creds["member_code"],
        "pricing_basis": creds["pricing_basis"],
        "status": "ISSUED",
    }
    db.stamp_create(rec, common_fields=True)
    db.discount_cards[rec["id"]] = rec

    # cascade: comparison RESOLVED -> CONVERTED
    comparison["status"] = "CONVERTED"
    db.touch(comparison)

    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/discount-cards/<cid>", methods=["GET"])
def get_card(cid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.discount_cards, cid, "DiscountCard")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/discount-cards", methods=["GET"])
def list_cards():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    member_id = request.args.get("member_id")
    drug_id = request.args.get("drug_id")
    comparison_id = request.args.get("comparison_id")
    pharmacy_id = request.args.get("pharmacy_id")
    items = list(db.discount_cards.values())
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if drug_id is not None:
        items = [c for c in items if c["drug_id"] == drug_id]
    if comparison_id is not None:
        items = [c for c in items if c["comparison_id"] == comparison_id]
    if pharmacy_id is not None:
        items = [c for c in items if c["pharmacy_id"] == pharmacy_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/discount-cards/<cid>/void", methods=["POST"])
def void_card(cid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): card path id, then body member_id
    rec = common.must_exist(db.discount_cards, cid, "DiscountCard")
    common.must_exist(db.members, member_id, "Member")

    # cross-check the card owner matches the supplied member_id for ownership.
    middleware.require_owner(user_id, role, rec["member_id"])

    # state (priority 5)
    if rec["status"] != "ISSUED":
        raise errors.invalid_state("Card is not ISSUED.")
    rec["status"] = "VOID"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
