"""Catalog & seed routes: SKUs, stores, customers (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import (get_body, parse_pagination, paginate, as_int, as_bool,
                     as_str, as_enum)
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404
from services import serializers

bp = Blueprint("catalog", __name__)

SPORTS = {"HOCKEY", "BASEBALL", "FOOTWEAR", "FISHING", "TEAMWEAR", "APPAREL"}
STATE_CODE_RE = None  # validated inline


def _valid_state_code(code):
    return isinstance(code, str) and len(code) == 2 and code.isalpha() and code.isupper()


# ---------------------------------------------------------------------------
# SKUs
# ---------------------------------------------------------------------------
@bp.route("/skus", methods=["POST"])
@require_roles("PlatformAdmin")
def create_sku():
    body = get_body()
    sport = as_enum(body, "sport", SPORTS, required=True)
    name = as_str(body, "name", required=True)
    base_price_cents = as_int(body, "base_price_cents", required=True, minimum=0)
    size_label = as_str(body, "size_label", required=False, default="NA")
    requires_license_permit = as_bool(body, "requires_license_permit", default=False)
    embroiderable = as_bool(body, "embroiderable", default=False)

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "sport": sport,
        "name": name,
        "size_label": size_label,
        # is_footwear is computed, never accepted (§3.1).
        "is_footwear": (sport == "FOOTWEAR"),
        "base_price_cents": base_price_cents,
        "requires_license_permit": requires_license_permit,
        "embroiderable": embroiderable,
        # lifecycle_base is the stored baseline; effective lifecycle is recomputed
        # on read against active markdowns (§3.1, §3.2).
        "lifecycle_base": "STANDARD",
    }
    db.skus[rid] = rec
    return success(serializers.sku(rec), 201)


@bp.route("/skus/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "ServiceTech", "Customer")
def get_sku(rid):
    rec = get_or_404(db.skus, rid)
    return success(serializers.sku(rec), 200)


@bp.route("/skus", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "ServiceTech", "Customer")
def list_skus():
    limit, offset = parse_pagination()
    sport = request.args.get("sport")
    items = list(db.skus.values())
    if sport is not None:
        items = [s for s in items if s["sport"] == sport]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.sku(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
@bp.route("/stores", methods=["POST"])
@require_roles("PlatformAdmin")
def create_store():
    body = get_body()
    name = as_str(body, "name", required=True)
    state_code = as_str(body, "state_code", required=True)
    if not _valid_state_code(state_code):
        raise errors.invalid_request("state_code must be two uppercase letters")
    ship = as_bool(body, "ship_from_store_enabled", default=True)
    pickup = as_bool(body, "pickup_enabled", default=True)

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "name": name,
        "state_code": state_code,
        "ship_from_store_enabled": ship,
        "pickup_enabled": pickup,
    }
    db.stores[rid] = rec
    return success(serializers.store(rec), 201)


@bp.route("/stores/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "ServiceTech", "Customer")
def get_store(rid):
    rec = get_or_404(db.stores, rid)
    return success(serializers.store(rec), 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_customer():
    body = get_body()
    email = as_str(body, "email", required=True)
    full_name = as_str(body, "full_name", required=True)
    home_state_code = as_str(body, "home_state_code", required=True)
    if not _valid_state_code(home_state_code):
        raise errors.invalid_request("home_state_code must be two uppercase letters")

    # Case-insensitive email uniqueness (§3.1).
    lowered = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lowered:
            raise errors.ApiError(errors.ERR_DUPLICATE_EMAIL, 409,
                                  "A customer with this email already exists")

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "email": email,
        "full_name": full_name,
        "home_state_code": home_state_code,
        "loyalty_points": 0,
        "loyalty_tier": "BRONZE",
    }
    db.customers[rid] = rec
    return success(serializers.customer(rec), 201)


@bp.route("/customers/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "StoreAssociate", "ServiceTech", "Customer")
def get_customer(rid):
    rec = get_or_404(db.customers, rid)
    return success(serializers.customer(rec), 200)
