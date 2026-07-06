"""Flask entry point + route registration for the Office-Pantry Subscription API."""
import os
from decimal import Decimal

from flask import Flask, request

from db import STORE, new_id, parse_iso, iso_from_datetime, add_days, add_hours
from errors import ApiError
from middleware import require_auth
from response import ok, created, ok_list, error
import services as svc


app = Flask(__name__)


# =====================================================================
# Error handler
# =====================================================================
@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(_e):
    return error("ERR_ROUTE_NOT_FOUND", "Route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_e):
    return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Don't leak in prod; but include message for debugging under tests
    return error("ERR_INTERNAL", f"{type(e).__name__}: {e}", 500)


def _json_body():
    """Return the JSON body or {} for empty bodies; 400 on malformed."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return body


def _require_str(body, key):
    v = body.get(key)
    if v is None or not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {key}")
    return v


def _require_int(body, key, allow_zero=True):
    v = body.get(key)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {key}")
    return v


def _opt_int(body, key, default):
    v = body.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field: {key} must be integer")
    return v


def _opt_bool(body, key, default):
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field: {key} must be boolean")
    return v


def _opt_str(body, key, default=None):
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field: {key} must be string")
    return v


# =====================================================================
# Plans
# =====================================================================

@app.route("/plans", methods=["POST"])
def create_plan():
    require_auth(["PlatformAdmin"])
    body = _json_body()
    tier = _require_str(body, "tier")
    billing_type = _require_str(body, "billing_type")
    if billing_type not in ("PER_EMPLOYEE", "FLAT"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "billing_type must be PER_EMPLOYEE or FLAT")
    base_fee = _opt_int(body, "base_fee_cents", 0)
    per_emp_fee = _opt_int(body, "per_employee_fee_cents", 0)
    flat_fee = _opt_int(body, "flat_fee_cents", 0)
    if "volume_discount_threshold_headcount" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing volume_discount_threshold_headcount")
    vd_threshold = _require_int(body, "volume_discount_threshold_headcount")
    vd_pct_raw = body.get("volume_discount_pct", 0)
    if isinstance(vd_pct_raw, bool) or not isinstance(vd_pct_raw, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "volume_discount_pct must be number")
    if any(x < 0 for x in (base_fee, per_emp_fee, flat_fee)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "fee fields must be >= 0")
    if vd_threshold < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "volume_discount_threshold_headcount must be >= 1")
    if not (0.0 <= float(vd_pct_raw) <= 1.0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "volume_discount_pct must be in [0.0, 1.0]")
    # Uniqueness of tier across active plans (all plans; no deletion path)
    for p in STORE.plans.values():
        if p["tier"] == tier:
            raise ApiError("ERR_INVALID_REQUEST", 400, "plan tier already exists")
    pid = new_id()
    plan = {
        "id": pid,
        "tier": tier,
        "billing_type": billing_type,
        "base_fee_cents": int(base_fee),
        "per_employee_fee_cents": int(per_emp_fee),
        "flat_fee_cents": int(flat_fee),
        "volume_discount_threshold_headcount": int(vd_threshold),
        "volume_discount_pct": float(vd_pct_raw),
    }
    svc._stamp_create(plan)
    STORE.plans[pid] = plan
    return created(svc.serialize_plan(plan))


@app.route("/plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_auth(["PlatformAdmin", "ClientAdmin"])
    plan = svc.get_plan_or_404(pid)
    return ok(svc.serialize_plan(plan))


@app.route("/plans", methods=["GET"])
def list_plans():
    require_auth(["PlatformAdmin", "ClientAdmin"])
    limit, offset = svc.pagination_params(request.args)
    items = svc.sort_by_created_at_asc(list(STORE.plans.values()))
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_plan(p) for p in sliced], limit, offset, total)


# =====================================================================
# Products
# =====================================================================

@app.route("/products", methods=["POST"])
def create_product():
    require_auth(["PlatformAdmin"])
    body = _json_body()
    sku = _require_str(body, "sku")
    name = _require_str(body, "name")
    category = _require_str(body, "category")
    if category not in ("SNACK", "BEVERAGE", "MEAL", "CANDY"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid category")
    dietary_flags = body.get("dietary_flags", [])
    if dietary_flags is None:
        dietary_flags = []
    if not isinstance(dietary_flags, list) or not all(isinstance(x, str) for x in dietary_flags):
        raise ApiError("ERR_INVALID_REQUEST", 400, "dietary_flags must be array of strings")
    unit_cost = _require_int(body, "unit_cost_cents")
    if unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "unit_cost_cents must be >= 0")
    requires_ref = _opt_bool(body, "requires_refrigeration", False)
    for p in STORE.products.values():
        if p["sku"] == sku:
            raise ApiError("ERR_INVALID_REQUEST", 400, "sku already exists")
    pid = new_id()
    prod = {
        "id": pid,
        "sku": sku,
        "name": name,
        "category": category,
        "dietary_flags": list(dietary_flags),
        "unit_cost_cents": int(unit_cost),
        "requires_refrigeration": bool(requires_ref),
    }
    svc._stamp_create(prod)
    STORE.products[pid] = prod
    return created(svc.serialize_product(prod))


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    p = svc.get_product_or_404(pid)
    return ok(svc.serialize_product(p))


@app.route("/products", methods=["GET"])
def list_products():
    require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    limit, offset = svc.pagination_params(request.args)
    cat = request.args.get("category")
    items = list(STORE.products.values())
    if cat:
        items = [p for p in items if p["category"] == cat]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_product(p) for p in sliced], limit, offset, total)


# =====================================================================
# Clients
# =====================================================================

@app.route("/clients", methods=["POST"])
def create_client():
    require_auth(["PlatformAdmin"])
    body = _json_body()
    name = _require_str(body, "name")
    headcount = _require_int(body, "headcount")
    if headcount < 1:
        raise ApiError("ERR_INVALID_HEADCOUNT", 422, "headcount must be >= 1")
    cid = new_id()
    c = {
        "id": cid,
        "name": name,
        "headcount": int(headcount),
        "credit_balance_cents": 0,
        "active_subscription_id": None,
    }
    svc._stamp_create(c)
    STORE.clients[cid] = c
    return created(svc.serialize_client(c))


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    return ok(svc.serialize_client(c))


@app.route("/clients/<cid>/headcount", methods=["PATCH"])
def patch_client_headcount(cid):
    require_auth(["PlatformAdmin"])
    c = svc.get_client_or_404(cid)
    body = _json_body()
    if "headcount" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing headcount")
    hc = _require_int(body, "headcount")
    if hc < 1:
        raise ApiError("ERR_INVALID_HEADCOUNT", 422, "headcount must be >= 1")
    c["headcount"] = int(hc)
    svc._touch(c)
    return ok(svc.serialize_client(c))


# =====================================================================
# Locations
# =====================================================================

@app.route("/clients/<cid>/locations", methods=["POST"])
def create_location(cid):
    role, uid = require_auth(["ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    body = _json_body()
    name = _require_str(body, "name")
    kind = _require_str(body, "kind")
    if kind not in ("PANTRY", "FRIDGE", "MICRO_MARKET"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid kind")
    cap = _require_int(body, "capacity_units")
    if cap < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity_units must be >= 1")
    svc_fee = _opt_int(body, "service_fee_bps", 0)
    if not (0 <= svc_fee <= 10000):
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_fee_bps must be 0..10000")
    lid = new_id()
    loc = {
        "id": lid,
        "client_id": cid,
        "name": name,
        "kind": kind,
        "capacity_units": int(cap),
        "service_fee_bps": int(svc_fee),
    }
    svc._stamp_create(loc)
    STORE.locations[lid] = loc
    return created(svc.serialize_location(loc))


@app.route("/clients/<cid>/locations", methods=["GET"])
def list_client_locations(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    limit, offset = svc.pagination_params(request.args)
    items = [l for l in STORE.locations.values() if l["client_id"] == cid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_location(l) for l in sliced], limit, offset, total)


@app.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    l = svc.get_location_or_404(lid)
    svc.check_location_ownership(role, uid, l)
    return ok(svc.serialize_location(l))


@app.route("/locations", methods=["GET"])
def list_locations():
    require_auth(["PlatformAdmin"])
    limit, offset = svc.pagination_params(request.args)
    cid = request.args.get("client_id")
    items = list(STORE.locations.values())
    if cid:
        items = [l for l in items if l["client_id"] == cid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_location(l) for l in sliced], limit, offset, total)


# =====================================================================
# Preferences
# =====================================================================

@app.route("/clients/<cid>/preferences", methods=["POST"])
def create_preference(cid):
    role, uid = require_auth(["ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    body = _json_body()
    flag = _require_str(body, "dietary_flag")
    # Uniqueness (client_id, dietary_flag)
    for p in STORE.preferences.values():
        if p["client_id"] == cid and p["dietary_flag"] == flag:
            raise ApiError("ERR_INVALID_REQUEST", 400, "preference already exists")
    pid = new_id()
    pref = {
        "id": pid,
        "client_id": cid,
        "dietary_flag": flag,
    }
    svc._stamp_create(pref, common=False)
    STORE.preferences[pid] = pref
    return created(svc.serialize_preference(pref))


@app.route("/clients/<cid>/preferences", methods=["GET"])
def list_preferences(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    limit, offset = svc.pagination_params(request.args)
    items = [p for p in STORE.preferences.values() if p["client_id"] == cid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_preference(p) for p in sliced], limit, offset, total)


# =====================================================================
# Par-levels
# =====================================================================

@app.route("/locations/<lid>/par-levels", methods=["POST"])
def create_par_level(lid):
    role, uid = require_auth(["LocationManager"])
    loc = svc.get_location_or_404(lid)
    # Body: product_id, par_units
    body = _json_body()
    product_id = _require_str(body, "product_id")
    par_units = _require_int(body, "par_units")
    if par_units < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "par_units must be >= 0")
    product = svc.get_product_or_404(product_id)
    # Ownership: LocationManager only owns their own location
    svc.check_location_ownership(role, uid, loc)
    # Uniqueness (location_id, product_id)
    for pl in STORE.par_levels.values():
        if pl["location_id"] == lid and pl["product_id"] == product_id:
            raise ApiError("ERR_INVALID_REQUEST", 400, "par level already exists for this (location, product)")
    # Dietary check
    client_id = loc["client_id"]
    blocked = svc.client_preference_flags(client_id)
    if any(f in blocked for f in product["dietary_flags"]):
        raise ApiError("ERR_DIETARY_PREFERENCE_VIOLATION", 422,
                       "product's dietary flag is blocked by client preferences")
    # Refrigeration
    if product["requires_refrigeration"] and loc["kind"] == "PANTRY":
        raise ApiError("ERR_REFRIGERATION_MISMATCH", 422,
                       "refrigerated product cannot be placed at PANTRY")
    # Capacity
    current_sum = sum(pl["par_units"] for pl in STORE.par_levels.values() if pl["location_id"] == lid)
    if current_sum + par_units > loc["capacity_units"]:
        raise ApiError("ERR_LOCATION_CAPACITY_EXCEEDED", 422,
                       "par_units sum would exceed location capacity")
    plid = new_id()
    pl = {
        "id": plid,
        "location_id": lid,
        "product_id": product_id,
        "par_units": int(par_units),
    }
    svc._stamp_create(pl)
    STORE.par_levels[plid] = pl
    return created(svc.serialize_par_level(pl))


@app.route("/locations/<lid>/par-levels", methods=["GET"])
def list_par_levels_for_location(lid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    loc = svc.get_location_or_404(lid)
    svc.check_location_ownership(role, uid, loc)
    limit, offset = svc.pagination_params(request.args)
    items = [pl for pl in STORE.par_levels.values() if pl["location_id"] == lid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_par_level(pl) for pl in sliced], limit, offset, total)


@app.route("/par-levels/<plid>", methods=["GET"])
def get_par_level(plid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    pl = STORE.par_levels.get(plid)
    if not pl:
        raise ApiError("ERR_LOCATION_NOT_FOUND", 404, "ParLevel not found")
    loc = STORE.locations.get(pl["location_id"])
    if loc:
        svc.check_location_ownership(role, uid, loc)
    return ok(svc.serialize_par_level(pl))


@app.route("/par-levels", methods=["GET"])
def list_par_levels():
    require_auth(["PlatformAdmin"])
    limit, offset = svc.pagination_params(request.args)
    lid_f = request.args.get("location_id")
    pid_f = request.args.get("product_id")
    items = list(STORE.par_levels.values())
    if lid_f:
        items = [pl for pl in items if pl["location_id"] == lid_f]
    if pid_f:
        items = [pl for pl in items if pl["product_id"] == pid_f]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_par_level(pl) for pl in sliced], limit, offset, total)


# =====================================================================
# Subscriptions
# =====================================================================

@app.route("/clients/<cid>/subscriptions", methods=["POST"])
def create_subscription(cid):
    role, uid = require_auth(["ClientAdmin"])
    c = svc.get_client_or_404(cid)
    body = _json_body()
    plan_id = _require_str(body, "plan_id")
    if "expected_client_version" not in body:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing expected_client_version")
    expected = body["expected_client_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_client_version must be integer")
    plan = svc.get_plan_or_404(plan_id)
    # Ownership
    svc.check_client_ownership(role, uid, c)
    # Priority 20: at most one non-terminal subscription per client
    for s in STORE.subscriptions.values():
        if s["client_id"] == cid and s["status"] != "CANCELLED":
            raise ApiError("ERR_SUBSCRIPTION_ALREADY_ACTIVE", 409,
                           "client already has a non-terminal subscription")
    # Priority 22: headcount floor
    if int(c["headcount"]) < 1:
        raise ApiError("ERR_INVALID_HEADCOUNT", 422, "client headcount must be >= 1")
    # Priority 23: OCC on client version
    if int(expected) != int(c["version"]):
        raise ApiError("ERR_STALE_CLIENT_VERSION", 412,
                       f"expected_client_version {expected} != current {c['version']}")
    sid = new_id()
    sub = {
        "id": sid,
        "client_id": cid,
        "plan_id": plan_id,
        "plan_version_snapshot": int(plan["version"]),
        "status": "DRAFT",
        "paused_at": None,
        "cancelled_at": None,
        "cumulative_active_days": 0,
        "_last_active_entry": None,  # internal: tracks most-recent ACTIVE-entry timestamp
    }
    svc._stamp_create(sub)
    STORE.subscriptions[sid] = sub
    c["active_subscription_id"] = sid
    svc._touch(c)
    return created(svc.serialize_subscription(sub))


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    sub = svc.get_subscription_or_404(sid)
    svc.check_subscription_ownership(role, uid, sub)
    return ok(svc.serialize_subscription(sub))


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    limit, offset = svc.pagination_params(request.args)
    cid = request.args.get("client_id")
    pid = request.args.get("plan_id")
    items = list(STORE.subscriptions.values())
    if role == "ClientAdmin":
        items = [s for s in items if s["client_id"] == uid]
    if cid:
        items = [s for s in items if s["client_id"] == cid]
    if pid:
        items = [s for s in items if s["plan_id"] == pid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_subscription(s) for s in sliced], limit, offset, total)


@app.route("/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    require_auth(["PlatformAdmin"])
    sub = svc.get_subscription_or_404(sid)
    if sub["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription must be DRAFT to activate")
    # At least one Location for the client
    locs = [l for l in STORE.locations.values() if l["client_id"] == sub["client_id"]]
    if not locs:
        raise ApiError("ERR_INVALID_STATE", 409, "Client must have at least one Location")
    loc_ids = {l["id"] for l in locs}
    par_exists = any(pl["location_id"] in loc_ids for pl in STORE.par_levels.values())
    if not par_exists:
        raise ApiError("ERR_INVALID_STATE", 409, "At least one ParLevel must exist across the client's Locations")
    # Open first rotation cycle
    now = STORE.now()
    eff_from_iso = iso_from_datetime(now)
    eff_to_iso = iso_from_datetime(add_days(now, 30))
    if svc.rotation_cycle_overlaps_existing(sid, eff_from_iso, eff_to_iso):
        raise ApiError("ERR_ROTATION_CYCLE_OVERLAP", 422,
                       "New rotation cycle overlaps existing cycle")
    rc_id = new_id()
    rc = {
        "id": rc_id,
        "subscription_id": sid,
        "cycle_index": 1,
        "effective_from": eff_from_iso,
        "effective_to": eff_to_iso,
        "status": "OPEN",
    }
    svc._stamp_create(rc)
    STORE.rotation_cycles[rc_id] = rc
    sub["status"] = "ACTIVE"
    sub["_last_active_entry"] = eff_from_iso
    svc._touch(sub)
    return ok(svc.serialize_subscription(sub))


@app.route("/subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    role, uid = require_auth(["ClientAdmin"])
    sub = svc.get_subscription_or_404(sid)
    svc.check_subscription_ownership(role, uid, sub)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription must be ACTIVE to pause")
    _pause_or_cancel_from_active(sub, target_status="PAUSED")
    return ok(svc.serialize_subscription(sub))


def _pause_or_cancel_from_active(sub, target_status):
    now = STORE.now()
    now_iso = iso_from_datetime(now)
    # cumulative_active_days increment (elapsed since most recent ACTIVE entry)
    last_active = sub.get("_last_active_entry")
    if last_active:
        dt_last = parse_iso(last_active)
        elapsed_days = int((now - dt_last).total_seconds() // 86400)
        if elapsed_days > 0:
            sub["cumulative_active_days"] = int(sub["cumulative_active_days"]) + elapsed_days
    sub["status"] = target_status
    if target_status == "PAUSED":
        sub["paused_at"] = now_iso
    else:  # CANCELLED
        sub["cancelled_at"] = now_iso
        client = STORE.clients.get(sub["client_id"])
        if client:
            client["active_subscription_id"] = None
            svc._touch(client)
    svc._touch(sub)
    # Cascade: invalidate the currently-OPEN rotation cycle
    open_rc = None
    for rc in STORE.rotation_cycles.values():
        if rc["subscription_id"] == sub["id"] and rc["status"] == "OPEN":
            open_rc = rc
            break
    if open_rc:
        svc.invalidate_rotation_cycle(open_rc)


@app.route("/subscriptions/<sid>/resume", methods=["POST"])
def resume_subscription(sid):
    role, uid = require_auth(["ClientAdmin"])
    sub = svc.get_subscription_or_404(sid)
    svc.check_subscription_ownership(role, uid, sub)
    if sub["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription must be PAUSED to resume")
    now = STORE.now()
    eff_from_iso = iso_from_datetime(now)
    eff_to_iso = iso_from_datetime(add_days(now, 30))
    if svc.rotation_cycle_overlaps_existing(sid, eff_from_iso, eff_to_iso):
        raise ApiError("ERR_ROTATION_CYCLE_OVERLAP", 422,
                       "New rotation cycle overlaps existing cycle")
    # Determine prev cycle_index
    prev_max = max(
        (rc["cycle_index"] for rc in STORE.rotation_cycles.values() if rc["subscription_id"] == sid),
        default=0,
    )
    rc_id = new_id()
    rc = {
        "id": rc_id,
        "subscription_id": sid,
        "cycle_index": prev_max + 1,
        "effective_from": eff_from_iso,
        "effective_to": eff_to_iso,
        "status": "OPEN",
    }
    svc._stamp_create(rc)
    STORE.rotation_cycles[rc_id] = rc
    sub["status"] = "ACTIVE"
    sub["paused_at"] = None
    sub["_last_active_entry"] = eff_from_iso
    svc._touch(sub)
    return ok(svc.serialize_subscription(sub))


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    role, uid = require_auth(["ClientAdmin"])
    sub = svc.get_subscription_or_404(sid)
    svc.check_subscription_ownership(role, uid, sub)
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription must be ACTIVE or PAUSED to cancel")
    if sub["status"] == "ACTIVE":
        _pause_or_cancel_from_active(sub, target_status="CANCELLED")
    else:
        # PAUSED -> CANCELLED: no cascade
        now = STORE.now()
        sub["status"] = "CANCELLED"
        sub["cancelled_at"] = iso_from_datetime(now)
        client = STORE.clients.get(sub["client_id"])
        if client:
            client["active_subscription_id"] = None
            svc._touch(client)
        svc._touch(sub)
    return ok(svc.serialize_subscription(sub))


@app.route("/subscriptions/<sid>/rotation-cycles", methods=["GET"])
def list_subscription_rotation_cycles(sid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    sub = svc.get_subscription_or_404(sid)
    svc.check_subscription_ownership(role, uid, sub)
    limit, offset = svc.pagination_params(request.args)
    items = [rc for rc in STORE.rotation_cycles.values() if rc["subscription_id"] == sid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_rotation_cycle(rc) for rc in sliced], limit, offset, total)


# =====================================================================
# Rotation cycles
# =====================================================================

@app.route("/rotation-cycles/<rid>", methods=["GET"])
def get_rotation_cycle(rid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    rc = svc.get_rotation_or_404(rid)
    svc.check_rotation_ownership(role, uid, rc)
    return ok(svc.serialize_rotation_cycle(rc))


@app.route("/rotation-cycles/<rid>/close", methods=["POST"])
def close_rotation_cycle(rid):
    require_auth(["PlatformAdmin"])
    rc = svc.get_rotation_or_404(rid)
    if rc["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "RotationCycle must be OPEN to close")
    # Every delivery under cycle must be FINALIZED or CANCELLED
    for d in STORE.deliveries.values():
        if d["rotation_cycle_id"] == rid and d["status"] not in ("FINALIZED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "All deliveries must be FINALIZED or CANCELLED to close cycle")
    # clock.now >= effective_to
    if STORE.now() < parse_iso(rc["effective_to"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Rotation cycle window has not elapsed")
    sub = STORE.subscriptions.get(rc["subscription_id"])
    if sub and sub["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Subscription CANCELLED — cycle cannot be closed")
    # Close
    rc["status"] = "CLOSED"
    svc._touch(rc)
    # Create invoice
    client = STORE.clients[sub["client_id"]]
    plan_snap = STORE.plans[sub["plan_id"]]
    sub_fee = svc.compute_subscription_fee_cents(plan_snap, int(client["headcount"]))
    consumption = svc.compute_invoice_consumption_cents(rid)
    credit_applied = min(int(client["credit_balance_cents"]), sub_fee + consumption)
    inv_id = new_id()
    inv = {
        "id": inv_id,
        "client_id": client["id"],
        "rotation_cycle_id": rid,
        "period_start": rc["effective_from"],
        "period_end": rc["effective_to"],
        "subscription_fee_cents": int(sub_fee),
        "consumption_cents": int(consumption),
        "credit_applied_cents": int(credit_applied),
        "total_cents": int(sub_fee + consumption - credit_applied),
        "payment_status": "UNPAID",
        "dispute_status": "CLEAN",
    }
    svc._stamp_create(inv)
    STORE.invoices[inv_id] = inv
    # Decrement client credit
    client["credit_balance_cents"] = int(client["credit_balance_cents"]) - int(credit_applied)
    svc._touch(client)
    return ok(svc.serialize_invoice(inv))


@app.route("/rotation-cycles/<rid>/deliveries", methods=["POST"])
def create_delivery(rid):
    require_auth(["PlatformAdmin"])
    rc = svc.get_rotation_or_404(rid)
    body = _json_body()
    location_id = _require_str(body, "location_id")
    scheduled_at_str = _require_str(body, "scheduled_at")
    loc = svc.get_location_or_404(location_id)
    # State: RotationCycle must be OPEN
    if rc["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "RotationCycle must be OPEN")
    # Delivery buffer check (24h at same location)
    try:
        sched_dt = parse_iso(scheduled_at_str)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid scheduled_at")
    for d in STORE.deliveries.values():
        if d["location_id"] == location_id and d["status"] != "CANCELLED":
            existing_dt = parse_iso(d["scheduled_at"])
            delta_hours = abs((sched_dt - existing_dt).total_seconds()) / 3600.0
            if delta_hours < 24.0:
                raise ApiError("ERR_DELIVERY_SCHEDULE_CONFLICT", 409,
                               "scheduled_at within 24h of an existing non-cancelled delivery")
    # Rotation window (delivery generated outside cycle -> overlap error)
    eff_from = parse_iso(rc["effective_from"])
    eff_to = parse_iso(rc["effective_to"])
    if not (eff_from <= sched_dt < eff_to):
        raise ApiError("ERR_ROTATION_CYCLE_OVERLAP", 422,
                       "scheduled_at outside rotation cycle window")
    # Cycle's subscription owns this location's client?
    sub = STORE.subscriptions.get(rc["subscription_id"])
    if not sub:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription not found")
    if loc["client_id"] != sub["client_id"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Location does not belong to the subscription's client")
    # Project assortment
    candidates = svc.project_assortment(loc)
    if not candidates:
        raise ApiError("ERR_EMPTY_ASSORTMENT", 422,
                       "candidate assortment is empty after filters")
    # Create delivery
    did = new_id()
    delivery = {
        "id": did,
        "location_id": location_id,
        "rotation_cycle_id": rid,
        "scheduled_at": iso_from_datetime(sched_dt),
        "dispatched_at": None,
        "delivered_at": None,
        "status": "SCHEDULED",
        "dispute_reason": None,
        "provisional_cents": 0,
        "final_cents": 0,
        "dispute_credit_cents": 0,
    }
    svc._stamp_create(delivery)
    STORE.deliveries[did] = delivery
    # Create delivery lines from candidates
    for pl in candidates:
        prod = STORE.products[pl["product_id"]]
        dl_id = new_id()
        dl = {
            "id": dl_id,
            "delivery_id": did,
            "product_id": pl["product_id"],
            "planned_units": int(pl["par_units"]),
            "actual_units": None,
            "unit_price_cents_snapshot": int(prod["unit_cost_cents"]),
            "service_fee_bps_snapshot": int(loc["service_fee_bps"]),
        }
        svc._stamp_create(dl)
        STORE.delivery_lines[dl_id] = dl
    # Bump rotation cycle version
    svc._touch(rc)
    return created(svc.serialize_delivery(delivery))


@app.route("/rotation-cycles/<rid>/deliveries", methods=["GET"])
def list_deliveries_for_cycle(rid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    rc = svc.get_rotation_or_404(rid)
    if role == "ClientAdmin":
        sub = STORE.subscriptions.get(rc["subscription_id"])
        if not sub or uid != sub["client_id"]:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin ownership check failed")
    limit, offset = svc.pagination_params(request.args)
    items = [d for d in STORE.deliveries.values() if d["rotation_cycle_id"] == rid]
    if role == "LocationManager":
        items = [d for d in items if d["location_id"] == uid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_delivery(d) for d in sliced], limit, offset, total)


# =====================================================================
# Deliveries
# =====================================================================

@app.route("/deliveries/<did>", methods=["GET"])
def get_delivery(did):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    d = svc.get_delivery_or_404(did)
    svc.check_delivery_ownership(role, uid, d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries", methods=["GET"])
def list_deliveries():
    require_auth(["PlatformAdmin"])
    limit, offset = svc.pagination_params(request.args)
    lid = request.args.get("location_id")
    rid = request.args.get("rotation_cycle_id")
    items = list(STORE.deliveries.values())
    if lid:
        items = [d for d in items if d["location_id"] == lid]
    if rid:
        items = [d for d in items if d["rotation_cycle_id"] == rid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_delivery(d) for d in sliced], limit, offset, total)


@app.route("/deliveries/<did>/dispatch", methods=["POST"])
def dispatch_delivery(did):
    require_auth(["PlatformAdmin"])
    d = svc.get_delivery_or_404(did)
    if d["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Delivery must be SCHEDULED to dispatch")
    rc = STORE.rotation_cycles[d["rotation_cycle_id"]]
    sub = STORE.subscriptions[rc["subscription_id"]]
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription must be ACTIVE to dispatch")
    if rc["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "RotationCycle must be OPEN to dispatch")
    now = STORE.now()
    if now >= add_hours(parse_iso(d["scheduled_at"]), 24):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispatch window has closed (>=24h past scheduled_at)")
    d["status"] = "EN_ROUTE"
    d["dispatched_at"] = iso_from_datetime(now)
    d["provisional_cents"] = svc.compute_provisional_cents(d)
    svc._touch(d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries/<did>/confirm", methods=["POST"])
def confirm_delivery(did):
    role, uid = require_auth(["LocationManager"])
    d = svc.get_delivery_or_404(did)
    svc.check_delivery_ownership(role, uid, d)
    if d["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Delivery must be EN_ROUTE to confirm")
    rc = STORE.rotation_cycles[d["rotation_cycle_id"]]
    sub = STORE.subscriptions[rc["subscription_id"]]
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription must be ACTIVE to confirm")
    d["status"] = "DELIVERED"
    d["delivered_at"] = STORE.now_iso()
    svc._touch(d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries/<did>/dispute", methods=["POST"])
def dispute_delivery(did):
    role, uid = require_auth(["LocationManager"])
    d = svc.get_delivery_or_404(did)
    svc.check_delivery_ownership(role, uid, d)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Delivery must be DELIVERED to dispute")
    body = _json_body()
    reason = _require_str(body, "dispute_reason")
    now = STORE.now()
    if now >= add_hours(parse_iso(d["delivered_at"]), 48):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute window has closed (>=48h past delivered_at)")
    d["status"] = "DISPUTED"
    d["dispute_reason"] = reason
    svc._touch(d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries/<did>/resolve-dispute", methods=["POST"])
def resolve_dispute_delivery(did):
    require_auth(["PlatformAdmin"])
    d = svc.get_delivery_or_404(did)
    if d["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Delivery must be DISPUTED to resolve-dispute")
    # actual_units set on every line
    lines = [dl for dl in STORE.delivery_lines.values() if dl["delivery_id"] == did]
    for dl in lines:
        if dl["actual_units"] is None:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Every DeliveryLine must have actual_units set before resolve-dispute")
    d["final_cents"] = svc.compute_final_cents(d)
    d["dispute_credit_cents"] = svc.compute_dispute_credit_cents(d)
    if d["dispute_credit_cents"] > 0:
        loc = STORE.locations[d["location_id"]]
        client = STORE.clients[loc["client_id"]]
        client["credit_balance_cents"] = int(client["credit_balance_cents"]) + int(d["dispute_credit_cents"])
        svc._touch(client)
    d["status"] = "FINALIZED"
    svc._touch(d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries/<did>/finalize", methods=["POST"])
def finalize_delivery(did):
    require_auth(["PlatformAdmin"])
    d = svc.get_delivery_or_404(did)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Delivery must be DELIVERED to auto-finalize")
    now = STORE.now()
    if now < add_hours(parse_iso(d["delivered_at"]), 48):
        raise ApiError("ERR_INVALID_STATE", 409, "Auto-finalize window not yet open (<48h since delivered_at)")
    # Actuals default to planned -> final_cents == provisional_cents
    # But use chronological with defaulted actuals.
    d["final_cents"] = svc.compute_final_cents(d)  # actual_units defaults to planned_units
    d["status"] = "FINALIZED"
    svc._touch(d)
    return ok(svc.serialize_delivery(d))


@app.route("/deliveries/<did>/lines", methods=["GET"])
def list_delivery_lines_under_delivery(did):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin", "LocationManager"])
    d = svc.get_delivery_or_404(did)
    svc.check_delivery_ownership(role, uid, d)
    limit, offset = svc.pagination_params(request.args)
    items = [dl for dl in STORE.delivery_lines.values() if dl["delivery_id"] == did]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_delivery_line(dl) for dl in sliced], limit, offset, total)


@app.route("/delivery-lines/<lid>", methods=["GET"])
def get_delivery_line(lid):
    role, uid = require_auth(["PlatformAdmin", "LocationManager"])
    dl = STORE.delivery_lines.get(lid)
    if not dl:
        raise ApiError("ERR_DELIVERY_LINE_NOT_FOUND", 404, "DeliveryLine not found")
    svc.check_delivery_line_ownership(role, uid, dl)
    return ok(svc.serialize_delivery_line(dl))


@app.route("/delivery-lines", methods=["GET"])
def list_delivery_lines():
    role, uid = require_auth(["PlatformAdmin", "LocationManager"])
    limit, offset = svc.pagination_params(request.args)
    d_f = request.args.get("delivery_id")
    p_f = request.args.get("product_id")
    items = list(STORE.delivery_lines.values())
    if role == "LocationManager":
        items = [dl for dl in items if STORE.deliveries.get(dl["delivery_id"], {}).get("location_id") == uid]
    if d_f:
        items = [dl for dl in items if dl["delivery_id"] == d_f]
    if p_f:
        items = [dl for dl in items if dl["product_id"] == p_f]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_delivery_line(dl) for dl in sliced], limit, offset, total)


@app.route("/delivery-lines/<lid>/actual", methods=["PATCH"])
def patch_delivery_line_actual(lid):
    role, uid = require_auth(["LocationManager"])
    dl = STORE.delivery_lines.get(lid)
    if not dl:
        raise ApiError("ERR_DELIVERY_LINE_NOT_FOUND", 404, "DeliveryLine not found")
    svc.check_delivery_line_ownership(role, uid, dl)
    body = _json_body()
    au = _require_int(body, "actual_units")
    if au < 0 or au > int(dl["planned_units"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"actual_units must be in [0, planned_units={dl['planned_units']}]")
    dl["actual_units"] = int(au)
    svc._touch(dl)
    return ok(svc.serialize_delivery_line(dl))


# =====================================================================
# Invoices
# =====================================================================

@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    inv = svc.get_invoice_or_404(iid)
    svc.check_invoice_ownership(role, uid, inv)
    return ok(svc.serialize_invoice(inv))


@app.route("/clients/<cid>/invoices", methods=["GET"])
def list_client_invoices(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    limit, offset = svc.pagination_params(request.args)
    items = [inv for inv in STORE.invoices.values() if inv["client_id"] == cid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_invoice(inv) for inv in sliced], limit, offset, total)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    require_auth(["PlatformAdmin"])
    limit, offset = svc.pagination_params(request.args)
    rid = request.args.get("rotation_cycle_id")
    items = list(STORE.invoices.values())
    if rid:
        items = [inv for inv in items if inv["rotation_cycle_id"] == rid]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_invoice(inv) for inv in sliced], limit, offset, total)


@app.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    role, uid = require_auth(["ClientAdmin"])
    inv = svc.get_invoice_or_404(iid)
    svc.check_invoice_ownership(role, uid, inv)
    if inv["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice payment_status must be UNPAID")
    if inv["dispute_status"] == "UNDER_DISPUTE":
        raise ApiError("ERR_INVOICE_UNDER_DISPUTE", 409, "Invoice is under dispute")
    inv["payment_status"] = "PAID"
    svc._touch(inv)
    return ok(svc.serialize_invoice(inv))


@app.route("/invoices/<iid>/resolve-dispute", methods=["POST"])
def resolve_invoice_dispute(iid):
    require_auth(["PlatformAdmin"])
    inv = svc.get_invoice_or_404(iid)
    if inv["dispute_status"] != "UNDER_DISPUTE":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice must be UNDER_DISPUTE to resolve")
    inv["dispute_status"] = "RESOLVED"
    svc._touch(inv)
    return ok(svc.serialize_invoice(inv))


# =====================================================================
# Feedback
# =====================================================================

@app.route("/clients/<cid>/feedback", methods=["POST"])
def create_feedback(cid):
    role, uid = require_auth(["ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    body = _json_body()
    product_id = _require_str(body, "product_id")
    rating = _require_int(body, "rating")
    if rating < 1 or rating > 5:
        raise ApiError("ERR_INVALID_REQUEST", 400, "rating must be 1..5")
    prod = svc.get_product_or_404(product_id)
    swap_id = body.get("swap_suggestion_product_id")
    if swap_id is not None:
        if not isinstance(swap_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "swap_suggestion_product_id must be string")
        swap_prod = svc.get_product_or_404(swap_id)
        # Dietary check on swap suggestion
        blocked = svc.client_preference_flags(cid)
        if any(f in blocked for f in swap_prod["dietary_flags"]):
            raise ApiError("ERR_DIETARY_PREFERENCE_VIOLATION", 422,
                           "swap suggestion product's dietary flag is blocked")
    comment = _opt_str(body, "comment", None)
    fid = new_id()
    fb = {
        "id": fid,
        "client_id": cid,
        "product_id": product_id,
        "rating": int(rating),
        "comment": comment,
        "swap_suggestion_product_id": swap_id,
    }
    svc._stamp_create(fb, common=False)
    STORE.feedback[fid] = fb
    return created(svc.serialize_feedback(fb))


@app.route("/clients/<cid>/feedback", methods=["GET"])
def list_client_feedback(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    limit, offset = svc.pagination_params(request.args)
    p_f = request.args.get("product_id")
    items = [f for f in STORE.feedback.values() if f["client_id"] == cid]
    if p_f:
        items = [f for f in items if f["product_id"] == p_f]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_feedback(f) for f in sliced], limit, offset, total)


@app.route("/feedback/<fid>", methods=["GET"])
def get_feedback(fid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    f = STORE.feedback.get(fid)
    if not f:
        raise ApiError("ERR_FEEDBACK_NOT_FOUND", 404, "Feedback not found")
    if role == "ClientAdmin" and uid != f["client_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "ClientAdmin does not own this feedback")
    return ok(svc.serialize_feedback(f))


@app.route("/feedback", methods=["GET"])
def list_feedback():
    require_auth(["PlatformAdmin"])
    limit, offset = svc.pagination_params(request.args)
    cid = request.args.get("client_id")
    pid = request.args.get("product_id")
    ssp = request.args.get("swap_suggestion_product_id")
    items = list(STORE.feedback.values())
    if cid:
        items = [f for f in items if f["client_id"] == cid]
    if pid:
        items = [f for f in items if f["product_id"] == pid]
    if ssp:
        items = [f for f in items if f["swap_suggestion_product_id"] == ssp]
    items = svc.sort_by_created_at_asc(items)
    sliced, total = svc.paginate(items, limit, offset)
    return ok_list([svc.serialize_feedback(f) for f in sliced], limit, offset, total)


@app.route("/clients/<cid>/satisfaction", methods=["GET"])
def client_satisfaction(cid):
    role, uid = require_auth(["PlatformAdmin", "ClientAdmin"])
    c = svc.get_client_or_404(cid)
    svc.check_client_ownership(role, uid, c)
    variant = request.args.get("variant", "authoritative")
    if variant not in ("authoritative", "provisional"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid variant")
    all_feedback = [f for f in STORE.feedback.values() if f["client_id"] == cid]
    if variant == "authoritative":
        client_locs = {l["id"] for l in STORE.locations.values() if l["client_id"] == cid}
        stocked_products = {
            pl["product_id"] for pl in STORE.par_levels.values() if pl["location_id"] in client_locs
        }
        filtered = [f for f in all_feedback if f["product_id"] in stocked_products]
    else:
        filtered = all_feedback

    if not filtered:
        score_val = svc.round_half_up_2dp(Decimal("3.00"))
    else:
        num = Decimal(0)
        den = Decimal(0)
        for f in filtered:
            w = Decimal(2) if f["swap_suggestion_product_id"] is not None else Decimal(1)
            num += Decimal(f["rating"]) * w
            den += w
        score_val = svc.round_half_up_2dp(num / den)
    return ok({
        "client_id": cid,
        "variant": variant,
        "score": float(score_val),
        "feedback_considered": len(filtered),
    })


# =====================================================================
# Test-driving endpoints
# =====================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])
    body = _json_body()
    iso = _require_str(body, "to_iso8601")
    try:
        STORE.set_clock(iso)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    return ok({})


@app.route("/_system/advance-invoice-default", methods=["POST"])
def advance_invoice_default():
    require_auth(["PlatformAdmin"])
    now = STORE.now()
    for inv in STORE.invoices.values():
        if inv["payment_status"] != "UNPAID":
            continue
        period_end = parse_iso(inv["period_end"])
        if now >= add_days(period_end, 30):
            inv["payment_status"] = "DEFAULT"
            svc._touch(inv)
    return ok({})


# =====================================================================
# Entrypoint
# =====================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
