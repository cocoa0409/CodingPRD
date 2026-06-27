"""Claim endpoints (PRD §3.7, §3.9)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, claim_engine

bp = Blueprint("claims", __name__)

READ_ROLES = ["PharmacyOperator", "PlatformAdmin", "Member"]


@bp.route("/claims", methods=["POST"])
def create_claim():
    middleware.require_auth(["PharmacyOperator"])
    body = common.get_body()
    discount_card_id = common.req_str(body, "discount_card_id")
    pharmacy_id = common.req_str(body, "pharmacy_id")
    quantity = common.req_int(body, "quantity")

    # existence (priority 4): card then pharmacy
    card = common.must_exist(db.discount_cards, discount_card_id, "DiscountCard")
    common.must_exist(db.pharmacies, pharmacy_id, "Pharmacy")

    # state (priority 5): card must be ISSUED
    if card["status"] != "ISSUED":
        raise errors.invalid_state("DiscountCard is not ISSUED.")

    # business referential (priority 8): card pharmacy must match claim pharmacy
    if card["pharmacy_id"] != pharmacy_id:
        raise errors.ApiError(errors.ERR_PHARMACY_MISMATCH, 422,
                              "DiscountCard pharmacy does not match claim pharmacy.")

    # quantity bounds (priority 16): claim quantity >= 1
    if quantity < 1:
        raise errors.ApiError(errors.ERR_QUANTITY_OUT_OF_RANGE, 422,
                              "Claim quantity must be >= 1.")

    rec = {
        "discount_card_id": discount_card_id,
        "pharmacy_id": pharmacy_id,
        "drug_id": card["drug_id"],
        "quantity": quantity,
        "gross_cents": 0,
        "net_cents": 0,
        "savings_cents": 0,
        "copay_offset_cents": 0,
        "status": "SUBMITTED",
    }
    db.stamp_create(rec, common_fields=True)
    db.claims[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/claims/<clid>", methods=["GET"])
def get_claim(clid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.claims, clid, "Claim")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    discount_card_id = request.args.get("discount_card_id")
    pharmacy_id = request.args.get("pharmacy_id")
    drug_id = request.args.get("drug_id")
    status = request.args.get("status")
    items = list(db.claims.values())
    if discount_card_id is not None:
        items = [c for c in items if c["discount_card_id"] == discount_card_id]
    if pharmacy_id is not None:
        items = [c for c in items if c["pharmacy_id"] == pharmacy_id]
    if drug_id is not None:
        items = [c for c in items if c["drug_id"] == drug_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/claims/<clid>/adjudicate", methods=["POST"])
def adjudicate_claim(clid):
    middleware.require_auth(["PharmacyOperator"])
    rec = common.must_exist(db.claims, clid, "Claim")

    # state (priority 5): claim must be SUBMITTED and card ISSUED
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not SUBMITTED.")
    card = db.discount_cards.get(rec["discount_card_id"])
    if card is None:
        raise errors.not_found("DiscountCard not found.")
    if card["status"] != "ISSUED":
        raise errors.invalid_state("DiscountCard is not ISSUED.")

    # business referential (priority 8): card pharmacy must match claim pharmacy
    if card["pharmacy_id"] != rec["pharmacy_id"]:
        raise errors.ApiError(errors.ERR_PHARMACY_MISMATCH, 422,
                              "DiscountCard pharmacy does not match claim pharmacy.")

    # pharmacy must be ACTIVE (state dependency)
    pharmacy = db.pharmacies.get(rec["pharmacy_id"])
    if pharmacy is None:
        raise errors.not_found("Pharmacy not found.")
    if pharmacy["status"] != "ACTIVE":
        raise errors.invalid_state("Pharmacy is not ACTIVE.")

    claim_engine.adjudicate(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/claims/<clid>/reject", methods=["POST"])
def reject_claim(clid):
    middleware.require_auth(["PharmacyOperator"])
    rec = common.must_exist(db.claims, clid, "Claim")
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not SUBMITTED.")
    claim_engine.reject(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/claims/<clid>/reverse", methods=["POST"])
def reverse_claim(clid):
    middleware.require_auth(["PharmacyOperator"])
    body = common.get_body()
    expected_version = common.req_int(body, "expected_claim_version")

    rec = common.must_exist(db.claims, clid, "Claim")

    # state (priority 5): claim must be ADJUDICATED
    if rec["status"] != "ADJUDICATED":
        raise errors.invalid_state("Claim is not ADJUDICATED.")

    # OCC (priority 6): expected_claim_version must match
    if expected_version != rec["version"]:
        raise errors.stale_version("expected_claim_version does not match claim version.")

    claim_engine.reverse(rec)
    return response.object_response(serializers.serialize(rec), 200)
