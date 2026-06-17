"""PricingPolicy endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_id, add_common_fields, touch
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.common import (
    get_json_body, require_enum, require_int, optional_int,
    optional_number, parse_pagination, paginate,
)
from services.lookup import get_park, get_pricing_policy

bp = Blueprint("pricing", __name__)

PRODUCT_TYPES = {"DAY_TICKET", "SEASON_PASS"}


@bp.route("/pricing-policies", methods=["POST"])
def create_policy():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = get_json_body()

    # Existence (priority 4) before schema (priority 5): resolve park_id.
    if "park_id" not in body or body["park_id"] is None:
        from errors import ApiError
        import errors
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: park_id")
    park = get_park(body["park_id"])

    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    base_price_cents = require_int(body, "base_price_cents", minimum=0)
    resident_discount_pct = optional_number(body, "resident_discount_pct", 0, minimum=0, maximum=0.90)
    group_threshold = optional_int(body, "group_threshold", 10, minimum=2)
    group_discount_pct = optional_number(body, "group_discount_pct", 0, minimum=0, maximum=0.90)
    combo_price_cents = optional_int(body, "combo_price_cents", 0, minimum=0)

    # Supersede prior active policy for same (park_id, product_type).
    for p in db.pricing_policies.values():
        if p["park_id"] == park["id"] and p["product_type"] == product_type and p["active"]:
            p["active"] = False
            touch(p)

    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "product_type": product_type,
        "base_price_cents": base_price_cents,
        "resident_discount_pct": resident_discount_pct,
        "group_threshold": group_threshold,
        "group_discount_pct": group_discount_pct,
        "combo_price_cents": combo_price_cents,
        "active": True,
    }
    add_common_fields(rec)
    db.pricing_policies[rec["id"]] = rec
    return success(serialize.pricing_policy(rec), status=201)


@bp.route("/pricing-policies", methods=["GET"])
def list_policies():
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    limit, offset = parse_pagination()
    rows = list(db.pricing_policies.values())
    park_id = request.args.get("park_id")
    product_type = request.args.get("product_type")
    active = request.args.get("active")
    if park_id is not None:
        rows = [p for p in rows if p["park_id"] == park_id]
    if product_type is not None:
        rows = [p for p in rows if p["product_type"] == product_type]
    if active is not None:
        want = active.lower() == "true"
        rows = [p for p in rows if p["active"] == want]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.pricing_policy(r) for r in page], limit, offset, total)


@bp.route("/pricing-policies/<pid>", methods=["GET"])
def get_policy(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    rec = get_pricing_policy(pid)
    return success(serialize.pricing_policy(rec))


def find_active_policy(park_id, product_type):
    for p in db.pricing_policies.values():
        if p["park_id"] == park_id and p["product_type"] == product_type and p["active"]:
            return p
    return None
