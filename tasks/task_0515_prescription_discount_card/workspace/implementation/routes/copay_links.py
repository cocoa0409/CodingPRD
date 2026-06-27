"""CopayLink endpoints (PRD §3.8)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("copay_links", __name__)

READ_ROLES = ["Member", "PlatformAdmin", "CopayCardSponsor"]


@bp.route("/copay-links", methods=["POST"])
def create_link():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    copay_card_id = common.req_str(body, "copay_card_id")
    member_id = common.req_str(body, "member_id")
    claim_id = common.req_str(body, "claim_id")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): copay_card, member, claim (left-to-right per body order)
    copay_card = common.must_exist(db.copay_cards, copay_card_id, "CopayCard")
    common.must_exist(db.members, member_id, "Member")
    claim = common.must_exist(db.claims, claim_id, "Claim")

    # business referential (priority 9): copay card drug must match the claim's card drug
    card = db.discount_cards.get(claim["discount_card_id"])
    claim_drug_id = card["drug_id"] if card is not None else claim.get("drug_id")
    if copay_card["drug_id"] != claim_drug_id:
        raise errors.ApiError(errors.ERR_COPAY_DRUG_MISMATCH, 422,
                              "Copay card drug does not match the claim's card drug.")

    # business constraint (priority 10): at most one LINKED link per claim
    for link in db.copay_links.values():
        if link.get("claim_id") == claim_id and link["status"] == "LINKED":
            raise errors.ApiError(errors.ERR_COPAY_ALREADY_LINKED, 409,
                                  "A LINKED copay link already references this claim.")

    # business constraint (priority 16.5): copay card must be ACTIVE
    if copay_card["status"] != "ACTIVE":
        raise errors.validation("Copay card is not ACTIVE.")

    rec = {
        "copay_card_id": copay_card_id,
        "member_id": member_id,
        "claim_id": claim_id,
        "applied_offset_cents": 0,
        "status": "LINKED",
    }
    db.stamp_create(rec, common_fields=True)
    db.copay_links[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/copay-links/<lid>", methods=["GET"])
def get_link(lid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.copay_links, lid, "CopayLink")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/copay-links", methods=["GET"])
def list_links():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    copay_card_id = request.args.get("copay_card_id")
    member_id = request.args.get("member_id")
    claim_id = request.args.get("claim_id")
    items = list(db.copay_links.values())
    if copay_card_id is not None:
        items = [l for l in items if l["copay_card_id"] == copay_card_id]
    if member_id is not None:
        items = [l for l in items if l["member_id"] == member_id]
    if claim_id is not None:
        items = [l for l in items if l.get("claim_id") == claim_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/copay-links/<lid>/release", methods=["POST"])
def release_link(lid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")

    middleware.require_owner(user_id, role, member_id)

    rec = common.must_exist(db.copay_links, lid, "CopayLink")
    common.must_exist(db.members, member_id, "Member")
    middleware.require_owner(user_id, role, rec["member_id"])

    if rec["status"] != "LINKED":
        raise errors.invalid_state("CopayLink is not LINKED.")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
