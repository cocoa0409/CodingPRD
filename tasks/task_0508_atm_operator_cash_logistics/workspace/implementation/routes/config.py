"""Config / provisioning routes: site-merchants, vaults, routes, locations."""
from flask import Blueprint, request

import lookups
import serialize
import validate
from constants import COMMISSION_BASES, JURISDICTIONS
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------- #
# Site merchants
# --------------------------------------------------------------------------- #
@bp.route("/site-merchants", methods=["POST"])
def create_site_merchant():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    legal_name = validate.require_str(body, "legal_name")
    pct = validate.require_int(body, "commission_pct_bps")
    flat = validate.require_int(body, "commission_flat_per_wd_cents")
    ceiling = validate.require_int(body, "commission_monthly_ceiling_cents")
    basis = validate.optional_enum(body, "commission_basis", COMMISSION_BASES, "GREATER_OF")
    if pct < 0 or pct > 10000:
        raise err("ERR_INVALID_REQUEST", "commission_pct_bps must be in 0..10000.")
    m = {
        "legal_name": legal_name,
        "commission_pct_bps": pct,
        "commission_flat_per_wd_cents": flat,
        "commission_monthly_ceiling_cents": ceiling,
        "commission_basis": basis,
        "payout_status": "ACTIVE",
    }
    store.stamp_new(m)
    store.site_merchants[m["id"]] = m
    return ok_object(store.clock, serialize.site_merchant(m), 201)


@bp.route("/site-merchants/<sid>", methods=["GET"])
def get_site_merchant(sid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    m = lookups.site_merchant(store, sid)
    return ok_object(store.clock, serialize.site_merchant(m))


@bp.route("/site-merchants/<sid>/suspend", methods=["POST"])
def suspend_site_merchant(sid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    m = lookups.site_merchant(store, sid)
    m["payout_status"] = "SUSPENDED"
    store.touch(m)
    return ok_object(store.clock, serialize.site_merchant(m))


# --------------------------------------------------------------------------- #
# Vaults
# --------------------------------------------------------------------------- #
@bp.route("/vaults", methods=["POST"])
def create_vault():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    name = validate.require_str(body, "name")
    provisioned = validate.require_int(body, "provisioned_cents")
    v = {"name": name, "provisioned_cents": provisioned}
    store.stamp_new(v)
    store.vaults[v["id"]] = v
    return ok_object(store.clock, serialize.vault(store, v), 201)


@bp.route("/vaults/<vid>", methods=["GET"])
def get_vault(vid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController"})
    v = lookups.vault(store, vid)
    return ok_object(store.clock, serialize.vault(store, v))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@bp.route("/routes", methods=["POST"])
def create_route():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    carrier = validate.require_str(body, "carrier_name")
    vault_id = validate.require_str(body, "vault_id")
    lookups.vault(store, vault_id)  # body FK existence
    r = {"carrier_name": carrier, "vault_id": vault_id, "status": "ACTIVE"}
    store.stamp_new(r)
    store.routes[r["id"]] = r
    return ok_object(store.clock, serialize.route(r), 201)


@bp.route("/routes/<rid>/pause", methods=["POST"])
def pause_route(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController"})
    r = lookups.route(store, rid)
    r["status"] = "PAUSED"
    store.touch(r)
    return ok_object(store.clock, serialize.route(r))


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController"})
    r = lookups.route(store, rid)
    return ok_object(store.clock, serialize.route(r))


@bp.route("/routes", methods=["GET"])
def list_routes():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController"})
    limit, offset = validate.parse_pagination(request.args)
    vault_id = request.args.get("vault_id")
    items = store.sorted_values(store.routes)
    if vault_id is not None:
        items = [r for r in items if r["vault_id"] == vault_id]
    page, total = validate.paginate([serialize.route(r) for r in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
@bp.route("/locations", methods=["POST"])
def create_location():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    name = validate.require_str(body, "name")
    jurisdiction = validate.require_enum(body, "jurisdiction_code", JURISDICTIONS)
    site_merchant_id = validate.require_str(body, "site_merchant_id")
    route_id = validate.require_str(body, "route_id")
    address = validate.require_str(body, "address")
    lookups.site_merchant(store, site_merchant_id)
    lookups.route(store, route_id)
    loc = {
        "name": name,
        "jurisdiction_code": jurisdiction,
        "site_merchant_id": site_merchant_id,
        "route_id": route_id,
        "address": address,
    }
    store.stamp_new(loc)
    store.locations[loc["id"]] = loc
    return ok_object(store.clock, serialize.location(loc), 201)


@bp.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    loc = lookups.location(store, lid)
    return ok_object(store.clock, serialize.location(loc))


@bp.route("/locations", methods=["GET"])
def list_locations():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SettlementOfficer"})
    limit, offset = validate.parse_pagination(request.args)
    site_merchant_id = request.args.get("site_merchant_id")
    route_id = request.args.get("route_id")
    items = store.sorted_values(store.locations)
    if site_merchant_id is not None:
        items = [l for l in items if l["site_merchant_id"] == site_merchant_id]
    if route_id is not None:
        items = [l for l in items if l["route_id"] == route_id]
    page, total = validate.paginate([serialize.location(l) for l in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)
