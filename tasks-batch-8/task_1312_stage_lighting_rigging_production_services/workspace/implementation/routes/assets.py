"""EquipmentAsset endpoints: registration and the manual lifecycle."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    require_ts,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("assets", __name__)

ASSET_CLASSES = {
    "MOVING_LIGHT",
    "LED_PANEL",
    "TRUSS_12IN",
    "CHAIN_MOTOR",
    "DISTRO_BOX",
    "CABLE_FEEDER",
    "CONSOLE",
    "FOLLOWSPOT",
}
ASSET_STATES = {"AVAILABLE", "RESERVED", "PREPPED", "DEPLOYED", "DAMAGED", "LOST", "RETIRED"}
ASSET_TERMINAL = {"RETIRED", "LOST"}
# RESERVED/PREPPED/DEPLOYED/DAMAGED/LOST are driven only by pull-list cascades
# and damage assessment; manual transitions own only RETIRED and AVAILABLE.
ASSET_TO_OWNERS = {
    "RETIRED": {"WarehouseChief"},
    "AVAILABLE": {"WarehouseChief"},
}
ASSET_DECLARED = {
    "AVAILABLE": {"RETIRED"},
    "DAMAGED": {"AVAILABLE", "RETIRED"},
    "RESERVED": set(),
    "PREPPED": set(),
    "DEPLOYED": set(),
}


def get_asset_or_404(asset_id: str) -> dict:
    asset = db.assets.get(asset_id)
    if asset is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "EquipmentAsset id does not exist")
    return asset


@bp.route("/assets", methods=["POST"])
@require_roles("WarehouseChief")
def create_asset(_user_id: str, _role: str):
    body = get_json_body()
    asset_tag = require_string(body, "asset_tag")
    asset_class = require_enum(body, "asset_class", ASSET_CLASSES)
    weight_kg = require_number(body, "weight_kg", minimum=0, exclusive_min=True)
    power_draw_watts = optional_int(body, "power_draw_watts", 0, minimum=0)
    daily_rate = require_int(body, "daily_rate_cents", minimum=0, exclusive_min=True)
    replacement_cost = require_int(body, "replacement_cost_cents", minimum=0, exclusive_min=True)
    acquired_at = require_ts(body, "acquired_at")

    for asset in db.assets.values():
        if asset["asset_tag"] == asset_tag:
            raise_err(ERR_INVALID_REQUEST, "asset_tag already registered")

    asset = {
        "asset_tag": asset_tag,
        "asset_class": asset_class,
        "weight_kg": weight_kg,
        "power_draw_watts": power_draw_watts,
        "daily_rate_cents": daily_rate,
        "replacement_cost_cents": replacement_cost,
        "acquired_at": acquired_at,
        "status": "AVAILABLE",
    }
    db.stamp_new(asset)
    db.assets[asset["id"]] = asset
    return success_object(serialize(asset), 201)


@bp.route("/assets", methods=["GET"])
@require_roles("Any")
def list_assets(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.assets.values()))
    items = apply_filters(items, ["asset_class", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/assets/<asset_id>", methods=["GET"])
@require_roles("Any")
def get_asset(asset_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_asset_or_404(asset_id)))


@bp.route("/assets/<asset_id>/pull-list-entries", methods=["GET"])
@require_roles("Any")
def list_asset_entries(asset_id: str, _user_id: str, _role: str):
    get_asset_or_404(asset_id)
    limit, offset = parse_pagination()
    items = [e for e in db.pull_list_entries.values() if e["asset_id"] == asset_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/assets/<asset_id>/transition", methods=["POST"])
@require_roles("WarehouseChief")
def transition_asset(asset_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, ASSET_STATES)
    check_transition_owner(to, ASSET_TO_OWNERS, _role)
    asset = get_asset_or_404(asset_id)
    check_terminal(asset, ASSET_TERMINAL, to, ASSET_DECLARED)
    check_declared(asset, to, ASSET_DECLARED)

    # Manual QC pass (DAMAGED -> AVAILABLE) deliberately does NOT run the
    # waitlist promotion scan; promotion is tied to assets freed from pulls.
    asset["status"] = to
    db.touch(asset)
    return success_object(serialize(asset))
