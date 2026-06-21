import os
from flask import Flask, request, g

from db import db, common_fields, new_id, touch, public
from errors import ApiError, err
import errors as E
import calculations as calc
from response import success, error_response, iso_now

app = Flask(__name__)

ROLES = {"Rider", "Driver", "Dispatcher"}


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# =====================================================================
# Auth helpers
# =====================================================================
def get_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err(E.ERR_UNAUTHENTICATED, "X-User-Role missing or unknown")
    return role, uid


def require_role(role, *allowed):
    if role not in allowed:
        raise err(E.ERR_FORBIDDEN_ROLE, "Role not permitted for this endpoint")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(E.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


# =====================================================================
# Lookup helpers (existence -> ERR_NOT_FOUND)
# =====================================================================
def get_zone(zid):
    z = db.zones.get(zid)
    if z is None:
        raise err(E.ERR_NOT_FOUND, "Zone not found")
    return z


def get_driver(did):
    d = db.drivers.get(did)
    if d is None:
        raise err(E.ERR_NOT_FOUND, "Driver not found")
    return d


def get_rider(rid):
    r = db.riders.get(rid)
    if r is None:
        raise err(E.ERR_NOT_FOUND, "Rider not found")
    return r


def get_trip(tid):
    t = db.trips.get(tid)
    if t is None:
        raise err(E.ERR_NOT_FOUND, "Trip not found")
    return t


def get_quest(qid):
    q = db.quests.get(qid)
    if q is None:
        raise err(E.ERR_NOT_FOUND, "Quest not found")
    return q


def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise err(E.ERR_NOT_FOUND, "Dispute not found")
    return d


def get_queue_entry(qid):
    e = db.queue_entries.get(qid)
    if e is None:
        raise err(E.ERR_NOT_FOUND, "AirportQueueEntry not found")
    return e


# =====================================================================
# Validation helpers
# =====================================================================
def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err(E.ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(E.ERR_INVALID_REQUEST, f"Missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise err(E.ERR_INVALID_REQUEST, f"Field {field} below minimum {minimum}")
    return v


def opt_int(data, field, default, minimum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum)


def req_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, bool):
        raise err(E.ERR_INVALID_REQUEST, f"Field {field} must be boolean")
    return v


def req_datetime_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err(E.ERR_INVALID_REQUEST, f"Missing or invalid datetime field: {field}")
    return v


# =====================================================================
# Pagination
# =====================================================================
def paginate(items):
    """items: list already sorted. Returns (page, pagination_meta)."""
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise err(E.ERR_INVALID_REQUEST, "Invalid pagination parameter")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_created_asc(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def sort_created_desc(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]), reverse=True)


# =====================================================================
# Serializers
# =====================================================================
def ser_zone(z):
    return {
        "id": z["id"], "created_at": z["created_at"], "updated_at": z["updated_at"],
        "version": z["version"], "name": z["name"], "grid_code": z["grid_code"],
        "is_airport": z["is_airport"], "base_fare_cents": z["base_fare_cents"],
        "open_demand_count": z["open_demand_count"],
        "available_supply_count": z["available_supply_count"],
        "current_multiplier": z["current_multiplier"], "heat_level": z["heat_level"],
    }


def ser_driver(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"], "name": d["name"], "home_zone_id": d["home_zone_id"],
        "current_zone_id": d["current_zone_id"], "status": d["status"],
        "active_trip_id": d["active_trip_id"],
    }


def ser_rider(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "name": r["name"],
        "wallet_balance_cents": r["wallet_balance_cents"],
        "home_zone_id": r["home_zone_id"],
    }


def ser_snapshot(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "zone_id": s["zone_id"],
        "observed_demand": s["observed_demand"], "observed_supply": s["observed_supply"],
        "is_rush_hour": s["is_rush_hour"], "effective_from": s["effective_from"],
        "effective_to": s["effective_to"], "ratio": s["ratio"],
        "multiplier": s["multiplier"], "capped": s["capped"],
    }


def ser_trip(t):
    return {
        "id": t["id"], "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"], "rider_id": t["rider_id"],
        "pickup_zone_id": t["pickup_zone_id"], "dropoff_zone_id": t["dropoff_zone_id"],
        "driver_id": t["driver_id"], "status": t["status"],
        "quoted_multiplier": t["quoted_multiplier"],
        "quoted_base_fare_cents": t["quoted_base_fare_cents"],
        "final_fare_cents": t["final_fare_cents"],
        "driver_payout_cents": t["driver_payout_cents"],
        "refunded_cents": t["refunded_cents"],
    }


def ser_queue(e):
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "zone_id": e["zone_id"], "driver_id": e["driver_id"],
        "position": e["position"], "joined_at": e["joined_at"], "status": e["status"],
    }


def ser_quest(q):
    return {
        "id": q["id"], "created_at": q["created_at"], "updated_at": q["updated_at"],
        "version": q["version"], "driver_id": q["driver_id"],
        "target_trips": q["target_trips"], "bonus_cents": q["bonus_cents"],
        "window_start": q["window_start"], "window_end": q["window_end"],
        "completed_trips": q["completed_trips"], "status": q["status"],
        "paid_out_cents": q["paid_out_cents"],
    }


def ser_dispute(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"], "trip_id": d["trip_id"], "rider_id": d["rider_id"],
        "reason": d["reason"], "requested_refund_cents": d["requested_refund_cents"],
        "status": d["status"], "refund_cents": d["refund_cents"],
    }


def to2(x):
    """Decimal/number -> float rounded to 2dp for JSON."""
    return float(round(float(x), 2))


# =====================================================================
# Supply counter helpers (floored at 0)
# =====================================================================
def zone_supply_inc(zone, n=1):
    zone["available_supply_count"] += n
    touch(zone)


def zone_supply_dec(zone, n=1):
    zone["available_supply_count"] = max(0, zone["available_supply_count"] - n)
    touch(zone)


def zone_demand_inc(zone, n=1):
    zone["open_demand_count"] += n
    touch(zone)


def zone_demand_dec(zone, n=1):
    zone["open_demand_count"] = max(0, zone["open_demand_count"] - n)
    touch(zone)


def resequence_queue(zone_id):
    """Re-sequence WAITING entries in a zone by joined_at ASC, created_at ASC."""
    waiting = [e for e in db.queue_entries.values()
               if e["zone_id"] == zone_id and e["status"] == "WAITING"]
    waiting.sort(key=lambda e: (e["joined_at"], e["created_at"], e["_seq"]))
    for i, e in enumerate(waiting, start=1):
        if e["position"] != i:
            e["position"] = i
            touch(e)


# =====================================================================
# Zones
# =====================================================================
@app.route("/zones", methods=["POST"])
def create_zone():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    data = body()
    name = req_str(data, "name")
    grid_code = req_str(data, "grid_code")
    is_airport = req_bool(data, "is_airport", False)
    base_fare_cents = req_int(data, "base_fare_cents", minimum=100)
    # uniqueness of grid_code
    for z in db.zones.values():
        if z["grid_code"] == grid_code:
            raise err(E.ERR_DUPLICATE_GRID_CODE, "grid_code already exists")
    z = common_fields()
    z.update({
        "name": name, "grid_code": grid_code, "is_airport": is_airport,
        "base_fare_cents": base_fare_cents, "open_demand_count": 0,
        "available_supply_count": 0, "current_multiplier": 1.00, "heat_level": "COOL",
    })
    db.zones[z["id"]] = z
    return success(ser_zone(z), 201)


@app.route("/zones/<zid>", methods=["GET"])
def fetch_zone(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider", "Driver")
    z = get_zone(zid)
    return success(ser_zone(z))


@app.route("/zones", methods=["GET"])
def list_zones():
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider", "Driver")
    items = list(db.zones.values())
    is_airport = request.args.get("is_airport")
    if is_airport is not None:
        want = is_airport.lower() == "true"
        items = [z for z in items if z["is_airport"] == want]
    heat = request.args.get("heat_level")
    if heat is not None:
        items = [z for z in items if z["heat_level"] == heat]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_zone(z) for z in page], 200, meta)


@app.route("/zones/<zid>/surge-snapshots", methods=["POST"])
def publish_snapshot(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    z = get_zone(zid)
    data = body()
    observed_demand = req_int(data, "observed_demand", minimum=0)
    observed_supply = req_int(data, "observed_supply", minimum=0)
    is_rush_hour = req_bool(data, "is_rush_hour", False)
    effective_from = req_datetime_str(data, "effective_from")
    effective_to = req_datetime_str(data, "effective_to")
    expected_zone_version = req_int(data, "expected_zone_version")
    if effective_to <= effective_from:
        raise err(E.ERR_INVALID_REQUEST, "effective_to must be > effective_from")

    # Window overlap (priority 65) — half-open, adjacency allowed.
    for s in db.snapshots.values():
        if s["zone_id"] != zid:
            continue
        if effective_from < s["effective_to"] and s["effective_from"] < effective_to:
            raise err(E.ERR_SNAPSHOT_WINDOW_OVERLAP, "Snapshot window overlaps existing")

    # OCC (priority 13)
    if expected_zone_version != z["version"]:
        raise err(E.ERR_STALE_ZONE_VERSION, "expected_zone_version mismatch")

    ratio, multiplier, capped = calc.surge_multiplier(observed_demand, observed_supply, is_rush_hour)
    s = {
        "id": new_id(), "created_at": iso_now(), "_seq": db.next_seq(),
        "zone_id": zid, "observed_demand": observed_demand,
        "observed_supply": observed_supply, "is_rush_hour": is_rush_hour,
        "effective_from": effective_from, "effective_to": effective_to,
        "ratio": to2(ratio), "multiplier": to2(multiplier), "capped": capped,
    }
    db.snapshots[s["id"]] = s

    z["current_multiplier"] = to2(multiplier)
    z["heat_level"] = calc.heat_level(multiplier)
    touch(z)
    return success(ser_snapshot(s), 201)


@app.route("/zones/<zid>/surge-snapshots", methods=["GET"])
def list_snapshots(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider", "Driver")
    z = get_zone(zid)
    items = [s for s in db.snapshots.values() if s["zone_id"] == zid]
    items = sort_created_desc(items)
    page, meta = paginate(items)
    return success([ser_snapshot(s) for s in page], 200, meta)


@app.route("/zones/<zid>/trips", methods=["GET"])
def list_zone_trips(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    z = get_zone(zid)
    items = [t for t in db.trips.values() if t["pickup_zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_trip(t) for t in page], 200, meta)


@app.route("/zones/<zid>/drivers", methods=["GET"])
def list_zone_drivers(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    z = get_zone(zid)
    items = [d for d in db.drivers.values() if d["home_zone_id"] == zid]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_driver(d) for d in page], 200, meta)


@app.route("/zones/<zid>/airport-queue", methods=["GET"])
def list_zone_queue(zid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    z = get_zone(zid)
    items = [e for e in db.queue_entries.values() if e["zone_id"] == zid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    # WAITING ordered by position ASC; others fall back to created_at ASC.
    waiting = [e for e in items if e["status"] == "WAITING"]
    others = [e for e in items if e["status"] != "WAITING"]
    waiting.sort(key=lambda e: (e["position"], e["created_at"], e["_seq"]))
    others = sort_created_asc(others)
    ordered = waiting + others
    page, meta = paginate(ordered)
    return success([ser_queue(e) for e in page], 200, meta)


# =====================================================================
# Riders
# =====================================================================
@app.route("/riders", methods=["POST"])
def create_rider():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    data = body()
    name = req_str(data, "name")
    home_zone_id = req_str(data, "home_zone_id")
    wallet = opt_int(data, "wallet_balance_cents", 0, minimum=0)
    get_zone(home_zone_id)
    r = common_fields()
    r.update({"name": name, "home_zone_id": home_zone_id, "wallet_balance_cents": wallet})
    db.riders[r["id"]] = r
    return success(ser_rider(r), 201)


@app.route("/riders/<rid>", methods=["GET"])
def fetch_rider(rid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider")
    r = get_rider(rid)
    return success(ser_rider(r))


@app.route("/riders", methods=["GET"])
def list_riders():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    items = list(db.riders.values())
    hz = request.args.get("home_zone_id")
    if hz is not None:
        items = [r for r in items if r["home_zone_id"] == hz]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_rider(r) for r in page], 200, meta)


@app.route("/riders/<rid>/wallet/credit", methods=["POST"])
def credit_wallet(rid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    r = get_rider(rid)
    data = body()
    amount = req_int(data, "amount_cents", minimum=0)
    r["wallet_balance_cents"] += amount
    touch(r)
    return success(ser_rider(r))


# =====================================================================
# Drivers
# =====================================================================
@app.route("/drivers", methods=["POST"])
def create_driver():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    data = body()
    name = req_str(data, "name")
    home_zone_id = req_str(data, "home_zone_id")
    get_zone(home_zone_id)
    d = common_fields()
    d.update({
        "name": name, "home_zone_id": home_zone_id, "current_zone_id": home_zone_id,
        "status": "OFFLINE", "active_trip_id": None,
    })
    db.drivers[d["id"]] = d
    return success(ser_driver(d), 201)


@app.route("/drivers/<did>", methods=["GET"])
def fetch_driver(did):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    d = get_driver(did)
    return success(ser_driver(d))


@app.route("/drivers", methods=["GET"])
def list_drivers():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    items = list(db.drivers.values())
    for fld in ("home_zone_id", "current_zone_id", "active_trip_id", "status"):
        v = request.args.get(fld)
        if v is not None:
            items = [d for d in items if d[fld] == v]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_driver(d) for d in page], 200, meta)


@app.route("/drivers/<did>/go-online", methods=["POST"])
def go_online(did):
    role, uid = get_auth()
    require_role(role, "Driver")
    d = get_driver(did)
    if d["status"] != "OFFLINE":
        raise err(E.ERR_INVALID_STATE, "Driver not OFFLINE")
    if d["active_trip_id"] is not None:
        raise err(E.ERR_INVALID_STATE, "Driver has an active trip")
    d["status"] = "AVAILABLE"
    touch(d)
    zone = db.zones.get(d["current_zone_id"])
    if zone is not None:
        zone_supply_inc(zone)
    return success(ser_driver(d))


@app.route("/drivers/<did>/go-offline", methods=["POST"])
def go_offline(did):
    role, uid = get_auth()
    require_role(role, "Driver")
    d = get_driver(did)
    if d["status"] != "AVAILABLE":
        raise err(E.ERR_INVALID_STATE, "Driver not AVAILABLE")
    d["status"] = "OFFLINE"
    touch(d)
    zone = db.zones.get(d["current_zone_id"])
    if zone is not None:
        zone_supply_dec(zone)
    # Withdraw any WAITING airport queue entry for this driver.
    for e in db.queue_entries.values():
        if e["driver_id"] == did and e["status"] == "WAITING":
            e["status"] = "WITHDRAWN"
            touch(e)
            resequence_queue(e["zone_id"])
            break
    return success(ser_driver(d))


# =====================================================================
# Trips
# =====================================================================
@app.route("/trips", methods=["POST"])
def create_trip():
    role, uid = get_auth()
    require_role(role, "Rider")
    data = body()
    rider_id = req_str(data, "rider_id")
    pickup_zone_id = req_str(data, "pickup_zone_id")
    dropoff_zone_id = req_str(data, "dropoff_zone_id")
    # existence left-to-right: rider, pickup zone, dropoff zone
    rider = get_rider(rider_id)
    pickup = get_zone(pickup_zone_id)
    get_zone(dropoff_zone_id)
    # ownership: acting rider must be the rider
    if uid != rider_id:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Rider id mismatch")
    t = common_fields()
    t.update({
        "rider_id": rider_id, "pickup_zone_id": pickup_zone_id,
        "dropoff_zone_id": dropoff_zone_id, "driver_id": None, "status": "REQUESTED",
        "quoted_multiplier": pickup["current_multiplier"],
        "quoted_base_fare_cents": pickup["base_fare_cents"],
        "final_fare_cents": 0, "driver_payout_cents": 0, "refunded_cents": 0,
    })
    db.trips[t["id"]] = t
    zone_demand_inc(pickup)
    return success(ser_trip(t), 201)


@app.route("/trips/<tid>", methods=["GET"])
def fetch_trip(tid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider", "Driver")
    t = get_trip(tid)
    return success(ser_trip(t))


@app.route("/trips", methods=["GET"])
def list_trips():
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider", "Driver")
    items = list(db.trips.values())
    for fld in ("rider_id", "driver_id", "pickup_zone_id", "dropoff_zone_id", "status"):
        v = request.args.get(fld)
        if v is not None:
            items = [t for t in items if t[fld] == v]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_trip(t) for t in page], 200, meta)


@app.route("/trips/<tid>/start", methods=["POST"])
def start_trip(tid):
    role, uid = get_auth()
    require_role(role, "Driver")
    t = get_trip(tid)
    # ownership before state
    if t["driver_id"] != uid:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Not the assigned driver")
    if t["status"] != "MATCHED":
        raise err(E.ERR_INVALID_STATE, "Trip not MATCHED")
    t["status"] = "ENROUTE"
    touch(t)
    return success(ser_trip(t))


@app.route("/trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    role, uid = get_auth()
    require_role(role, "Driver")
    t = get_trip(tid)
    if t["driver_id"] != uid:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Not the assigned driver")
    if t["status"] != "ENROUTE":
        raise err(E.ERR_INVALID_STATE, "Trip not ENROUTE")

    final_fare = calc.trip_final_fare(t["quoted_base_fare_cents"], t["quoted_multiplier"])
    payout = calc.driver_payout(t["quoted_base_fare_cents"], t["quoted_multiplier"])

    rider = db.riders.get(t["rider_id"])
    if rider is None or rider["wallet_balance_cents"] < final_fare:
        raise err(E.ERR_INSUFFICIENT_WALLET, "Wallet balance insufficient")

    # Commit
    t["final_fare_cents"] = final_fare
    t["driver_payout_cents"] = payout
    t["status"] = "COMPLETED"
    touch(t)

    rider["wallet_balance_cents"] -= final_fare
    touch(rider)

    driver = db.drivers.get(t["driver_id"])
    if driver is not None:
        driver["active_trip_id"] = None
        driver["current_zone_id"] = t["dropoff_zone_id"]
        driver["status"] = "AVAILABLE"
        touch(driver)
        dz = db.zones.get(t["dropoff_zone_id"])
        if dz is not None:
            zone_supply_inc(dz)
        # Quest credit
        for q in db.quests.values():
            if q["driver_id"] == driver["id"] and q["status"] == "ACTIVE":
                q["completed_trips"] += 1
                if q["completed_trips"] >= q["target_trips"]:
                    q["status"] = "EARNED"
                    q["paid_out_cents"] = q["bonus_cents"]
                touch(q)
                break
    return success(ser_trip(t))


@app.route("/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    role, uid = get_auth()
    require_role(role, "Rider")
    t = get_trip(tid)
    if t["rider_id"] != uid:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Not the trip's rider")
    if t["status"] != "MATCHED":
        raise err(E.ERR_INVALID_STATE, "Trip not MATCHED")
    t["status"] = "CANCELLED"
    touch(t)
    driver = db.drivers.get(t["driver_id"]) if t["driver_id"] else None
    if driver is not None:
        driver["active_trip_id"] = None
        driver["status"] = "AVAILABLE"
        touch(driver)
        cz = db.zones.get(driver["current_zone_id"])
        if cz is not None:
            zone_supply_inc(cz)
    return success(ser_trip(t))


@app.route("/trips/<tid>/expire", methods=["POST"])
def expire_trip(tid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    t = get_trip(tid)
    if t["status"] != "REQUESTED":
        raise err(E.ERR_INVALID_STATE, "Trip not REQUESTED")
    t["status"] = "EXPIRED"
    touch(t)
    pickup = db.zones.get(t["pickup_zone_id"])
    if pickup is not None:
        zone_demand_dec(pickup)
    return success(ser_trip(t))


# =====================================================================
# Dispatch tick
# =====================================================================
def _match_trip(t):
    """Attempt to match a REQUESTED trip. Returns True if matched."""
    pickup = db.zones.get(t["pickup_zone_id"])
    if pickup is None:
        return False

    if pickup["is_airport"]:
        # FIFO candidates: drivers with a WAITING queue entry in this zone.
        waiting = [e for e in db.queue_entries.values()
                   if e["zone_id"] == t["pickup_zone_id"] and e["status"] == "WAITING"]
        waiting.sort(key=lambda e: (e["joined_at"], e["created_at"], e["_seq"]))
        chosen_entry = None
        chosen_driver = None
        for e in waiting:
            drv = db.drivers.get(e["driver_id"])
            if drv is not None and drv["status"] == "AVAILABLE":
                chosen_entry = e
                chosen_driver = drv
                break
        if chosen_driver is None:
            return False
    else:
        candidates = [d for d in db.drivers.values()
                      if d["status"] == "AVAILABLE" and d["current_zone_id"] == t["pickup_zone_id"]]
        candidates.sort(key=lambda d: (d["created_at"], d["_seq"]))
        if not candidates:
            return False
        chosen_driver = candidates[0]
        chosen_entry = None

    # Cascade
    t["driver_id"] = chosen_driver["id"]
    t["status"] = "MATCHED"
    touch(t)

    # Driver AVAILABLE -> ON_TRIP
    chosen_driver["status"] = "ON_TRIP"
    chosen_driver["active_trip_id"] = t["id"]
    touch(chosen_driver)
    dz = db.zones.get(chosen_driver["current_zone_id"])
    if dz is not None:
        zone_supply_dec(dz)

    # pickup demand -1
    zone_demand_dec(pickup)

    # airport entry -> DISPATCHED + re-sequence
    if chosen_entry is not None:
        chosen_entry["status"] = "DISPATCHED"
        touch(chosen_entry)
        resequence_queue(chosen_entry["zone_id"])
    return True


@app.route("/_dispatch/tick", methods=["POST"])
def dispatch_tick():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    data = body()
    zone_id = data.get("zone_id")
    if zone_id is not None:
        if not isinstance(zone_id, str):
            raise err(E.ERR_INVALID_REQUEST, "zone_id must be a string")
        get_zone(zone_id)

    requested = [t for t in db.trips.values() if t["status"] == "REQUESTED"]
    if zone_id is not None:
        requested = [t for t in requested if t["pickup_zone_id"] == zone_id]
    requested.sort(key=lambda t: (t["created_at"], t["_seq"]))

    matched_ids = []
    for t in requested:
        if _match_trip(t):
            matched_ids.append(t["id"])
    return success({"matched_trip_ids": matched_ids, "matched_count": len(matched_ids)})


# =====================================================================
# Airport queue
# =====================================================================
@app.route("/airport-queue", methods=["POST"])
def join_queue():
    role, uid = get_auth()
    require_role(role, "Driver")
    data = body()
    zone_id = req_str(data, "zone_id")
    driver_id = req_str(data, "driver_id")
    zone = get_zone(zone_id)
    driver = get_driver(driver_id)
    # ownership
    if uid != driver_id:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Driver id mismatch")
    # airport zone (priority 7)
    if not zone["is_airport"]:
        raise err(E.ERR_NOT_AIRPORT_ZONE, "Zone is not an airport")
    # already queued (priority 8)
    for e in db.queue_entries.values():
        if e["driver_id"] == driver_id and e["status"] == "WAITING":
            raise err(E.ERR_ALREADY_QUEUED, "Driver already has a WAITING entry")
    # driver availability (priority 9)
    if driver["status"] != "AVAILABLE":
        raise err(E.ERR_DRIVER_NOT_AVAILABLE, "Driver not AVAILABLE")

    e = common_fields()
    e.update({
        "zone_id": zone_id, "driver_id": driver_id,
        "joined_at": e["created_at"], "status": "WAITING", "position": 0,
    })
    db.queue_entries[e["id"]] = e
    resequence_queue(zone_id)
    return success(ser_queue(e), 201)


@app.route("/airport-queue/<qid>", methods=["GET"])
def fetch_queue(qid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    e = get_queue_entry(qid)
    return success(ser_queue(e))


@app.route("/airport-queue", methods=["GET"])
def list_queue():
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    items = list(db.queue_entries.values())
    for fld in ("zone_id", "driver_id", "status"):
        v = request.args.get(fld)
        if v is not None:
            items = [e for e in items if e[fld] == v]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_queue(e) for e in page], 200, meta)


@app.route("/airport-queue/<qid>/withdraw", methods=["POST"])
def withdraw_queue(qid):
    role, uid = get_auth()
    require_role(role, "Driver")
    e = get_queue_entry(qid)
    if e["driver_id"] != uid:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Not the queue entry's driver")
    if e["status"] != "WAITING":
        raise err(E.ERR_INVALID_STATE, "Entry not WAITING")
    e["status"] = "WITHDRAWN"
    touch(e)
    resequence_queue(e["zone_id"])
    return success(ser_queue(e))


# =====================================================================
# Quests
# =====================================================================
@app.route("/quests", methods=["POST"])
def create_quest():
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    data = body()
    driver_id = req_str(data, "driver_id")
    target_trips = req_int(data, "target_trips", minimum=1)
    bonus_cents = req_int(data, "bonus_cents", minimum=0)
    window_start = req_datetime_str(data, "window_start")
    window_end = req_datetime_str(data, "window_end")
    get_driver(driver_id)
    if window_end < window_start:
        raise err(E.ERR_INVALID_REQUEST, "window_end must be >= window_start")
    # window overlap (priority 66) — closed, adjacency forbidden, vs ACTIVE/EARNED.
    for q in db.quests.values():
        if q["driver_id"] != driver_id:
            continue
        if q["status"] not in ("ACTIVE", "EARNED"):
            continue
        if window_start <= q["window_end"] and q["window_start"] <= window_end:
            raise err(E.ERR_QUEST_WINDOW_OVERLAP, "Quest window overlaps existing")
    q = common_fields()
    q.update({
        "driver_id": driver_id, "target_trips": target_trips, "bonus_cents": bonus_cents,
        "window_start": window_start, "window_end": window_end,
        "completed_trips": 0, "status": "ACTIVE", "paid_out_cents": 0,
    })
    db.quests[q["id"]] = q
    return success(ser_quest(q), 201)


@app.route("/quests/<qid>", methods=["GET"])
def fetch_quest(qid):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    q = get_quest(qid)
    return success(ser_quest(q))


@app.route("/quests", methods=["GET"])
def list_quests():
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Driver")
    items = list(db.quests.values())
    for fld in ("driver_id", "status"):
        v = request.args.get(fld)
        if v is not None:
            items = [q for q in items if q[fld] == v]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_quest(q) for q in page], 200, meta)


@app.route("/quests/<qid>/expire", methods=["POST"])
def expire_quest(qid):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    q = get_quest(qid)
    if q["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Quest not ACTIVE")
    q["status"] = "EXPIRED"
    touch(q)
    return success(ser_quest(q))


# =====================================================================
# Disputes
# =====================================================================
VALID_REASONS = {"OVERCHARGED", "DRIVER_NO_SHOW", "ROUTE_ERROR"}


@app.route("/disputes", methods=["POST"])
def create_dispute():
    role, uid = get_auth()
    require_role(role, "Rider")
    data = body()
    trip_id = req_str(data, "trip_id")
    reason = data.get("reason")
    if not isinstance(reason, str) or reason not in VALID_REASONS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid reason")
    # requested_refund_cents presence/type checked as request validation;
    # the >=1 business check has its own error.
    requested = data.get("requested_refund_cents")
    if isinstance(requested, bool) or not isinstance(requested, int):
        raise err(E.ERR_INVALID_REQUEST, "requested_refund_cents must be an integer")
    trip = get_trip(trip_id)
    # ownership: acting rider must own the trip
    if trip["rider_id"] != uid:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Not the trip's rider")
    # trip must be COMPLETED (priority 10)
    if trip["status"] != "COMPLETED":
        raise err(E.ERR_TRIP_NOT_COMPLETED, "Trip not COMPLETED")
    # refund amount >= 1 (priority 11)
    if requested < 1:
        raise err(E.ERR_INVALID_REFUND_AMOUNT, "requested_refund_cents must be >= 1")
    d = common_fields()
    d.update({
        "trip_id": trip_id, "rider_id": trip["rider_id"], "reason": reason,
        "requested_refund_cents": requested, "status": "OPEN", "refund_cents": 0,
    })
    db.disputes[d["id"]] = d
    return success(ser_dispute(d), 201)


@app.route("/disputes/<did>", methods=["GET"])
def fetch_dispute(did):
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider")
    d = get_dispute(did)
    return success(ser_dispute(d))


@app.route("/disputes", methods=["GET"])
def list_disputes():
    role, uid = get_auth()
    require_role(role, "Dispatcher", "Rider")
    items = list(db.disputes.values())
    for fld in ("trip_id", "rider_id", "status"):
        v = request.args.get(fld)
        if v is not None:
            items = [d for d in items if d[fld] == v]
    items = sort_created_asc(items)
    page, meta = paginate(items)
    return success([ser_dispute(d) for d in page], 200, meta)


@app.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    role, uid = get_auth()
    require_role(role, "Dispatcher")
    d = get_dispute(did)
    data = body()
    decision = data.get("decision")
    if decision not in ("UPHELD", "REJECTED"):
        raise err(E.ERR_INVALID_REQUEST, "decision must be UPHELD or REJECTED")
    if d["status"] != "OPEN":
        raise err(E.ERR_INVALID_STATE, "Dispute not OPEN")
    trip = db.trips.get(d["trip_id"])

    if decision == "UPHELD":
        if trip is None or trip["status"] != "COMPLETED":
            raise err(E.ERR_INVALID_STATE, "Disputed trip not COMPLETED")
        refund = calc.dispute_refund(
            d["requested_refund_cents"], trip["final_fare_cents"], trip["refunded_cents"])
        d["refund_cents"] = refund
        d["status"] = "UPHELD"
        touch(d)
        if refund > 0:
            rider = db.riders.get(d["rider_id"])
            if rider is not None:
                rider["wallet_balance_cents"] += refund
                touch(rider)
            trip["refunded_cents"] += refund
            touch(trip)
    else:
        d["status"] = "REJECTED"
        touch(d)
    return success(ser_dispute(d))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
