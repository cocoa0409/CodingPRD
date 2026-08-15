"""Parts SKU catalog and restock (PRD §3.3)."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_common, touch, paginate, sorted_by_created, recompute_part_low_stock

bp = Blueprint("parts", __name__)

CATEGORIES = ["DRIVETRAIN", "BRAKES", "WHEELS", "FRAME", "COCKPIT", "SADDLE", "TIRES", "HELMET", "MISC"]
HELMET_SIZES = ["XS", "S", "M", "L", "XL"]


def part_view(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "category": p["category"],
        "helmet_size": p["helmet_size"],
        "unit_cost_cents": p["unit_cost_cents"],
        "quantity_on_hand": p["quantity_on_hand"],
        "reorder_threshold": p["reorder_threshold"],
        "low_stock": p["low_stock"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _get_part(part_id):
    part = db.parts.get(part_id)
    if part is None:
        raise ApiError("ERR_NOT_FOUND", f"Part {part_id} does not exist")
    return part


@bp.post("/parts")
def create_part():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "name": {"type": "string", "required": True},
        "category": {"type": "string", "required": True, "enum": CATEGORIES},
        "helmet_size": {"type": "string", "enum": HELMET_SIZES},
        "unit_cost_cents": {"type": "integer", "min_int": 0},
        "reorder_threshold": {"type": "integer", "min_int": 0},
    })
    if any(p["name"] == body["name"] for p in db.parts.values()):
        raise ApiError("ERR_PART_NAME_CONFLICT", "part name already exists")
    helmet_size = body.get("helmet_size")
    if body["category"] == "HELMET":
        if helmet_size is None:
            raise ApiError("ERR_HELMET_SIZE_REQUIRED", "HELMET parts require helmet_size")
    elif helmet_size is not None:
        raise ApiError("ERR_HELMET_SIZE_REQUIRED", "helmet_size is only allowed for HELMET parts")

    part = make_common()
    part.update({
        "name": body["name"],
        "category": body["category"],
        "helmet_size": helmet_size,
        "unit_cost_cents": body.get("unit_cost_cents", 0),
        "quantity_on_hand": 0,
        "reorder_threshold": body.get("reorder_threshold", 0),
        "low_stock": False,
    })
    recompute_part_low_stock(part)
    db.parts[part["id"]] = part
    return success(part_view(part), status=201)


@bp.get("/parts/<part_id>")
def get_part(part_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    return success(part_view(_get_part(part_id)))


@bp.get("/parts")
def list_parts():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.parts.values())
    category = request.args.get("category")
    if category is not None:
        rows = [p for p in rows if p["category"] == category]
    low_stock = request.args.get("low_stock")
    if low_stock is not None:
        want = low_stock.lower() == "true"
        rows = [p for p in rows if p["low_stock"] == want]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([part_view(p) for p in page], pagination=pg)


@bp.post("/parts/<part_id>/restock")
def restock_part(part_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "quantity": {"type": "integer", "required": True},
        "unit_cost_cents": {"type": "integer", "min_int": 0},
    })
    part = _get_part(part_id)
    if body["quantity"] < 1:
        raise ApiError("ERR_QUANTITY_INVALID", "quantity must be at least 1")
    part["quantity_on_hand"] += body["quantity"]
    if "unit_cost_cents" in body and body["unit_cost_cents"] is not None:
        part["unit_cost_cents"] = body["unit_cost_cents"]
    touch(part)
    recompute_part_low_stock(part)
    return success(part_view(part))
