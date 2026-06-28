"""TelehealthReferral endpoints (PRD §3.11, §3.12)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("telehealth_referrals", __name__)

REASONS = {"NO_RESULTS", "PRICE_TOO_HIGH", "NEW_PRESCRIPTION"}
READ_ROLES = ["Member", "PlatformAdmin"]


@bp.route("/telehealth-referrals", methods=["POST"])
def create_referral():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    comparison_id = common.req_str(body, "comparison_id")
    reason = common.req_enum(body, "reason", REASONS)

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): member then comparison
    member = common.must_exist(db.members, member_id, "Member")
    comparison = common.must_exist(db.comparisons, comparison_id, "PriceComparison")

    drug = db.drugs[comparison["drug_id"]]

    # controlled substance (priority 7): member.state_code must equal comparison.state_code
    if drug.get("is_controlled", False):
        if member["state_code"] != comparison["state_code"]:
            raise errors.ApiError(errors.ERR_CONTROLLED_SUBSTANCE_BLOCKED, 422,
                                  "Controlled substance telehealth blocked: state mismatch.")

    rec = {
        "member_id": member_id,
        "comparison_id": comparison_id,
        "drug_id": comparison["drug_id"],
        "reason": reason,
        "status": "REQUESTED",
    }
    db.stamp_create(rec, common_fields=True)
    db.telehealth_referrals[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/telehealth-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.telehealth_referrals, rid, "TelehealthReferral")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/telehealth-referrals", methods=["GET"])
def list_referrals():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    member_id = request.args.get("member_id")
    comparison_id = request.args.get("comparison_id")
    drug_id = request.args.get("drug_id")
    items = list(db.telehealth_referrals.values())
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if comparison_id is not None:
        items = [r for r in items if r["comparison_id"] == comparison_id]
    if drug_id is not None:
        items = [r for r in items if r["drug_id"] == drug_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/telehealth-referrals/<rid>/schedule", methods=["POST"])
def schedule_referral(rid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.telehealth_referrals, rid, "TelehealthReferral")
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state("Referral is not REQUESTED.")
    rec["status"] = "SCHEDULED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/telehealth-referrals/<rid>/complete", methods=["POST"])
def complete_referral(rid):
    middleware.require_auth(["PlatformAdmin"])
    rec = common.must_exist(db.telehealth_referrals, rid, "TelehealthReferral")
    if rec["status"] != "SCHEDULED":
        raise errors.invalid_state("Referral is not SCHEDULED.")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/telehealth-referrals/<rid>/cancel", methods=["POST"])
def cancel_referral(rid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    middleware.require_owner(user_id, role, member_id)
    rec = common.must_exist(db.telehealth_referrals, rid, "TelehealthReferral")
    common.must_exist(db.members, member_id, "Member")
    middleware.require_owner(user_id, role, rec["member_id"])
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state("Referral is not REQUESTED.")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
