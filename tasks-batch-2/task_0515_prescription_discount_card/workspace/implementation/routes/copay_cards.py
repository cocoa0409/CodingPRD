"""CopayCard endpoints (PRD §3.8)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("copay_cards", __name__)

WRITE_ROLES = ["CopayCardSponsor", "PlatformAdmin"]
READ_ROLES = ["CopayCardSponsor", "PlatformAdmin", "Member"]


@bp.route("/copay-cards", methods=["POST"])
def create_copay_card():
    middleware.require_auth(WRITE_ROLES)
    body = common.get_body()
    sponsor_name = common.req_str(body, "sponsor_name")
    drug_id = common.req_str(body, "drug_id")
    max_benefit_cents = common.req_int(body, "max_benefit_cents")
    per_fill_cap_cents = common.req_int(body, "per_fill_cap_cents")
    if max_benefit_cents < 1:
        raise errors.invalid_request("max_benefit_cents must be >= 1.")
    if per_fill_cap_cents < 1:
        raise errors.invalid_request("per_fill_cap_cents must be >= 1.")

    common.must_exist(db.drugs, drug_id, "Drug")

    rec = {
        "sponsor_name": sponsor_name,
        "drug_id": drug_id,
        "max_benefit_cents": max_benefit_cents,
        "per_fill_cap_cents": per_fill_cap_cents,
        "remaining_benefit_cents": max_benefit_cents,
        "status": "ACTIVE",
    }
    db.stamp_create(rec, common_fields=True)
    db.copay_cards[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/copay-cards/<cid>", methods=["GET"])
def get_copay_card(cid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.copay_cards, cid, "CopayCard")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/copay-cards", methods=["GET"])
def list_copay_cards():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    drug_id = request.args.get("drug_id")
    items = list(db.copay_cards.values())
    if drug_id is not None:
        items = [c for c in items if c["drug_id"] == drug_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/copay-cards/<cid>/withdraw", methods=["POST"])
def withdraw_copay_card(cid):
    middleware.require_auth(["CopayCardSponsor"])
    rec = common.must_exist(db.copay_cards, cid, "CopayCard")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("CopayCard is not ACTIVE.")
    rec["status"] = "WITHDRAWN"
    db.touch(rec)
    # cascade: LINKED links -> RELEASED (APPLIED untouched)
    for link in db.copay_links.values():
        if link["copay_card_id"] == cid and link["status"] == "LINKED":
            link["status"] = "RELEASED"
            db.touch(link)
    return response.object_response(serializers.serialize(rec), 200)
