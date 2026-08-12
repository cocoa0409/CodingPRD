"""Plan registration (PRD §3.1)."""

from flask import Blueprint, request

import constants as K
import envelope
import rows
import serializers
from context import Ctx
from errors import ApiError

bp = Blueprint("plans", __name__)

PLAN_SPEC = [
    {"name": "tier", "type": "string", "required": True, "enum": K.PLAN_TIERS},
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80},
    {"name": "monthly_fee_cents", "type": "integer", "required": True, "min": 0},
    {"name": "max_members", "type": "integer", "required": True, "min": 1, "max": 12},
    {"name": "profile_quota_per_cycle", "type": "integer", "required": True, "min": 1},
    {"name": "scan_quota_per_cycle", "type": "integer", "required": True, "min": 1},
    {"name": "removal_quota_per_cycle", "type": "integer", "required": True, "min": 1},
    {"name": "per_member_removal_subcap", "type": "integer", "required": True, "min": 1},
]


@bp.post("/plans")
def create_plan():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    ctx.load_body()
    fields = ctx.validate(PLAN_SPEC)
    # Rung 9 continued: the sub-cap may never exceed the pool it draws from.
    if fields["per_member_removal_subcap"] > fields["removal_quota_per_cycle"]:
        raise ApiError(
            "ERR_VALUE_OUT_OF_RANGE",
            "per_member_removal_subcap must not exceed removal_quota_per_cycle.",
        )
    row = rows.new_row(
        "plans",
        {
            "tier": fields["tier"],
            "name": fields["name"],
            "monthly_fee_cents": fields["monthly_fee_cents"],
            "max_members": fields["max_members"],
            "profile_quota_per_cycle": fields["profile_quota_per_cycle"],
            "scan_quota_per_cycle": fields["scan_quota_per_cycle"],
            "removal_quota_per_cycle": fields["removal_quota_per_cycle"],
            "per_member_removal_subcap": fields["per_member_removal_subcap"],
        },
    )
    return envelope.created(serializers.plan(row))
