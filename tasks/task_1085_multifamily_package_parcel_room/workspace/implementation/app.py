"""Multifamily Package & Parcel Room API — Flask implementation.

All storage is in-memory (see db.py). The store starts empty on every boot.
"""
import os
import random
import string
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

import db
from errors import *  # noqa: F401,F403  (error id constants + ApiError)

app = Flask(__name__)

ROLES = {"PropertyManager", "ConciergeStaff", "Resident", "Carrier", "PmsIntegration"}
ALL_ROLES = list(ROLES)

SIZE_RANK = {"SMALL": 1, "MEDIUM": 2, "LARGE": 3, "OVERSIZE": 4}
SIZE_CLASSES = set(SIZE_RANK.keys())
PACKAGE_STORAGE_TYPES = {"AMBIENT", "COLD", "PERISHABLE"}
LOCKER_STORAGE_CLASSES = {"AMBIENT", "REFRIGERATED"}
NOTIFY_CHANNELS = {"EMAIL", "SMS", "PUSH"}

PACKAGE_TERMINAL = {"PICKED_UP", "RETURNED", "DISPOSED"}


# ===========================================================================
# Response envelope
# ===========================================================================
def _meta(extra=None):
    m = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.fmt(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def make_list(items, serializer):
    """Apply pagination + created_at ascending sort; return (page, meta)."""
    args = request.args
    limit = _parse_pagination_int(args.get("limit"), default=10, lo=1, hi=100)
    offset = _parse_pagination_int(args.get("offset"), default=0, lo=0, hi=None)
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serializer(e) for e in page], meta


def _parse_pagination_int(raw, default, lo, hi):
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_VALIDATION, "message": "Unknown route"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": ERR_VALIDATION, "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ===========================================================================
# Auth
# ===========================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_MISSING_AUTH_HEADER, 401, "Missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")


# ===========================================================================
# Body / field helpers
# ===========================================================================
def get_json_body():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {f}")


def check_enum(value, allowed, name):
    if value not in allowed:
        raise ApiError(ERR_VALIDATION, 400, f"Invalid {name}: {value}")


def check_str(value, name):
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be a non-empty string")


def check_non_negative_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be a number")
    if value < 0:
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be non-negative")


def check_non_negative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be an integer")
    if value < 0:
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be non-negative")


# ===========================================================================
# Common system fields
# ===========================================================================
def new_entity(extra):
    ts = db.now()
    ent = {
        "id": db.new_id(),
        "created_at": db.fmt(ts),
        "updated_at": db.fmt(ts),
        "version": 1,
        "_seq": db.next_seq(),
    }
    ent.update(extra)
    return ent


def touch(ent):
    ent["updated_at"] = db.fmt(db.now())
    ent["version"] = ent.get("version", 1) + 1


# ===========================================================================
# Existence lookups (raise the specific 404 when absent)
# ===========================================================================
def get_property(pid):
    p = db.properties.get(pid)
    if p is None:
        raise ApiError(ERR_PROPERTY_NOT_FOUND, 404, "Property not found")
    return p


def get_locker_bank(bid):
    b = db.locker_banks.get(bid)
    if b is None:
        raise ApiError(ERR_LOCKER_BANK_NOT_FOUND, 404, "LockerBank not found")
    return b


def get_locker(lid):
    l = db.lockers.get(lid)
    if l is None:
        raise ApiError(ERR_LOCKER_NOT_FOUND, 404, "Locker not found")
    return l


def get_shelf(sid):
    s = db.shelves.get(sid)
    if s is None:
        raise ApiError(ERR_SHELF_NOT_FOUND, 404, "Shelf not found")
    return s


def get_resident(rid):
    r = db.residents.get(rid)
    if r is None:
        raise ApiError(ERR_RESIDENT_NOT_FOUND, 404, "Resident not found")
    return r


def get_carrier(cid):
    c = db.carriers.get(cid)
    if c is None:
        raise ApiError(ERR_CARRIER_NOT_FOUND, 404, "Carrier not found")
    return c


def get_package(pid):
    p = db.packages.get(pid)
    if p is None:
        raise ApiError(ERR_PACKAGE_NOT_FOUND, 404, "Package not found")
    return p


def get_retail_return(rid):
    r = db.retail_returns.get(rid)
    if r is None:
        raise ApiError(ERR_RETAIL_RETURN_NOT_FOUND, 404, "RetailReturn not found")
    return r


# ===========================================================================
# Relationship helpers
# ===========================================================================
def lockers_of_bank(bank_id):
    return [l for l in db.lockers.values() if l["locker_bank_id"] == bank_id]


def lockers_of_property(property_id):
    bank_ids = {b["id"] for b in db.locker_banks.values() if b["property_id"] == property_id}
    return [l for l in db.lockers.values() if l["locker_bank_id"] in bank_ids]


def bank_property_id(bank_id):
    b = db.locker_banks.get(bank_id)
    return b["property_id"] if b else None


def packages_of_property(property_id):
    return [p for p in db.packages.values() if p["property_id"] == property_id]


def charges_of_package(package_id):
    return [c for c in db.storage_charges.values() if c["package_id"] == package_id]


def required_storage_class(storage_type):
    return "AMBIENT" if storage_type == "AMBIENT" else "REFRIGERATED"


# ===========================================================================
# Computed counts
# ===========================================================================
def occupied_locker_count(property_id):
    return sum(1 for l in lockers_of_property(property_id) if l["status"] == "OCCUPIED")


def in_service_locker_count(property_id):
    return sum(1 for l in lockers_of_property(property_id) if l["status"] != "OUT_OF_SERVICE")


def uncollected_fee_cents(property_id):
    pkg_ids = {p["id"] for p in packages_of_property(property_id)}
    total = 0
    for c in db.storage_charges.values():
        if c["package_id"] in pkg_ids and c["charge_type"] == "HOLDING_FEE" and c["status"] == "OUTSTANDING":
            total += c["amount_cents"]
    return total


def return_staging_count(property_id):
    return sum(
        1 for r in db.retail_returns.values()
        if r["property_id"] == property_id and r["status"] in ("DROPPED_OFF", "AWAITING_CARRIER")
    )


def bank_nominal_count(bank_id):
    return len(lockers_of_bank(bank_id))


def bank_available_count(bank_id):
    return sum(1 for l in lockers_of_bank(bank_id) if l["status"] == "AVAILABLE")


def shelf_occupied_count(shelf_id):
    return sum(
        1 for p in db.packages.values()
        if p.get("shelf_id") == shelf_id and p["status"] == "AWAITING_PICKUP"
    )


# ===========================================================================
# Posture + property version bump
# ===========================================================================
def compute_posture(prop):
    in_svc = in_service_locker_count(prop["id"])
    occ = occupied_locker_count(prop["id"])
    utilization = 1.0 if in_svc == 0 else (occ / in_svc)
    threshold = prop["overflow_threshold_pct"]
    if utilization >= 1.0:
        return "FROZEN"
    if utilization >= threshold and utilization < 1.0:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(prop):
    """Recompute + persist posture WITHOUT bumping version."""
    prop["occupancy_posture"] = compute_posture(prop)


def occupancy_event(prop):
    """A locker occupancy / in-service change: recompute posture, bump version."""
    prop["occupancy_posture"] = compute_posture(prop)
    touch(prop)


# ===========================================================================
# Fee calculation
# ===========================================================================
def _round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def holding_fee_gross(pkg, prop, end):
    """Gross holding fee in cents accrued from intake_at to `end`."""
    intake = db.parse_iso(pkg["intake_at"])
    elapsed_days = int((end - intake).total_seconds() // 86400)
    if elapsed_days < 0:
        elapsed_days = 0
    chargeable_days = max(0, elapsed_days - prop["holding_fee_grace_days"])
    multiplier = prop["perishable_fee_multiplier"] if pkg["storage_type"] in ("COLD", "PERISHABLE") else 1
    daily = Decimal(str(prop["holding_fee_daily_cents"])) * Decimal(str(multiplier))
    per_day = _round_half_up(daily)
    gross = per_day * chargeable_days
    if pkg["is_oversize"]:
        gross += prop["oversize_surcharge_cents"]
    gross = min(gross, prop["holding_fee_cap_cents"])
    return gross


def net_after_discount(gross, resident):
    disc = Decimal(str(resident["loyalty_discount_pct"]))
    net = Decimal(gross) * (Decimal(1) - disc)
    return _round_half_up(net)


def provisional_fee(pkg):
    prop = db.properties.get(pkg["property_id"])
    if prop is None:
        return 0
    if pkg["status"] in PACKAGE_TERMINAL or pkg["status"] == "RETURN_INITIATED":
        return pkg["final_fee_cents"] if pkg["final_fee_cents"] is not None else 0
    return holding_fee_gross(pkg, prop, db.now())


# ===========================================================================
# Storage class fit
# ===========================================================================
def locker_fits(locker, pkg):
    return SIZE_RANK[locker["size_class"]] >= SIZE_RANK[pkg["size_class"]]


# ===========================================================================
# Serializers
# ===========================================================================
def ser_property(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "timezone": p["timezone"],
        "overflow_threshold_pct": p["overflow_threshold_pct"],
        "aging_days_standard": p["aging_days_standard"],
        "aging_days_perishable": p["aging_days_perishable"],
        "perishable_hold_hours": p["perishable_hold_hours"],
        "holding_fee_grace_days": p["holding_fee_grace_days"],
        "holding_fee_daily_cents": p["holding_fee_daily_cents"],
        "perishable_fee_multiplier": p["perishable_fee_multiplier"],
        "oversize_surcharge_cents": p["oversize_surcharge_cents"],
        "holding_fee_cap_cents": p["holding_fee_cap_cents"],
        "return_staging_capacity": p["return_staging_capacity"],
        "occupancy_posture": p["occupancy_posture"],
        "occupied_locker_count": occupied_locker_count(p["id"]),
        "in_service_locker_count": in_service_locker_count(p["id"]),
        "uncollected_fee_cents": uncollected_fee_cents(p["id"]),
        "return_staging_count": return_staging_count(p["id"]),
    }


def ser_locker_bank(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "property_id": b["property_id"],
        "label": b["label"],
        "storage_class": b["storage_class"],
        "nominal_locker_count": bank_nominal_count(b["id"]),
        "available_locker_count": bank_available_count(b["id"]),
    }


def ser_locker(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "locker_bank_id": l["locker_bank_id"],
        "size_class": l["size_class"],
        "storage_class": l["storage_class"],
        "status": l["status"],
        "current_package_id": l["current_package_id"],
    }


def ser_shelf(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "property_id": s["property_id"],
        "zone": s["zone"],
        "storage_class": s["storage_class"],
        "capacity": s["capacity"],
        "occupied_count": shelf_occupied_count(s["id"]),
    }


def ser_resident(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "property_id": r["property_id"],
        "unit_number": r["unit_number"],
        "full_name": r["full_name"],
        "email": r["email"],
        "phone": r["phone"],
        "notify_channel": r["notify_channel"],
        "loyalty_discount_pct": r["loyalty_discount_pct"],
        "status": r["status"],
    }


def ser_carrier(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "property_id": c["property_id"],
        "name": c["name"],
        "scac": c["scac"],
        "allows_smart_locker_delivery": c["allows_smart_locker_delivery"],
    }


def ser_package(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "property_id": p["property_id"],
        "resident_id": p["resident_id"],
        "carrier_id": p["carrier_id"],
        "locker_id": p["locker_id"],
        "shelf_id": p["shelf_id"],
        "tracking_number": p["tracking_number"],
        "size_class": p["size_class"],
        "storage_type": p["storage_type"],
        "is_oversize": p["is_oversize"],
        "storage_mode": p["storage_mode"],
        "pickup_code": p["pickup_code"],
        "status": p["status"],
        "intake_at": p["intake_at"],
        "notified_at": p["notified_at"],
        "picked_up_at": p.get("picked_up_at"),
        "cold_chain_deadline_at": p["cold_chain_deadline_at"],
        "aging_deadline_at": p["aging_deadline_at"],
        "provisional_fee_cents": provisional_fee(p),
        "final_fee_cents": p["final_fee_cents"],
        "notify_count": p["notify_count"],
        "return_initiated_by_user_id": p["return_initiated_by_user_id"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "package_id": n["package_id"],
        "channel": n["channel"],
        "kind": n["kind"],
        "pickup_code": n["pickup_code"],
        "sent_at": n["sent_at"],
    }


def ser_retail_return(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "property_id": r["property_id"],
        "resident_id": r["resident_id"],
        "carrier_id": r["carrier_id"],
        "tracking_number": r["tracking_number"],
        "status": r["status"],
        "dropped_off_at": r["dropped_off_at"],
        "reject_reason": r["reject_reason"],
    }


def ser_charge(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "package_id": c["package_id"],
        "charge_type": c["charge_type"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "basis": c["basis"],
        "settled_at": c["settled_at"],
    }


# ===========================================================================
# Domain service helpers
# ===========================================================================
def mint_pickup_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_notification(pkg, kind, channel, pickup_code):
    n = new_entity({
        "package_id": pkg["id"],
        "channel": channel,
        "kind": kind,
        "pickup_code": pickup_code,
        "sent_at": db.fmt(db.now()),
    })
    db.notifications[n["id"]] = n
    return n


def fee_basis(chargeable_days, per_day, oversize_cents):
    return f"{chargeable_days} chargeable days x {per_day} + {oversize_cents} oversize"


def fee_components(pkg, prop, end):
    """Return (gross, chargeable_days, per_day, oversize_cents)."""
    intake = db.parse_iso(pkg["intake_at"])
    elapsed_days = int((end - intake).total_seconds() // 86400)
    if elapsed_days < 0:
        elapsed_days = 0
    chargeable_days = max(0, elapsed_days - prop["holding_fee_grace_days"])
    multiplier = prop["perishable_fee_multiplier"] if pkg["storage_type"] in ("COLD", "PERISHABLE") else 1
    daily = Decimal(str(prop["holding_fee_daily_cents"])) * Decimal(str(multiplier))
    per_day = _round_half_up(daily)
    gross = per_day * chargeable_days
    oversize_cents = prop["oversize_surcharge_cents"] if pkg["is_oversize"] else 0
    gross += oversize_cents
    gross = min(gross, prop["holding_fee_cap_cents"])
    return gross, chargeable_days, per_day, oversize_cents


def create_holding_charge(pkg, prop, resident, gross, components, status):
    """Create a HOLDING_FEE StorageCharge; returns the charge (or None if gross<=0)."""
    if gross <= 0:
        return None
    net = net_after_discount(gross, resident)
    _, chargeable_days, per_day, oversize_cents = components
    settled = db.fmt(db.now()) if status != "OUTSTANDING" else None
    c = new_entity({
        "package_id": pkg["id"],
        "charge_type": "HOLDING_FEE",
        "amount_cents": net,
        "status": status,
        "basis": fee_basis(chargeable_days, per_day, oversize_cents),
        "settled_at": settled,
    })
    db.storage_charges[c["id"]] = c
    return c


def release_storage(pkg):
    """Release whatever storage the package occupies; clear its assignment."""
    if pkg.get("locker_id"):
        locker = db.lockers.get(pkg["locker_id"])
        if locker is not None:
            locker["status"] = "AVAILABLE"
            locker["current_package_id"] = None
            touch(locker)
    pkg["locker_id"] = None
    pkg["shelf_id"] = None
    pkg["storage_mode"] = "NONE"


# ---- posture gating -------------------------------------------------------
def posture_allows_locker(prop, req_class):
    posture = prop["occupancy_posture"]
    if posture == "FROZEN":
        return False
    if posture == "RESTRICTED" and req_class == "AMBIENT":
        return False
    return True


def gate_locker_posture(prop, req_class):
    posture = prop["occupancy_posture"]
    if posture == "FROZEN":
        raise ApiError(ERR_STORAGE_FROZEN, 409, "Locker assignment blocked: property FROZEN")
    if posture == "RESTRICTED" and req_class == "AMBIENT":
        raise ApiError(ERR_STORAGE_RESTRICTED, 409, "AMBIENT locker assignment blocked: property RESTRICTED")


# ---- auto pick ------------------------------------------------------------
def auto_pick_locker(prop, req_class, pkg):
    candidates = [
        l for l in lockers_of_property(prop["id"])
        if l["status"] == "AVAILABLE" and l["storage_class"] == req_class and locker_fits(l, pkg)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (SIZE_RANK[l["size_class"]], l["created_at"], l["_seq"]))
    return candidates[0]


def auto_pick_shelf(prop, req_class):
    candidates = [
        s for s in db.shelves.values()
        if s["property_id"] == prop["id"] and s["storage_class"] == req_class
        and shelf_occupied_count(s["id"]) < s["capacity"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return candidates[0]


def resolve_storage(pkg, prop, body):
    """Resolve and validate the storage target. Returns ('LOCKER', locker) or ('SHELF', shelf)."""
    req_class = required_storage_class(pkg["storage_type"])
    locker_id = body.get("locker_id")
    shelf_id = body.get("shelf_id")
    storage_target = body.get("storage_target")
    if storage_target is not None and storage_target not in ("LOCKER", "SHELF"):
        raise ApiError(ERR_VALIDATION, 400, f"Invalid storage_target: {storage_target}")

    if locker_id is not None:
        locker = get_locker(locker_id)
        gate_locker_posture(prop, req_class)
        if locker["status"] != "AVAILABLE":
            raise ApiError(ERR_LOCKER_UNAVAILABLE, 409, "Locker not available")
        if not locker_fits(locker, pkg):
            raise ApiError(ERR_LOCKER_SIZE_MISMATCH, 409, "Locker too small for package")
        if locker["storage_class"] != req_class:
            raise ApiError(ERR_LOCKER_SIZE_MISMATCH, 409, "Locker storage class mismatch")
        return "LOCKER", locker

    if shelf_id is not None:
        shelf = get_shelf(shelf_id)
        if shelf["storage_class"] != req_class:
            raise ApiError(ERR_LOCKER_SIZE_MISMATCH, 409, "Shelf storage class mismatch")
        if shelf_occupied_count(shelf["id"]) >= shelf["capacity"]:
            raise ApiError(ERR_SHELF_FULL, 409, "Shelf is full")
        return "SHELF", shelf

    if storage_target == "SHELF":
        shelf = auto_pick_shelf(prop, req_class)
        if shelf is None:
            raise ApiError(ERR_NO_STORAGE_AVAILABLE, 409, "No eligible shelf")
        return "SHELF", shelf

    if storage_target == "LOCKER":
        gate_locker_posture(prop, req_class)
        locker = auto_pick_locker(prop, req_class, pkg)
        if locker is None:
            raise ApiError(ERR_NO_STORAGE_AVAILABLE, 409, "No eligible locker")
        return "LOCKER", locker

    # Fully auto: prefer a locker (when posture permits), else fall back to shelf.
    locker = None
    if posture_allows_locker(prop, req_class):
        locker = auto_pick_locker(prop, req_class, pkg)
    if locker is not None:
        return "LOCKER", locker
    shelf = auto_pick_shelf(prop, req_class)
    if shelf is not None:
        return "SHELF", shelf
    raise ApiError(ERR_NO_STORAGE_AVAILABLE, 409, "No eligible locker or shelf")


# ===========================================================================
# Policy field validation (shared by create + patch)
# ===========================================================================
def validate_policy_fields(body):
    if "overflow_threshold_pct" in body and body["overflow_threshold_pct"] is not None:
        v = body["overflow_threshold_pct"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= 1):
            raise ApiError(ERR_VALIDATION, 400, "overflow_threshold_pct must be in (0, 1]")
    for f in ("aging_days_standard", "aging_days_perishable", "perishable_hold_hours",
              "holding_fee_grace_days", "holding_fee_daily_cents", "oversize_surcharge_cents",
              "holding_fee_cap_cents", "return_staging_capacity"):
        if f in body and body[f] is not None:
            check_non_negative_int(body[f], f)
    if "perishable_fee_multiplier" in body and body["perishable_fee_multiplier"] is not None:
        check_non_negative_number(body["perishable_fee_multiplier"], "perishable_fee_multiplier")


POLICY_FIELDS = [
    "overflow_threshold_pct", "aging_days_standard", "aging_days_perishable",
    "perishable_hold_hours", "holding_fee_grace_days", "holding_fee_daily_cents",
    "perishable_fee_multiplier", "oversize_surcharge_cents", "holding_fee_cap_cents",
    "return_staging_capacity",
]

POLICY_DEFAULTS = {
    "timezone": "UTC",
    "overflow_threshold_pct": 0.85,
    "aging_days_standard": 10,
    "aging_days_perishable": 2,
    "perishable_hold_hours": 48,
    "holding_fee_grace_days": 3,
    "holding_fee_daily_cents": 150,
    "perishable_fee_multiplier": 2,
    "oversize_surcharge_cents": 500,
    "holding_fee_cap_cents": 5000,
    "return_staging_capacity": 25,
}


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"PropertyManager", "PmsIntegration"})
    body = get_json_body()
    if body.get("to_iso8601") is None:
        raise ApiError(ERR_VALIDATION, 400, "to_iso8601 is required")
    try:
        dt = db.parse_iso(body["to_iso8601"])
    except Exception:
        raise ApiError(ERR_VALIDATION, 400, "to_iso8601 is not a valid ISO 8601 instant")
    db.set_clock(dt)
    return ok({}, 200)


# ===========================================================================
# Property
# ===========================================================================
@app.route("/parcelroom/properties", methods=["POST"])
def create_property():
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    body = get_json_body()
    if body.get("name") is None:
        raise ApiError(ERR_VALIDATION, 400, "name is required")
    check_str(body["name"], "name")
    if body.get("timezone") is not None and not isinstance(body["timezone"], str):
        raise ApiError(ERR_VALIDATION, 400, "timezone must be a string")
    validate_policy_fields(body)

    fields = {"name": body["name"]}
    fields["timezone"] = body.get("timezone") if body.get("timezone") is not None else POLICY_DEFAULTS["timezone"]
    for f in POLICY_FIELDS:
        fields[f] = body[f] if body.get(f) is not None else POLICY_DEFAULTS[f]
    fields["occupancy_posture"] = "OPEN"
    prop = new_entity(fields)
    db.properties[prop["id"]] = prop
    return ok(ser_property(prop), 201)


@app.route("/parcelroom/properties/<pid>", methods=["GET"])
def get_property_route(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    prop = get_property(pid)
    return ok(ser_property(prop), 200)


@app.route("/parcelroom/properties/<pid>/policy", methods=["PATCH"])
def update_policy(pid):
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    prop = get_property(pid)
    body = get_json_body()
    if body.get("expected_property_version") is None:
        raise ApiError(ERR_VALIDATION, 400, "expected_property_version is required")
    expected = body["expected_property_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_VALIDATION, 400, "expected_property_version must be an integer")
    if expected != prop["version"]:
        raise ApiError(ERR_STALE_PROPERTY_VERSION, 412, "Stale property version")
    validate_policy_fields(body)
    for f in POLICY_FIELDS:
        if f in body and body[f] is not None:
            prop[f] = body[f]
    touch(prop)
    recompute_posture(prop)
    return ok(ser_property(prop), 200)


@app.route("/parcelroom/properties/<pid>/report", methods=["GET"])
def property_report(pid):
    _, role = authenticate()
    require_role(role, {"PropertyManager", "ConciergeStaff"})
    prop = get_property(pid)
    return ok(ser_property(prop), 200)


@app.route("/parcelroom/properties/<pid>/locker-banks", methods=["GET"])
def list_property_banks(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_property(pid)
    items = [b for b in db.locker_banks.values() if b["property_id"] == pid]
    page, meta = make_list(items, ser_locker_bank)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/properties/<pid>/shelves", methods=["GET"])
def list_property_shelves(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_property(pid)
    items = [s for s in db.shelves.values() if s["property_id"] == pid]
    page, meta = make_list(items, ser_shelf)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/properties/<pid>/residents", methods=["GET"])
def list_property_residents(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_property(pid)
    items = [r for r in db.residents.values() if r["property_id"] == pid]
    page, meta = make_list(items, ser_resident)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/properties/<pid>/carriers", methods=["GET"])
def list_property_carriers(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_property(pid)
    items = [c for c in db.carriers.values() if c["property_id"] == pid]
    page, meta = make_list(items, ser_carrier)
    return ok(page, 200, "array", meta)


# ===========================================================================
# LockerBank
# ===========================================================================
@app.route("/parcelroom/locker-banks", methods=["POST"])
def create_locker_bank():
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    body = get_json_body()
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    require_fields(body, ["property_id", "label", "storage_class"])
    check_str(body["label"], "label")
    check_enum(body["storage_class"], LOCKER_STORAGE_CLASSES, "storage_class")
    bank = new_entity({
        "property_id": body["property_id"],
        "label": body["label"],
        "storage_class": body["storage_class"],
    })
    db.locker_banks[bank["id"]] = bank
    return ok(ser_locker_bank(bank), 201)


@app.route("/parcelroom/locker-banks/<bid>", methods=["GET"])
def get_locker_bank_route(bid):
    _, role = authenticate()
    require_role(role, ROLES)
    bank = get_locker_bank(bid)
    return ok(ser_locker_bank(bank), 200)


@app.route("/parcelroom/locker-banks/<bid>/lockers", methods=["GET"])
def list_bank_lockers(bid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_locker_bank(bid)
    items = [l for l in db.lockers.values() if l["locker_bank_id"] == bid]
    page, meta = make_list(items, ser_locker)
    return ok(page, 200, "array", meta)


# ===========================================================================
# Locker
# ===========================================================================
@app.route("/parcelroom/lockers", methods=["POST"])
def create_locker():
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    body = get_json_body()
    if body.get("locker_bank_id") is not None:
        bank = get_locker_bank(body["locker_bank_id"])
    else:
        bank = None
    require_fields(body, ["locker_bank_id", "size_class"])
    check_enum(body["size_class"], SIZE_CLASSES, "size_class")
    storage_class = body.get("storage_class")
    if storage_class is not None:
        check_enum(storage_class, LOCKER_STORAGE_CLASSES, "storage_class")
    else:
        storage_class = bank["storage_class"]
    locker = new_entity({
        "locker_bank_id": body["locker_bank_id"],
        "size_class": body["size_class"],
        "storage_class": storage_class,
        "status": "AVAILABLE",
        "current_package_id": None,
    })
    db.lockers[locker["id"]] = locker
    prop = db.properties.get(bank["property_id"])
    if prop is not None:
        occupancy_event(prop)
    return ok(ser_locker(locker), 201)


@app.route("/parcelroom/lockers/<lid>", methods=["GET"])
def get_locker_route(lid):
    _, role = authenticate()
    require_role(role, ROLES)
    locker = get_locker(lid)
    return ok(ser_locker(locker), 200)


@app.route("/parcelroom/lockers/<lid>/out-of-service", methods=["POST"])
def locker_out_of_service(lid):
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    locker = get_locker(lid)
    if locker["status"] != "AVAILABLE":
        raise ApiError(ERR_LOCKER_UNAVAILABLE, 409, "Only an AVAILABLE locker may be taken out of service")
    locker["status"] = "OUT_OF_SERVICE"
    locker["current_package_id"] = None
    touch(locker)
    prop = db.properties.get(bank_property_id(locker["locker_bank_id"]))
    if prop is not None:
        occupancy_event(prop)
    return ok(ser_locker(locker), 200)


# ===========================================================================
# Shelf
# ===========================================================================
@app.route("/parcelroom/shelves", methods=["POST"])
def create_shelf():
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    body = get_json_body()
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    require_fields(body, ["property_id", "zone", "storage_class", "capacity"])
    check_str(body["zone"], "zone")
    check_enum(body["storage_class"], LOCKER_STORAGE_CLASSES, "storage_class")
    cap = body["capacity"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise ApiError(ERR_VALIDATION, 400, "capacity must be an integer > 0")
    shelf = new_entity({
        "property_id": body["property_id"],
        "zone": body["zone"],
        "storage_class": body["storage_class"],
        "capacity": cap,
    })
    db.shelves[shelf["id"]] = shelf
    return ok(ser_shelf(shelf), 201)


@app.route("/parcelroom/shelves/<sid>", methods=["GET"])
def get_shelf_route(sid):
    _, role = authenticate()
    require_role(role, ROLES)
    shelf = get_shelf(sid)
    return ok(ser_shelf(shelf), 200)


# ===========================================================================
# Resident
# ===========================================================================
@app.route("/parcelroom/residents", methods=["POST"])
def create_resident():
    _, role = authenticate()
    require_role(role, {"PropertyManager", "PmsIntegration"})
    body = get_json_body()
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    require_fields(body, ["property_id", "unit_number", "full_name", "email"])
    check_str(body["unit_number"], "unit_number")
    check_str(body["full_name"], "full_name")
    check_str(body["email"], "email")
    notify_channel = body.get("notify_channel")
    if notify_channel is not None:
        check_enum(notify_channel, NOTIFY_CHANNELS, "notify_channel")
    else:
        notify_channel = "EMAIL"
    disc = body.get("loyalty_discount_pct")
    if disc is not None:
        if isinstance(disc, bool) or not isinstance(disc, (int, float)) or not (0 <= disc < 1):
            raise ApiError(ERR_VALIDATION, 400, "loyalty_discount_pct must be in [0, 1)")
    else:
        disc = 0.0
    phone = body.get("phone")
    if phone is not None and not isinstance(phone, str):
        raise ApiError(ERR_VALIDATION, 400, "phone must be a string")
    resident = new_entity({
        "property_id": body["property_id"],
        "unit_number": body["unit_number"],
        "full_name": body["full_name"],
        "email": body["email"],
        "phone": phone,
        "notify_channel": notify_channel,
        "loyalty_discount_pct": disc,
        "status": "ACTIVE",
    })
    db.residents[resident["id"]] = resident
    return ok(ser_resident(resident), 201)


@app.route("/parcelroom/residents/<rid>", methods=["GET"])
def get_resident_route(rid):
    _, role = authenticate()
    require_role(role, ROLES)
    resident = get_resident(rid)
    return ok(ser_resident(resident), 200)


def _cascade_awaiting_to_held(resident):
    for pkg in packages_of_property(resident["property_id"]):
        if pkg["resident_id"] == resident["id"] and pkg["status"] == "AWAITING_PICKUP":
            pkg["status"] = "HELD"
            touch(pkg)
            create_notification(pkg, "MOVE_OUT_HOLD", resident["notify_channel"], None)


def _cascade_held_to_awaiting(resident):
    for pkg in packages_of_property(resident["property_id"]):
        if pkg["resident_id"] == resident["id"] and pkg["status"] == "HELD":
            pkg["status"] = "AWAITING_PICKUP"
            touch(pkg)


def _waive_outstanding_charges(resident):
    pkg_ids = {p["id"] for p in packages_of_property(resident["property_id"]) if p["resident_id"] == resident["id"]}
    for c in db.storage_charges.values():
        if c["package_id"] in pkg_ids and c["charge_type"] == "HOLDING_FEE" and c["status"] == "OUTSTANDING":
            c["status"] = "WAIVED"
            c["settled_at"] = db.fmt(db.now())
            touch(c)


@app.route("/parcelroom/residents/<rid>/pms-sync", methods=["POST"])
def resident_pms_sync(rid):
    _, role = authenticate()
    require_role(role, {"PmsIntegration"})
    resident = get_resident(rid)
    body = get_json_body()
    event_type = body.get("event_type")
    if event_type is None:
        raise ApiError(ERR_VALIDATION, 400, "event_type is required")
    if event_type not in ("PLACE_HOLD", "RELEASE_HOLD", "MOVE_OUT"):
        raise ApiError(ERR_VALIDATION, 400, f"Invalid event_type: {event_type}")

    if event_type == "PLACE_HOLD":
        if resident["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "Resident is not ACTIVE")
        resident["status"] = "HOLD"
        touch(resident)
        _cascade_awaiting_to_held(resident)
    elif event_type == "RELEASE_HOLD":
        if resident["status"] != "HOLD":
            raise ApiError(ERR_INVALID_STATE, 409, "Resident is not on HOLD")
        resident["status"] = "ACTIVE"
        touch(resident)
        _cascade_held_to_awaiting(resident)
    else:  # MOVE_OUT
        if resident["status"] not in ("ACTIVE", "HOLD"):
            raise ApiError(ERR_INVALID_STATE, 409, "Resident already moved out")
        was_active = resident["status"] == "ACTIVE"
        resident["status"] = "MOVED_OUT"
        touch(resident)
        if was_active:
            _cascade_awaiting_to_held(resident)
        _waive_outstanding_charges(resident)
    return ok(ser_resident(resident), 200)


# ===========================================================================
# Carrier
# ===========================================================================
@app.route("/parcelroom/carriers", methods=["POST"])
def create_carrier():
    _, role = authenticate()
    require_role(role, {"PropertyManager"})
    body = get_json_body()
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    require_fields(body, ["property_id", "name", "scac"])
    check_str(body["name"], "name")
    check_str(body["scac"], "scac")
    allows = body.get("allows_smart_locker_delivery")
    if allows is None:
        allows = True
    elif not isinstance(allows, bool):
        raise ApiError(ERR_VALIDATION, 400, "allows_smart_locker_delivery must be a boolean")
    carrier = new_entity({
        "property_id": body["property_id"],
        "name": body["name"],
        "scac": body["scac"],
        "allows_smart_locker_delivery": allows,
    })
    db.carriers[carrier["id"]] = carrier
    return ok(ser_carrier(carrier), 201)


@app.route("/parcelroom/carriers/<cid>", methods=["GET"])
def get_carrier_route(cid):
    _, role = authenticate()
    require_role(role, ROLES)
    carrier = get_carrier(cid)
    return ok(ser_carrier(carrier), 200)


# ===========================================================================
# Package
# ===========================================================================
@app.route("/parcelroom/packages", methods=["POST"])
def create_package():
    uid, role = authenticate()
    require_role(role, {"Carrier", "ConciergeStaff"})
    body = get_json_body()
    # Entity-backed ownership (priority 2): a Carrier must log against its own id.
    if role == "Carrier" and body.get("carrier_id") is not None and body["carrier_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Carrier may only log its own packages")
    # Existence (priority 3): body FKs left-to-right.
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    if body.get("resident_id") is not None:
        get_resident(body["resident_id"])
    if body.get("carrier_id") is not None:
        get_carrier(body["carrier_id"])
    # Duplicate tracking (priority 12): per property across non-terminal packages.
    if body.get("property_id") is not None and body.get("tracking_number") is not None:
        for p in db.packages.values():
            if (p["property_id"] == body["property_id"] and p["tracking_number"] == body["tracking_number"]
                    and p["status"] not in PACKAGE_TERMINAL):
                raise ApiError(ERR_DUPLICATE_TRACKING, 409, "tracking_number already in use")
    # Body validation (priority 14).
    require_fields(body, ["property_id", "resident_id", "carrier_id", "tracking_number", "size_class", "storage_type"])
    check_str(body["tracking_number"], "tracking_number")
    check_enum(body["size_class"], SIZE_CLASSES, "size_class")
    check_enum(body["storage_type"], PACKAGE_STORAGE_TYPES, "storage_type")

    prop = db.properties[body["property_id"]]
    intake = db.now()
    storage_type = body["storage_type"]
    aging_days = prop["aging_days_perishable"] if storage_type in ("COLD", "PERISHABLE") else prop["aging_days_standard"]
    aging_deadline = db.add_days(intake, aging_days)
    cold_deadline = db.add_hours(intake, prop["perishable_hold_hours"]) if storage_type == "PERISHABLE" else None
    pkg = new_entity({
        "property_id": body["property_id"],
        "resident_id": body["resident_id"],
        "carrier_id": body["carrier_id"],
        "locker_id": None,
        "shelf_id": None,
        "tracking_number": body["tracking_number"],
        "size_class": body["size_class"],
        "storage_type": storage_type,
        "is_oversize": body["size_class"] == "OVERSIZE",
        "storage_mode": "NONE",
        "pickup_code": None,
        "status": "LOGGED",
        "intake_at": db.fmt(intake),
        "notified_at": None,
        "picked_up_at": None,
        "cold_chain_deadline_at": db.fmt(cold_deadline),
        "aging_deadline_at": db.fmt(aging_deadline),
        "final_fee_cents": None,
        "notify_count": 0,
        "return_initiated_by_user_id": None,
    })
    db.packages[pkg["id"]] = pkg
    return ok(ser_package(pkg), 201)


@app.route("/parcelroom/packages/<pid>", methods=["GET"])
def get_package_route(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    pkg = get_package(pid)
    return ok(ser_package(pkg), 200)


@app.route("/parcelroom/packages", methods=["GET"])
def list_packages():
    _, role = authenticate()
    require_role(role, ROLES)
    args = request.args
    items = list(db.packages.values())
    for key in ("property_id", "resident_id", "carrier_id", "locker_id", "shelf_id", "status"):
        val = args.get(key)
        if val is not None and val != "":
            items = [p for p in items if p.get(key) == val]
    page, meta = make_list(items, ser_package)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/packages/<pid>/notify", methods=["POST"])
def notify_package(pid):
    _, role = authenticate()
    require_role(role, {"ConciergeStaff"})
    pkg = get_package(pid)
    body = get_json_body()
    # State (priority 4): only LOGGED (initial) or AWAITING_PICKUP (reminder).
    if pkg["status"] not in ("LOGGED", "AWAITING_PICKUP"):
        raise ApiError(ERR_INVALID_STATE, 409, "Package cannot be notified in its current state")
    resident = get_resident(pkg["resident_id"])
    # Resident active (priority 6).
    if resident["status"] != "ACTIVE":
        raise ApiError(ERR_RESIDENT_NOT_ACTIVE, 409, "Recipient resident is not ACTIVE")

    if pkg["status"] == "AWAITING_PICKUP":
        # Reminder self-transition: reuse code, no storage change.
        pkg["notify_count"] += 1
        pkg["notified_at"] = db.fmt(db.now())
        touch(pkg)
        create_notification(pkg, "REMINDER", resident["notify_channel"], pkg["pickup_code"])
        return ok(ser_package(pkg), 200)

    # Initial notify: resolve + assign storage (priorities 8, 9).
    mode, target = resolve_storage(pkg, db.properties[pkg["property_id"]], body)
    prop = db.properties[pkg["property_id"]]
    if mode == "LOCKER":
        target["status"] = "OCCUPIED"
        target["current_package_id"] = pkg["id"]
        touch(target)
        pkg["locker_id"] = target["id"]
        pkg["storage_mode"] = "LOCKER"
    else:
        pkg["shelf_id"] = target["id"]
        pkg["storage_mode"] = "SHELF"
    pkg["pickup_code"] = mint_pickup_code()
    pkg["notified_at"] = db.fmt(db.now())
    pkg["notify_count"] += 1
    pkg["status"] = "AWAITING_PICKUP"
    touch(pkg)
    create_notification(pkg, "INITIAL", resident["notify_channel"], pkg["pickup_code"])
    occupancy_event(prop)
    return ok(ser_package(pkg), 200)


@app.route("/parcelroom/packages/<pid>/pickup", methods=["POST"])
def pickup_package(pid):
    uid, role = authenticate()
    require_role(role, {"Resident", "ConciergeStaff"})
    pkg = get_package(pid)
    if role == "Resident" and pkg["resident_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Resident may only pick up their own package")
    if pkg["status"] != "AWAITING_PICKUP":
        raise ApiError(ERR_INVALID_STATE, 409, "Package is not awaiting pickup")
    # Cold-chain (priority 7): strictly after deadline forfeits.
    if pkg["storage_type"] == "PERISHABLE" and pkg["cold_chain_deadline_at"] is not None:
        if db.now() > db.parse_iso(pkg["cold_chain_deadline_at"]):
            raise ApiError(ERR_COLD_CHAIN_EXPIRED, 409, "Cold-chain window expired")
    body = get_json_body()
    supplied = body.get("pickup_code")
    if supplied is None or supplied != pkg["pickup_code"]:
        raise ApiError(ERR_INVALID_PICKUP_CODE, 403, "Invalid pickup code")

    prop = db.properties[pkg["property_id"]]
    resident = db.residents[pkg["resident_id"]]
    end = db.now()
    gross, cdays, per_day, ov = fee_components(pkg, prop, end)
    pkg["final_fee_cents"] = gross
    pkg["picked_up_at"] = db.fmt(end)
    create_holding_charge(pkg, prop, resident, gross, (gross, cdays, per_day, ov), "COLLECTED")
    release_storage(pkg)
    pkg["status"] = "PICKED_UP"
    touch(pkg)
    occupancy_event(prop)
    return ok(ser_package(pkg), 200)


def _do_return_initiate(pkg, prop, actor_id):
    resident = db.residents.get(pkg["resident_id"])
    end = db.now()
    gross, cdays, per_day, ov = fee_components(pkg, prop, end)
    pkg["final_fee_cents"] = gross
    create_holding_charge(pkg, prop, resident, gross, (gross, cdays, per_day, ov), "OUTSTANDING")
    release_storage(pkg)
    pkg["return_initiated_by_user_id"] = actor_id
    pkg["status"] = "RETURN_INITIATED"
    touch(pkg)
    create_notification(pkg, "RETURN_NOTICE", resident["notify_channel"] if resident else "EMAIL", None)
    occupancy_event(prop)


@app.route("/parcelroom/packages/<pid>/return-initiate", methods=["POST"])
def return_initiate(pid):
    uid, role = authenticate()
    require_role(role, {"ConciergeStaff", "PropertyManager"})
    pkg = get_package(pid)
    if pkg["status"] != "AWAITING_PICKUP":
        raise ApiError(ERR_INVALID_STATE, 409, "Package is not awaiting pickup")
    prop = db.properties[pkg["property_id"]]
    _do_return_initiate(pkg, prop, uid)
    return ok(ser_package(pkg), 200)


@app.route("/parcelroom/packages/<pid>/return-complete", methods=["POST"])
def return_complete(pid):
    uid, role = authenticate()
    require_role(role, {"ConciergeStaff", "Carrier"})
    pkg = get_package(pid)
    if pkg["status"] != "RETURN_INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Package is not awaiting return completion")
    # Dual-control SoD (priority 5).
    if uid == pkg["return_initiated_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Return completion must be performed by a different user")
    pkg["status"] = "RETURNED"
    touch(pkg)
    return ok(ser_package(pkg), 200)


@app.route("/parcelroom/packages/<pid>/notifications", methods=["GET"])
def list_package_notifications(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_package(pid)
    items = [n for n in db.notifications.values() if n["package_id"] == pid]
    page, meta = make_list(items, ser_notification)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/packages/<pid>/charges", methods=["GET"])
def list_package_charges(pid):
    _, role = authenticate()
    require_role(role, ROLES)
    get_package(pid)
    items = [c for c in db.storage_charges.values() if c["package_id"] == pid]
    page, meta = make_list(items, ser_charge)
    return ok(page, 200, "array", meta)


# ===========================================================================
# Aging sweep
# ===========================================================================
@app.route("/parcelroom/properties/<pid>/aging-sweep", methods=["POST"])
def aging_sweep(pid):
    _, role = authenticate()
    require_role(role, {"PropertyManager", "ConciergeStaff"})
    prop = get_property(pid)
    now = db.now()
    candidates = [
        p for p in packages_of_property(pid)
        if p["status"] == "AWAITING_PICKUP" and now >= db.parse_iso(p["aging_deadline_at"])
    ]
    candidates.sort(key=lambda p: (db.parse_iso(p["intake_at"]), p["_seq"]))
    # Perishable packages strictly past cold-chain deadline are DISPOSED first.
    for p in candidates:
        if (p["storage_type"] == "PERISHABLE" and p["cold_chain_deadline_at"] is not None
                and now > db.parse_iso(p["cold_chain_deadline_at"])):
            release_storage(p)
            p["status"] = "DISPOSED"
            touch(p)
            resident = db.residents.get(p["resident_id"])
            create_notification(p, "DISPOSED_NOTICE", resident["notify_channel"] if resident else "EMAIL", None)
            occupancy_event(prop)
    # Remaining candidates are evicted to return by the SYSTEM actor.
    for p in candidates:
        if p["status"] == "AWAITING_PICKUP":
            _do_return_initiate(p, prop, "SYSTEM")
    return ok(ser_property(prop), 200)


# ===========================================================================
# RetailReturn
# ===========================================================================
@app.route("/parcelroom/retail-returns", methods=["POST"])
def create_retail_return():
    uid, role = authenticate()
    require_role(role, {"Resident"})
    body = get_json_body()
    # Entity-backed ownership (priority 2): resident drops off under their own id.
    if body.get("resident_id") is not None and body["resident_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Resident may only drop off their own returns")
    # Existence (priority 3).
    if body.get("property_id") is not None:
        get_property(body["property_id"])
    if body.get("resident_id") is not None:
        get_resident(body["resident_id"])
    if body.get("carrier_id") is not None:
        get_carrier(body["carrier_id"])
    # Staging capacity (priority 11).
    if body.get("property_id") is not None:
        prop = db.properties[body["property_id"]]
        if return_staging_count(prop["id"]) >= prop["return_staging_capacity"]:
            raise ApiError(ERR_STAGING_FULL, 409, "Return staging is full")
    # Body validation (priority 14).
    require_fields(body, ["property_id", "resident_id", "carrier_id", "tracking_number"])
    check_str(body["tracking_number"], "tracking_number")

    rr = new_entity({
        "property_id": body["property_id"],
        "resident_id": body["resident_id"],
        "carrier_id": body["carrier_id"],
        "tracking_number": body["tracking_number"],
        "status": "DROPPED_OFF",
        "dropped_off_at": db.fmt(db.now()),
        "reject_reason": None,
    })
    db.retail_returns[rr["id"]] = rr
    return ok(ser_retail_return(rr), 201)


@app.route("/parcelroom/retail-returns/<rid>", methods=["GET"])
def get_retail_return_route(rid):
    _, role = authenticate()
    require_role(role, ROLES)
    rr = get_retail_return(rid)
    return ok(ser_retail_return(rr), 200)


@app.route("/parcelroom/retail-returns", methods=["GET"])
def list_retail_returns():
    _, role = authenticate()
    require_role(role, ROLES)
    args = request.args
    items = list(db.retail_returns.values())
    for key in ("property_id", "resident_id", "carrier_id", "status"):
        val = args.get(key)
        if val is not None and val != "":
            items = [r for r in items if r.get(key) == val]
    page, meta = make_list(items, ser_retail_return)
    return ok(page, 200, "array", meta)


@app.route("/parcelroom/retail-returns/<rid>/verify-label", methods=["POST"])
def verify_label(rid):
    _, role = authenticate()
    require_role(role, {"ConciergeStaff"})
    rr = get_retail_return(rid)
    if rr["status"] != "DROPPED_OFF":
        raise ApiError(ERR_INVALID_STATE, 409, "Return is not in DROPPED_OFF state")
    rr["status"] = "AWAITING_CARRIER"
    touch(rr)
    return ok(ser_retail_return(rr), 200)


@app.route("/parcelroom/retail-returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    _, role = authenticate()
    require_role(role, {"ConciergeStaff"})
    rr = get_retail_return(rid)
    if rr["status"] != "DROPPED_OFF":
        raise ApiError(ERR_INVALID_STATE, 409, "Return is not in DROPPED_OFF state")
    body = get_json_body()
    reason = body.get("reject_reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError(ERR_VALIDATION, 400, "reject_reason must be a string")
    rr["status"] = "REJECTED"
    rr["reject_reason"] = reason
    touch(rr)
    return ok(ser_retail_return(rr), 200)


@app.route("/parcelroom/retail-returns/<rid>/carrier-pickup", methods=["POST"])
def carrier_pickup(rid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    rr = get_retail_return(rid)
    # Entity-backed ownership (priority 2, resolved after existence).
    if uid != rr["carrier_id"]:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Carrier may only collect its own returns")
    if rr["status"] != "AWAITING_CARRIER":
        raise ApiError(ERR_INVALID_STATE, 409, "Return is not awaiting carrier pickup")
    rr["status"] = "PICKED_UP"
    touch(rr)
    return ok(ser_retail_return(rr), 200)


# ===========================================================================
# Entrypoint
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
