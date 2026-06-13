"""Configuration & customer endpoints: products, options, production-days,
routes, customers, credit adjustments, plus test-only clock/override tools."""
from datetime import datetime, timezone

from flask import Blueprint, request, g

import clock
import db
import serializers as S
import validators as V
from db import store
from errors import err, ERR_REFERENCE_NOT_FOUND, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_auth
from response import success, list_response, parse_pagination
from services.calculations import loyalty_tier

bp = Blueprint("config", __name__)


def _sorted(values):
    return sorted(values, key=lambda o: (o["created_at"], o["id"]))


def _parse_iso(value, field):
    try:
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 timestamp")


# ---- products -----------------------------------------------------------

@bp.route("/products", methods=["POST"])
@require_auth(["BakeryManager"])
def create_product():
    data = V.body()
    obj = {
        "name": V.require_str(data, "name"),
        "base_price_cents": V.require_int(data, "base_price_cents", minimum=0),
        "base_lead_days": V.require_int(data, "base_lead_days", minimum=0),
        "tier_levels": V.optional_int(data, "tier_levels", default=1, minimum=1),
        "allowed_option_codes": V.optional_str_array(data, "allowed_option_codes", default=[]),
        "declared_allergen_codes": V.optional_str_array(data, "declared_allergen_codes", default=[]),
        "status": V.require_enum(data, "status", {"ACTIVE", "RETIRED"}) if data.get("status") is not None else "ACTIVE",
    }
    store.stamp_create(obj)
    store.products[obj["id"]] = obj
    return success(S.product(obj), status=201)


@bp.route("/products/<pid>", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "Customer"])
def get_product(pid):
    obj = store.products.get(pid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "product not found")
    return success(S.product(obj), status=200)


@bp.route("/products", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "Customer"])
def list_products():
    limit, offset = parse_pagination(request.args)
    items = list(store.products.values())
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response([S.product(o) for o in _sorted(items)], limit, offset)


# ---- options ------------------------------------------------------------

@bp.route("/options", methods=["POST"])
@require_auth(["BakeryManager"])
def create_option():
    data = V.body()
    obj = {
        "option_code": V.require_str(data, "option_code"),
        "surcharge_cents": V.require_int(data, "surcharge_cents", minimum=0),
        "introduces_allergen_codes": V.optional_str_array(data, "introduces_allergen_codes", default=[]),
        "dietary_exclusion_codes": V.optional_str_array(data, "dietary_exclusion_codes", default=[]),
    }
    store.stamp_create(obj)
    store.options[obj["id"]] = obj
    return success(S.option(obj), status=201)


@bp.route("/options/<oid>", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "Customer"])
def get_option(oid):
    obj = store.options.get(oid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "option not found")
    return success(S.option(obj), status=200)


@bp.route("/options", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "Customer"])
def list_options():
    limit, offset = parse_pagination(request.args)
    items = list(store.options.values())
    return list_response([S.option(o) for o in _sorted(items)], limit, offset)


# ---- production days ----------------------------------------------------

@bp.route("/production-days", methods=["POST"])
@require_auth(["BakeryManager"])
def create_production_day():
    data = V.body()
    cutoff = V.require_str(data, "order_cutoff_at")
    _parse_iso(cutoff, "order_cutoff_at")  # validate format
    obj = {
        "production_date": V.require_str(data, "production_date"),
        "unit_capacity": V.require_int(data, "unit_capacity", minimum=0),
        "is_peak": V.optional_bool(data, "is_peak", default=False),
        "order_cutoff_at": cutoff,
        "units_committed": 0,
    }
    store.stamp_create(obj)
    store.production_days[obj["id"]] = obj
    return success(S.production_day(obj), status=201)


@bp.route("/production-days/<pdid>", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "DeliveryDispatcher", "Customer"])
def get_production_day(pdid):
    obj = store.production_days.get(pdid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "production day not found")
    return success(S.production_day(obj), status=200)


@bp.route("/production-days", methods=["GET"])
@require_auth(["BakeryManager", "BakeryStaff", "DeliveryDispatcher", "Customer"])
def list_production_days():
    limit, offset = parse_pagination(request.args)
    items = list(store.production_days.values())
    is_peak = request.args.get("is_peak")
    if is_peak is not None:
        want = is_peak.lower() == "true"
        items = [o for o in items if bool(o["is_peak"]) == want]
    return list_response([S.production_day(o) for o in _sorted(items)], limit, offset)


@bp.route("/production-days/<pdid>/orders", methods=["GET"])
@require_auth(["BakeryStaff", "BakeryManager", "DeliveryDispatcher"])
def list_production_day_orders(pdid):
    if store.production_days.get(pdid) is None:
        raise err(ERR_NOT_FOUND, "production day not found")
    limit, offset = parse_pagination(request.args)
    items = [o for o in store.orders.values() if o["production_day_id"] == pdid]
    return list_response([S.order(o) for o in _sorted(items)], limit, offset)


# ---- routes -------------------------------------------------------------

@bp.route("/routes", methods=["POST"])
@require_auth(["BakeryManager", "DeliveryDispatcher"])
def create_route():
    data = V.body()
    obj = {
        "route_name": V.require_str(data, "route_name"),
        "service_date": V.require_str(data, "service_date"),
        "stop_minutes": V.require_int(data, "stop_minutes", minimum=1),
    }
    store.stamp_create(obj)
    store.routes[obj["id"]] = obj
    return success(S.route(obj), status=201)


@bp.route("/routes/<rid>", methods=["GET"])
@require_auth(["BakeryManager", "DeliveryDispatcher", "Customer"])
def get_route(rid):
    obj = store.routes.get(rid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "route not found")
    return success(S.route(obj), status=200)


@bp.route("/routes", methods=["GET"])
@require_auth(["BakeryManager", "DeliveryDispatcher", "Customer"])
def list_routes():
    limit, offset = parse_pagination(request.args)
    items = list(store.routes.values())
    service_date = request.args.get("service_date")
    if service_date is not None:
        items = [o for o in items if o["service_date"] == service_date]
    return list_response([S.route(o) for o in _sorted(items)], limit, offset)


@bp.route("/routes/<rid>/reservations", methods=["GET"])
@require_auth(["DeliveryDispatcher", "BakeryManager"])
def list_route_reservations(rid):
    if store.routes.get(rid) is None:
        raise err(ERR_NOT_FOUND, "route not found")
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.reservations.values()
             if r.get("route_id") == rid and r["status"] == "COMMITTED"]
    return list_response([S.reservation(o) for o in _sorted(items)], limit, offset)


# ---- customers ----------------------------------------------------------

@bp.route("/customers", methods=["POST"])
@require_auth(["Anonymous", "BakeryManager"])
def create_customer():
    data = V.body()
    obj = {
        "email": V.require_str(data, "email"),
        "full_name": V.require_str(data, "full_name"),
        "store_credit_cents": 0,
        "lifetime_spend_cents": 0,
        "loyalty_tier": "STANDARD",
    }
    store.stamp_create(obj)
    store.customers[obj["id"]] = obj
    return success(S.customer(obj), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
@require_auth(["Customer", "BakeryManager", "BakeryStaff"])
def get_customer(cid):
    obj = store.customers.get(cid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    return success(S.customer(obj), status=200)


@bp.route("/customers/<cid>/credit-adjustments", methods=["POST"])
@require_auth(["BakeryManager"])
def adjust_credit(cid):
    obj = store.customers.get(cid)
    if obj is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    data = V.body()
    delta = V.require_int(data, "delta_cents")
    obj["store_credit_cents"] += delta
    store.touch(obj)
    return success(S.customer(obj), status=200)


# ---- test-only tooling --------------------------------------------------

@bp.route("/_clock/set", methods=["POST"])
@require_auth(["BakeryManager"])
def set_clock():
    data = V.body()
    instant = V.require_str(data, "now_iso8601")
    dt = _parse_iso(instant, "now_iso8601")
    clock.set_now(dt)
    return success({}, status=200)


@bp.route("/_overrides/mint", methods=["POST"])
@require_auth(["BakeryManager"])
def mint_override():
    data = V.body()
    scope = V.require_str(data, "scope")
    token = "ovr_" + store.new_id().replace("-", "")
    store.override_tokens[token] = scope
    return success({"token": token, "scope": scope}, status=201)
