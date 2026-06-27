"""PriceComparison endpoints (PRD §3.3, §3.4)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, calculations

bp = Blueprint("comparisons", __name__)


@bp.route("/comparisons", methods=["POST"])
def create_comparison():
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    drug_id = common.req_str(body, "drug_id")
    state_code = common.req_str(body, "state_code")
    common.validate_state_code(state_code)

    # ownership (priority 3): member acting on own resource
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): FKs left-to-right (member then drug)
    common.must_exist(db.members, member_id, "Member")
    common.must_exist(db.drugs, drug_id, "Drug")

    rec = {
        "member_id": member_id,
        "drug_id": drug_id,
        "state_code": state_code,
        "selected_pharmacy_id": None,
        "best_price_cents": None,
        "candidate_count": 0,
        "status": "OPEN",
    }
    db.stamp_create(rec, common_fields=True)
    db.comparisons[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/comparisons/<cid>", methods=["GET"])
def get_comparison(cid):
    middleware.require_auth(["Member", "PlatformAdmin"])
    rec = common.must_exist(db.comparisons, cid, "PriceComparison")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/comparisons", methods=["GET"])
def list_comparisons():
    middleware.require_auth(["Member", "PlatformAdmin"])
    limit, offset = common.parse_pagination()
    member_id = request.args.get("member_id")
    drug_id = request.args.get("drug_id")
    items = list(db.comparisons.values())
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if drug_id is not None:
        items = [c for c in items if c["drug_id"] == drug_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/comparisons/<cid>/run", methods=["POST"])
def run_comparison(cid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")

    # ownership: the running member must own the comparison.
    rec = db.comparisons.get(cid)
    # Existence checked after ownership? Priority: auth(3) before existence(4).
    # But ownership needs the resource. Per spec ownership compares X-User-ID to
    # the body member_id (entity_backed role's id vs owning member_id). Validate
    # body member_id ownership first.
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): path id then body member_id
    rec = common.must_exist(db.comparisons, cid, "PriceComparison")
    common.must_exist(db.members, member_id, "Member")

    # state (priority 5)
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Comparison is not OPEN.")

    member = db.members[member_id]
    selected, best_price, count = calculations.best_price_selection(rec, member)
    rec["candidate_count"] = count
    if count == 0:
        rec["selected_pharmacy_id"] = None
        rec["best_price_cents"] = None
        rec["status"] = "NO_RESULTS"
    else:
        rec["selected_pharmacy_id"] = selected
        rec["best_price_cents"] = best_price
        rec["status"] = "RESOLVED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/comparisons/<cid>/insurance-estimate", methods=["POST"])
def insurance_estimate(cid):
    user_id, role = middleware.require_auth(["Member"])
    body = common.get_body()
    member_id = common.req_str(body, "member_id")
    copay_cents = common.req_int(body, "copay_cents")
    deductible_remaining_cents = common.req_int(body, "deductible_remaining_cents")
    if copay_cents < 0:
        raise errors.invalid_request("copay_cents must be >= 0.")
    if deductible_remaining_cents < 0:
        raise errors.invalid_request("deductible_remaining_cents must be >= 0.")

    # ownership (priority 3)
    middleware.require_owner(user_id, role, member_id)

    # existence (priority 4): comparison path id, then body member_id
    comparison = common.must_exist(db.comparisons, cid, "PriceComparison")
    member = common.must_exist(db.members, member_id, "Member")

    # business: member must have insurance (priority 14)
    if not member.get("has_insurance", False):
        raise errors.ApiError(errors.ERR_NO_INSURANCE_ON_FILE, 422,
                              "Member has no insurance on file.")

    # business: comparison must be RESOLVED (priority 15)
    if comparison["status"] != "RESOLVED" or comparison.get("best_price_cents") is None:
        raise errors.ApiError(errors.ERR_COMPARISON_NOT_RESOLVED, 409,
                              "Comparison is not RESOLVED.")

    drug = db.drugs[comparison["drug_id"]]
    recommended = calculations.discount_vs_insurance(
        comparison["best_price_cents"], copay_cents, deductible_remaining_cents, drug["awp_cents"])

    rec = {
        "comparison_id": cid,
        "member_id": member_id,
        "copay_cents": copay_cents,
        "deductible_remaining_cents": deductible_remaining_cents,
        "recommended_path": recommended,
    }
    # InsuranceEstimate is immutable: only id + created_at (no updated_at/version).
    db.stamp_create(rec, common_fields=False)
    db.insurance_estimates[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)
