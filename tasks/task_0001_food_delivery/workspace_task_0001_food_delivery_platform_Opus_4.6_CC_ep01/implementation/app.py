"""Food Delivery Platform API - Flask implementation."""
import os
import math
import uuid
import string
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from threading import RLock
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock_offset = timedelta(0)
_lock = RLock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc) + _clock_offset


def fmt_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return fmt_ts(now_utc())


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
restaurants: dict = {}
customers: dict = {}
riders: dict = {}
menu_items: dict = {}
orders: dict = {}
returns_: dict = {}
work_orders: dict = {}
assignments: dict = {}
route_groups: dict = {}
fines: dict = {}

# rider history (for rates): lists of booleans/outcomes
rider_offer_history: dict = {}  # rider_id -> list of ("ACCEPTED"|"REJECTED"), newest last
rider_delivery_history: dict = {}  # rider_id -> list of bool (on_time), newest last


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ORDER_ALREADY_ASSIGNED": 409,
    "ERR_DUPLICATE_RETURN": 409,
    "ERR_RESTAURANT_UNAVAILABLE": 422,
    "ERR_SUSPEND_CRITERIA_NOT_MET": 422,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_REFUND_AMOUNT_INVALID": 422,
    "ERR_ORDER_INVALID": 422,
    "ERR_RELATED_RETURN_UNRESOLVED": 422,
    "ERR_VALIDATION": 422,
}


def _make_req_id() -> str:
    alnum = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alnum) for _ in range(20))


def _make_meta(extra: dict | None = None) -> dict:
    m = {
        "api_request_id": _make_req_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _make_meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    return ok(
        items,
        status=status,
        response_type="array",
        meta_extra={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
    )


def err(error_id: str, message: str = ""):
    body = {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), ERROR_STATUS[error_id]


# ---------------------------------------------------------------------------
# Auth / RBAC helpers
# ---------------------------------------------------------------------------
VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        return None, None, err("ERR_AUTH_REQUIRED")
    return uid, role, None


def require_role(role, allowed):
    if role not in allowed:
        return err("ERR_FORBIDDEN")
    return None


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------
def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def round1(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def is_peak_time(dt: datetime) -> bool:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    h = dt.hour
    m = dt.minute
    # 11:00 through 13:00 UTC, 18:00 through 20:00 UTC
    in1 = (h == 11) or (h == 12) or (h == 13 and m == 0)
    in2 = (h == 18) or (h == 19) or (h == 20 and m == 0)
    return in1 or in2


def delivery_fee_solo(distance_km: float, is_peak: bool) -> int:
    bands = math.ceil(distance_km) if distance_km > 0 else 0
    fee = 300 + 120 * bands
    if is_peak:
        fee += 200
    return fee


def tiered_commission_cents(subtotal: int) -> int:
    s = Decimal(subtotal)
    t1 = min(s, Decimal(20000))
    t2 = min(max(s - Decimal(20000), Decimal(0)), Decimal(30000))
    t3 = max(s - Decimal(50000), Decimal(0))
    total = t1 * Decimal("0.15") + t2 * Decimal("0.18") + t3 * Decimal("0.22")
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def flat_commission_cents(subtotal: int, rate) -> int:
    total = Decimal(subtotal) * Decimal(str(rate))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def late_fine_amount(minutes_late: int, final_delivery_fee_cents: int) -> int:
    if minutes_late <= 0:
        return 0
    if 1 <= minutes_late <= 10:
        return 200
    if 11 <= minutes_late <= 30:
        return 500 + 50 * (minutes_late - 10)
    # > 30
    return min(final_delivery_fee_cents, 1500) + 500


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    score = (
        Decimal("0.6") * Decimal(str(on_time_rate))
        + Decimal("0.3") * Decimal(str(acceptance_rate))
        + Decimal("0.1") * (Decimal(str(rating)) / Decimal("5"))
    )
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if score >= Decimal("0.900"):
        return "PLATINUM"
    if score >= Decimal("0.800"):
        return "GOLD"
    if score >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"


def recompute_rider_metrics(rider):
    # acceptance_rate from last 30 offers
    hist = rider_offer_history.get(rider["id"], [])
    window = hist[-30:]
    if window:
        accepts = sum(1 for x in window if x == "ACCEPTED")
        rider["acceptance_rate"] = round(accepts / len(window), 6)
    else:
        rider["acceptance_rate"] = 1.0
    # on_time_rate
    delivs = rider_delivery_history.get(rider["id"], [])
    if len(delivs) >= 10:
        window_d = delivs[-30:]
        on_time = sum(1 for x in window_d if x)
        rider["on_time_rate"] = round(on_time / len(window_d), 6)
    else:
        rider["on_time_rate"] = 1.0
    rider["bonus_tier"] = compute_bonus_tier(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )


def bump(resource):
    resource["updated_at"] = now_iso()
    if "version" in resource:
        resource["version"] += 1


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_restaurant(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "lat": r["lat"],
        "lng": r["lng"],
        "commission_rate_override": r["commission_rate_override"],
        "pending_settlement_cents": r["pending_settlement_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "phone": c["phone"],
        "address": c["address"],
        "lat": c["lat"],
        "lng": c["lng"],
        "credit_balance_cents": c["credit_balance_cents"],
        "trust_score": c["trust_score"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_rider(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "phone": r["phone"],
        "status": r["status"],
        "on_time_rate": r["on_time_rate"],
        "acceptance_rate": r["acceptance_rate"],
        "rating": r["rating"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "bonus_tier": r["bonus_tier"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_menu_item(m):
    return {
        "id": m["id"],
        "restaurant_id": m["restaurant_id"],
        "name": m["name"],
        "price_cents": m["price_cents"],
        "is_listed": m["is_listed"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "restaurant_id": o["restaurant_id"],
        "items": o["items"],
        "subtotal_cents": o["subtotal_cents"],
        "distance_km": o["distance_km"],
        "is_peak": o["is_peak"],
        "promised_delivery_time": o["promised_delivery_time"],
        "actual_delivery_time": o["actual_delivery_time"],
        "minutes_late": o["minutes_late"],
        "provisional_delivery_fee_cents": o["provisional_delivery_fee_cents"],
        "final_delivery_fee_cents": o["final_delivery_fee_cents"],
        "provisional_commission_cents": o["provisional_commission_cents"],
        "final_commission_cents": o["final_commission_cents"],
        "status": o["status"],
        "payment_status": o["payment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_return(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "reason": r["reason"],
        "requested_refund_cents": r["requested_refund_cents"],
        "approved_refund_cents": r["approved_refund_cents"],
        "reviewer_cs_user_id": r["reviewer_cs_user_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_work_order(w):
    return {
        "id": w["id"],
        "opened_by_role": w["opened_by_role"],
        "opened_by_id": w["opened_by_id"],
        "category": w["category"],
        "related_order_id": w["related_order_id"],
        "related_return_id": w["related_return_id"],
        "assigned_cs_user_id": w["assigned_cs_user_id"],
        "resolution_notes": w["resolution_notes"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "rider_id": a["rider_id"],
        "route_group_id": a["route_group_id"],
        "status": a["status"],
        "offered_at": a["offered_at"],
        "accepted_at": a["accepted_at"],
        "picked_up_at": a["picked_up_at"],
        "delivered_at": a["delivered_at"],
        "final_delivery_fee_cents": a["final_delivery_fee_cents"],
        "created_at": a["created_at"],
    }


def ser_route_group(g):
    return {
        "id": g["id"],
        "rider_id": g["rider_id"],
        "assignment_ids": g["assignment_ids"],
        "merged_at": g["merged_at"],
        "status": g["status"],
        "created_at": g["created_at"],
    }


def ser_fine(f):
    return {
        "id": f["id"],
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "reason": f["reason"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "created_at": f["created_at"],
    }


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------
def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return None, None, err("ERR_VALIDATION", "invalid pagination params")
    if limit < 1 or limit > 100 or offset < 0:
        return None, None, err("ERR_VALIDATION", "pagination out of range")
    return limit, offset, None


def apply_page(items, limit, offset):
    items_sorted = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items_sorted)
    window = items_sorted[offset : offset + limit]
    return window, total


def body_json():
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    return data or {}


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------
def find_best_rider_for_order(order) -> str | None:
    """Select a candidate rider for dispatch."""
    eligible = [r for r in riders.values() if r["status"] in ("AVAILABLE", "ON_DELIVERY")]
    if not eligible:
        return None
    # Prefer rider with pending unpicked assignment at near pickup restaurant (merge candidate)
    rest = restaurants.get(order["restaurant_id"])
    merge_candidate = None
    solo_candidates = []
    for r in eligible:
        has_merge = False
        for a in assignments.values():
            if a["rider_id"] == r["id"] and a["status"] in ("ACCEPTED",):
                peer_order = orders.get(a["order_id"])
                if peer_order and peer_order["id"] != order["id"]:
                    peer_rest = restaurants.get(peer_order["restaurant_id"])
                    if peer_rest and rest:
                        d = haversine_km(rest["lat"], rest["lng"], peer_rest["lat"], peer_rest["lng"])
                        if d <= 0.5:
                            has_merge = True
                            break
        if has_merge:
            merge_candidate = r
            break
        if r["status"] == "AVAILABLE":
            solo_candidates.append(r)
    if merge_candidate:
        return merge_candidate["id"]
    if solo_candidates:
        solo_candidates.sort(key=lambda x: x["created_at"])
        return solo_candidates[0]["id"]
    return None


def create_dispatch_for_order(order, exclude_rider_ids=None) -> dict | None:
    exclude_rider_ids = exclude_rider_ids or set()
    eligible = [
        r
        for r in riders.values()
        if r["status"] in ("AVAILABLE", "ON_DELIVERY") and r["id"] not in exclude_rider_ids
    ]
    if not eligible:
        return None
    # Use same logic as find_best_rider_for_order but respect exclusions
    rest = restaurants.get(order["restaurant_id"])
    merge_candidate = None
    solo_candidates = []
    for r in eligible:
        has_merge = False
        for a in assignments.values():
            if a["rider_id"] == r["id"] and a["status"] in ("ACCEPTED",):
                peer_order = orders.get(a["order_id"])
                if peer_order and peer_order["id"] != order["id"]:
                    peer_rest = restaurants.get(peer_order["restaurant_id"])
                    if peer_rest and rest:
                        d = haversine_km(rest["lat"], rest["lng"], peer_rest["lat"], peer_rest["lng"])
                        if d <= 0.5:
                            has_merge = True
                            break
        if has_merge:
            merge_candidate = r
            break
        if r["status"] == "AVAILABLE":
            solo_candidates.append(r)
    chosen_id = None
    if merge_candidate:
        chosen_id = merge_candidate["id"]
    elif solo_candidates:
        solo_candidates.sort(key=lambda x: x["created_at"])
        chosen_id = solo_candidates[0]["id"]
    if not chosen_id:
        return None
    aid = new_id()
    now = now_iso()
    a = {
        "id": aid,
        "order_id": order["id"],
        "rider_id": chosen_id,
        "route_group_id": None,
        "status": "OFFERED",
        "offered_at": now,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "final_delivery_fee_cents": None,
        "created_at": now,
    }
    assignments[aid] = a
    return a


# ---------------------------------------------------------------------------
# Restaurant endpoints
# ---------------------------------------------------------------------------
@app.post("/api/restaurants")
def post_restaurant():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        data = body_json()
        name = data.get("name")
        address = data.get("address")
        lat = data.get("lat")
        lng = data.get("lng")
        cro = data.get("commission_rate_override", None)
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            return err("ERR_VALIDATION", "invalid name")
        if not isinstance(address, str) or not address:
            return err("ERR_VALIDATION", "invalid address")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            return err("ERR_VALIDATION", "invalid coordinates")
        if cro is not None:
            if not isinstance(cro, (int, float)):
                return err("ERR_VALIDATION", "invalid commission_rate_override")
            if cro < 0.05 or cro > 0.35:
                return err("ERR_VALIDATION", "commission_rate_override out of range")
        for existing in restaurants.values():
            if (
                existing["name"] == name
                and existing["status"] in ("PENDING_APPROVAL", "ACTIVE", "SUSPENDED")
            ):
                return err("ERR_VALIDATION", "name must be unique among active restaurants")
        now = now_iso()
        rid = new_id()
        r = {
            "id": rid,
            "name": name,
            "address": address,
            "lat": float(lat),
            "lng": float(lng),
            "commission_rate_override": float(cro) if cro is not None else None,
            "pending_settlement_cents": 0,
            "status": "PENDING_APPROVAL",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        restaurants[rid] = r
        return ok(ser_restaurant(r), status=201)


@app.get("/api/restaurants")
def list_restaurants():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        limit, offset, e = parse_pagination()
        if e:
            return e
        status_filter = request.args.get("status")
        items = [r for r in restaurants.values() if not status_filter or r["status"] == status_filter]
        window, total = apply_page(items, limit, offset)
        return ok_list([ser_restaurant(r) for r in window], total, limit, offset)


@app.get("/api/restaurants/<rid>")
def get_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        return ok(ser_restaurant(r))


@app.patch("/api/restaurants/<rid>")
def patch_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Restaurant"}:
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if role == "Restaurant" and uid != rid:
            return err("ERR_FORBIDDEN")
        data = body_json()
        if "name" in data:
            return err("ERR_VALIDATION", "name is immutable")
        # OCC
        if "version" in data and data["version"] != r["version"]:
            return err("ERR_VERSION_CONFLICT")
        if "address" in data:
            if not isinstance(data["address"], str) or not data["address"]:
                return err("ERR_VALIDATION", "invalid address")
            r["address"] = data["address"]
        if "lat" in data:
            if not isinstance(data["lat"], (int, float)):
                return err("ERR_VALIDATION", "invalid lat")
            r["lat"] = float(data["lat"])
        if "lng" in data:
            if not isinstance(data["lng"], (int, float)):
                return err("ERR_VALIDATION", "invalid lng")
            r["lng"] = float(data["lng"])
        if "commission_rate_override" in data:
            cro = data["commission_rate_override"]
            if cro is not None:
                if not isinstance(cro, (int, float)):
                    return err("ERR_VALIDATION", "invalid commission_rate_override")
                if cro < 0.05 or cro > 0.35:
                    return err("ERR_VALIDATION", "commission_rate_override out of range")
                r["commission_rate_override"] = float(cro)
            else:
                r["commission_rate_override"] = None
        bump(r)
        return ok(ser_restaurant(r))


@app.post("/api/restaurants/<rid>/approve")
def approve_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "PENDING_APPROVAL":
            return err("ERR_INVALID_STATE")
        r["status"] = "ACTIVE"
        bump(r)
        return ok(ser_restaurant(r))


@app.post("/api/restaurants/<rid>/suspend")
def suspend_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "ACTIVE":
            return err("ERR_INVALID_STATE")
        r["status"] = "SUSPENDED"
        bump(r)
        # fan out cancellation for PLACED orders
        for o in orders.values():
            if o["restaurant_id"] == rid and o["status"] == "PLACED":
                o["status"] = "CANCELLED"
                if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
                    o["payment_status"] = "VOIDED"
                bump(o)
        return ok(ser_restaurant(r))


@app.post("/api/restaurants/<rid>/reinstate")
def reinstate_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "SUSPENDED":
            return err("ERR_INVALID_STATE")
        r["status"] = "ACTIVE"
        bump(r)
        return ok(ser_restaurant(r))


@app.post("/api/restaurants/<rid>/settle")
def settle_restaurant(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        r["pending_settlement_cents"] = 0
        bump(r)
        return ok(ser_restaurant(r))


# ---------------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------------
@app.post("/api/restaurants/<rid>/menu-items")
def create_menu_item(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"Restaurant", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if role == "Restaurant" and uid != rid:
            return err("ERR_FORBIDDEN")
        data = body_json()
        name = data.get("name")
        price = data.get("price_cents")
        is_listed = data.get("is_listed", True)
        if not isinstance(name, str) or not name:
            return err("ERR_VALIDATION", "invalid name")
        if not isinstance(price, int) or isinstance(price, bool):
            return err("ERR_VALIDATION", "invalid price_cents")
        if price < 1 or price > 1_000_000:
            return err("ERR_VALIDATION", "price_cents out of range")
        if not isinstance(is_listed, bool):
            return err("ERR_VALIDATION", "invalid is_listed")
        now = now_iso()
        mid = new_id()
        m = {
            "id": mid,
            "restaurant_id": rid,
            "name": name,
            "price_cents": price,
            "is_listed": is_listed,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        menu_items[mid] = m
        return ok(ser_menu_item(m), status=201)


@app.patch("/api/menu-items/<mid>")
def patch_menu_item(mid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"Restaurant", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        m = menu_items.get(mid)
        if not m:
            return err("ERR_NOT_FOUND")
        if role == "Restaurant" and uid != m["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        data = body_json()
        if "version" in data and data["version"] != m["version"]:
            return err("ERR_VERSION_CONFLICT")
        if "price_cents" in data:
            p = data["price_cents"]
            if not isinstance(p, int) or isinstance(p, bool) or p < 1 or p > 1_000_000:
                return err("ERR_VALIDATION", "invalid price_cents")
            m["price_cents"] = p
        if "is_listed" in data:
            if not isinstance(data["is_listed"], bool):
                return err("ERR_VALIDATION", "invalid is_listed")
            m["is_listed"] = data["is_listed"]
        bump(m)
        return ok(ser_menu_item(m))


@app.get("/api/restaurants/<rid>/menu-items")
def list_menu_items(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        r = restaurants.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        limit, offset, e = parse_pagination()
        if e:
            return e
        is_listed_q = request.args.get("is_listed")
        items = [m for m in menu_items.values() if m["restaurant_id"] == rid]
        if is_listed_q is not None:
            v = is_listed_q.lower() == "true"
            items = [m for m in items if m["is_listed"] == v]
        window, total = apply_page(items, limit, offset)
        return ok_list([ser_menu_item(m) for m in window], total, limit, offset)


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------
@app.post("/api/riders")
def post_rider():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        data = body_json()
        name = data.get("name")
        phone = data.get("phone")
        if not isinstance(name, str) or not name:
            return err("ERR_VALIDATION", "invalid name")
        if not isinstance(phone, str) or not phone:
            return err("ERR_VALIDATION", "invalid phone")
        for existing in riders.values():
            if existing["phone"] == phone:
                return err("ERR_VALIDATION", "phone already registered")
        now = now_iso()
        rid = new_id()
        r = {
            "id": rid,
            "name": name,
            "phone": phone,
            "status": "OFFLINE",
            "on_time_rate": 1.0,
            "acceptance_rate": 1.0,
            "rating": 5.0,
            "wallet_balance_cents": 0,
            "bonus_tier": "BRONZE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        riders[rid] = r
        rider_offer_history[rid] = []
        rider_delivery_history[rid] = []
        return ok(ser_rider(r), status=201)


@app.get("/api/riders/<rid>")
def get_rider(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        r = riders.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if role == "Rider" and uid != rid:
            return err("ERR_FORBIDDEN")
        return ok(ser_rider(r))


@app.post("/api/riders/<rid>/go-online")
def rider_go_online(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        r = riders.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if uid != rid:
            return err("ERR_FORBIDDEN")
        if r["status"] != "OFFLINE":
            return err("ERR_INVALID_STATE")
        r["status"] = "AVAILABLE"
        bump(r)
        return ok(ser_rider(r))


@app.post("/api/riders/<rid>/go-offline")
def rider_go_offline(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        r = riders.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if uid != rid:
            return err("ERR_FORBIDDEN")
        if r["status"] != "AVAILABLE":
            return err("ERR_INVALID_STATE")
        # no active assignments
        for a in assignments.values():
            if a["rider_id"] == rid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
                return err("ERR_INVALID_STATE")
        r["status"] = "OFFLINE"
        bump(r)
        return ok(ser_rider(r))


@app.post("/api/riders/<rid>/suspend")
def rider_suspend(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        r = riders.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "AVAILABLE":
            return err("ERR_INVALID_STATE")
        if not (r["on_time_rate"] < 0.70 or r["acceptance_rate"] < 0.50):
            return err("ERR_SUSPEND_CRITERIA_NOT_MET")
        r["status"] = "SUSPENDED"
        bump(r)
        return ok(ser_rider(r))


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------
@app.post("/api/customers")
def post_customer():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        data = body_json()
        name = data.get("name")
        phone = data.get("phone")
        address = data.get("address")
        lat = data.get("lat")
        lng = data.get("lng")
        if not isinstance(name, str) or not name:
            return err("ERR_VALIDATION", "invalid name")
        if not isinstance(phone, str) or not phone:
            return err("ERR_VALIDATION", "invalid phone")
        if not isinstance(address, str) or not address:
            return err("ERR_VALIDATION", "invalid address")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            return err("ERR_VALIDATION", "invalid coordinates")
        for existing in customers.values():
            if existing["phone"] == phone:
                return err("ERR_VALIDATION", "phone already registered")
        now = now_iso()
        cid = new_id()
        c = {
            "id": cid,
            "name": name,
            "phone": phone,
            "address": address,
            "lat": float(lat),
            "lng": float(lng),
            "credit_balance_cents": 0,
            "trust_score": 1.0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        customers[cid] = c
        return ok(ser_customer(c), status=201)


@app.get("/api/customers/<cid>")
def get_customer(cid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        c = customers.get(cid)
        if not c:
            return err("ERR_NOT_FOUND")
        if role == "Customer" and uid != cid:
            return err("ERR_FORBIDDEN")
        return ok(ser_customer(c))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@app.post("/api/orders")
def place_order():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Customer":
            return err("ERR_FORBIDDEN")
        data = body_json()
        customer_id = data.get("customer_id")
        restaurant_id = data.get("restaurant_id")
        items = data.get("items")
        # FK existence checks (priority 4)
        if not customer_id or customer_id not in customers:
            return err("ERR_NOT_FOUND", "customer not found")
        if not restaurant_id or restaurant_id not in restaurants:
            return err("ERR_NOT_FOUND", "restaurant not found")
        if not isinstance(items, list):
            return err("ERR_ORDER_INVALID", "items must be a list")
        for it in items:
            if not isinstance(it, dict):
                return err("ERR_ORDER_INVALID", "invalid item")
            mid = it.get("menu_item_id")
            if not mid or mid not in menu_items:
                return err("ERR_NOT_FOUND", "menu_item not found")
        # Identity match - customer
        if uid != customer_id:
            return err("ERR_FORBIDDEN")
        # Domain: restaurant ACTIVE and menu items listed + belong to restaurant
        rest = restaurants[restaurant_id]
        if rest["status"] != "ACTIVE":
            return err("ERR_RESTAURANT_UNAVAILABLE")
        for it in items:
            m = menu_items[it["menu_item_id"]]
            if m["restaurant_id"] != restaurant_id or not m["is_listed"]:
                return err("ERR_RESTAURANT_UNAVAILABLE")
        # Shape: items non-empty
        if len(items) == 0:
            return err("ERR_ORDER_INVALID", "items must be non-empty")
        subtotal = 0
        frozen_items = []
        for it in items:
            q = it.get("quantity", 0)
            if not isinstance(q, int) or isinstance(q, bool) or q < 1:
                return err("ERR_ORDER_INVALID", "invalid quantity")
            m = menu_items[it["menu_item_id"]]
            up = m["price_cents"]
            subtotal += up * q
            frozen_items.append(
                {
                    "menu_item_id": m["id"],
                    "name": m["name"],
                    "unit_price_cents": up,
                    "quantity": q,
                }
            )
        if subtotal < 100:
            return err("ERR_ORDER_INVALID", "subtotal below minimum")
        customer = customers[customer_id]
        dist_raw = haversine_km(rest["lat"], rest["lng"], customer["lat"], customer["lng"])
        dist = round1(dist_raw)
        now_dt = now_utc()
        peak = is_peak_time(now_dt)
        prov_fee = delivery_fee_solo(dist, peak)
        prov_comm = tiered_commission_cents(subtotal)
        promised = now_dt + timedelta(minutes=45)
        # Payment - draw credit first, then authorize remainder
        if customer["credit_balance_cents"] > 0:
            # draw down but we don't track payment amounts; just reduce credit balance
            customer["credit_balance_cents"] = max(
                0, customer["credit_balance_cents"] - (subtotal + prov_fee)
            )
            bump(customer)
        oid = new_id()
        now = now_iso()
        o = {
            "id": oid,
            "customer_id": customer_id,
            "restaurant_id": restaurant_id,
            "items": frozen_items,
            "subtotal_cents": subtotal,
            "distance_km": dist,
            "is_peak": peak,
            "promised_delivery_time": fmt_ts(promised),
            "actual_delivery_time": None,
            "minutes_late": None,
            "provisional_delivery_fee_cents": prov_fee,
            "final_delivery_fee_cents": None,
            "provisional_commission_cents": prov_comm,
            "final_commission_cents": None,
            "status": "PLACED",
            "payment_status": "AUTHORIZED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        orders[oid] = o
        return ok(ser_order(o), status=201)


@app.get("/api/orders/<oid>")
def get_order(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if role == "Customer" and uid != o["customer_id"]:
            return err("ERR_FORBIDDEN")
        if role == "Restaurant" and uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        if role == "Rider":
            # rider can read if they have an assignment for this order
            has = any(a for a in assignments.values() if a["order_id"] == oid and a["rider_id"] == uid)
            if not has:
                return err("ERR_FORBIDDEN")
        return ok(ser_order(o))


@app.get("/api/orders")
def list_orders():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        limit, offset, e = parse_pagination()
        if e:
            return e
        customer_id = request.args.get("customer_id")
        restaurant_id = request.args.get("restaurant_id")
        rider_id = request.args.get("rider_id")
        status_q = request.args.get("status")
        items = list(orders.values())
        if customer_id:
            items = [o for o in items if o["customer_id"] == customer_id]
        if restaurant_id:
            items = [o for o in items if o["restaurant_id"] == restaurant_id]
        if rider_id:
            order_ids = {a["order_id"] for a in assignments.values() if a["rider_id"] == rider_id}
            items = [o for o in items if o["id"] in order_ids]
        if status_q:
            items = [o for o in items if o["status"] == status_q]
        # Role scoping
        if role == "Customer":
            items = [o for o in items if o["customer_id"] == uid]
        elif role == "Restaurant":
            items = [o for o in items if o["restaurant_id"] == uid]
        elif role == "Rider":
            rider_order_ids = {a["order_id"] for a in assignments.values() if a["rider_id"] == uid}
            items = [o for o in items if o["id"] in rider_order_ids]
        window, total = apply_page(items, limit, offset)
        return ok_list([ser_order(o) for o in window], total, limit, offset)


@app.post("/api/orders/<oid>/accept")
def order_accept(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Restaurant":
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        if o["status"] != "PLACED":
            return err("ERR_INVALID_STATE")
        rest = restaurants[o["restaurant_id"]]
        if rest["status"] != "ACTIVE":
            return err("ERR_RESTAURANT_UNAVAILABLE")
        o["status"] = "RESTAURANT_ACCEPTED"
        bump(o)
        return ok(ser_order(o))


@app.post("/api/orders/<oid>/cancel")
def order_cancel(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"Customer", "Restaurant", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if role == "Customer" and uid != o["customer_id"]:
            return err("ERR_FORBIDDEN")
        if role == "Restaurant" and uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        if o["status"] != "PLACED":
            return err("ERR_INVALID_STATE")
        o["status"] = "CANCELLED"
        if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
            o["payment_status"] = "VOIDED"
        bump(o)
        return ok(ser_order(o))


@app.post("/api/orders/<oid>/start-preparing")
def order_start_preparing(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Restaurant":
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        if o["status"] != "RESTAURANT_ACCEPTED":
            return err("ERR_INVALID_STATE")
        o["status"] = "PREPARING"
        bump(o)
        # open dispatch
        create_dispatch_for_order(o)
        return ok(ser_order(o))


@app.post("/api/orders/<oid>/ready")
def order_ready(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Restaurant":
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        if o["status"] != "PREPARING":
            return err("ERR_INVALID_STATE")
        # rider must have ACCEPTED or PICKED_UP
        has_rider = any(
            a for a in assignments.values()
            if a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
        )
        if not has_rider:
            return err("ERR_INVALID_STATE")
        o["status"] = "READY_FOR_PICKUP"
        bump(o)
        return ok(ser_order(o))


@app.post("/api/orders/<oid>/dispatch")
def order_dispatch(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            return err("ERR_INVALID_STATE")
        # no existing active assignment
        for a in assignments.values():
            if a["order_id"] == oid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
                return err("ERR_ORDER_ALREADY_ASSIGNED")
        a = create_dispatch_for_order(o)
        if not a:
            return err("ERR_INVALID_STATE", "no riders available")
        return ok(ser_assignment(a), status=201)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------
@app.post("/api/orders/<oid>/returns")
def open_return(oid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Customer":
            return err("ERR_FORBIDDEN")
        o = orders.get(oid)
        if not o:
            return err("ERR_NOT_FOUND")
        if uid != o["customer_id"]:
            return err("ERR_FORBIDDEN")
        data = body_json()
        reason = data.get("reason")
        requested = data.get("requested_refund_cents")
        if o["status"] != "DELIVERED":
            return err("ERR_INVALID_STATE")
        # duplicate check
        for r in returns_.values():
            if r["order_id"] == oid and r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
                return err("ERR_DUPLICATE_RETURN")
        # window check
        if not o["actual_delivery_time"]:
            return err("ERR_RETURN_WINDOW_EXPIRED")
        adt = datetime.strptime(o["actual_delivery_time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        if (now_utc() - adt) > timedelta(hours=24):
            return err("ERR_RETURN_WINDOW_EXPIRED")
        if (
            not isinstance(requested, int)
            or isinstance(requested, bool)
            or requested < 1
            or requested > o["subtotal_cents"]
        ):
            return err("ERR_REFUND_AMOUNT_INVALID")
        if reason not in ("QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"):
            return err("ERR_VALIDATION", "invalid reason")
        rid = new_id()
        now = now_iso()
        ret = {
            "id": rid,
            "order_id": oid,
            "reason": reason,
            "requested_refund_cents": requested,
            "approved_refund_cents": None,
            "reviewer_cs_user_id": None,
            "status": "REQUESTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        returns_[rid] = ret
        o["status"] = "REFUND_REQUESTED"
        bump(o)
        return ok(ser_return(ret), status=201)


@app.get("/api/returns/<rid>")
def get_return(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Customer", "Restaurant", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        r = returns_.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        o = orders.get(r["order_id"])
        if role == "Customer" and o and uid != o["customer_id"]:
            return err("ERR_FORBIDDEN")
        if role == "Restaurant" and o and uid != o["restaurant_id"]:
            return err("ERR_FORBIDDEN")
        return ok(ser_return(r))


@app.post("/api/returns/<rid>/approve")
def return_approve(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "CustomerService":
            return err("ERR_FORBIDDEN")
        r = returns_.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] not in ("REQUESTED", "ESCALATED"):
            return err("ERR_INVALID_STATE")
        data = body_json()
        approved = data.get("approved_refund_cents")
        o = orders[r["order_id"]]
        if (
            not isinstance(approved, int)
            or isinstance(approved, bool)
            or approved < 1
            or approved > o["subtotal_cents"]
            or approved > r["requested_refund_cents"]
        ):
            return err("ERR_REFUND_AMOUNT_INVALID")
        r["status"] = "APPROVED"
        r["approved_refund_cents"] = approved
        r["reviewer_cs_user_id"] = uid
        bump(r)
        # cascade: order -> REFUNDED, payment_status
        o["status"] = "REFUNDED"
        if approved == o["subtotal_cents"]:
            o["payment_status"] = "FULLY_REFUNDED"
        else:
            o["payment_status"] = "PARTIALLY_REFUNDED"
        bump(o)
        # customer credit
        customer = customers[o["customer_id"]]
        customer["credit_balance_cents"] += approved
        bump(customer)
        # restaurant pending settlement
        rest = restaurants[o["restaurant_id"]]
        rest["pending_settlement_cents"] -= approved
        bump(rest)
        # Close linked work order if escalated
        for w in work_orders.values():
            if w.get("related_return_id") == rid and w["status"] != "CLOSED":
                # No auto-close for approve, spec says reopen closes it, not approve
                pass
        # abusive return fine
        if customer["trust_score"] < 0.5 and r["reason"] == "QUALITY_ISSUE":
            fid = new_id()
            f = {
                "id": fid,
                "subject_type": "CUSTOMER",
                "subject_id": customer["id"],
                "reason": "ABUSIVE_RETURN",
                "amount_cents": approved,
                "settlement_status": "PENDING",
                "created_at": now_iso(),
            }
            fines[fid] = f
        return ok(ser_return(r))


@app.post("/api/returns/<rid>/reject")
def return_reject(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "CustomerService":
            return err("ERR_FORBIDDEN")
        r = returns_.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] not in ("REQUESTED", "ESCALATED"):
            return err("ERR_INVALID_STATE")
        r["status"] = "REJECTED"
        r["reviewer_cs_user_id"] = uid
        bump(r)
        o = orders[r["order_id"]]
        o["status"] = "DELIVERED"
        bump(o)
        return ok(ser_return(r))


@app.post("/api/returns/<rid>/escalate")
def return_escalate(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "CustomerService":
            return err("ERR_FORBIDDEN")
        r = returns_.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "REQUESTED":
            return err("ERR_INVALID_STATE")
        r["status"] = "ESCALATED"
        bump(r)
        # open work order
        wid = new_id()
        now = now_iso()
        w = {
            "id": wid,
            "opened_by_role": "CUSTOMER_SERVICE",
            "opened_by_id": uid,
            "category": "OTHER",
            "related_order_id": r["order_id"],
            "related_return_id": rid,
            "assigned_cs_user_id": None,
            "resolution_notes": None,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        work_orders[wid] = w
        return ok(ser_return(r))


@app.post("/api/returns/<rid>/reopen")
def return_reopen(rid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "CustomerService":
            return err("ERR_FORBIDDEN")
        r = returns_.get(rid)
        if not r:
            return err("ERR_NOT_FOUND")
        if r["status"] != "ESCALATED":
            return err("ERR_INVALID_STATE")
        r["status"] = "REQUESTED"
        bump(r)
        # close linked work order
        for w in work_orders.values():
            if w.get("related_return_id") == rid and w["status"] not in ("CLOSED",):
                w["status"] = "CLOSED"
                bump(w)
        return ok(ser_return(r))


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------
@app.get("/api/assignments/<aid>")
def get_assignment(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "Rider", "CustomerService"}:
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if role == "Rider" and uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        return ok(ser_assignment(a))


@app.post("/api/assignments/<aid>/accept")
def assignment_accept(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        if a["status"] != "OFFERED":
            return err("ERR_INVALID_STATE")
        rider = riders[a["rider_id"]]
        if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            return err("ERR_INVALID_STATE")
        order = orders.get(a["order_id"])
        if not order:
            return err("ERR_NOT_FOUND")
        if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            return err("ERR_INVALID_STATE")
        # uniqueness: no other active assignment for this order
        for other in assignments.values():
            if (
                other["id"] != aid
                and other["order_id"] == a["order_id"]
                and other["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
            ):
                return err("ERR_ORDER_ALREADY_ASSIGNED")
        a["status"] = "ACCEPTED"
        a["accepted_at"] = now_iso()
        rider_offer_history.setdefault(rider["id"], []).append("ACCEPTED")
        # route merge
        rest = restaurants.get(order["restaurant_id"])
        merge_peer = None
        for other in assignments.values():
            if (
                other["id"] != aid
                and other["rider_id"] == rider["id"]
                and other["status"] in ("ACCEPTED",)
            ):
                peer_order = orders.get(other["order_id"])
                if not peer_order:
                    continue
                peer_rest = restaurants.get(peer_order["restaurant_id"])
                if not peer_rest or not rest:
                    continue
                d = haversine_km(rest["lat"], rest["lng"], peer_rest["lat"], peer_rest["lng"])
                if d <= 0.5:
                    merge_peer = other
                    break
        if merge_peer:
            # find or create route group
            group = None
            if merge_peer.get("route_group_id"):
                group = route_groups.get(merge_peer["route_group_id"])
            if group:
                if a["id"] not in group["assignment_ids"]:
                    group["assignment_ids"].append(a["id"])
                a["route_group_id"] = group["id"]
            else:
                gid = new_id()
                now = now_iso()
                group = {
                    "id": gid,
                    "rider_id": rider["id"],
                    "assignment_ids": [merge_peer["id"], a["id"]],
                    "merged_at": now,
                    "status": "ACTIVE",
                    "created_at": now,
                }
                route_groups[gid] = group
                merge_peer["route_group_id"] = gid
                a["route_group_id"] = gid
        # rider status
        if rider["status"] == "AVAILABLE":
            rider["status"] = "ON_DELIVERY"
        recompute_rider_metrics(rider)
        bump(rider)
        return ok(ser_assignment(a))


@app.post("/api/assignments/<aid>/reject")
def assignment_reject(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        if a["status"] != "OFFERED":
            return err("ERR_INVALID_STATE")
        a["status"] = "REJECTED"
        rider = riders[a["rider_id"]]
        rider_offer_history.setdefault(rider["id"], []).append("REJECTED")
        recompute_rider_metrics(rider)
        bump(rider)
        # redispatch
        order = orders.get(a["order_id"])
        if order and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            create_dispatch_for_order(order, exclude_rider_ids={rider["id"]})
        return ok(ser_assignment(a))


@app.post("/api/assignments/<aid>/pickup")
def assignment_pickup(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        if a["status"] != "ACCEPTED":
            return err("ERR_INVALID_STATE")
        order = orders[a["order_id"]]
        if order["status"] != "READY_FOR_PICKUP":
            return err("ERR_INVALID_STATE")
        a["status"] = "PICKED_UP"
        a["picked_up_at"] = now_iso()
        order["status"] = "PICKED_UP"
        bump(order)
        return ok(ser_assignment(a))


@app.post("/api/assignments/<aid>/deliver")
def assignment_deliver(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        if a["status"] != "PICKED_UP":
            return err("ERR_INVALID_STATE")
        order = orders[a["order_id"]]
        if order["status"] != "PICKED_UP":
            return err("ERR_INVALID_STATE")
        now = now_utc()
        delivered_iso = fmt_ts(now)
        a["status"] = "DELIVERED"
        a["delivered_at"] = delivered_iso
        order["actual_delivery_time"] = delivered_iso
        promised_dt = datetime.strptime(order["promised_delivery_time"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        delta_seconds = (now - promised_dt).total_seconds()
        minutes_late = max(0, int(delta_seconds // 60))
        order["minutes_late"] = minutes_late
        # final delivery fee
        solo = delivery_fee_solo(order["distance_km"], order["is_peak"])
        rg = None
        if a.get("route_group_id"):
            rg = route_groups.get(a["route_group_id"])
        if rg and len(rg["assignment_ids"]) >= 2:
            discount = int(solo * Decimal("0.25"))  # floor
            final_fee = solo - discount
        else:
            final_fee = solo
        order["final_delivery_fee_cents"] = final_fee
        a["final_delivery_fee_cents"] = final_fee
        # final commission
        rest = restaurants[order["restaurant_id"]]
        if rest["commission_rate_override"] is not None:
            final_comm = flat_commission_cents(order["subtotal_cents"], rest["commission_rate_override"])
        else:
            final_comm = tiered_commission_cents(order["subtotal_cents"])
        order["final_commission_cents"] = final_comm
        # payment captured
        order["payment_status"] = "CAPTURED"
        order["status"] = "DELIVERED"
        bump(order)
        # late fine
        if minutes_late > 0:
            fine_amt = late_fine_amount(minutes_late, final_fee)
            fid = new_id()
            f = {
                "id": fid,
                "subject_type": "RIDER",
                "subject_id": a["rider_id"],
                "reason": "LATE_DELIVERY",
                "amount_cents": fine_amt,
                "settlement_status": "PENDING",
                "created_at": now_iso(),
            }
            fines[fid] = f
            rider = riders[a["rider_id"]]
            rider["wallet_balance_cents"] -= fine_amt
            # recompute metrics/tier
            rider_delivery_history.setdefault(rider["id"], []).append(False)
            recompute_rider_metrics(rider)
            bump(rider)
        else:
            rider = riders[a["rider_id"]]
            rider_delivery_history.setdefault(rider["id"], []).append(True)
            recompute_rider_metrics(rider)
        # restaurant pending settlement
        rest["pending_settlement_cents"] += order["subtotal_cents"] - final_comm
        bump(rest)
        # rider wallet credit + tier recompute (final recompute after delivery)
        rider = riders[a["rider_id"]]
        rider["wallet_balance_cents"] += final_fee
        recompute_rider_metrics(rider)
        # rider status transition
        has_other_active = any(
            x for x in assignments.values()
            if x["id"] != a["id"] and x["rider_id"] == rider["id"]
            and x["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        )
        if not has_other_active:
            rider["status"] = "AVAILABLE"
        bump(rider)
        # route group completion
        if rg:
            if all(assignments[aid2]["status"] == "DELIVERED" for aid2 in rg["assignment_ids"]):
                rg["status"] = "COMPLETED"
        return ok(ser_assignment(a))


@app.post("/api/assignments/<aid>/cancel")
def assignment_cancel(aid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "Rider":
            return err("ERR_FORBIDDEN")
        a = assignments.get(aid)
        if not a:
            return err("ERR_NOT_FOUND")
        if uid != a["rider_id"]:
            return err("ERR_FORBIDDEN")
        if a["status"] != "ACCEPTED":
            return err("ERR_INVALID_STATE")
        order = orders[a["order_id"]]
        if order["status"] == "PICKED_UP":
            return err("ERR_INVALID_STATE")
        a["status"] = "CANCELLED"
        # create no-show fine
        fid = new_id()
        rider = riders[a["rider_id"]]
        f = {
            "id": fid,
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "RIDER_NO_SHOW",
            "amount_cents": 500,
            "settlement_status": "PENDING",
            "created_at": now_iso(),
        }
        fines[fid] = f
        rider["wallet_balance_cents"] -= 500
        recompute_rider_metrics(rider)
        # rider back to available if no other active
        has_other_active = any(
            x for x in assignments.values()
            if x["id"] != a["id"] and x["rider_id"] == rider["id"]
            and x["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        )
        if not has_other_active and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
        bump(rider)
        # redispatch
        if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            create_dispatch_for_order(order, exclude_rider_ids={rider["id"]})
        return ok(ser_assignment(a))


# ---------------------------------------------------------------------------
# Fines
# ---------------------------------------------------------------------------
@app.get("/api/fines/<fid>")
def get_fine(fid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"}:
            return err("ERR_FORBIDDEN")
        f = fines.get(fid)
        if not f:
            return err("ERR_NOT_FOUND")
        if role == "Rider" and (f["subject_type"] != "RIDER" or f["subject_id"] != uid):
            return err("ERR_FORBIDDEN")
        if role == "Restaurant" and (f["subject_type"] != "RESTAURANT" or f["subject_id"] != uid):
            return err("ERR_FORBIDDEN")
        if role == "Customer" and (f["subject_type"] != "CUSTOMER" or f["subject_id"] != uid):
            return err("ERR_FORBIDDEN")
        return ok(ser_fine(f))


@app.get("/api/fines")
def list_fines():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"}:
            return err("ERR_FORBIDDEN")
        limit, offset, e = parse_pagination()
        if e:
            return e
        st = request.args.get("subject_type")
        sid = request.args.get("subject_id")
        ss = request.args.get("settlement_status")
        # ownership for subject-type roles
        if role == "Rider":
            if sid and sid != uid:
                return err("ERR_FORBIDDEN")
            sid = uid
            st = "RIDER"
        elif role == "Restaurant":
            if sid and sid != uid:
                return err("ERR_FORBIDDEN")
            sid = uid
            st = "RESTAURANT"
        elif role == "Customer":
            if sid and sid != uid:
                return err("ERR_FORBIDDEN")
            sid = uid
            st = "CUSTOMER"
        items = list(fines.values())
        if st:
            items = [f for f in items if f["subject_type"] == st]
        if sid:
            items = [f for f in items if f["subject_id"] == sid]
        if ss:
            items = [f for f in items if f["settlement_status"] == ss]
        window, total = apply_page(items, limit, offset)
        return ok_list([ser_fine(f) for f in window], total, limit, offset)


@app.post("/api/fines/<fid>/waive")
def fine_waive(fid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        f = fines.get(fid)
        if not f:
            return err("ERR_NOT_FOUND")
        if f["settlement_status"] != "PENDING":
            return err("ERR_INVALID_STATE")
        f["settlement_status"] = "WAIVED"
        # reverse
        if f["subject_type"] == "RIDER":
            rider = riders.get(f["subject_id"])
            if rider:
                rider["wallet_balance_cents"] += f["amount_cents"]
                recompute_rider_metrics(rider)
                bump(rider)
        elif f["subject_type"] == "CUSTOMER":
            c = customers.get(f["subject_id"])
            if c:
                c["credit_balance_cents"] += f["amount_cents"]
                bump(c)
        elif f["subject_type"] == "RESTAURANT":
            r = restaurants.get(f["subject_id"])
            if r:
                r["pending_settlement_cents"] += f["amount_cents"]
                bump(r)
        return ok(ser_fine(f))


# ---------------------------------------------------------------------------
# Work Orders
# ---------------------------------------------------------------------------
@app.post("/api/work-orders")
def create_work_order():
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"Customer", "Rider", "Restaurant", "CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        data = body_json()
        opened_by_role = data.get("opened_by_role")
        opened_by_id = data.get("opened_by_id")
        category = data.get("category")
        related_order_id = data.get("related_order_id")
        related_return_id = data.get("related_return_id")
        if opened_by_role not in {"CUSTOMER", "RIDER", "RESTAURANT", "CUSTOMER_SERVICE"}:
            return err("ERR_VALIDATION", "invalid opened_by_role")
        if category not in {
            "DELIVERY_LATE", "FOOD_QUALITY", "MISSING_ITEM",
            "RIDER_BEHAVIOR", "RESTAURANT_BEHAVIOR", "PAYMENT_ISSUE", "OTHER",
        }:
            return err("ERR_VALIDATION", "invalid category")
        if related_order_id and related_order_id not in orders:
            return err("ERR_NOT_FOUND")
        if related_return_id and related_return_id not in returns_:
            return err("ERR_NOT_FOUND")
        # identity match - opened_by_id must equal uid when role maps
        role_map = {
            "CUSTOMER": "Customer",
            "RIDER": "Rider",
            "RESTAURANT": "Restaurant",
            "CUSTOMER_SERVICE": "CustomerService",
        }
        expected_role = role_map.get(opened_by_role)
        if role != expected_role and role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        if role in ("Customer", "Rider", "Restaurant") and uid != opened_by_id:
            return err("ERR_FORBIDDEN")
        wid = new_id()
        now = now_iso()
        w = {
            "id": wid,
            "opened_by_role": opened_by_role,
            "opened_by_id": opened_by_id,
            "category": category,
            "related_order_id": related_order_id,
            "related_return_id": related_return_id,
            "assigned_cs_user_id": None,
            "resolution_notes": None,
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        work_orders[wid] = w
        return ok(ser_work_order(w), status=201)


@app.get("/api/work-orders/<wid>")
def get_work_order(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"PlatformAdmin", "CustomerService", "Customer", "Rider", "Restaurant"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        role_map = {
            "CUSTOMER": "Customer",
            "RIDER": "Rider",
            "RESTAURANT": "Restaurant",
        }
        if role in ("Customer", "Rider", "Restaurant"):
            if role_map.get(w["opened_by_role"]) != role or uid != w["opened_by_id"]:
                return err("ERR_FORBIDDEN")
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/assign")
def work_order_assign(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if w["status"] != "OPEN":
            return err("ERR_INVALID_STATE")
        w["status"] = "UNDER_REVIEW"
        w["assigned_cs_user_id"] = uid
        bump(w)
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/request-info")
def work_order_request_info(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if w["status"] != "UNDER_REVIEW":
            return err("ERR_INVALID_STATE")
        w["status"] = "AWAITING_INFO"
        bump(w)
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/submit-info")
def work_order_submit_info(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"Customer", "Rider", "Restaurant"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if uid != w["opened_by_id"]:
            return err("ERR_FORBIDDEN")
        if w["status"] != "AWAITING_INFO":
            return err("ERR_INVALID_STATE")
        w["status"] = "UNDER_REVIEW"
        bump(w)
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/resolve")
def work_order_resolve(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if w["status"] not in ("UNDER_REVIEW", "ESCALATED"):
            return err("ERR_INVALID_STATE")
        if not w["assigned_cs_user_id"]:
            return err("ERR_INVALID_STATE")
        data = body_json()
        notes = data.get("resolution_notes")
        if not isinstance(notes, str) or not notes:
            return err("ERR_VALIDATION", "resolution_notes required")
        if w.get("related_return_id"):
            r = returns_.get(w["related_return_id"])
            if r and r["status"] not in ("APPROVED", "REJECTED"):
                return err("ERR_RELATED_RETURN_UNRESOLVED")
        w["status"] = "RESOLVED"
        w["resolution_notes"] = notes
        bump(w)
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/escalate")
def work_order_escalate(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if w["status"] != "UNDER_REVIEW":
            return err("ERR_INVALID_STATE")
        w["status"] = "ESCALATED"
        bump(w)
        return ok(ser_work_order(w))


@app.post("/api/work-orders/<wid>/close")
def work_order_close(wid):
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role not in {"CustomerService", "PlatformAdmin"}:
            return err("ERR_FORBIDDEN")
        w = work_orders.get(wid)
        if not w:
            return err("ERR_NOT_FOUND")
        if w["status"] != "RESOLVED":
            return err("ERR_INVALID_STATE")
        w["status"] = "CLOSED"
        bump(w)
        return ok(ser_work_order(w))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.post("/api/_clock/advance")
def clock_advance():
    global _clock_offset
    with _lock:
        uid, role, e = get_auth()
        if e:
            return e
        if role != "PlatformAdmin":
            return err("ERR_FORBIDDEN")
        data = body_json()
        seconds = data.get("seconds")
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
            return err("ERR_VALIDATION", "invalid seconds")
        _clock_offset += timedelta(seconds=seconds)
        # sweep offer timeouts
        now = now_utc()
        for a in list(assignments.values()):
            if a["status"] == "OFFERED":
                offered_dt = datetime.strptime(
                    a["offered_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
                ).replace(tzinfo=timezone.utc)
                if (now - offered_dt).total_seconds() >= 60:
                    a["status"] = "REJECTED"
                    rider = riders.get(a["rider_id"])
                    if rider:
                        rider_offer_history.setdefault(rider["id"], []).append("REJECTED")
                        recompute_rider_metrics(rider)
                        bump(rider)
                    order = orders.get(a["order_id"])
                    if order and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                        create_dispatch_for_order(
                            order, exclude_rider_ids={a["rider_id"]}
                        )
        return ok({"clock_offset_seconds": int(_clock_offset.total_seconds())})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/")
def health():
    return ok({"status": "ok"})


@app.errorhandler(404)
def not_found(_e):
    return err("ERR_NOT_FOUND")


@app.errorhandler(405)
def method_not_allowed(_e):
    return err("ERR_NOT_FOUND")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
