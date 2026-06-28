"""InsuranceEstimate read endpoints (PRD §3.4)."""
from flask import Blueprint, request
import db
import response
import common
import middleware
from services import serializers

bp = Blueprint("insurance_estimates", __name__)

READ_ROLES = ["Member", "PlatformAdmin"]


@bp.route("/insurance-estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.insurance_estimates, eid, "InsuranceEstimate")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/insurance-estimates", methods=["GET"])
def list_estimates():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    comparison_id = request.args.get("comparison_id")
    member_id = request.args.get("member_id")
    items = list(db.insurance_estimates.values())
    if comparison_id is not None:
        items = [e for e in items if e["comparison_id"] == comparison_id]
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)
