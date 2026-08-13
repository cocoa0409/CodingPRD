"""HardPart endpoints, including OCC-gated stock adjustments."""

import uuid

from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_PART_NOT_FOUND, ERR_STALE_VERSION, ERR_NEGATIVE_STOCK,
)
from middleware import require_role
from response import success
from services.allocation import promotion_scan
from services.serializers import part_view
from validators import (
    get_json_body, require_fields, check_string, check_int, invalid,
)

bp = Blueprint("hard_parts", __name__)


@bp.post("/api/hard-parts")
def create_part():
    require_role({"InventoryPlanner"})
    body = get_json_body()
    require_fields(body, ["part_number", "part_family", "unit_cost_cents", "qty_on_hand"])
    check_string(body["part_number"], "part_number")
    check_string(body["part_family"], "part_family")
    check_int(body["unit_cost_cents"], "unit_cost_cents")
    check_int(body["qty_on_hand"], "qty_on_hand")
    if body["qty_on_hand"] < 0:
        invalid("qty_on_hand must not be negative")

    if any(p["part_number"] == body["part_number"] for p in db.hard_parts.values()):
        invalid("part_number must be unique")

    now = db.now()
    p = {
        "id": str(uuid.uuid4()),
        "part_number": body["part_number"],
        "part_family": body["part_family"],
        "unit_cost_cents": body["unit_cost_cents"],
        "qty_on_hand": body["qty_on_hand"],
        "qty_reserved": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.hard_parts[p["id"]] = p
    return success(part_view(p), "object", 201)


@bp.get("/api/hard-parts/<pid>")
def get_part(pid):
    require_role({"Any"})
    p = db.hard_parts.get(pid)
    if p is None:
        raise ApiError(ERR_PART_NOT_FOUND, "HardPart id does not exist", 404)
    return success(part_view(p), "object", 200)


@bp.post("/api/hard-parts/<pid>/stock-adjustments")
def stock_adjustment(pid):
    require_role({"InventoryPlanner"})
    body = get_json_body()
    require_fields(body, ["qty_delta", "expected_hard_part_version"])
    check_int(body["qty_delta"], "qty_delta")
    check_int(body["expected_hard_part_version"], "expected_hard_part_version")

    p = db.hard_parts.get(pid)
    if p is None:
        raise ApiError(ERR_PART_NOT_FOUND, "HardPart id does not exist", 404)

    # OCC (priority 5) precedes the fiscal floor (priority 10).
    if body["expected_hard_part_version"] != p["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_hard_part_version does not match the part's current version",
            412,
        )
    new_qty = p["qty_on_hand"] + body["qty_delta"]
    if new_qty < 0:
        raise ApiError(
            ERR_NEGATIVE_STOCK,
            "stock adjustment would drive qty_on_hand below zero",
            422,
        )
    p["qty_on_hand"] = new_qty
    p["version"] += 1
    p["updated_at"] = db.now()
    if body["qty_delta"] > 0:
        promotion_scan()
    return success(part_view(p), "object", 200)
