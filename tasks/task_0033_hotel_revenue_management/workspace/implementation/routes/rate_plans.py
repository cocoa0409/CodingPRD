"""RatePlan + ChannelRatePlanMapping routes."""
from flask import Blueprint, request

from db import rate_plans, channels, room_types, channel_rate_plan_mappings, stamp_create, lock
from errors import err
from middleware import require_auth
from response import success
from services.projections import project_rate_plan, project_mapping
from services.validation import (
    require_dict, required_str, required_int, optional_bool, in_range, must_uppercase
)


bp = Blueprint("rate_plans", __name__)

_VALID_REFUND_TIERS = {"FLEXIBLE", "MODERATE", "STRICT", "NON_REFUNDABLE"}
_RP_ROLES = ["PlatformAdmin", "RevenueManager"]


@bp.route("/hotel/rate-plans", methods=["POST"])
@require_auth(roles=_RP_ROLES)
def create_rate_plan():
    body = require_dict(request.get_json(silent=True))
    code = required_str(body, "code")
    must_uppercase(code, "code")
    room_type_id = required_str(body, "room_type_id")
    refund_tier_code = required_str(body, "refund_tier_code")
    if refund_tier_code not in _VALID_REFUND_TIERS:
        raise err("ERR_INVALID_INPUT", "refund_tier_code invalid")
    modification_allowed = optional_bool(body, "modification_allowed", default=True)

    with lock():
        rt = room_types.get(room_type_id)
        if rt is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType not found")
        if rt.get("status") != "ACTIVE":
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType is not ACTIVE")
        # uniqueness across active rate plans
        for rp in rate_plans.values():
            if rp.get("status") == "ACTIVE" and rp.get("code") == code:
                raise err("ERR_INVALID_INPUT", "code already in use among active rate plans")

        row = {
            "code": code,
            "room_type_id": room_type_id,
            "refund_tier_code": refund_tier_code,
            "modification_allowed": modification_allowed,
            "status": "ACTIVE",
        }
        stamp_create(row, common_fields=True)
        rate_plans[row["id"]] = row
    return success(project_rate_plan(row), 201)


@bp.route("/hotel/channel-rate-plan-mappings", methods=["POST"])
@require_auth(roles=_RP_ROLES)
def create_mapping():
    body = require_dict(request.get_json(silent=True))
    channel_id = required_str(body, "channel_id")
    rate_plan_id = required_str(body, "rate_plan_id")
    share_bp = required_int(body, "inventory_share_basis_points")
    in_range(share_bp, 0, 10000, "inventory_share_basis_points")

    with lock():
        ch = channels.get(channel_id)
        if ch is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "Channel not found")
        rp = rate_plans.get(rate_plan_id)
        if rp is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "RatePlan not found")

        # Sum of inventory_share_basis_points across mappings sharing rate_plan_id must be <= 10000
        existing = sum(
            m["inventory_share_basis_points"]
            for m in channel_rate_plan_mappings.values()
            if m.get("rate_plan_id") == rate_plan_id
        )
        if existing + share_bp > 10000:
            raise err("ERR_INVENTORY_SHARE_EXCEEDED",
                      "Sum of inventory_share_basis_points for this rate plan would exceed 10000")

        row = {
            "channel_id": channel_id,
            "rate_plan_id": rate_plan_id,
            "inventory_share_basis_points": share_bp,
            "enabled": True,
        }
        # mappings are immutable join rows: only id + created_at
        stamp_create(row, common_fields=False)
        channel_rate_plan_mappings[row["id"]] = row
    return success(project_mapping(row), 201)
