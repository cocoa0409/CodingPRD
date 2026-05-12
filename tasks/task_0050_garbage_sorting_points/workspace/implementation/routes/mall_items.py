"""MallItem endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db
from errors import ERR_VALIDATION, raise_api_error
from middleware import require_roles
from response import list_response, success_response
from services.common import (
    check_version,
    get_json_body,
    optional_enum,
    optional_int,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
)
from services.lookup import get_community, get_mall_item

bp = Blueprint("mall_items", __name__)

CHANNELS = {"ONLINE", "STATION"}
STATUSES = {"LISTED", "DELISTED"}


@bp.post("/communities/<community_id>/mall-items")
@require_roles("CommunityAdmin")
def create_mall_item(community_id: str):
    get_community(community_id)
    body = get_json_body()
    name = require_str(body, "name", min_len=1, max_len=120)
    cost_points = require_int(body, "cost_points", minimum=1, maximum=1_000_000)
    stock = require_int(body, "stock", minimum=0)
    channel = require_enum(body, "channel", CHANNELS)

    obj = {
        "community_id": community_id,
        "name": name,
        "cost_points": cost_points,
        "stock": stock,
        "channel": channel,
        "status": "LISTED",
    }
    db.stamp_create(obj)
    db.mall_items[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.patch("/communities/<community_id>/mall-items/<item_id>")
@require_roles("CommunityAdmin")
def patch_mall_item(community_id: str, item_id: str):
    item = get_mall_item(community_id, item_id)
    body = get_json_body()
    check_version(body, item)

    stock = optional_int(body, "stock", minimum=0)
    cost_points = optional_int(body, "cost_points", minimum=1, maximum=1_000_000)
    status = optional_enum(body, "status", STATUSES)

    if stock is None and cost_points is None and status is None:
        raise_api_error(ERR_VALIDATION, "At least one updatable field must be supplied.")

    if stock is not None:
        item["stock"] = stock
    if cost_points is not None:
        item["cost_points"] = cost_points
    if status is not None:
        item["status"] = status
    db.stamp_update(item)
    return jsonify(success_response(item)), 200


@bp.get("/communities/<community_id>/mall-items")
@require_roles("CommunityAdmin", "Resident")
def list_mall_items(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    channel = request.args.get("channel")
    status = request.args.get("status")
    items = [
        m
        for m in db.mall_items.values()
        if m["community_id"] == community_id
        and (channel is None or m["channel"] == channel)
        and (status is None or m["status"] == status)
    ]
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
