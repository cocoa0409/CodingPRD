"""GoldMembership endpoints (PRD §3.5). Parallel state machine."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, calculations

bp = Blueprint("gold_memberships", __name__)

TIERS = {"GOLD_INDIVIDUAL", "GOLD_FAMILY"}
READ_ROLES = ["Member", "PlatformAdmin"]


@bp.route("/gold-memberships", methods=["POST"])
def create_membership():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    tier = common.req_enum(body, "tier", TIERS)
    coverage_start = common.req_str(body, "coverage_start")
    coverage_end = common.req_str(body, "coverage_end")
    covered_member_ids = common.opt_list(body, "covered_member_ids", [])

    start_dt = db.parse_iso(coverage_start)
    end_dt = db.parse_iso(coverage_end)
    if start_dt is None or end_dt is None:
        raise errors.invalid_request("coverage_start/coverage_end must be valid ISO 8601 instants.")
    if not (end_dt > start_dt):
        raise errors.invalid_request("coverage_end must be strictly after coverage_start.")
    for cid in covered_member_ids:
        if not isinstance(cid, str):
            raise errors.invalid_request("covered_member_ids must be an array of strings.")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): member
    common.must_exist(db.members, member_id, "Member")

    # period overlap (priority 11.6): closed interval + 1-day buffer against same member
    buffer = calculations.MEMBERSHIP_BUFFER_SECONDS
    for m in db.gold_memberships.values():
        if m["member_id"] != member_id:
            continue
        m_start = db.parse_iso(m["coverage_start"])
        m_end = db.parse_iso(m["coverage_end"])
        # Accept only if new window is at least `buffer` seconds clear of existing
        # window on either side. (gap measured between closed endpoints.)
        # new entirely after existing: new.start - existing.end >= buffer
        # new entirely before existing: existing.start - new.end >= buffer
        after_ok = (start_dt.timestamp() - m_end.timestamp()) >= buffer
        before_ok = (m_start.timestamp() - end_dt.timestamp()) >= buffer
        if not (after_ok or before_ok):
            raise errors.ApiError(errors.ERR_MEMBERSHIP_PERIOD_OVERLAP, 409,
                                  "Coverage window overlaps or abuts an existing membership.")

    # coverage limit (priority 12)
    if tier == "GOLD_INDIVIDUAL":
        if len(covered_member_ids) != 0:
            raise errors.ApiError(errors.ERR_COVERAGE_LIMIT, 422,
                                  "GOLD_INDIVIDUAL must have empty covered_member_ids.")
    else:  # GOLD_FAMILY
        if len(covered_member_ids) > calculations.MAX_FAMILY_COVERED:
            raise errors.ApiError(errors.ERR_COVERAGE_LIMIT, 422,
                                  "GOLD_FAMILY may cover at most %d ids." % calculations.MAX_FAMILY_COVERED)

    monthly_fee = calculations.gold_monthly_fee(tier)

    rec = {
        "member_id": member_id,
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "billing_status": "PENDING_PAYMENT",
        "access_status": "INACTIVE",
        "covered_member_ids": list(covered_member_ids),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }
    db.stamp_create(rec, common_fields=True)
    db.gold_memberships[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/gold-memberships/<mid>", methods=["GET"])
def get_membership(mid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.gold_memberships, mid, "GoldMembership")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/gold-memberships", methods=["GET"])
def list_memberships():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    member_id = request.args.get("member_id")
    items = list(db.gold_memberships.values())
    if member_id is not None:
        items = [m for m in items if m["member_id"] == member_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/gold-memberships/<mid>/record-payment", methods=["POST"])
def record_payment(mid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.gold_memberships, mid, "GoldMembership")
    if rec["billing_status"] != "PENDING_PAYMENT":
        raise errors.invalid_state("Billing is not PENDING_PAYMENT.")
    rec["billing_status"] = "PAID"
    # cross-dimension activation on first payment
    if rec["access_status"] == "INACTIVE":
        rec["access_status"] = "ACTIVE"
        member = db.members.get(rec["member_id"])
        if member is not None:
            member["active_gold_membership_id"] = rec["id"]
            db.touch(member)
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/gold-memberships/<mid>/lapse", methods=["POST"])
def lapse_membership(mid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.gold_memberships, mid, "GoldMembership")
    if rec["billing_status"] != "PAID":
        raise errors.invalid_state("Billing is not PAID.")
    rec["billing_status"] = "PAST_DUE"
    # access ACTIVE -> REVOKED (cross-dimension revocation)
    if rec["access_status"] == "ACTIVE":
        rec["access_status"] = "REVOKED"
    member = db.members.get(rec["member_id"])
    if member is not None:
        member["active_gold_membership_id"] = None
        db.touch(member)
        # cascade: GOLD-basis ISSUED cards owned by member -> VOID
        for card in db.discount_cards.values():
            if (card["member_id"] == member["id"]
                    and card["status"] == "ISSUED"
                    and card["pricing_basis"] == "GOLD"):
                card["status"] = "VOID"
                db.touch(card)
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/gold-memberships/<mid>/revoke", methods=["POST"])
def revoke_membership(mid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")

    middleware.require_owner(user_id, role, member_id)

    rec = common.must_exist(db.gold_memberships, mid, "GoldMembership")
    common.must_exist(db.members, member_id, "Member")
    middleware.require_owner(user_id, role, rec["member_id"])

    # access ACTIVE -> REVOKED; billing left unchanged
    if rec["access_status"] != "ACTIVE":
        raise errors.invalid_state("Access is not ACTIVE.")
    rec["access_status"] = "REVOKED"
    member = db.members.get(rec["member_id"])
    if member is not None:
        member["active_gold_membership_id"] = None
        db.touch(member)
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
