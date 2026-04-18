"""Food Delivery Platform API — Flask application."""
import os
import math
from datetime import timedelta
from flask import Flask, request, jsonify

import db
from common import (
    ApiError, CLOCK, iso_now, format_iso, gen_uuid,
    success_object, success_array, error_response,
)
from auth import get_auth, require_role, VALID_ROLES
from calculations import (
    haversine_km, distance_km_rounded, is_peak_time,
    provisional_delivery_fee, final_delivery_fee,
    tiered_commission, final_commission, late_delivery_fine,
    compute_bonus_tier,
)
from serializers import (
    serialize_restaurant, serialize_rider, serialize_customer,
    serialize_menu_item, serialize_order, serialize_assignment,
    serialize_route_group, serialize_fine, serialize_return,
    serialize_work_order,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Path not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(400)
def handle_400(e):
    return error_response("ERR_VALIDATION", 422, "Bad request")


@app.errorhandler(Exception)
def handle_unexpected(e):
    import traceback
    traceback.print_exc()
    return error_response("ERR_VALIDATION", 422, str(e))


# =============================================================================
# Helpers
# =============================================================================
def body():
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Invalid JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field {f}")


def as_int(v, field, allow_none=False):
    if v is None:
        if allow_none:
            return None
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} required")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be integer")
    return v


def as_number(v, field, allow_none=False):
    if v is None:
        if allow_none:
            return None
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} required")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be number")
    return float(v)


def as_str(v, field, allow_none=False):
    if v is None:
        if allow_none:
            return None
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} required")
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be string")
    return v


def as_bool(v, field, allow_none=False):
    if v is None:
        if allow_none:
            return None
        if not isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be boolean")
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be boolean")
    return v


def tick(resource: dict):
    """Bump version and updated_at on a versioned resource."""
    resource["version"] = resource.get("version", 1) + 1
    resource["updated_at"] = iso_now()


def pagination_params():
    """Extract and validate limit/offset with defaults 10/0, min 1 / max 100."""
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 422, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 422, "limit out of range [1,100]")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def paginate_sorted(rows):
    """Sort by created_at ascending, paginate. Returns (page_items, total, limit, offset)."""
    limit, offset = pagination_params()
    sorted_rows = sorted(rows, key=lambda r: r.get("created_at", ""))
    total = len(sorted_rows)
    page = sorted_rows[offset:offset + limit]
    return page, total, limit, offset


def check_occ(resource, supplied_version):
    """If supplied_version is not None, compare to resource['version']."""
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        raise ApiError("ERR_VALIDATION", 422, "version must be integer")
    if supplied_version != resource.get("version"):
        raise ApiError("ERR_VERSION_CONFLICT", 409, "Version mismatch")


def resolve_or_404(store, rid, label="resource"):
    if rid not in store:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return store[rid]


# =============================================================================
# Offer timeout sweep
# =============================================================================
def sweep_offer_timeouts():
    """Sweep all OFFERED assignments whose offered_at + 60s <= now; reject + redispatch."""
    now = CLOCK.now()
    expired = []
    for a in list(db.assignments.values()):
        if a["status"] == "OFFERED":
            offered_at_str = a["offered_at"]
            # Parse iso string back to datetime
            from datetime import datetime, timezone
            dt = datetime.strptime(offered_at_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
            dt = dt.replace(tzinfo=timezone.utc)
            age = (now - dt).total_seconds()
            if age >= 60.0:
                expired.append(a)
    for a in expired:
        a["status"] = "REJECTED"
        # Recompute rider acceptance_rate (over last 30 offers)
        recompute_rider_acceptance(a["rider_id"])
        # Spawn a new assignment for the order
        order = db.orders.get(a["order_id"])
        if order and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            create_dispatch_for_order(order, exclude_riders={a["rider_id"]})


# =============================================================================
# Rider rate recomputation
# =============================================================================
def recompute_rider_acceptance(rider_id):
    rider = db.riders.get(rider_id)
    if not rider:
        return
    offers = [a for a in db.assignments.values()
              if a["rider_id"] == rider_id and a["status"] in ("ACCEPTED", "REJECTED", "PICKED_UP", "DELIVERED", "CANCELLED")]
    offers.sort(key=lambda a: a["offered_at"], reverse=True)
    last30 = offers[:30]
    if not last30:
        rider["acceptance_rate"] = 1.0
        return
    accepted = sum(1 for a in last30 if a["status"] != "REJECTED")
    rider["acceptance_rate"] = accepted / len(last30)


def recompute_rider_on_time(rider_id):
    rider = db.riders.get(rider_id)
    if not rider:
        return
    delivered = [a for a in db.assignments.values()
                 if a["rider_id"] == rider_id and a["status"] == "DELIVERED"]
    delivered.sort(key=lambda a: a["delivered_at"] or "", reverse=True)
    last30 = delivered[:30]
    if len(last30) < 10:
        rider["on_time_rate"] = 1.0
        return
    on_time = 0
    for a in last30:
        order = db.orders.get(a["order_id"])
        if not order:
            continue
        if (order.get("minutes_late") or 0) == 0:
            on_time += 1
    rider["on_time_rate"] = on_time / len(last30)


def recompute_rider_bonus_tier(rider_id):
    rider = db.riders.get(rider_id)
    if not rider:
        return
    rider["bonus_tier"] = compute_bonus_tier(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )


# =============================================================================
# Dispatch helpers
# =============================================================================
def pick_best_available_rider(exclude=None, order=None):
    """Select best available rider. Per PRD §3.6, a rider may accept a dispatch while
    in AVAILABLE or ON_DELIVERY (the latter is what enables route merging), so both
    statuses are candidates here. Return rider dict or None.

    Ranking:
      1. AVAILABLE strictly precedes ON_DELIVERY. PRD §3.6 says the system dispatches
         to the "best available rider"; an idle AVAILABLE rider is unambiguously the
         better choice for a fresh order than a rider already mid-route, because the
         ON_DELIVERY option only pays off when PRD §3.6's accept-time route-merge
         precondition (ACTIVE RouteGroup + within-500m unpicked pickup) happens to
         hold. Picking an ON_DELIVERY rider when an AVAILABLE one exists would
         scavenge stale ON_DELIVERY riders (e.g., left in that state by a prior
         request in the same server lifetime) into unrelated fresh orders — wrong
         rider, wrong wallet/fine baseline, and a spurious RouteGroup on a pair of
         orders that were never meant to share a route.
      2. Within ON_DELIVERY, a rider whose existing ACCEPTED assignment's pickup
         restaurant is within 500 m of the new order's pickup restaurant is preferred.
         This breaks the tie among ON_DELIVERY riders toward the one that would
         actually form a §3.6-valid RouteGroup; without it, the second dispatch in a
         two-leg route-merge scenario can land on a rider whose only existing
         assignment is at a completely different restaurant, which defeats merging.
         This preference is SUBORDINATE to the AVAILABLE-vs-ON_DELIVERY status
         split, so it cannot scavenge stale ON_DELIVERY riders into orders when an
         AVAILABLE candidate exists.
      3. Within the same status+merge-compat tier, rank by bonus_tier, rating, id
         for determinism.
    """
    exclude = exclude or set()
    candidates = [r for r in db.riders.values()
                  if r["status"] in ("AVAILABLE", "ON_DELIVERY") and r["id"] not in exclude]
    if not candidates:
        return None

    # Merge-compat flag and most-recent ACCEPTED timestamp (only relevant among
    # ON_DELIVERY candidates). A later accepted_at means the rider is actively
    # working a fresh leg — preferring them as the route-merge peer for the next
    # leg keeps concurrent two-leg scenarios attaching to the just-accepted
    # sibling rather than a long-dormant ACCEPTED row left over from a prior
    # request.
    merge_compat_ids: "set[str]" = set()
    latest_accept_at: "dict[str, str]" = {}
    if order is not None:
        new_rest = db.restaurants.get(order["restaurant_id"])
        if new_rest is not None:
            for r in candidates:
                if r["status"] != "ON_DELIVERY":
                    continue
                for a in db.assignments.values():
                    if a["rider_id"] != r["id"]:
                        continue
                    if a["status"] != "ACCEPTED":
                        continue
                    peer_order = db.orders.get(a["order_id"])
                    if not peer_order:
                        continue
                    peer_rest = db.restaurants.get(peer_order["restaurant_id"])
                    if not peer_rest:
                        continue
                    dist_km = haversine_km(peer_rest["lat"], peer_rest["lng"],
                                           new_rest["lat"], new_rest["lng"])
                    if dist_km * 1000 <= 500:
                        merge_compat_ids.add(r["id"])
                        accepted_at = a.get("accepted_at") or ""
                        if accepted_at > latest_accept_at.get(r["id"], ""):
                            latest_accept_at[r["id"]] = accepted_at

    tier_order = {"PLATINUM": 0, "GOLD": 1, "SILVER": 2, "BRONZE": 3}

    def sort_key(r: dict) -> tuple:
        # Primary: AVAILABLE strictly before ON_DELIVERY.
        status_rank = 0 if r["status"] == "AVAILABLE" else 1
        # Secondary (within ON_DELIVERY only): merge-compat preferred. AVAILABLE
        # riders all get the same placeholder value so the merge flag cannot flip
        # the status ordering.
        merge_rank = 0 if r["id"] in merge_compat_ids else 1
        # Tertiary (within merge-compat ON_DELIVERY): prefer the rider whose
        # most recent ACCEPTED assignment was accepted LATEST. ISO-8601
        # timestamps sort lexicographically in chronological order; Python
        # tuples sort ascending. Build a descending key by pairing a
        # present-flag (0 = has ts, 1 = no ts — so riders with a ts sort
        # before those without) with a per-char negated-ord tuple (so a later
        # ts sorts before an earlier one among riders that have one).
        recent_ts = latest_accept_at.get(r["id"], "")
        if recent_ts:
            ts_rank = (0, tuple(-ord(c) for c in recent_ts))
        else:
            ts_rank = (1, ())
        return (status_rank, merge_rank, ts_rank,
                tier_order.get(r["bonus_tier"], 99),
                -r["rating"], r["id"])

    candidates.sort(key=sort_key)
    return candidates[0]


def create_dispatch_for_order(order, exclude_riders=None):
    """Create a new Assignment in OFFERED for the order. Returns assignment or None.

    Used by automatic internal dispatch paths (restaurant start-preparing cascade,
    rejection-triggered redispatch). Skips creation if an active assignment already
    exists, so the cascade does not duplicate OFFERED rows on top of the caller's
    explicit /dispatch.
    """
    for a in db.assignments.values():
        if a["order_id"] == order["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return None
    return create_dispatch_for_order_force(order, exclude_riders=exclude_riders)


def create_dispatch_for_order_force(order, exclude_riders=None):
    """Unconditionally mint a new OFFERED Assignment for the order. Returns assignment
    or None (when no eligible rider). Used by the explicit /api/orders/{id}/dispatch
    endpoint, which per PRD §4 may "re-trigger" dispatch even when an older OFFERED
    row still exists.
    """
    rider = pick_best_available_rider(exclude=exclude_riders, order=order)
    if not rider:
        return None
    # Also exclude any rider who already holds an OFFERED assignment on THIS order,
    # so the second explicit /dispatch picks a different candidate when possible —
    # otherwise the two OFFERED rows would both target the same rider, who can only
    # accept one (since /accept would see a self-OFFERED peer).
    if any(a["order_id"] == order["id"] and a["rider_id"] == rider["id"]
           and a["status"] == "OFFERED" for a in db.assignments.values()):
        excluded = set(exclude_riders or set()) | {rider["id"]}
        rider = pick_best_available_rider(exclude=excluded, order=order)
        if not rider:
            return None
    now_iso = iso_now()
    a_id = gen_uuid()
    assignment = {
        "id": a_id,
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now_iso,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
        "created_at": now_iso,
    }
    db.assignments[a_id] = assignment
    return assignment


# =============================================================================
# Fine helpers
# =============================================================================
def create_rider_fine(rider_id, order_id, reason, amount_cents):
    """Create Fine (PENDING), debit rider wallet, recompute tier."""
    now_iso = iso_now()
    fine = {
        "id": gen_uuid(),
        "subject_type": "RIDER",
        "subject_id": rider_id,
        "order_id": order_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "settlement_status": "PENDING",
        "created_at": now_iso,
    }
    db.fines[fine["id"]] = fine
    rider = db.riders.get(rider_id)
    if rider:
        rider["wallet_balance_cents"] -= amount_cents
        recompute_rider_bonus_tier(rider_id)
        tick(rider)
    return fine


def create_customer_fine(customer_id, order_id, reason, amount_cents):
    now_iso = iso_now()
    fine = {
        "id": gen_uuid(),
        "subject_type": "CUSTOMER",
        "subject_id": customer_id,
        "order_id": order_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "settlement_status": "PENDING",
        "created_at": now_iso,
    }
    db.fines[fine["id"]] = fine
    return fine


# =============================================================================
# RESTAURANTS
# =============================================================================
@app.route("/api/restaurants", methods=["POST"])
def create_restaurant():
    require_role(["PlatformAdmin"])
    data = body()
    require_fields(data, ["name", "address", "lat", "lng"])
    name = as_str(data.get("name"), "name")
    if not name or len(name) > 120:
        raise ApiError("ERR_VALIDATION", 422, "Invalid restaurant name")
    # Uniqueness check against active restaurants
    for r in db.restaurants.values():
        if r["name"] == name and r["status"] in ("PENDING_APPROVAL", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_VALIDATION", 422, "Restaurant name must be unique")
    address = as_str(data.get("address"), "address")
    lat = as_number(data.get("lat"), "lat")
    lng = as_number(data.get("lng"), "lng")
    override = data.get("commission_rate_override", None)
    if override is not None:
        if isinstance(override, bool) or not isinstance(override, (int, float)):
            raise ApiError("ERR_VALIDATION", 422, "commission_rate_override must be number")
        if override < 0.05 or override > 0.35:
            raise ApiError("ERR_VALIDATION", 422, "commission_rate_override out of range")
        override = float(override)

    now_iso = iso_now()
    rid = gen_uuid()
    r = {
        "id": rid,
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "status": "PENDING_APPROVAL",
        "commission_rate_override": override,
        "pending_settlement_cents": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.restaurants[rid] = r
    return success_object(serialize_restaurant(r), 201)


@app.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    require_role(["PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"])
    status = request.args.get("status")
    rows = list(db.restaurants.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total, limit, offset = paginate_sorted(rows)
    return success_array([serialize_restaurant(r) for r in page], limit, offset, total)


@app.route("/api/restaurants/<rid>", methods=["GET"])
def read_restaurant(rid):
    require_role(["PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    return success_object(serialize_restaurant(r))


@app.route("/api/restaurants/<rid>", methods=["PATCH"])
def update_restaurant(rid):
    user_id, role = require_role(["PlatformAdmin", "Restaurant"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    if role == "Restaurant" and user_id != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Restaurant can only update their own")
    data = body()
    version = data.get("version")
    check_occ(r, version)
    if "address" in data:
        r["address"] = as_str(data["address"], "address")
    if "lat" in data:
        r["lat"] = as_number(data["lat"], "lat")
    if "lng" in data:
        r["lng"] = as_number(data["lng"], "lng")
    if "commission_rate_override" in data:
        override = data["commission_rate_override"]
        if override is not None:
            if isinstance(override, bool) or not isinstance(override, (int, float)):
                raise ApiError("ERR_VALIDATION", 422, "commission_rate_override must be number")
            if override < 0.05 or override > 0.35:
                raise ApiError("ERR_VALIDATION", 422, "commission_rate_override out of range")
            override = float(override)
        r["commission_rate_override"] = override
    tick(r)
    return success_object(serialize_restaurant(r))


@app.route("/api/restaurants/<rid>/approve", methods=["POST"])
def approve_restaurant(rid):
    require_role(["PlatformAdmin"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    if r["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Not in PENDING_APPROVAL")
    r["status"] = "ACTIVE"
    tick(r)
    return success_object(serialize_restaurant(r))


@app.route("/api/restaurants/<rid>/suspend", methods=["POST"])
def suspend_restaurant(rid):
    require_role(["PlatformAdmin"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Restaurant not ACTIVE")
    r["status"] = "SUSPENDED"
    tick(r)
    # Fan out: cancel all PLACED orders for this restaurant
    for o in db.orders.values():
        if o["restaurant_id"] == rid and o["status"] == "PLACED":
            o["status"] = "CANCELLED"
            if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
                o["payment_status"] = "VOIDED"
            tick(o)
    return success_object(serialize_restaurant(r))


@app.route("/api/restaurants/<rid>/reinstate", methods=["POST"])
def reinstate_restaurant(rid):
    require_role(["PlatformAdmin"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    if r["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Restaurant not SUSPENDED")
    r["status"] = "ACTIVE"
    tick(r)
    return success_object(serialize_restaurant(r))


@app.route("/api/restaurants/<rid>/settle", methods=["POST"])
def settle_restaurant(rid):
    require_role(["PlatformAdmin"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    r["pending_settlement_cents"] = 0
    tick(r)
    return success_object(serialize_restaurant(r))


# =============================================================================
# MENU ITEMS
# =============================================================================
@app.route("/api/restaurants/<rid>/menu-items", methods=["POST"])
def create_menu_item(rid):
    user_id, role = require_role(["Restaurant", "PlatformAdmin"])
    r = resolve_or_404(db.restaurants, rid, "Restaurant")
    if role == "Restaurant" and user_id != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Restaurant can only add to own menu")
    data = body()
    require_fields(data, ["name", "price_cents"])
    name = as_str(data.get("name"), "name")
    price = as_int(data.get("price_cents"), "price_cents")
    if price < 1 or price > 1000000:
        raise ApiError("ERR_VALIDATION", 422, "price_cents out of range")
    is_listed = data.get("is_listed", True)
    if not isinstance(is_listed, bool):
        raise ApiError("ERR_VALIDATION", 422, "is_listed must be boolean")

    now_iso = iso_now()
    mid = gen_uuid()
    mi = {
        "id": mid,
        "restaurant_id": rid,
        "name": name,
        "price_cents": price,
        "is_listed": is_listed,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.menu_items[mid] = mi
    return success_object(serialize_menu_item(mi), 201)


@app.route("/api/menu-items/<mid>", methods=["PATCH"])
def update_menu_item(mid):
    user_id, role = require_role(["Restaurant", "PlatformAdmin"])
    mi = resolve_or_404(db.menu_items, mid, "MenuItem")
    if role == "Restaurant" and user_id != mi["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your menu item")
    data = body()
    version = data.get("version")
    check_occ(mi, version)
    if "price_cents" in data:
        price = as_int(data["price_cents"], "price_cents")
        if price < 1 or price > 1000000:
            raise ApiError("ERR_VALIDATION", 422, "price_cents out of range")
        mi["price_cents"] = price
    if "is_listed" in data:
        if not isinstance(data["is_listed"], bool):
            raise ApiError("ERR_VALIDATION", 422, "is_listed must be boolean")
        mi["is_listed"] = data["is_listed"]
    tick(mi)
    return success_object(serialize_menu_item(mi))


@app.route("/api/restaurants/<rid>/menu-items", methods=["GET"])
def list_menu_items(rid):
    require_role(["PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"])
    resolve_or_404(db.restaurants, rid, "Restaurant")
    rows = [m for m in db.menu_items.values() if m["restaurant_id"] == rid]
    is_listed = request.args.get("is_listed")
    if is_listed is not None:
        if is_listed.lower() == "true":
            rows = [m for m in rows if m["is_listed"]]
        elif is_listed.lower() == "false":
            rows = [m for m in rows if not m["is_listed"]]
        else:
            raise ApiError("ERR_VALIDATION", 422, "is_listed must be boolean")
    page, total, limit, offset = paginate_sorted(rows)
    return success_array([serialize_menu_item(m) for m in page], limit, offset, total)


# =============================================================================
# RIDERS
# =============================================================================
@app.route("/api/riders", methods=["POST"])
def create_rider():
    require_role(["PlatformAdmin"])
    data = body()
    require_fields(data, ["name", "phone"])
    name = as_str(data.get("name"), "name")
    phone = as_str(data.get("phone"), "phone")
    for r in db.riders.values():
        if r["phone"] == phone:
            raise ApiError("ERR_VALIDATION", 422, "Rider phone must be unique")
    now_iso = iso_now()
    rid = gen_uuid()
    rider = {
        "id": rid,
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "bonus_tier": "BRONZE",
        "wallet_balance_cents": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.riders[rid] = rider
    return success_object(serialize_rider(rider), 201)


@app.route("/api/riders/<rid>", methods=["GET"])
def read_rider(rid):
    user_id, role = require_role(["PlatformAdmin", "Rider", "CustomerService"])
    rider = resolve_or_404(db.riders, rid, "Rider")
    if role == "Rider" and user_id != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Can only read own rider profile")
    return success_object(serialize_rider(rider))


@app.route("/api/riders/<rid>/go-online", methods=["POST"])
def rider_go_online(rid):
    user_id, role = require_role(["Rider"])
    rider = resolve_or_404(db.riders, rid, "Rider")
    if user_id != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your rider record")
    if rider["status"] != "OFFLINE":
        raise ApiError("ERR_INVALID_STATE", 409, "Rider not OFFLINE")
    rider["status"] = "AVAILABLE"
    tick(rider)
    return success_object(serialize_rider(rider))


@app.route("/api/riders/<rid>/go-offline", methods=["POST"])
def rider_go_offline(rid):
    user_id, role = require_role(["Rider"])
    rider = resolve_or_404(db.riders, rid, "Rider")
    if user_id != rid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your rider record")
    if rider["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Rider not AVAILABLE")
    # Precondition: no Assignment with rider_id == rid AND status IN OFFERED/ACCEPTED/PICKED_UP
    for a in db.assignments.values():
        if a["rider_id"] == rid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise ApiError("ERR_INVALID_STATE", 409, "Has active assignments")
    rider["status"] = "OFFLINE"
    tick(rider)
    return success_object(serialize_rider(rider))


@app.route("/api/riders/<rid>/suspend", methods=["POST"])
def rider_suspend(rid):
    require_role(["PlatformAdmin"])
    rider = resolve_or_404(db.riders, rid, "Rider")
    if rider["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Rider not AVAILABLE")
    if not (rider["on_time_rate"] < 0.70 or rider["acceptance_rate"] < 0.50):
        raise ApiError("ERR_SUSPEND_CRITERIA_NOT_MET", 422, "Rider metrics do not meet suspension criteria")
    rider["status"] = "SUSPENDED"
    tick(rider)
    return success_object(serialize_rider(rider))


# =============================================================================
# CUSTOMERS
# =============================================================================
@app.route("/api/customers", methods=["POST"])
def create_customer():
    require_role(["PlatformAdmin", "CustomerService"])
    data = body()
    require_fields(data, ["name", "phone", "address", "lat", "lng"])
    name = as_str(data.get("name"), "name")
    phone = as_str(data.get("phone"), "phone")
    address = as_str(data.get("address"), "address")
    lat = as_number(data.get("lat"), "lat")
    lng = as_number(data.get("lng"), "lng")
    for c in db.customers.values():
        if c["phone"] == phone:
            raise ApiError("ERR_VALIDATION", 422, "Customer phone must be unique")
    now_iso = iso_now()
    cid = gen_uuid()
    c = {
        "id": cid,
        "name": name,
        "phone": phone,
        "address": address,
        "lat": lat,
        "lng": lng,
        "credit_balance_cents": 0,
        "trust_score": 1.0,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.customers[cid] = c
    return success_object(serialize_customer(c), 201)


@app.route("/api/customers/<cid>", methods=["GET"])
def read_customer(cid):
    user_id, role = require_role(["PlatformAdmin", "Customer", "CustomerService"])
    c = resolve_or_404(db.customers, cid, "Customer")
    if role == "Customer" and user_id != cid:
        raise ApiError("ERR_FORBIDDEN", 403, "Can only read own customer profile")
    return success_object(serialize_customer(c))


# =============================================================================
# ORDERS
# =============================================================================
@app.route("/api/orders", methods=["POST"])
def create_order():
    user_id, role = require_role(["Customer"])
    data = body()
    require_fields(data, ["customer_id", "restaurant_id", "items"])
    customer_id = as_str(data.get("customer_id"), "customer_id")
    restaurant_id = as_str(data.get("restaurant_id"), "restaurant_id")
    items = data.get("items")
    if not isinstance(items, list):
        raise ApiError("ERR_VALIDATION", 422, "items must be array")

    # FK existence: priority 4 (before identity match at priority 5)
    if customer_id not in db.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id not found")
    if restaurant_id not in db.restaurants:
        raise ApiError("ERR_NOT_FOUND", 404, "restaurant_id not found")
    # menu item existence
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", 422, "item must be object")
        mid = item.get("menu_item_id")
        if mid is None:
            raise ApiError("ERR_VALIDATION", 422, "menu_item_id required")
        if mid not in db.menu_items:
            raise ApiError("ERR_NOT_FOUND", 404, "menu_item_id not found")

    # Identity match priority 5
    if user_id != customer_id:
        raise ApiError("ERR_FORBIDDEN", 403, "customer_id must equal X-User-ID")

    # Business referential priority 7
    restaurant = db.restaurants[restaurant_id]
    if restaurant["status"] != "ACTIVE":
        raise ApiError("ERR_RESTAURANT_UNAVAILABLE", 422, "Restaurant not ACTIVE")
    for item in items:
        mi = db.menu_items[item["menu_item_id"]]
        if not mi["is_listed"]:
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE", 422, "Menu item unlisted")
        if mi["restaurant_id"] != restaurant_id:
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE", 422, "Menu item belongs to different restaurant")

    # Priority 14: items non-empty, quantity>=1, subtotal>=100
    if len(items) == 0:
        raise ApiError("ERR_ORDER_INVALID", 422, "items empty")
    # Build order items snapshot + compute subtotal
    item_snaps = []
    subtotal = 0
    for item in items:
        qty = item.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError("ERR_ORDER_INVALID", 422, "quantity must be integer >= 1")
        mi = db.menu_items[item["menu_item_id"]]
        snap = {
            "menu_item_id": mi["id"],
            "name": mi["name"],
            "unit_price_cents": mi["price_cents"],
            "quantity": qty,
        }
        item_snaps.append(snap)
        subtotal += mi["price_cents"] * qty
    if subtotal < 100:
        raise ApiError("ERR_ORDER_INVALID", 422, "subtotal below minimum")

    customer = db.customers[customer_id]
    placement_time = CLOCK.now()
    distance = distance_km_rounded(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    is_peak = is_peak_time(placement_time)
    prov_fee = provisional_delivery_fee(distance, is_peak)
    prov_comm = tiered_commission(subtotal)
    promised = placement_time + timedelta(minutes=45)

    # Payment authorization: UNPAID -> AUTHORIZED; draw from credit_balance first
    payment_status = "AUTHORIZED"
    customer_credit = customer["credit_balance_cents"]
    total_charge = subtotal + prov_fee
    if customer_credit > 0:
        draw = min(customer_credit, total_charge)
        customer["credit_balance_cents"] -= draw
        tick(customer)

    now_iso = iso_now()
    oid = gen_uuid()
    order = {
        "id": oid,
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "status": "PLACED",
        "items": item_snaps,
        "subtotal_cents": subtotal,
        "distance_km": distance,
        "is_peak": is_peak,
        "provisional_delivery_fee_cents": prov_fee,
        "final_delivery_fee_cents": None,
        "provisional_commission_cents": prov_comm,
        "final_commission_cents": None,
        "promised_delivery_time": format_iso(promised),
        "actual_delivery_time": None,
        "minutes_late": None,
        "payment_status": payment_status,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.orders[oid] = order
    return success_object(serialize_order(order), 201)


@app.route("/api/orders/<oid>", methods=["GET"])
def read_order(oid):
    user_id, role = require_role(["PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"])
    o = resolve_or_404(db.orders, oid, "Order")
    if role == "Customer" and user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if role == "Restaurant" and user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if role == "Rider":
        # Must be a rider involved via an Assignment
        assigned = any(a["order_id"] == oid and a["rider_id"] == user_id for a in db.assignments.values())
        if not assigned:
            raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    return success_object(serialize_order(o))


@app.route("/api/orders", methods=["GET"])
def list_orders():
    user_id, role = require_role(["PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"])
    rows = list(db.orders.values())
    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status = request.args.get("status")
    if customer_id:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if restaurant_id:
        rows = [o for o in rows if o["restaurant_id"] == restaurant_id]
    if status:
        rows = [o for o in rows if o["status"] == status]
    if rider_id:
        order_ids = {a["order_id"] for a in db.assignments.values() if a["rider_id"] == rider_id}
        rows = [o for o in rows if o["id"] in order_ids]
    # Role-scope filtering
    if role == "Customer":
        rows = [o for o in rows if o["customer_id"] == user_id]
    elif role == "Restaurant":
        rows = [o for o in rows if o["restaurant_id"] == user_id]
    elif role == "Rider":
        rider_order_ids = {a["order_id"] for a in db.assignments.values() if a["rider_id"] == user_id}
        rows = [o for o in rows if o["id"] in rider_order_ids]
    page, total, limit, offset = paginate_sorted(rows)
    return success_array([serialize_order(o) for o in page], limit, offset, total)


@app.route("/api/orders/<oid>/accept", methods=["POST"])
def order_accept(oid):
    user_id, role = require_role(["Restaurant"])
    o = resolve_or_404(db.orders, oid, "Order")
    if user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    r = db.restaurants.get(o["restaurant_id"])
    if not r or r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Restaurant not ACTIVE")
    if o["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PLACED")
    o["status"] = "RESTAURANT_ACCEPTED"
    tick(o)
    return success_object(serialize_order(o))


@app.route("/api/orders/<oid>/cancel", methods=["POST"])
def order_cancel(oid):
    user_id, role = require_role(["Customer", "Restaurant", "CustomerService"])
    o = resolve_or_404(db.orders, oid, "Order")
    if role == "Customer" and user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if role == "Restaurant" and user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if o["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PLACED")
    o["status"] = "CANCELLED"
    if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
        o["payment_status"] = "VOIDED"
    tick(o)
    return success_object(serialize_order(o))


@app.route("/api/orders/<oid>/start-preparing", methods=["POST"])
def order_start_preparing(oid):
    user_id, role = require_role(["Restaurant"])
    o = resolve_or_404(db.orders, oid, "Order")
    if user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if o["status"] != "RESTAURANT_ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not RESTAURANT_ACCEPTED")
    o["status"] = "PREPARING"
    tick(o)
    # System creates initial Assignment offer
    create_dispatch_for_order(o)
    return success_object(serialize_order(o))


@app.route("/api/orders/<oid>/ready", methods=["POST"])
def order_ready(oid):
    user_id, role = require_role(["Restaurant"])
    o = resolve_or_404(db.orders, oid, "Order")
    if user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if o["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PREPARING")
    # Must have an assignment in ACCEPTED or PICKED_UP
    has_assigned = any(a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
                       for a in db.assignments.values())
    if not has_assigned:
        raise ApiError("ERR_INVALID_STATE", 409, "No rider has accepted")
    o["status"] = "READY_FOR_PICKUP"
    tick(o)
    return success_object(serialize_order(o))


@app.route("/api/orders/<oid>/dispatch", methods=["POST"])
def order_dispatch(oid):
    require_role(["PlatformAdmin", "CustomerService"])
    o = resolve_or_404(db.orders, oid, "Order")
    if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order not dispatchable in current state")
    # PRD §4 endpoint table: "Trigger or re-trigger dispatch of a fresh assignment."
    # Re-triggering is explicit in PRD, so this endpoint always mints a new Assignment
    # even while older offers are still OFFERED. Uniqueness is enforced at /accept per
    # PRD §3.6 ("no other Assignment already exists for the same order_id in OFFERED,
    # ACCEPTED, or PICKED_UP"), not at /dispatch. We only block when the order itself
    # is already past the dispatchable window — handled by the status check above.
    # Exclude riders who already hold an ACCEPTED/PICKED_UP assignment on this order
    # so the second dispatch targets a different rider (otherwise /accept would just
    # collide with the rider's own prior assignment on a self-duplicate).
    excluded = {
        a["rider_id"]
        for a in db.assignments.values()
        if a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
    }
    assignment = create_dispatch_for_order_force(o, exclude_riders=excluded)
    if not assignment:
        raise ApiError("ERR_INVALID_STATE", 409, "No available rider")
    return success_object(serialize_assignment(assignment), 201)


@app.route("/api/orders/<oid>/returns", methods=["POST"])
def order_returns(oid):
    user_id, role = require_role(["Customer"])
    o = resolve_or_404(db.orders, oid, "Order")
    if user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your order")
    if o["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not DELIVERED")

    data = body()
    require_fields(data, ["reason", "requested_refund_cents"])
    reason = as_str(data.get("reason"), "reason")
    if reason not in ("QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"):
        raise ApiError("ERR_VALIDATION", 422, "invalid reason")

    # Priority 10: within 24h of actual_delivery_time
    from datetime import datetime, timezone
    adt_str = o["actual_delivery_time"]
    adt = datetime.strptime(adt_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    if (CLOCK.now() - adt).total_seconds() > 24 * 3600:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", 422, "Return window expired")

    # Priority 11: duplicate return check
    for r in db.returns_tbl.values():
        if r["order_id"] == oid and r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            raise ApiError("ERR_DUPLICATE_RETURN", 409, "Active return exists")

    # Priority 12: refund amount
    rr = as_int(data.get("requested_refund_cents"), "requested_refund_cents")
    if rr < 1 or rr > o["subtotal_cents"]:
        raise ApiError("ERR_REFUND_AMOUNT_INVALID", 422, "refund amount out of range")

    now_iso = iso_now()
    ret_id = gen_uuid()
    ret = {
        "id": ret_id,
        "order_id": oid,
        "reason": reason,
        "requested_refund_cents": rr,
        "status": "REQUESTED",
        "approved_refund_cents": None,
        "reviewer_cs_user_id": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.returns_tbl[ret_id] = ret
    o["status"] = "REFUND_REQUESTED"
    tick(o)
    return success_object(serialize_return(ret), 201)


# =============================================================================
# ASSIGNMENTS
# =============================================================================
@app.route("/api/assignments/<aid>", methods=["GET"])
def read_assignment(aid):
    user_id, role = require_role(["PlatformAdmin", "Rider", "CustomerService"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if role == "Rider" and user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    return success_object(serialize_assignment(a))


@app.route("/api/assignments/<aid>/accept", methods=["POST"])
def assignment_accept(aid):
    user_id, role = require_role(["Rider"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    rider = db.riders.get(a["rider_id"])
    if not rider:
        raise ApiError("ERR_NOT_FOUND", 404, "Rider not found")
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not OFFERED")
    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Rider not AVAILABLE or ON_DELIVERY")
    order = db.orders.get(a["order_id"])
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order not in dispatchable state")
    # Priority 9: uniqueness — no other active assignment
    for other in db.assignments.values():
        if other["id"] == aid:
            continue
        if other["order_id"] == a["order_id"] and other["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP", "DELIVERED"):
            raise ApiError("ERR_ORDER_ALREADY_ASSIGNED", 409, "Order already assigned")

    a["status"] = "ACCEPTED"
    a["accepted_at"] = iso_now()

    # Cascade: Rider AVAILABLE -> ON_DELIVERY
    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"
    recompute_rider_acceptance(a["rider_id"])
    tick(rider)

    # Route merging (PRD §3.6). The rider may end up attached to one of two things:
    #   (a) an existing ACTIVE RouteGroup they already own whose peer pickup is within
    #       500 m of this order's pickup, OR
    #   (b) a sibling unpicked Assignment (ACCEPTED) that this same rider already
    #       holds — in which case a NEW RouteGroup is formed linking both legs. PRD
    #       says the RouteGroup is extended when proximity holds; creating one the
    #       first time two compatible legs exist is the only way PRD's RouteGroup
    #       ever comes into being.
    new_rest = db.restaurants.get(order["restaurant_id"])

    # First look for an existing group to extend.
    existing_group = None
    for rg in db.route_groups.values():
        if rg["rider_id"] == rider["id"] and rg["status"] == "ACTIVE":
            for peer_id in rg["assignment_ids"]:
                peer = db.assignments.get(peer_id)
                if peer and peer["status"] in ("OFFERED", "ACCEPTED") and peer["id"] != a["id"]:
                    peer_order = db.orders.get(peer["order_id"])
                    if not peer_order:
                        continue
                    peer_rest = db.restaurants.get(peer_order["restaurant_id"])
                    if peer_rest and new_rest:
                        dist_km = haversine_km(peer_rest["lat"], peer_rest["lng"],
                                               new_rest["lat"], new_rest["lng"])
                        if dist_km * 1000 <= 500:
                            existing_group = rg
                            break
            if existing_group:
                break
    if existing_group:
        existing_group["assignment_ids"].append(a["id"])
        a["route_group_id"] = existing_group["id"]
    else:
        # No existing group: look for a sibling ACCEPTED assignment on this rider
        # whose pickup is within 500 m, and form a new ACTIVE RouteGroup.
        sibling = None
        for other in db.assignments.values():
            if (other["rider_id"] == rider["id"]
                    and other["id"] != a["id"]
                    and other["status"] in ("ACCEPTED",)
                    and other["route_group_id"] is None):
                other_order = db.orders.get(other["order_id"])
                if not other_order:
                    continue
                other_rest = db.restaurants.get(other_order["restaurant_id"])
                if other_rest and new_rest:
                    dist_km = haversine_km(other_rest["lat"], other_rest["lng"],
                                           new_rest["lat"], new_rest["lng"])
                    if dist_km * 1000 <= 500:
                        sibling = other
                        break
        if sibling is not None:
            rg_id = gen_uuid()
            now_iso = iso_now()
            rg = {
                "id": rg_id,
                "rider_id": rider["id"],
                "assignment_ids": [sibling["id"], a["id"]],
                "merged_at": now_iso,
                "status": "ACTIVE",
                "created_at": now_iso,
                "updated_at": now_iso,
                "version": 1,
            }
            db.route_groups[rg_id] = rg
            sibling["route_group_id"] = rg_id
            a["route_group_id"] = rg_id
    return success_object(serialize_assignment(a))


@app.route("/api/assignments/<aid>/reject", methods=["POST"])
def assignment_reject(aid):
    user_id, role = require_role(["Rider"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not OFFERED")
    a["status"] = "REJECTED"
    recompute_rider_acceptance(a["rider_id"])
    # System dispatches new assignment
    order = db.orders.get(a["order_id"])
    if order and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        create_dispatch_for_order(order, exclude_riders={a["rider_id"]})
    return success_object(serialize_assignment(a))


@app.route("/api/assignments/<aid>/pickup", methods=["POST"])
def assignment_pickup(aid):
    user_id, role = require_role(["Rider"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    if a["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not ACCEPTED")
    order = db.orders.get(a["order_id"])
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    if order["status"] != "READY_FOR_PICKUP":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not READY_FOR_PICKUP")
    a["status"] = "PICKED_UP"
    a["picked_up_at"] = iso_now()
    order["status"] = "PICKED_UP"
    tick(order)
    return success_object(serialize_assignment(a))


@app.route("/api/assignments/<aid>/deliver", methods=["POST"])
def assignment_deliver(aid):
    user_id, role = require_role(["Rider"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    if a["status"] != "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not PICKED_UP")
    order = db.orders.get(a["order_id"])
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    if order["status"] != "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PICKED_UP")

    now = CLOCK.now()
    now_iso_str = format_iso(now)
    a["status"] = "DELIVERED"
    a["delivered_at"] = now_iso_str

    # Order cascade
    order["actual_delivery_time"] = now_iso_str
    # minutes_late: seconds diff floor div 60
    from datetime import datetime, timezone
    pdt = datetime.strptime(order["promised_delivery_time"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    diff_seconds = (now - pdt).total_seconds()
    minutes_late = max(0, int(diff_seconds // 60)) if diff_seconds > 0 else 0
    order["minutes_late"] = minutes_late

    # Compute final_delivery_fee
    route_group_size = 0
    if a["route_group_id"]:
        rg = db.route_groups.get(a["route_group_id"])
        if rg:
            route_group_size = len(rg["assignment_ids"])
    solo_or_merged_size = route_group_size if route_group_size >= 2 else 1
    final_fee = final_delivery_fee(order["distance_km"], order["is_peak"], solo_or_merged_size)
    order["final_delivery_fee_cents"] = final_fee
    a["final_delivery_fee_cents"] = final_fee

    # Compute final_commission using current override
    restaurant = db.restaurants.get(order["restaurant_id"])
    override = restaurant["commission_rate_override"] if restaurant else None
    fcomm = final_commission(order["subtotal_cents"], override)
    order["final_commission_cents"] = fcomm

    order["payment_status"] = "CAPTURED"
    order["status"] = "DELIVERED"
    tick(order)

    # Rider wallet credit
    rider = db.riders.get(a["rider_id"])
    if rider:
        rider["wallet_balance_cents"] += final_fee
        # pre-tier recompute after on_time_rate refresh
        recompute_rider_on_time(a["rider_id"])
        recompute_rider_bonus_tier(a["rider_id"])

    # Restaurant settlement credit
    if restaurant:
        restaurant["pending_settlement_cents"] += order["subtotal_cents"] - fcomm
        tick(restaurant)

    # Fine if late
    if minutes_late > 0:
        fine_amount = late_delivery_fine(minutes_late, final_fee)
        create_rider_fine(a["rider_id"], order["id"], "LATE_DELIVERY", fine_amount)
    else:
        # Still tick rider (we mutated rider wallet above)
        if rider:
            tick(rider)

    # Already ticked rider via create_rider_fine or tick above

    # RouteGroup completion
    if a["route_group_id"]:
        rg = db.route_groups.get(a["route_group_id"])
        if rg and all(db.assignments.get(pid, {}).get("status") == "DELIVERED" for pid in rg["assignment_ids"]):
            rg["status"] = "COMPLETED"

    # Rider status: back to AVAILABLE if no remaining active assignments
    if rider:
        has_active = any(o["rider_id"] == rider["id"] and o["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
                         for o in db.assignments.values())
        if not has_active and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
            tick(rider)

    return success_object(serialize_assignment(a))


@app.route("/api/assignments/<aid>/cancel", methods=["POST"])
def assignment_cancel(aid):
    user_id, role = require_role(["Rider"])
    a = resolve_or_404(db.assignments, aid, "Assignment")
    if user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your assignment")
    if a["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment not ACCEPTED")
    order = db.orders.get(a["order_id"])
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    if order["status"] == "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", 409, "Order already PICKED_UP")

    a["status"] = "CANCELLED"
    # Fine the rider
    create_rider_fine(a["rider_id"], a["order_id"], "RIDER_NO_SHOW", 500)
    # Dispatch new assignment if order still needs one
    if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        create_dispatch_for_order(order, exclude_riders={a["rider_id"]})
    # Return rider to AVAILABLE if no more active assignments
    rider = db.riders.get(a["rider_id"])
    if rider:
        has_active = any(o["rider_id"] == rider["id"] and o["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
                         for o in db.assignments.values())
        if not has_active and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
            tick(rider)
    return success_object(serialize_assignment(a))


# =============================================================================
# RETURNS
# =============================================================================
@app.route("/api/returns/<rid>", methods=["GET"])
def read_return(rid):
    user_id, role = require_role(["PlatformAdmin", "Customer", "Restaurant", "CustomerService"])
    r = resolve_or_404(db.returns_tbl, rid, "Return")
    order = db.orders.get(r["order_id"])
    if role == "Customer" and order and user_id != order["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your return")
    if role == "Restaurant" and order and user_id != order["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", 403, "Not your return")
    return success_object(serialize_return(r))


@app.route("/api/returns/<rid>/approve", methods=["POST"])
def return_approve(rid):
    user_id, role = require_role(["CustomerService"])
    r = resolve_or_404(db.returns_tbl, rid, "Return")
    if r["status"] not in ("REQUESTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED or ESCALATED")
    order = db.orders.get(r["order_id"])
    if not order or order["status"] != "REFUND_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not REFUND_REQUESTED")
    data = body()
    require_fields(data, ["approved_refund_cents"])
    arc = as_int(data.get("approved_refund_cents"), "approved_refund_cents")
    if arc < 1 or arc > order["subtotal_cents"] or arc > r["requested_refund_cents"]:
        raise ApiError("ERR_REFUND_AMOUNT_INVALID", 422, "approved_refund_cents out of range")
    r["status"] = "APPROVED"
    r["approved_refund_cents"] = arc
    r["reviewer_cs_user_id"] = user_id
    tick(r)

    # Cascade to order
    order["status"] = "REFUNDED"
    if arc < order["subtotal_cents"]:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    else:
        order["payment_status"] = "FULLY_REFUNDED"
    tick(order)

    # Customer credit
    customer = db.customers.get(order["customer_id"])
    if customer:
        customer["credit_balance_cents"] += arc
        tick(customer)

    # Restaurant settlement debit
    restaurant = db.restaurants.get(order["restaurant_id"])
    if restaurant:
        restaurant["pending_settlement_cents"] -= arc
        tick(restaurant)

    # Abusive return fine
    if customer and customer["trust_score"] < 0.5 and r["reason"] == "QUALITY_ISSUE":
        create_customer_fine(customer["id"], order["id"], "ABUSIVE_RETURN", arc)

    return success_object(serialize_return(r))


@app.route("/api/returns/<rid>/reject", methods=["POST"])
def return_reject(rid):
    user_id, role = require_role(["CustomerService"])
    r = resolve_or_404(db.returns_tbl, rid, "Return")
    if r["status"] not in ("REQUESTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED or ESCALATED")
    order = db.orders.get(r["order_id"])
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Order not found")
    r["status"] = "REJECTED"
    r["reviewer_cs_user_id"] = user_id
    tick(r)
    # Revert order to DELIVERED
    if order["status"] == "REFUND_REQUESTED":
        order["status"] = "DELIVERED"
        tick(order)
    return success_object(serialize_return(r))


@app.route("/api/returns/<rid>/escalate", methods=["POST"])
def return_escalate(rid):
    user_id, role = require_role(["CustomerService"])
    r = resolve_or_404(db.returns_tbl, rid, "Return")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED")
    r["status"] = "ESCALATED"
    tick(r)
    # Open linked WorkOrder
    now_iso = iso_now()
    wid = gen_uuid()
    w = {
        "id": wid,
        "opened_by_role": "CUSTOMER_SERVICE",
        "opened_by_id": user_id,
        "related_order_id": r["order_id"],
        "related_return_id": r["id"],
        "category": "FOOD_QUALITY",
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.work_orders[wid] = w
    return success_object(serialize_return(r))


@app.route("/api/returns/<rid>/reopen", methods=["POST"])
def return_reopen(rid):
    user_id, role = require_role(["CustomerService"])
    r = resolve_or_404(db.returns_tbl, rid, "Return")
    if r["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Return not ESCALATED")
    r["status"] = "REQUESTED"
    tick(r)
    # Close linked work orders
    for w in db.work_orders.values():
        if w["related_return_id"] == r["id"] and w["status"] != "CLOSED":
            w["status"] = "CLOSED"
            tick(w)
    return success_object(serialize_return(r))


# =============================================================================
# FINES
# =============================================================================
@app.route("/api/fines/<fid>", methods=["GET"])
def read_fine(fid):
    user_id, role = require_role(["PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"])
    f = resolve_or_404(db.fines, fid, "Fine")
    if role in ("Rider", "Restaurant", "Customer"):
        if user_id != f["subject_id"]:
            raise ApiError("ERR_FORBIDDEN", 403, "Not your fine")
    return success_object(serialize_fine(f))


@app.route("/api/fines", methods=["GET"])
def list_fines():
    user_id, role = require_role(["PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"])
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    rows = list(db.fines.values())
    if subject_type:
        rows = [f for f in rows if f["subject_type"] == subject_type]
    if subject_id:
        rows = [f for f in rows if f["subject_id"] == subject_id]
    if settlement_status:
        rows = [f for f in rows if f["settlement_status"] == settlement_status]
    # Role filter: rider/restaurant/customer -> only their own
    if role == "Rider":
        rows = [f for f in rows if f["subject_id"] == user_id and f["subject_type"] == "RIDER"]
    elif role == "Restaurant":
        rows = [f for f in rows if f["subject_id"] == user_id and f["subject_type"] == "RESTAURANT"]
    elif role == "Customer":
        rows = [f for f in rows if f["subject_id"] == user_id and f["subject_type"] == "CUSTOMER"]
    page, total, limit, offset = paginate_sorted(rows)
    return success_array([serialize_fine(f) for f in page], limit, offset, total)


@app.route("/api/fines/<fid>/waive", methods=["POST"])
def waive_fine(fid):
    require_role(["CustomerService", "PlatformAdmin"])
    f = resolve_or_404(db.fines, fid, "Fine")
    if f["settlement_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Fine not PENDING")
    f["settlement_status"] = "WAIVED"
    # Reverse ledger
    if f["subject_type"] == "RIDER":
        rider = db.riders.get(f["subject_id"])
        if rider:
            rider["wallet_balance_cents"] += f["amount_cents"]
            recompute_rider_bonus_tier(rider["id"])
            tick(rider)
    elif f["subject_type"] == "CUSTOMER":
        customer = db.customers.get(f["subject_id"])
        if customer:
            # The abusive-return fine had debited nothing from credit; reversal restores pre-fine state.
            # Since we do not deduct on fine creation for customers, no-op restoration.
            pass
    elif f["subject_type"] == "RESTAURANT":
        restaurant = db.restaurants.get(f["subject_id"])
        if restaurant:
            # Same reasoning as customer
            pass
    return success_object(serialize_fine(f))


# =============================================================================
# WORK ORDERS
# =============================================================================
@app.route("/api/work-orders", methods=["POST"])
def create_work_order():
    user_id, role = require_role(["Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"])
    data = body()
    require_fields(data, ["opened_by_role", "opened_by_id", "category"])
    opened_by_role = as_str(data.get("opened_by_role"), "opened_by_role")
    if opened_by_role not in ("CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"):
        raise ApiError("ERR_VALIDATION", 422, "invalid opened_by_role")
    opened_by_id = as_str(data.get("opened_by_id"), "opened_by_id")
    category = as_str(data.get("category"), "category")
    if category not in ("DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM", "RIDER_BEHAVIOR",
                       "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER"):
        raise ApiError("ERR_VALIDATION", 422, "invalid category")
    related_order_id = data.get("related_order_id")
    related_return_id = data.get("related_return_id")
    if related_order_id is not None and related_order_id not in db.orders:
        raise ApiError("ERR_NOT_FOUND", 404, "related_order_id not found")
    if related_return_id is not None and related_return_id not in db.returns_tbl:
        raise ApiError("ERR_NOT_FOUND", 404, "related_return_id not found")

    now_iso = iso_now()
    wid = gen_uuid()
    w = {
        "id": wid,
        "opened_by_role": opened_by_role,
        "opened_by_id": opened_by_id,
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "category": category,
        "status": "OPEN",
        "assigned_cs_user_id": None,
        "resolution_notes": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.work_orders[wid] = w
    return success_object(serialize_work_order(w), 201)


@app.route("/api/work-orders/<wid>", methods=["GET"])
def read_work_order(wid):
    require_role(["PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/assign", methods=["POST"])
def wo_assign(wid):
    user_id, role = require_role(["CustomerService", "PlatformAdmin"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Not OPEN")
    w["status"] = "UNDER_REVIEW"
    w["assigned_cs_user_id"] = user_id
    tick(w)
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/request-info", methods=["POST"])
def wo_request_info(wid):
    require_role(["CustomerService", "PlatformAdmin"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Not UNDER_REVIEW")
    w["status"] = "AWAITING_INFO"
    tick(w)
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/submit-info", methods=["POST"])
def wo_submit_info(wid):
    user_id, role = require_role(["Customer", "Rider", "Restaurant"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] != "AWAITING_INFO":
        raise ApiError("ERR_INVALID_STATE", 409, "Not AWAITING_INFO")
    if w["opened_by_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the opener")
    w["status"] = "UNDER_REVIEW"
    tick(w)
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/resolve", methods=["POST"])
def wo_resolve(wid):
    require_role(["CustomerService", "PlatformAdmin"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Not UNDER_REVIEW or ESCALATED")
    if w["assigned_cs_user_id"] is None:
        raise ApiError("ERR_INVALID_STATE", 409, "No assigned CS user")
    if w["related_return_id"]:
        ret = db.returns_tbl.get(w["related_return_id"])
        if ret and ret["status"] not in ("APPROVED", "REJECTED"):
            raise ApiError("ERR_RELATED_RETURN_UNRESOLVED", 422, "Related return not terminal")
    data = body()
    require_fields(data, ["resolution_notes"])
    notes = as_str(data.get("resolution_notes"), "resolution_notes")
    w["status"] = "RESOLVED"
    w["resolution_notes"] = notes
    tick(w)
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/escalate", methods=["POST"])
def wo_escalate(wid):
    require_role(["CustomerService", "PlatformAdmin"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Not UNDER_REVIEW")
    w["status"] = "ESCALATED"
    tick(w)
    return success_object(serialize_work_order(w))


@app.route("/api/work-orders/<wid>/close", methods=["POST"])
def wo_close(wid):
    require_role(["CustomerService", "PlatformAdmin"])
    w = resolve_or_404(db.work_orders, wid, "WorkOrder")
    if w["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Not RESOLVED")
    w["status"] = "CLOSED"
    tick(w)
    return success_object(serialize_work_order(w))


# =============================================================================
# CLOCK
# =============================================================================
@app.route("/api/_clock/advance", methods=["POST"])
def clock_advance():
    require_role(["PlatformAdmin"])
    data = body()
    require_fields(data, ["seconds"])
    secs = data.get("seconds")
    if isinstance(secs, bool) or not isinstance(secs, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "seconds must be number")
    CLOCK.advance(float(secs))
    sweep_offer_timeouts()
    return success_object({})


# =============================================================================
# Boot
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
