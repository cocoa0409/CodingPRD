from __future__ import annotations

from flask import Blueprint, g, request

from .. import projections, resolvers
from ..auth import require_role
from ..entities import bump, init_versioned
from ..envelope import (
    err_forbidden,
    err_invalid_state,
    err_validation,
    success,
    success_list,
)
from ..occ import check as occ_check
from ..store import store
from ..validators import (
    get_json,
    optional_int,
    optional_str,
    pagination_params,
    require_int,
    require_str,
)

bp = Blueprint("menu_items", __name__)


def _serialize(m: dict) -> dict:
    return projections.menu_item(m)


@bp.route("/api/restaurants/<rid>/menu-items", methods=["POST"])
def create_menu_item(rid: str):
    require_role("Restaurant", "PlatformAdmin")
    r = resolvers.restaurant(rid)
    if g.user_role == "Restaurant" and g.user_id != r["id"]:
        raise err_forbidden("Restaurant identity mismatch")
    body = get_json()
    name = require_str(body, "name", max_len=200)
    price = require_int(body, "price_cents", minv=1, maxv=1_000_000)
    is_listed = body.get("is_listed", True)
    if not isinstance(is_listed, bool):
        raise err_validation("is_listed must be a boolean")
    m = init_versioned("MenuItem")
    m.update(
        {
            "restaurant_id": r["id"],
            "name": name,
            "price_cents": price,
            "is_listed": is_listed,
        }
    )
    store.menu_items[m["id"]] = m
    return success(_serialize(m), status=201)


@bp.route("/api/restaurants/<rid>/menu-items", methods=["GET"])
def list_menu_items(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    r = resolvers.restaurant(rid)
    limit, offset = pagination_params()
    items = [m for m in store.menu_items.values() if m["restaurant_id"] == r["id"]]
    listed_filter = request.args.get("is_listed")
    if listed_filter is not None:
        if listed_filter not in ("true", "false"):
            raise err_validation("is_listed must be 'true' or 'false'")
        want = listed_filter == "true"
        items = [m for m in items if m["is_listed"] == want]
    items.sort(key=lambda m: m["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([_serialize(m) for m in page], limit, offset, total)


@bp.route("/api/menu-items/<mid>", methods=["PATCH"])
def patch_menu_item(mid: str):
    require_role("Restaurant", "PlatformAdmin")
    m = resolvers.menu_item(mid)
    if g.user_role == "Restaurant" and g.user_id != m["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    body = get_json()
    new_price = optional_int(body, "price_cents", minv=1, maxv=1_000_000)
    listed_supplied = "is_listed" in body
    if listed_supplied:
        v = body["is_listed"]
        if not isinstance(v, bool):
            raise err_validation("is_listed must be a boolean")
    occ_check(m, body.get("version"))
    if new_price is not None:
        m["price_cents"] = new_price
    if listed_supplied:
        m["is_listed"] = body["is_listed"]
    bump(m)
    return success(_serialize(m))
