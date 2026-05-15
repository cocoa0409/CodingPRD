"""Member routes."""

from flask import Blueprint

from db import DB, new_id
from errors import ERR_DUPLICATE_RESOURCE, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.common import (
    get_body,
    get_or_404,
    init_common,
    optional_enum,
    optional_int,
    require_string,
)


bp = Blueprint("members", __name__, url_prefix="/swap-stations")


SUBSCRIPTION_TIERS = {"NONE", "BASIC", "PREMIUM"}


@bp.route("/members", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_member():
    body = get_body()
    name = require_string(body, "name")
    phone = require_string(body, "phone")
    subscription_tier = optional_enum(body, "subscription_tier", SUBSCRIPTION_TIERS, default="NONE")
    subscription_swaps_remaining = optional_int(body, "subscription_swaps_remaining",
                                                default=0, min_value=0)

    for m in DB["members"].values():
        if m.get("phone") == phone:
            raise_error(ERR_DUPLICATE_RESOURCE, "Member phone already exists")

    row = {
        "id": new_id(),
        "name": name,
        "phone": phone,
        "subscription_tier": subscription_tier,
        "subscription_swaps_remaining": int(subscription_swaps_remaining),
        "no_show_count_30d": 0,
        "reservation_blocked_until": None,
    }
    init_common(row)
    DB["members"][row["id"]] = row
    return success_response(row, http_status=201)


@bp.route("/members/<member_id>", methods=["GET"])
@auth_required(["Member", "PlatformAdmin"])
def get_member(member_id):
    row = get_or_404("members", member_id)
    return success_response(row)
