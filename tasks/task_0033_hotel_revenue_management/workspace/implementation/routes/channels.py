"""Channel routes."""
from flask import Blueprint, request

from db import channels, stamp_create, lock
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.projections import project_channel
from services.validation import (
    require_dict, required_str, required_int, in_range, must_uppercase, at_least
)
from services.listing import list_resource

bp = Blueprint("channels", __name__)

_VALID_CHANNEL_TYPES = {"DIRECT", "OTA", "GDS", "WHOLESALER"}
_LIST_ROLES = ["PlatformAdmin", "RevenueAnalyst", "RevenueManager", "ReservationsAgent"]


@bp.route("/hotel/channels", methods=["POST"])
@require_auth(roles=["PlatformAdmin"])
def create_channel():
    body = require_dict(request.get_json(silent=True))
    code = required_str(body, "code")
    must_uppercase(code, "code")
    channel_type = required_str(body, "channel_type")
    if channel_type not in _VALID_CHANNEL_TYPES:
        raise err("ERR_INVALID_INPUT", "channel_type must be one of DIRECT/OTA/GDS/WHOLESALER")
    commission = required_int(body, "commission_basis_points")
    in_range(commission, 0, 5000, "commission_basis_points")
    priority = required_int(body, "priority_rank")
    at_least(priority, 1, "priority_rank")

    with lock():
        # uniqueness across active channels: code unique among ACTIVE
        for c in channels.values():
            if c.get("status") == "ACTIVE" and c.get("code") == code:
                raise err("ERR_INVALID_INPUT", "code already in use among active channels")
        # priority_rank unique across active channels
        for c in channels.values():
            if c.get("status") == "ACTIVE" and c.get("priority_rank") == priority:
                raise err("ERR_DUPLICATE_PRIORITY_RANK",
                          "priority_rank already in use among active channels")

        row = {
            "code": code,
            "channel_type": channel_type,
            "commission_basis_points": commission,
            "priority_rank": priority,
            "status": "ACTIVE",
        }
        stamp_create(row, common_fields=True)
        channels[row["id"]] = row
    return success(project_channel(row), 201)


@bp.route("/hotel/channels", methods=["GET"])
@require_auth(roles=_LIST_ROLES)
def list_channels():
    limit, offset = get_pagination()
    filters = {}
    for k in ("channel_type", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    items, total = list_resource(channels, filters=filters,
                                  projector=project_channel,
                                  limit=limit, offset=offset)
    return success_list(items, limit, offset, total)
