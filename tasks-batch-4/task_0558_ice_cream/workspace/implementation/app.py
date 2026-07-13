"""Ice Cream / Frozen Dessert Shop API — Flask reference implementation.

In-memory only. State is wiped on every process start (per-test-server isolation).
No entity data is seeded at startup.
"""
import os
import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

from errors import ApiError

app = Flask(__name__)

# --------------------------------------------------------------------------
# Constants (from PRD / scaffold)
# --------------------------------------------------------------------------
SCOOP_VOLUME_ML = 90
TAX_RATE = Decimal("0.0875")
SEASONAL_SURCHARGE_CENTS_PER_SCOOP = 40
SHRINK_ALLOWANCE_PCT = Decimal("0.05")
PUNCH_THRESHOLD = 10
DEPOSIT_PCT = Decimal("0.20")
CATERING_RATE_CENTS_PER_ML = 2
STATION_CLEAN_BUFFER = timedelta(minutes=30)

ROLES = {"Manager", "ShiftLead", "Scooper", "Baker"}
ALL_ROLES = set(ROLES)

WASTE_TYPES = {"MELT", "SPILLAGE", "TRIM_SHRINK", "EXPIRED_DISCARD"}
MEASURED_SHRINK_TYPES = {"MELT", "SPILLAGE", "TRIM_SHRINK"}

# --------------------------------------------------------------------------
# In-memory store
# --------------------------------------------------------------------------
DB = {
    "flavors": {},
    "size_options": {},
    "toppings": {},
    "event_carts": {},
    "decorating_stations": {},
    "loyalty_accounts": {},
    "drawers": {},
    "batches": {},
    "waste_events": {},
    "orders": {},
    "order_lines": {},
    "pre_orders": {},
    "catering_bookings": {},
}
STATE = {"seq": 0}
LOCK = threading.RLock()


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


STATE["clock"] = parse_dt("2026-05-01T00:00:00Z")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def dec(x):
    return Decimal(str(x))


def rhu(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def base(extra, versioned=True):
    now = now_iso()
    d = {"id": new_id(), "created_at": now, "_seq": next_seq()}
    if versioned:
        d["updated_at"] = now
        d["version"] = 1
    d.update(extra)
    return d


def mark(res):
    if res is not None:
        g._dirty[id(res)] = res


def flush_dirty():
    for r in g._dirty.values():
        r["updated_at"] = now_iso()
        r["version"] = r.get("version", 1) + 1
    g._dirty = {}


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, code=200, response_type="object", pagination=None):
    return (
        jsonify({"meta": _meta(pagination), "response_type": response_type, "data": data}),
        code,
    )


@app.errorhandler(ApiError)
def handle_api_error(e):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": e.error_id, "message": e.message},
            }
        ),
        e.http_status,
    )


@app.errorhandler(404)
def handle_404(e):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
            }
        ),
        404,
    )


@app.errorhandler(405)
def handle_405(e):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"},
            }
        ),
        405,
    )


@app.before_request
def _before():
    g._dirty = {}
    LOCK.acquire()


@app.teardown_request
def _teardown(exc):
    try:
        LOCK.release()
    except RuntimeError:
        pass


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authorize(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid authentication headers")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "role not permitted for this operation")
    return role


# --------------------------------------------------------------------------
# Body validation helpers
# --------------------------------------------------------------------------
def body_of():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return b


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 422, "%s is required" % field)
    return body[field]


def v_str(v, field):
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, "%s must be a non-empty string" % field)
    return v


def v_int(v, field, minv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, "%s must be an integer" % field)
    if minv is not None and v < minv:
        raise ApiError("ERR_VALIDATION", 422, "%s must be >= %s" % (field, minv))
    return v


def v_num(v, field, minv=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "%s must be a number" % field)
    if minv is not None and v < minv:
        raise ApiError("ERR_VALIDATION", 422, "%s must be >= %s" % (field, minv))
    return v


def v_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, "%s must be a boolean" % field)
    return v


def v_list(v, field):
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 422, "%s must be an array" % field)
    return v


def v_str_list(v, field):
    v_list(v, field)
    for e in v:
        if not isinstance(e, str) or e == "":
            raise ApiError("ERR_VALIDATION", 422, "%s must contain non-empty strings" % field)
    return v


# --------------------------------------------------------------------------
# Existence helpers
# --------------------------------------------------------------------------
def get_or_404(collection, ident, error_id):
    obj = DB[collection].get(ident)
    if obj is None:
        raise ApiError(error_id, 404, "%s not found" % ident)
    return obj


def fk_exists_if_str(collection, val, error_id):
    """Existence check for a body FK: only runs if val is a non-empty string."""
    if isinstance(val, str) and val != "":
        if val not in DB[collection]:
            raise ApiError(error_id, 404, "referenced resource not found")


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def get_pagination():
    lim = request.args.get("limit")
    off = request.args.get("offset")
    if lim is None:
        limit = 10
    else:
        try:
            limit = int(lim)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if off is None:
        offset = 0
    else:
        try:
            offset = int(off)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, serializer):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset : offset + limit]
    data = [serializer(x) for x in page]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success(data, 200, "array", pag)


# --------------------------------------------------------------------------
# Inventory volume helpers
# --------------------------------------------------------------------------
def remaining(b):
    return b["initial_volume_ml"] - b["committed"] - b["wasted"]


def headroom(b):
    return remaining(b) - b["reserved"]


def fifo_candidates(flavor_id):
    cands = [
        b
        for b in DB["batches"].values()
        if b["flavor_id"] == flavor_id and b["status"] == "AVAILABLE" and headroom(b) > 0
    ]
    cands.sort(key=lambda b: (b["_expiry_dt"], b["created_at"], b["_seq"]))
    return cands


def compute_allocations(flavor_id, need_ml):
    """Return FIFO draw list or raise ERR_INSUFFICIENT_BATCH_VOLUME. Does not mutate."""
    cands = fifo_candidates(flavor_id)
    total = sum(headroom(b) for b in cands)
    if total < need_ml:
        raise ApiError(
            "ERR_INSUFFICIENT_BATCH_VOLUME", 409, "insufficient batch volume for flavor"
        )
    allocs = []
    rem = need_ml
    for b in cands:
        if rem <= 0:
            break
        take = min(headroom(b), rem)
        if take > 0:
            allocs.append(
                {
                    "batch_id": b["id"],
                    "volume_ml": take,
                    "unit_cost_cents_per_ml": b["unit_cost_cents_per_ml"],
                }
            )
            rem -= take
    return allocs


def recompute_flavor_stock(flavor, cascade=True):
    total = sum(
        remaining(b)
        for b in DB["batches"].values()
        if b["flavor_id"] == flavor["id"] and b["status"] == "AVAILABLE"
    )
    par = flavor["par_level_ml"]
    if total == 0:
        status = "OUT_OF_STOCK"
    elif total < par:
        status = "BELOW_PAR"
    else:
        status = "IN_STOCK"
    changed = total != flavor["total_available_ml"] or status != flavor["stock_status"]
    flavor["total_available_ml"] = total
    flavor["stock_status"] = status
    if changed and cascade:
        mark(flavor)


def flavor_in_season(f, clock):
    if not f["is_seasonal"]:
        return True
    if f["_season_start"] is None or f["_season_end"] is None:
        return False
    return f["_season_start"] <= clock < f["_season_end"]


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def ser_flavor(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "allergens": list(f["allergens"]),
        "is_seasonal": f["is_seasonal"],
        "seasonal_start_utc": f["seasonal_start_utc"],
        "seasonal_end_utc": f["seasonal_end_utc"],
        "is_premium": f["is_premium"],
        "premium_surcharge_cents_per_scoop": f["premium_surcharge_cents_per_scoop"],
        "standard_cost_cents_per_ml": f["standard_cost_cents_per_ml"],
        "par_level_ml": f["par_level_ml"],
        "is_active": f["is_active"],
        "total_available_ml": f["total_available_ml"],
        "stock_status": f["stock_status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_size(s):
    return {
        "id": s["id"],
        "code": s["code"],
        "scoop_count": s["scoop_count"],
        "base_price_cents": s["base_price_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_topping(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "price_cents": t["price_cents"],
        "allergens": list(t["allergens"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_cart(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "capacity_ml": c["capacity_ml"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_station(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_loyalty(a):
    return {
        "id": a["id"],
        "phone": a["phone"],
        "allergen_restrictions": list(a["allergen_restrictions"]),
        "punches": a["punches"],
        "free_scoop_credits": a["free_scoop_credits"],
        "lifetime_scoops": a["lifetime_scoops"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_drawer(d):
    orders = [o for o in DB["orders"].values() if o["drawer_id"] == d["id"]]
    expected = (
        d["opening_float_cents"]
        + sum(o["cash_collected_cents"] for o in orders)
        - sum(o["cash_refunded_cents"] for o in orders)
    )
    gross = sum(o["total_cents"] for o in orders if o["status"] in ("PAID", "REFUNDED"))
    net = sum(o["total_cents"] for o in orders if o["status"] == "PAID")
    return {
        "id": d["id"],
        "opening_float_cents": d["opening_float_cents"],
        "expected_cash_cents": expected,
        "gross_sales_cents": gross,
        "net_sales_cents": net,
        "counted_cash_cents": d["counted_cash_cents"],
        "variance_cents": d["variance_cents"],
        "reconciliation_status": d["reconciliation_status"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_batch(b):
    rem = remaining(b)
    expected_shrink = rhu(dec(b["initial_volume_ml"]) * SHRINK_ALLOWANCE_PCT)
    actual_shrink = sum(
        w["volume_ml"]
        for w in DB["waste_events"].values()
        if w["batch_id"] == b["id"] and w["waste_type"] in MEASURED_SHRINK_TYPES
    )
    return {
        "id": b["id"],
        "flavor_id": b["flavor_id"],
        "initial_volume_ml": b["initial_volume_ml"],
        "unit_cost_cents_per_ml": b["unit_cost_cents_per_ml"],
        "produced_at": b["produced_at"],
        "expiry_at": b["expiry_at"],
        "remaining_volume_ml": rem,
        "reserved_volume_ml": b["reserved"],
        "committed_volume_ml": b["committed"],
        "wasted_volume_ml": b["wasted"],
        "expected_shrink_ml": expected_shrink,
        "actual_shrink_ml": actual_shrink,
        "shrink_variance_ml": actual_shrink - expected_shrink,
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_waste(w):
    return {
        "id": w["id"],
        "batch_id": w["batch_id"],
        "waste_type": w["waste_type"],
        "volume_ml": w["volume_ml"],
        "reason": w["reason"],
        "created_at": w["created_at"],
    }


def line_scoops(line):
    return line["scoops"]


def line_standard_cogs(line):
    flavor = DB["flavors"].get(line["flavor_id"])
    if flavor is None:
        return 0
    return rhu(dec(line["scoops"] * SCOOP_VOLUME_ML) * dec(flavor["standard_cost_cents_per_ml"]))


def line_actual_cogs(line):
    total = Decimal(0)
    for a in line["allocations"]:
        total += dec(a["volume_ml"]) * dec(a["unit_cost_cents_per_ml"])
    return rhu(total)


def ser_line(line):
    return {
        "id": line["id"],
        "order_id": line["order_id"],
        "size_option_id": line["size_option_id"],
        "flavor_id": line["flavor_id"],
        "topping_ids": list(line["topping_ids"]),
        "quantity": line["quantity"],
        "scoops": line["scoops"],
        "line_price_cents": line["line_price_cents"],
        "line_tax_cents": line["line_tax_cents"],
        "allergen_label": list(line["allergen_label"]),
        "allocations": [dict(a) for a in line["allocations"]],
        "standard_cogs_cents": line_standard_cogs(line),
        "actual_cogs_cents": line_actual_cogs(line),
        "status": line["status"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "drawer_id": o["drawer_id"],
        "loyalty_account_id": o["loyalty_account_id"],
        "payment_method": o["payment_method"],
        "subtotal_cents": o["subtotal_cents"],
        "tax_cents": o["tax_cents"],
        "total_cents": o["total_cents"],
        "tendered_cash_cents": o["tendered_cash_cents"],
        "change_cents": o["change_cents"],
        "cash_collected_cents": o["cash_collected_cents"],
        "cash_refunded_cents": o["cash_refunded_cents"],
        "standard_cogs_cents": o["standard_cogs_cents"],
        "actual_cogs_cents": o["actual_cogs_cents"],
        "punches_earned": o["punches_earned"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_preorder(p):
    flavor = DB["flavors"].get(p["flavor_id"])
    allergen_label = list(flavor["allergens"]) if flavor else []
    return {
        "id": p["id"],
        "flavor_id": p["flavor_id"],
        "decorating_station_id": p["decorating_station_id"],
        "customer_name": p["customer_name"],
        "is_custom": p["is_custom"],
        "custom_notes": p["custom_notes"],
        "decorate_start_utc": p["decorate_start_utc"],
        "decorate_end_utc": p["decorate_end_utc"],
        "pickup_utc": p["pickup_utc"],
        "quoted_price_cents": p["quoted_price_cents"],
        "deposit_cents": p["deposit_cents"],
        "final_price_cents": p["final_price_cents"],
        "refunded_cents": p["refunded_cents"],
        "allergen_label": allergen_label,
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_catering(c):
    return {
        "id": c["id"],
        "event_cart_id": c["event_cart_id"],
        "event_start_utc": c["event_start_utc"],
        "event_end_utc": c["event_end_utc"],
        "requested_items": [dict(i) for i in c["requested_items"]],
        "estimate_cents": c["estimate_cents"],
        "actual_items": [dict(i) for i in c["actual_items"]],
        "actual_cents": c["actual_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# --------------------------------------------------------------------------
# Order totals recompute
# --------------------------------------------------------------------------
def contributing_lines(order_id):
    return [
        l
        for l in DB["order_lines"].values()
        if l["order_id"] == order_id and l["status"] in ("ACTIVE", "COMMITTED")
    ]


def recompute_order_totals(order):
    lines = contributing_lines(order["id"])
    subtotal = sum(l["line_price_cents"] for l in lines)
    tax = sum(l["line_tax_cents"] for l in lines)
    order["subtotal_cents"] = subtotal
    order["tax_cents"] = tax
    order["total_cents"] = subtotal + tax
    order["punches_earned"] = sum(l["scoops"] for l in lines)


# ==========================================================================
# CLOCK
# ==========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    authorize(ALL_ROLES)
    body = body_of()
    to_iso = require_present(body, "to_iso8601")
    STATE["clock"] = parse_dt(to_iso)
    return success({}, 200, "object")


# ==========================================================================
# FLAVOR
# ==========================================================================
@app.post("/flavors")
def create_flavor():
    authorize({"Manager"})
    body = body_of()
    name = v_str(require_present(body, "name"), "name")
    standard_cost = v_num(require_present(body, "standard_cost_cents_per_ml"), "standard_cost_cents_per_ml", 0)
    par = v_int(require_present(body, "par_level_ml"), "par_level_ml", 0)

    allergens = body.get("allergens", [])
    if allergens is None:
        allergens = []
    v_str_list(allergens, "allergens")

    is_seasonal = body.get("is_seasonal", False)
    if is_seasonal is None:
        is_seasonal = False
    v_bool(is_seasonal, "is_seasonal")

    is_premium = body.get("is_premium", False)
    if is_premium is None:
        is_premium = False
    v_bool(is_premium, "is_premium")

    premium = body.get("premium_surcharge_cents_per_scoop", 0)
    if premium is None:
        premium = 0
    v_int(premium, "premium_surcharge_cents_per_scoop", 0)

    is_active = body.get("is_active", True)
    if is_active is None:
        is_active = True
    v_bool(is_active, "is_active")

    season_start_raw = body.get("seasonal_start_utc")
    season_end_raw = body.get("seasonal_end_utc")
    season_start_dt = None
    season_end_dt = None
    if is_seasonal:
        if season_start_raw is None or season_end_raw is None:
            raise ApiError("ERR_VALIDATION", 422, "seasonal window required when is_seasonal")
        season_start_dt = parse_dt(season_start_raw)
        season_end_dt = parse_dt(season_end_raw)
        if season_end_dt <= season_start_dt:
            raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "seasonal_end must be after start")
    else:
        if season_start_raw is not None:
            season_start_dt = parse_dt(season_start_raw)
        if season_end_raw is not None:
            season_end_dt = parse_dt(season_end_raw)

    for f in DB["flavors"].values():
        if f["name"] == name:
            raise ApiError("ERR_VALIDATION", 422, "flavor name must be unique")

    f = base(
        {
            "name": name,
            "allergens": list(allergens),
            "is_seasonal": is_seasonal,
            "seasonal_start_utc": season_start_raw if is_seasonal or season_start_raw else None,
            "seasonal_end_utc": season_end_raw if is_seasonal or season_end_raw else None,
            "_season_start": season_start_dt,
            "_season_end": season_end_dt,
            "is_premium": is_premium,
            "premium_surcharge_cents_per_scoop": premium,
            "standard_cost_cents_per_ml": standard_cost,
            "par_level_ml": par,
            "is_active": is_active,
            "total_available_ml": 0,
            "stock_status": "OUT_OF_STOCK",
        }
    )
    DB["flavors"][f["id"]] = f
    return success(ser_flavor(f), 201)


@app.get("/flavors")
def list_flavors():
    authorize(ALL_ROLES)
    items = list(DB["flavors"].values())
    ss = request.args.get("stock_status")
    if ss is not None:
        items = [f for f in items if f["stock_status"] == ss]
    seasonal = request.args.get("is_seasonal")
    if seasonal is not None:
        want = seasonal.lower() == "true"
        items = [f for f in items if f["is_seasonal"] == want]
    return list_response(items, ser_flavor)


@app.get("/flavors/<fid>")
def get_flavor(fid):
    authorize(ALL_ROLES)
    f = get_or_404("flavors", fid, "ERR_FLAVOR_NOT_FOUND")
    return success(ser_flavor(f), 200)


@app.patch("/flavors/<fid>")
def patch_flavor(fid):
    authorize({"Manager"})
    f = get_or_404("flavors", fid, "ERR_FLAVOR_NOT_FOUND")
    body = body_of()

    if "par_level_ml" in body and body["par_level_ml"] is not None:
        f["par_level_ml"] = v_int(body["par_level_ml"], "par_level_ml", 0)
    if "is_active" in body and body["is_active"] is not None:
        f["is_active"] = v_bool(body["is_active"], "is_active")
    if "is_premium" in body and body["is_premium"] is not None:
        f["is_premium"] = v_bool(body["is_premium"], "is_premium")
    if "premium_surcharge_cents_per_scoop" in body and body["premium_surcharge_cents_per_scoop"] is not None:
        f["premium_surcharge_cents_per_scoop"] = v_int(
            body["premium_surcharge_cents_per_scoop"], "premium_surcharge_cents_per_scoop", 0
        )

    new_seasonal = f["is_seasonal"]
    if "is_seasonal" in body and body["is_seasonal"] is not None:
        new_seasonal = v_bool(body["is_seasonal"], "is_seasonal")

    start_raw = f["seasonal_start_utc"]
    end_raw = f["seasonal_end_utc"]
    if "seasonal_start_utc" in body:
        start_raw = body["seasonal_start_utc"]
    if "seasonal_end_utc" in body:
        end_raw = body["seasonal_end_utc"]

    start_dt = parse_dt(start_raw) if start_raw is not None else None
    end_dt = parse_dt(end_raw) if end_raw is not None else None

    if new_seasonal:
        if start_dt is None or end_dt is None:
            raise ApiError("ERR_VALIDATION", 422, "seasonal window required when is_seasonal")
        if end_dt <= start_dt:
            raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "seasonal_end must be after start")
    else:
        if start_dt is not None and end_dt is not None and end_dt <= start_dt:
            raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "seasonal_end must be after start")

    f["is_seasonal"] = new_seasonal
    f["seasonal_start_utc"] = start_raw
    f["seasonal_end_utc"] = end_raw
    f["_season_start"] = start_dt
    f["_season_end"] = end_dt

    recompute_flavor_stock(f, cascade=False)
    mark(f)
    flush_dirty()
    return success(ser_flavor(f), 200)


# ==========================================================================
# SIZE OPTION
# ==========================================================================
@app.post("/size-options")
def create_size():
    authorize({"Manager"})
    body = body_of()
    code = v_str(require_present(body, "code"), "code")
    scoop_count = v_int(require_present(body, "scoop_count"), "scoop_count", 1)
    base_price = v_int(require_present(body, "base_price_cents"), "base_price_cents", 0)
    for s in DB["size_options"].values():
        if s["code"] == code:
            raise ApiError("ERR_VALIDATION", 422, "size option code must be unique")
    s = base({"code": code, "scoop_count": scoop_count, "base_price_cents": base_price})
    DB["size_options"][s["id"]] = s
    return success(ser_size(s), 201)


@app.get("/size-options")
def list_sizes():
    authorize(ALL_ROLES)
    return list_response(list(DB["size_options"].values()), ser_size)


# ==========================================================================
# TOPPING
# ==========================================================================
@app.post("/toppings")
def create_topping():
    authorize({"Manager"})
    body = body_of()
    name = v_str(require_present(body, "name"), "name")
    price = v_int(require_present(body, "price_cents"), "price_cents", 0)
    allergens = body.get("allergens", [])
    if allergens is None:
        allergens = []
    v_str_list(allergens, "allergens")
    for t in DB["toppings"].values():
        if t["name"] == name:
            raise ApiError("ERR_VALIDATION", 422, "topping name must be unique")
    t = base({"name": name, "price_cents": price, "allergens": list(allergens)})
    DB["toppings"][t["id"]] = t
    return success(ser_topping(t), 201)


@app.get("/toppings")
def list_toppings():
    authorize(ALL_ROLES)
    return list_response(list(DB["toppings"].values()), ser_topping)


# ==========================================================================
# EVENT CART / DECORATING STATION
# ==========================================================================
@app.post("/event-carts")
def create_cart():
    authorize({"Manager"})
    body = body_of()
    name = v_str(require_present(body, "name"), "name")
    cap = v_int(require_present(body, "capacity_ml"), "capacity_ml", 1)
    c = base({"name": name, "capacity_ml": cap})
    DB["event_carts"][c["id"]] = c
    return success(ser_cart(c), 201)


@app.post("/decorating-stations")
def create_station():
    authorize({"Manager"})
    body = body_of()
    name = v_str(require_present(body, "name"), "name")
    s = base({"name": name})
    DB["decorating_stations"][s["id"]] = s
    return success(ser_station(s), 201)


# ==========================================================================
# BATCH
# ==========================================================================
@app.post("/batches")
def create_batch():
    authorize({"Baker"})
    body = body_of()
    flavor_id = body.get("flavor_id")
    fk_exists_if_str("flavors", flavor_id, "ERR_FLAVOR_NOT_FOUND")
    flavor_id = v_str(require_present(body, "flavor_id"), "flavor_id")
    if flavor_id not in DB["flavors"]:
        raise ApiError("ERR_FLAVOR_NOT_FOUND", 404, "flavor not found")
    initial = v_int(require_present(body, "initial_volume_ml"), "initial_volume_ml", 1)
    unit_cost = v_num(require_present(body, "unit_cost_cents_per_ml"), "unit_cost_cents_per_ml", 0)
    produced_raw = require_present(body, "produced_at")
    expiry_raw = require_present(body, "expiry_at")
    produced_dt = parse_dt(produced_raw)
    expiry_dt = parse_dt(expiry_raw)

    b = base(
        {
            "flavor_id": flavor_id,
            "initial_volume_ml": initial,
            "unit_cost_cents_per_ml": unit_cost,
            "produced_at": produced_raw,
            "expiry_at": expiry_raw,
            "_produced_dt": produced_dt,
            "_expiry_dt": expiry_dt,
            "reserved": 0,
            "committed": 0,
            "wasted": 0,
            "status": "PREP",
        }
    )
    DB["batches"][b["id"]] = b
    return success(ser_batch(b), 201)


@app.post("/batches/<bid>/release")
def release_batch(bid):
    authorize({"Baker"})
    b = get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")
    if b["status"] != "PREP":
        raise ApiError("ERR_BATCH_NOT_PREP", 409, "batch not in PREP")
    b["status"] = "AVAILABLE"
    mark(b)
    recompute_flavor_stock(DB["flavors"][b["flavor_id"]], cascade=True)
    flush_dirty()
    return success(ser_batch(b), 200)


@app.get("/batches")
def list_batches():
    authorize(ALL_ROLES)
    items = list(DB["batches"].values())
    fid = request.args.get("flavor_id")
    if fid is not None:
        items = [b for b in items if b["flavor_id"] == fid]
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    return list_response(items, ser_batch)


@app.get("/batches/<bid>")
def get_batch(bid):
    authorize(ALL_ROLES)
    b = get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")
    return success(ser_batch(b), 200)


# ==========================================================================
# WASTE EVENT
# ==========================================================================
@app.post("/waste-events")
def create_waste():
    authorize({"Baker"})
    body = body_of()
    batch_id = body.get("batch_id")
    fk_exists_if_str("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    batch_id = v_str(require_present(body, "batch_id"), "batch_id")
    b = DB["batches"].get(batch_id)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404, "batch not found")

    waste_type = require_present(body, "waste_type")
    if not isinstance(waste_type, str) or waste_type not in WASTE_TYPES:
        raise ApiError("ERR_VALIDATION", 422, "invalid waste_type")
    volume = v_int(require_present(body, "volume_ml"), "volume_ml", 1)
    reason = body.get("reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise ApiError("ERR_VALIDATION", 422, "reason must be a string")

    # state: batch must be PREP or AVAILABLE
    if b["status"] not in ("PREP", "AVAILABLE"):
        raise ApiError("ERR_BATCH_NOT_AVAILABLE", 409, "batch not in PREP/AVAILABLE")

    if waste_type == "EXPIRED_DISCARD":
        if volume != remaining(b):
            raise ApiError(
                "ERR_VALIDATION", 422, "EXPIRED_DISCARD volume must equal remaining_volume_ml"
            )

    w = base(
        {
            "batch_id": batch_id,
            "waste_type": waste_type,
            "volume_ml": volume,
            "reason": reason,
        },
        versioned=False,
    )
    DB["waste_events"][w["id"]] = w

    b["wasted"] += volume
    if waste_type == "EXPIRED_DISCARD":
        b["status"] = "DISCARDED"
    elif b["status"] == "AVAILABLE" and remaining(b) == 0:
        b["status"] = "DEPLETED"
    mark(b)
    recompute_flavor_stock(DB["flavors"][b["flavor_id"]], cascade=True)
    flush_dirty()
    return success(ser_waste(w), 201)


@app.get("/waste-events")
def list_waste():
    authorize(ALL_ROLES)
    items = list(DB["waste_events"].values())
    bid = request.args.get("batch_id")
    if bid is not None:
        items = [w for w in items if w["batch_id"] == bid]
    return list_response(items, ser_waste)


@app.get("/waste-events/<wid>")
def get_waste(wid):
    authorize(ALL_ROLES)
    w = get_or_404("waste_events", wid, "ERR_WASTE_EVENT_NOT_FOUND")
    return success(ser_waste(w), 200)


# ==========================================================================
# LOYALTY ACCOUNT
# ==========================================================================
@app.post("/loyalty-accounts")
def create_loyalty():
    authorize({"Manager", "Scooper"})
    body = body_of()
    phone = v_str(require_present(body, "phone"), "phone")
    restrictions = body.get("allergen_restrictions", [])
    if restrictions is None:
        restrictions = []
    v_str_list(restrictions, "allergen_restrictions")
    for a in DB["loyalty_accounts"].values():
        if a["phone"] == phone:
            raise ApiError("ERR_VALIDATION", 422, "phone must be unique")
    a = base(
        {
            "phone": phone,
            "allergen_restrictions": list(restrictions),
            "punches": 0,
            "free_scoop_credits": 0,
            "lifetime_scoops": 0,
        }
    )
    DB["loyalty_accounts"][a["id"]] = a
    return success(ser_loyalty(a), 201)


@app.get("/loyalty-accounts/<aid>")
def get_loyalty(aid):
    authorize(ALL_ROLES)
    a = get_or_404("loyalty_accounts", aid, "ERR_LOYALTY_ACCOUNT_NOT_FOUND")
    return success(ser_loyalty(a), 200)


# ==========================================================================
# CASH DRAWER SESSION
# ==========================================================================
@app.post("/cash-drawer-sessions")
def open_drawer():
    authorize({"ShiftLead"})
    body = body_of()
    opening = v_int(require_present(body, "opening_float_cents"), "opening_float_cents", 0)
    d = base(
        {
            "opening_float_cents": opening,
            "counted_cash_cents": None,
            "variance_cents": None,
            "reconciliation_status": "PENDING",
            "status": "OPEN",
        }
    )
    DB["drawers"][d["id"]] = d
    return success(ser_drawer(d), 201)


@app.post("/cash-drawer-sessions/<did>/close")
def close_drawer(did):
    authorize({"ShiftLead"})
    d = get_or_404("drawers", did, "ERR_DRAWER_NOT_FOUND")
    body = body_of()
    counted = v_int(require_present(body, "counted_cash_cents"), "counted_cash_cents")
    if d["status"] != "OPEN":
        raise ApiError("ERR_DRAWER_ALREADY_CLOSED", 409, "drawer already closed")
    orders = [o for o in DB["orders"].values() if o["drawer_id"] == d["id"]]
    expected = (
        d["opening_float_cents"]
        + sum(o["cash_collected_cents"] for o in orders)
        - sum(o["cash_refunded_cents"] for o in orders)
    )
    variance = counted - expected
    d["counted_cash_cents"] = counted
    d["variance_cents"] = variance
    if variance == 0:
        d["reconciliation_status"] = "BALANCED"
    elif variance > 0:
        d["reconciliation_status"] = "OVER"
    else:
        d["reconciliation_status"] = "SHORT"
    d["status"] = "CLOSED"
    mark(d)
    flush_dirty()
    return success(ser_drawer(d), 200)


@app.get("/cash-drawer-sessions/<did>")
def get_drawer(did):
    authorize(ALL_ROLES)
    d = get_or_404("drawers", did, "ERR_DRAWER_NOT_FOUND")
    return success(ser_drawer(d), 200)


# ==========================================================================
# ORDER
# ==========================================================================
@app.post("/orders")
def create_order():
    authorize({"Scooper", "ShiftLead"})
    body = body_of()
    drawer_id = body.get("drawer_id")
    fk_exists_if_str("drawers", drawer_id, "ERR_DRAWER_NOT_FOUND")
    loyalty_id = body.get("loyalty_account_id")
    fk_exists_if_str("loyalty_accounts", loyalty_id, "ERR_LOYALTY_ACCOUNT_NOT_FOUND")

    drawer_id = v_str(require_present(body, "drawer_id"), "drawer_id")
    if drawer_id not in DB["drawers"]:
        raise ApiError("ERR_DRAWER_NOT_FOUND", 404, "drawer not found")
    if loyalty_id is not None:
        if not isinstance(loyalty_id, str) or loyalty_id not in DB["loyalty_accounts"]:
            raise ApiError("ERR_LOYALTY_ACCOUNT_NOT_FOUND", 404, "loyalty account not found")

    o = base(
        {
            "drawer_id": drawer_id,
            "loyalty_account_id": loyalty_id,
            "payment_method": None,
            "subtotal_cents": 0,
            "tax_cents": 0,
            "total_cents": 0,
            "tendered_cash_cents": None,
            "change_cents": None,
            "cash_collected_cents": 0,
            "cash_refunded_cents": 0,
            "standard_cogs_cents": 0,
            "actual_cogs_cents": 0,
            "punches_earned": 0,
            "status": "OPEN",
        }
    )
    DB["orders"][o["id"]] = o
    return success(ser_order(o), 201)


@app.get("/orders")
def list_orders():
    authorize(ALL_ROLES)
    items = list(DB["orders"].values())
    for key, field in (("drawer_id", "drawer_id"), ("loyalty_account_id", "loyalty_account_id"), ("status", "status")):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[field] == val]
    return list_response(items, ser_order)


@app.get("/orders/<oid>")
def get_order(oid):
    authorize(ALL_ROLES)
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    return success(ser_order(o), 200)


@app.post("/orders/<oid>/lines")
def add_line(oid):
    authorize({"Scooper", "ShiftLead"})
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    body = body_of()

    # existence: body FKs (size, flavor, toppings) — only for provided str ids
    size_id = body.get("size_option_id")
    fk_exists_if_str("size_options", size_id, "ERR_SIZE_OPTION_NOT_FOUND")
    flavor_id = body.get("flavor_id")
    fk_exists_if_str("flavors", flavor_id, "ERR_FLAVOR_NOT_FOUND")
    topping_ids = body.get("topping_ids", [])
    if topping_ids is None:
        topping_ids = []
    if isinstance(topping_ids, list):
        for tid in topping_ids:
            if isinstance(tid, str) and tid != "" and tid not in DB["toppings"]:
                raise ApiError("ERR_TOPPING_NOT_FOUND", 404, "topping not found")

    # schema
    size_id = v_str(require_present(body, "size_option_id"), "size_option_id")
    flavor_id = v_str(require_present(body, "flavor_id"), "flavor_id")
    v_list(topping_ids, "topping_ids")
    for tid in topping_ids:
        if not isinstance(tid, str) or tid == "":
            raise ApiError("ERR_VALIDATION", 422, "topping_ids must contain non-empty strings")
    quantity = body.get("quantity", 1)
    if quantity is None:
        quantity = 1
    quantity = v_int(quantity, "quantity", 1)

    size = DB["size_options"].get(size_id)
    if size is None:
        raise ApiError("ERR_SIZE_OPTION_NOT_FOUND", 404, "size option not found")
    flavor = DB["flavors"].get(flavor_id)
    if flavor is None:
        raise ApiError("ERR_FLAVOR_NOT_FOUND", 404, "flavor not found")
    toppings = []
    for tid in topping_ids:
        t = DB["toppings"].get(tid)
        if t is None:
            raise ApiError("ERR_TOPPING_NOT_FOUND", 404, "topping not found")
        toppings.append(t)

    # state
    if o["status"] != "OPEN":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409, "order not OPEN")

    scoops = size["scoop_count"] * quantity

    # allergen label
    allergen_set = set(flavor["allergens"])
    for t in toppings:
        allergen_set.update(t["allergens"])
    allergen_label = sorted(allergen_set)

    # business: allergen restriction
    if o["loyalty_account_id"]:
        acct = DB["loyalty_accounts"].get(o["loyalty_account_id"])
        if acct and (allergen_set & set(acct["allergen_restrictions"])):
            raise ApiError("ERR_ALLERGEN_RESTRICTION_CONFLICT", 409, "allergen restriction conflict")

    # business: seasonal window
    if flavor["is_seasonal"]:
        if not flavor_in_season(flavor, STATE["clock"]):
            raise ApiError("ERR_FLAVOR_OUT_OF_SEASON", 409, "flavor out of season")

    # business: FIFO headroom
    need = scoops * SCOOP_VOLUME_ML
    allocs = compute_allocations(flavor_id, need)

    # pricing
    base_price = size["base_price_cents"] * quantity
    topping_total = sum(t["price_cents"] for t in toppings) * quantity
    seasonal_surcharge = SEASONAL_SURCHARGE_CENTS_PER_SCOOP * scoops if flavor["is_seasonal"] else 0
    premium_surcharge = flavor["premium_surcharge_cents_per_scoop"] * scoops if flavor["is_premium"] else 0
    line_price = base_price + topping_total + seasonal_surcharge + premium_surcharge
    line_tax = rhu(dec(line_price) * TAX_RATE)

    # apply reservation
    touched_batches = []
    for a in allocs:
        b = DB["batches"][a["batch_id"]]
        b["reserved"] += a["volume_ml"]
        touched_batches.append(b)

    line = base(
        {
            "order_id": o["id"],
            "size_option_id": size_id,
            "flavor_id": flavor_id,
            "topping_ids": list(topping_ids),
            "quantity": quantity,
            "scoops": scoops,
            "line_price_cents": line_price,
            "line_tax_cents": line_tax,
            "allergen_label": allergen_label,
            "allocations": [dict(a) for a in allocs],
            "status": "ACTIVE",
        }
    )
    DB["order_lines"][line["id"]] = line

    for b in touched_batches:
        mark(b)
    recompute_order_totals(o)
    mark(o)
    flush_dirty()
    return success(ser_line(line), 201)


@app.delete("/orders/<oid>/lines/<lid>")
def remove_line(oid, lid):
    authorize({"Scooper", "ShiftLead"})
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    line = DB["order_lines"].get(lid)
    if line is None or line["order_id"] != oid:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "order line not found")
    if o["status"] != "OPEN":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409, "order not OPEN")
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "order line not active")

    for a in line["allocations"]:
        b = DB["batches"].get(a["batch_id"])
        if b is not None:
            b["reserved"] -= a["volume_ml"]
            mark(b)
    line["status"] = "REMOVED"
    mark(line)
    recompute_order_totals(o)
    mark(o)
    flush_dirty()
    return success(ser_line(line), 200)


@app.get("/order-lines")
def list_lines():
    authorize(ALL_ROLES)
    items = list(DB["order_lines"].values())
    for key in ("order_id", "size_option_id", "flavor_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l[key] == val]
    return list_response(items, ser_line)


@app.get("/order-lines/<lid>")
def get_line(lid):
    authorize(ALL_ROLES)
    line = get_or_404("order_lines", lid, "ERR_ORDER_LINE_NOT_FOUND")
    return success(ser_line(line), 200)


@app.post("/orders/<oid>/pay")
def pay_order(oid):
    authorize({"Scooper", "ShiftLead"})
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    body = body_of()
    payment_method = require_present(body, "payment_method")
    if not isinstance(payment_method, str) or payment_method not in ("CASH", "CARD"):
        raise ApiError("ERR_VALIDATION", 422, "invalid payment_method")
    tendered = body.get("tendered_cash_cents")
    if payment_method == "CASH":
        if tendered is None:
            raise ApiError("ERR_VALIDATION", 422, "tendered_cash_cents required for CASH")
        tendered = v_int(tendered, "tendered_cash_cents", 0)

    # state
    if o["status"] != "OPEN":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409, "order not OPEN")
    active_lines = [l for l in DB["order_lines"].values() if l["order_id"] == oid and l["status"] == "ACTIVE"]
    if len(active_lines) == 0:
        raise ApiError("ERR_EMPTY_ORDER", 409, "order has no active lines")
    drawer = DB["drawers"].get(o["drawer_id"])
    if drawer is None or drawer["status"] != "OPEN":
        raise ApiError("ERR_DRAWER_NOT_OPEN", 409, "drawer not open")

    recompute_order_totals(o)

    # fiscal
    if payment_method == "CASH":
        if tendered < o["total_cents"]:
            raise ApiError("ERR_INSUFFICIENT_CASH_TENDERED", 402, "insufficient cash tendered")

    # commit cascade
    affected_flavors = set()
    touched = []
    for line in active_lines:
        for a in line["allocations"]:
            b = DB["batches"].get(a["batch_id"])
            if b is None:
                continue
            b["reserved"] -= a["volume_ml"]
            b["committed"] += a["volume_ml"]
            touched.append(b)
            affected_flavors.add(b["flavor_id"])
        line["status"] = "COMMITTED"
        mark(line)
    for b in touched:
        if b["status"] == "AVAILABLE" and remaining(b) == 0:
            b["status"] = "DEPLETED"
        mark(b)
    for fid in affected_flavors:
        recompute_flavor_stock(DB["flavors"][fid], cascade=True)

    # COGS freeze
    o["standard_cogs_cents"] = sum(line_standard_cogs(l) for l in active_lines)
    o["actual_cogs_cents"] = sum(line_actual_cogs(l) for l in active_lines)

    # payment fields
    o["payment_method"] = payment_method
    if payment_method == "CASH":
        o["tendered_cash_cents"] = tendered
        o["change_cents"] = tendered - o["total_cents"]
        o["cash_collected_cents"] = o["total_cents"]
    else:
        o["cash_collected_cents"] = 0
    o["status"] = "PAID"
    recompute_order_totals(o)

    # loyalty accrual
    if o["loyalty_account_id"]:
        acct = DB["loyalty_accounts"].get(o["loyalty_account_id"])
        if acct:
            earned = o["punches_earned"]
            acct["lifetime_scoops"] += earned
            running = acct["punches"] + earned
            acct["free_scoop_credits"] += running // PUNCH_THRESHOLD
            acct["punches"] = running % PUNCH_THRESHOLD
            mark(acct)

    mark(o)
    mark(drawer)
    flush_dirty()
    return success(ser_order(o), 200)


@app.post("/orders/<oid>/void")
def void_order(oid):
    authorize({"ShiftLead"})
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "OPEN":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409, "order not OPEN")
    active_lines = [l for l in DB["order_lines"].values() if l["order_id"] == oid and l["status"] == "ACTIVE"]
    for line in active_lines:
        for a in line["allocations"]:
            b = DB["batches"].get(a["batch_id"])
            if b is not None:
                b["reserved"] -= a["volume_ml"]
                mark(b)
        line["status"] = "REMOVED"
        mark(line)
    o["status"] = "VOID"
    recompute_order_totals(o)
    mark(o)
    flush_dirty()
    return success(ser_order(o), 200)


@app.post("/orders/<oid>/refund")
def refund_order(oid):
    authorize({"ShiftLead", "Manager"})
    o = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409, "order not PAID")

    committed_lines = [l for l in DB["order_lines"].values() if l["order_id"] == oid and l["status"] == "COMMITTED"]
    affected_flavors = set()
    touched = []
    for line in committed_lines:
        for a in line["allocations"]:
            b = DB["batches"].get(a["batch_id"])
            if b is None:
                continue
            b["committed"] -= a["volume_ml"]
            touched.append(b)
            affected_flavors.add(b["flavor_id"])
    for b in touched:
        if b["status"] == "DEPLETED" and remaining(b) > 0:
            b["status"] = "AVAILABLE"
        mark(b)
    for fid in affected_flavors:
        recompute_flavor_stock(DB["flavors"][fid], cascade=True)

    # cash side
    if o["payment_method"] == "CASH":
        o["cash_refunded_cents"] = o["total_cents"]
    else:
        o["cash_refunded_cents"] = 0

    # loyalty reversal
    if o["loyalty_account_id"]:
        acct = DB["loyalty_accounts"].get(o["loyalty_account_id"])
        if acct:
            earned = o["punches_earned"]
            new_lifetime = acct["lifetime_scoops"] - earned
            if new_lifetime < 0:
                new_lifetime = 0
            acct["lifetime_scoops"] = new_lifetime
            acct["free_scoop_credits"] = new_lifetime // PUNCH_THRESHOLD
            acct["punches"] = new_lifetime % PUNCH_THRESHOLD
            mark(acct)

    o["status"] = "REFUNDED"
    mark(o)
    drawer = DB["drawers"].get(o["drawer_id"])
    if drawer:
        mark(drawer)
    flush_dirty()
    return success(ser_order(o), 200)


# ==========================================================================
# PRE-ORDER
# ==========================================================================
def station_overlaps(station_id, start_dt, end_dt, exclude_id=None):
    for p in DB["pre_orders"].values():
        if p["decorating_station_id"] != station_id:
            continue
        if p["status"] == "CANCELLED":
            continue
        if exclude_id and p["id"] == exclude_id:
            continue
        o_start = p["_dec_start"]
        o_end = p["_dec_end"]
        # ok if separated by >= buffer on either side
        if start_dt >= o_end + STATION_CLEAN_BUFFER or end_dt <= o_start - STATION_CLEAN_BUFFER:
            continue
        return True
    return False


@app.post("/pre-orders")
def create_preorder():
    authorize({"Scooper", "Manager"})
    body = body_of()
    flavor_id = body.get("flavor_id")
    fk_exists_if_str("flavors", flavor_id, "ERR_FLAVOR_NOT_FOUND")
    station_id = body.get("decorating_station_id")
    fk_exists_if_str("decorating_stations", station_id, "ERR_DECORATING_STATION_NOT_FOUND")

    flavor_id = v_str(require_present(body, "flavor_id"), "flavor_id")
    if flavor_id not in DB["flavors"]:
        raise ApiError("ERR_FLAVOR_NOT_FOUND", 404, "flavor not found")
    station_id = v_str(require_present(body, "decorating_station_id"), "decorating_station_id")
    if station_id not in DB["decorating_stations"]:
        raise ApiError("ERR_DECORATING_STATION_NOT_FOUND", 404, "station not found")

    customer_name = v_str(require_present(body, "customer_name"), "customer_name")
    is_custom = body.get("is_custom", False)
    if is_custom is None:
        is_custom = False
    v_bool(is_custom, "is_custom")
    custom_notes = body.get("custom_notes", "")
    if custom_notes is None:
        custom_notes = ""
    if not isinstance(custom_notes, str):
        raise ApiError("ERR_VALIDATION", 422, "custom_notes must be a string")

    dec_start_raw = require_present(body, "decorate_start_utc")
    dec_end_raw = require_present(body, "decorate_end_utc")
    pickup_raw = require_present(body, "pickup_utc")
    quoted = v_int(require_present(body, "quoted_price_cents"), "quoted_price_cents", 0)

    dec_start = parse_dt(dec_start_raw)
    dec_end = parse_dt(dec_end_raw)
    pickup = parse_dt(pickup_raw)
    if dec_end <= dec_start:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "decorate_end must be after start")

    if station_overlaps(station_id, dec_start, dec_end):
        raise ApiError("ERR_STATION_OVERLAP", 409, "decorating station window overlap")

    p = base(
        {
            "flavor_id": flavor_id,
            "decorating_station_id": station_id,
            "customer_name": customer_name,
            "is_custom": is_custom,
            "custom_notes": custom_notes,
            "decorate_start_utc": dec_start_raw,
            "decorate_end_utc": dec_end_raw,
            "pickup_utc": pickup_raw,
            "_dec_start": dec_start,
            "_dec_end": dec_end,
            "_pickup": pickup,
            "quoted_price_cents": quoted,
            "deposit_cents": 0,
            "final_price_cents": 0,
            "refunded_cents": 0,
            "status": "QUOTED",
        }
    )
    DB["pre_orders"][p["id"]] = p
    return success(ser_preorder(p), 201)


@app.get("/pre-orders")
def list_preorders():
    authorize(ALL_ROLES)
    items = list(DB["pre_orders"].values())
    for key in ("flavor_id", "decorating_station_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    return list_response(items, ser_preorder)


@app.get("/pre-orders/<pid>")
def get_preorder(pid):
    authorize(ALL_ROLES)
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/requote")
def requote_preorder(pid):
    authorize({"Manager"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    body = body_of()
    quoted = v_int(require_present(body, "quoted_price_cents"), "quoted_price_cents", 0)
    expected_version = v_int(require_present(body, "expected_preorder_version"), "expected_preorder_version")
    if p["status"] != "QUOTED":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order not QUOTED")
    if expected_version != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale pre-order version")
    p["quoted_price_cents"] = quoted
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/confirm")
def confirm_preorder(pid):
    authorize({"Scooper", "Manager"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    if p["status"] != "QUOTED":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order not QUOTED")
    p["deposit_cents"] = rhu(dec(p["quoted_price_cents"]) * DEPOSIT_PCT)
    p["status"] = "CONFIRMED"
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/start-production")
def start_production(pid):
    authorize({"Baker"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    if p["status"] != "CONFIRMED":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order not CONFIRMED")
    flavor = DB["flavors"][p["flavor_id"]]
    if (
        not flavor["is_active"]
        or not flavor_in_season(flavor, STATE["clock"])
        or flavor["stock_status"] == "OUT_OF_STOCK"
    ):
        raise ApiError("ERR_FLAVOR_UNAVAILABLE", 409, "base flavor unavailable")
    p["status"] = "IN_PRODUCTION"
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/request-revision")
def request_revision(pid):
    authorize({"Baker"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    if p["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order not IN_PRODUCTION")
    p["status"] = "CONFIRMED"
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/fulfill")
def fulfill_preorder(pid):
    authorize({"Scooper", "Manager"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    if p["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order not IN_PRODUCTION")
    p["final_price_cents"] = p["quoted_price_cents"]
    p["status"] = "FULFILLED"
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


@app.post("/pre-orders/<pid>/cancel")
def cancel_preorder(pid):
    authorize({"Manager"})
    p = get_or_404("pre_orders", pid, "ERR_PREORDER_NOT_FOUND")
    if p["status"] not in ("QUOTED", "CONFIRMED", "IN_PRODUCTION"):
        raise ApiError("ERR_PREORDER_INVALID_STATE", 409, "pre-order cannot be cancelled")
    if p["status"] in ("CONFIRMED", "IN_PRODUCTION"):
        p["refunded_cents"] = p["deposit_cents"]
    else:
        p["refunded_cents"] = 0
    p["status"] = "CANCELLED"
    mark(p)
    flush_dirty()
    return success(ser_preorder(p), 200)


# ==========================================================================
# CATERING BOOKING
# ==========================================================================
def cart_overlaps(cart_id, start_dt, end_dt, exclude_id=None):
    for c in DB["catering_bookings"].values():
        if c["event_cart_id"] != cart_id:
            continue
        if c["status"] == "CANCELLED":
            continue
        if exclude_id and c["id"] == exclude_id:
            continue
        o_start = c["_ev_start"]
        o_end = c["_ev_end"]
        # half-open, touching allowed
        if start_dt < o_end and o_start < end_dt:
            return True
    return False


@app.post("/catering-bookings")
def create_catering():
    authorize({"Manager"})
    body = body_of()
    cart_id = body.get("event_cart_id")
    fk_exists_if_str("event_carts", cart_id, "ERR_EVENT_CART_NOT_FOUND")

    # existence of requested_items flavors (best-effort, before schema)
    raw_items = body.get("requested_items")
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict):
                fid = it.get("flavor_id")
                if isinstance(fid, str) and fid != "" and fid not in DB["flavors"]:
                    raise ApiError("ERR_FLAVOR_NOT_FOUND", 404, "flavor not found")

    cart_id = v_str(require_present(body, "event_cart_id"), "event_cart_id")
    cart = DB["event_carts"].get(cart_id)
    if cart is None:
        raise ApiError("ERR_EVENT_CART_NOT_FOUND", 404, "event cart not found")

    ev_start_raw = require_present(body, "event_start_utc")
    ev_end_raw = require_present(body, "event_end_utc")
    ev_start = parse_dt(ev_start_raw)
    ev_end = parse_dt(ev_end_raw)

    items = v_list(require_present(body, "requested_items"), "requested_items")
    if len(items) == 0:
        raise ApiError("ERR_VALIDATION", 422, "requested_items must be non-empty")
    parsed_items = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError("ERR_VALIDATION", 422, "requested_items entries must be objects")
        fid = v_str(require_present(it, "flavor_id"), "flavor_id")
        vol = v_int(require_present(it, "volume_ml"), "volume_ml", 1)
        if fid not in DB["flavors"]:
            raise ApiError("ERR_FLAVOR_NOT_FOUND", 404, "flavor not found")
        parsed_items.append({"flavor_id": fid, "volume_ml": vol})

    if ev_end <= ev_start:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422, "event_end must be after start")

    # cart overlap
    if cart_overlaps(cart_id, ev_start, ev_end):
        raise ApiError("ERR_CART_OVERLAP", 409, "event cart window overlap")

    # capacity guard
    total_requested = sum(it["volume_ml"] for it in parsed_items)
    if total_requested > cart["capacity_ml"]:
        raise ApiError("ERR_VALIDATION", 422, "requested volume exceeds cart capacity")

    # FIFO reservation (atomic across all requested items)
    applied = []  # (batch, volume)
    internal_allocs = []  # {flavor_id, batch_id, volume_ml}
    try:
        for it in parsed_items:
            allocs = compute_allocations(it["flavor_id"], it["volume_ml"])
            for a in allocs:
                b = DB["batches"][a["batch_id"]]
                b["reserved"] += a["volume_ml"]
                applied.append((b, a["volume_ml"]))
                internal_allocs.append(
                    {"flavor_id": it["flavor_id"], "batch_id": a["batch_id"], "volume_ml": a["volume_ml"]}
                )
    except ApiError:
        for b, v in applied:
            b["reserved"] -= v
        raise

    estimate = total_requested * CATERING_RATE_CENTS_PER_ML

    c = base(
        {
            "event_cart_id": cart_id,
            "event_start_utc": ev_start_raw,
            "event_end_utc": ev_end_raw,
            "_ev_start": ev_start,
            "_ev_end": ev_end,
            "requested_items": parsed_items,
            "estimate_cents": estimate,
            "actual_items": [],
            "actual_cents": 0,
            "_allocs": internal_allocs,
            "status": "BOOKED",
        }
    )
    DB["catering_bookings"][c["id"]] = c

    for b, _v in applied:
        mark(b)
    flush_dirty()
    return success(ser_catering(c), 201)


@app.get("/catering-bookings")
def list_catering():
    authorize(ALL_ROLES)
    items = list(DB["catering_bookings"].values())
    for key in ("event_cart_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return list_response(items, ser_catering)


@app.get("/catering-bookings/<cid>")
def get_catering(cid):
    authorize(ALL_ROLES)
    c = get_or_404("catering_bookings", cid, "ERR_CATERING_BOOKING_NOT_FOUND")
    return success(ser_catering(c), 200)


@app.post("/catering-bookings/<cid>/close")
def close_catering(cid):
    authorize({"Manager"})
    c = get_or_404("catering_bookings", cid, "ERR_CATERING_BOOKING_NOT_FOUND")
    body = body_of()
    actual_raw = v_list(require_present(body, "actual_items"), "actual_items")

    if c["status"] != "BOOKED":
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "booking not BOOKED")

    # reserved per flavor
    reserved_by_flavor = {}
    for a in c["_allocs"]:
        reserved_by_flavor[a["flavor_id"]] = reserved_by_flavor.get(a["flavor_id"], 0) + a["volume_ml"]

    actual_map = {}
    parsed_actual = []
    for it in actual_raw:
        if not isinstance(it, dict):
            raise ApiError("ERR_VALIDATION", 422, "actual_items entries must be objects")
        fid = v_str(require_present(it, "flavor_id"), "flavor_id")
        vol = v_int(require_present(it, "volume_ml"), "volume_ml", 0)
        if fid not in reserved_by_flavor:
            raise ApiError("ERR_VALIDATION", 422, "actual flavor not part of requested_items")
        actual_map[fid] = actual_map.get(fid, 0) + vol
        parsed_actual.append({"flavor_id": fid, "volume_ml": vol})

    for fid, vol in actual_map.items():
        if vol > reserved_by_flavor[fid]:
            raise ApiError("ERR_VALIDATION", 422, "actual volume exceeds reserved for flavor")

    # commit cascade per flavor (FIFO over reserved batches)
    affected_flavors = set()
    touched = []
    # group internal allocs preserving order
    for fid in reserved_by_flavor:
        to_commit = actual_map.get(fid, 0)
        for a in c["_allocs"]:
            if a["flavor_id"] != fid:
                continue
            b = DB["batches"].get(a["batch_id"])
            if b is None:
                continue
            b["reserved"] -= a["volume_ml"]
            take = min(to_commit, a["volume_ml"])
            if take > 0:
                b["committed"] += take
                to_commit -= take
            touched.append(b)
            affected_flavors.add(b["flavor_id"])

    for b in touched:
        if b["status"] == "AVAILABLE" and remaining(b) == 0:
            b["status"] = "DEPLETED"
        mark(b)
    for fid in affected_flavors:
        recompute_flavor_stock(DB["flavors"][fid], cascade=True)

    total_actual = sum(it["volume_ml"] for it in parsed_actual)
    c["actual_items"] = parsed_actual
    c["actual_cents"] = total_actual * CATERING_RATE_CENTS_PER_ML
    c["status"] = "SETTLED"
    mark(c)
    flush_dirty()
    return success(ser_catering(c), 200)


@app.post("/catering-bookings/<cid>/cancel")
def cancel_catering(cid):
    authorize({"Manager"})
    c = get_or_404("catering_bookings", cid, "ERR_CATERING_BOOKING_NOT_FOUND")
    if c["status"] != "BOOKED":
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "booking not BOOKED")
    for a in c["_allocs"]:
        b = DB["batches"].get(a["batch_id"])
        if b is not None:
            b["reserved"] -= a["volume_ml"]
            mark(b)
    c["status"] = "CANCELLED"
    mark(c)
    flush_dirty()
    return success(ser_catering(c), 200)


# ==========================================================================
# Health
# ==========================================================================
@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
