"""Menu item endpoints (nested under restaurants for creation/listing)."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import restaurants as svc


bp = Blueprint("menu_items", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


@bp.route("/api/restaurants/<rid>/menu-items", methods=["POST"])
def create_menu_item(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("Restaurant", "PlatformAdmin"):
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        if role == "Restaurant" and user_id != rec["id"]:
            return envelope.forbidden()

        # Body shape
        if "name" not in payload or not isinstance(payload["name"], str) or not payload["name"]:
            return envelope.validation("name must be a non-empty string.")
        if "price_cents" not in payload or not validators.is_int(payload["price_cents"]):
            return envelope.validation("price_cents must be an integer.")
        price = payload["price_cents"]
        if price < 1 or price > 1_000_000:
            return envelope.validation("price_cents must be in [1, 1000000].")
        is_listed = payload.get("is_listed", True)
        if not isinstance(is_listed, bool):
            return envelope.validation("is_listed must be a boolean.")

        item = svc.new_menu_item(rid, payload["name"], price, is_listed)
        return envelope.created(projection.render(item))


@bp.route("/api/restaurants/<rid>/menu-items", methods=["GET"])
def list_menu_items(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    allowed = {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}
    if role not in allowed:
        return envelope.forbidden()

    page, perr = validators.pagination_params(request.args)
    if perr:
        return perr
    limit, offset = page

    with state.lock():
        rec = state.STORE.restaurants.get(rid)
        if rec is None:
            return envelope.not_found("Restaurant not found.")
        items = [m for m in state.STORE.menu_items.values() if m["restaurant_id"] == rid]
        is_listed = request.args.get("is_listed")
        if is_listed is not None:
            want = is_listed.lower() == "true"
            items = [m for m in items if m["is_listed"] == want]
        items.sort(key=lambda m: m["created_at"])
        total = len(items)
        window = items[offset : offset + limit]
        return envelope.list_response(
            [projection.render(m) for m in window], limit, offset, total
        )


@bp.route("/api/menu-items/<mid>", methods=["PATCH"])
def patch_menu_item(mid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("Restaurant", "PlatformAdmin"):
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    with state.lock():
        item = state.STORE.menu_items.get(mid)
        if item is None:
            return envelope.not_found("Menu item not found.")
        owning_restaurant = state.STORE.restaurants.get(item["restaurant_id"])

        if role == "Restaurant" and (owning_restaurant is None or user_id != owning_restaurant["id"]):
            return envelope.forbidden()

        allowed_keys = {"price_cents", "is_listed", "version"}
        bad_keys = set(payload.keys()) - allowed_keys
        if "name" in bad_keys or "restaurant_id" in bad_keys:
            return envelope.validation("name and restaurant_id are immutable.")
        if bad_keys:
            return envelope.validation(
                f"Field(s) not editable: {', '.join(sorted(bad_keys))}."
            )

        if "price_cents" in payload:
            if not validators.is_int(payload["price_cents"]):
                return envelope.validation("price_cents must be an integer.")
            if payload["price_cents"] < 1 or payload["price_cents"] > 1_000_000:
                return envelope.validation("price_cents must be in [1, 1000000].")
        if "is_listed" in payload and not isinstance(payload["is_listed"], bool):
            return envelope.validation("is_listed must be a boolean.")

        if "version" in payload and payload["version"] != item["version"]:
            return envelope.version_conflict()

        for k in ("price_cents", "is_listed"):
            if k in payload:
                item[k] = payload[k]
        item["updated_at"] = state.now()
        item["version"] = item["version"] + 1
        return envelope.success(projection.render(item))
