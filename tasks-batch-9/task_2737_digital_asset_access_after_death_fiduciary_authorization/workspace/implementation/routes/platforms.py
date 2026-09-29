"""Platform register (PRD section 3.1)."""
from flask import Blueprint, request

from authz import ALL_ROLES, ESTATE_ADMIN, authenticate, require_role
from db import DB, bump, stamp_new
from response import public, single
from routes.common import paged
from services import lookup
from validation import (parse_body, v_bool, v_enum, v_int, v_str, validate)

bp = Blueprint("platforms", __name__)

PLATFORM_TYPES = ("FINANCIAL", "EMAIL", "CLOUD_STORAGE", "SUBSCRIPTION",
                  "LOYALTY", "SOCIAL")
PLATFORM_STATUSES = ("PARTICIPATING", "LIMITED", "SUSPENDED")
REFUND_POLICIES = ("PRORATA_DAILY", "UNUSED_PERIOD", "NONE")

FIELD_CHECKS = {
    "name": v_str(120),
    "platform_type": v_enum(PLATFORM_TYPES),
    "status": v_enum(PLATFORM_STATUSES),
    "supports_online_tool": v_bool(),
    "supports_transfer": v_bool(),
    "supports_memorialization": v_bool(),
    "supports_deletion": v_bool(),
    "requires_court_order_for_content": v_bool(),
    "license_terminates_at_death": v_bool(),
    "review_window_days": v_int(1, 90),
    "form_code": v_str(40),
    "refund_policy": v_enum(REFUND_POLICIES),
    "transfer_fee_cents": v_int(0),
    "request_fee_cents": v_int(0),
}

CREATE_REQUIRED = ("name", "platform_type", "form_code", "review_window_days",
                   "refund_policy", "supports_online_tool", "supports_transfer",
                   "supports_memorialization", "supports_deletion",
                   "requires_court_order_for_content",
                   "license_terminates_at_death", "transfer_fee_cents",
                   "request_fee_cents")

PATCH_FIELDS = ("status", "refund_policy", "supports_online_tool",
                "supports_transfer", "supports_memorialization",
                "supports_deletion", "requires_court_order_for_content",
                "license_terminates_at_death", "review_window_days",
                "transfer_fee_cents", "request_fee_cents", "form_code")


@bp.route("/platforms", methods=["POST"])
def create_platform():
    _, role = authenticate(request)
    require_role(role, (ESTATE_ADMIN,))
    body = validate(
        parse_body(request),
        required={k: FIELD_CHECKS[k] for k in CREATE_REQUIRED},
        optional={"status": FIELD_CHECKS["status"]},
    )
    record = {k: body[k] for k in CREATE_REQUIRED}
    record["status"] = body.get("status", "PARTICIPATING")
    stamp_new(record)
    DB.platforms[record["id"]] = record
    return single(public(record), 201)


@bp.route("/platforms/<platform_id>", methods=["GET"])
def read_platform(platform_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_platform(platform_id)), 200)


@bp.route("/platforms", methods=["GET"])
def list_platforms():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.platforms.values(), request.args, {
        "platform_type": "platform_type",
        "status": "status",
        "refund_policy": "refund_policy",
    })


@bp.route("/platforms/<platform_id>", methods=["PATCH"])
def patch_platform(platform_id):
    _, role = authenticate(request)
    require_role(role, (ESTATE_ADMIN,))
    body = validate(
        parse_body(request),
        optional={k: FIELD_CHECKS[k] for k in PATCH_FIELDS},
    )
    platform = lookup.get_platform(platform_id)
    for key, value in body.items():
        platform[key] = value
    bump(platform)
    return single(public(platform), 200)
