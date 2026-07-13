import os
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"}

CURE_DAYS = 14
LATE_FEE_CENTS = 5000
LIEN_ADMIN_FEE_CENTS = 10000
BUYER_PREMIUM_BPS = 1500
DEPOSIT_REQUIRED_CENTS = 20000
PAYMENT_WINDOW_HOURS = 48
CLEANOUT_DAYS = 3
ONSITE_BUFFER = timedelta(minutes=120)

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
facilities = {}
tenants = {}
units = {}
lien_notices = {}
auctions = {}
buyers = {}
bids = {}
sales = {}
settlements = {}
disputes = {}

_seq_counter = 0
_clock = {"now": DEFAULT_CLOCK}


def now():
    return _clock["now"]


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def gen_req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def rhu_div(numerator, denominator):
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps(amount, rate_bps):
    return rhu_div(amount * rate_bps, 10000)


# ---------------------------------------------------------------------------
# Errors + envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt(now())}


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."}}
    return jsonify(body), 404


def success(data, code=200, rtype="object", pag=None):
    meta = _meta()
    if pag:
        meta.update(pag)
    return jsonify({"meta": meta, "response_type": rtype, "data": data}), code


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown role.")
    uid = request.headers.get("X-User-ID")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation.")
    return role, uid


def get_body():
    return request.get_json(force=True, silent=True) or {}


def need(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def need_int(body, fields):
    for f in fields:
        v = body[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ApiError("ERR_VALIDATION", 422, f"Field must be a non-negative integer: {f}")


def need_enum(body, field, allowed):
    if body.get(field) not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Invalid enum for {field}")


def fetch(store, key, kind="Resource"):
    obj = store.get(key)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{kind} not found.")
    return obj


def forbid_if(condition):
    if condition:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the owner of this resource.")


def parse_pagination():
    def parse_param(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID", 422, f"Invalid {name}")

    limit = parse_param("limit", 10)
    offset = parse_param("offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_PAGINATION_INVALID", 422, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 422, "offset out of range")
    return limit, offset


def list_response(items):
    """items: full matching set (already sorted). Applies pagination + envelope."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    data = [serialize(o) for o in page]
    return success(data, 200, rtype="array", pag=pag)


def sorted_by_creation(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt(v)
        else:
            out[k] = v
    if obj.get("_type") == "Auction":
        out["min_next_bid_cents"] = auction_min_next(obj)
    return out


def base_fields(kind):
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq(), "_type": kind}


def touch(obj):
    obj["updated_at"] = now()
    obj["version"] += 1


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def auction_min_next(a):
    if a["high_bid_cents"] == 0:
        return a["reserve_cents"]
    return a["high_bid_cents"] + a["min_increment_cents"]


def daily_rent(unit):
    return rhu_div(unit["monthly_rent_cents"], 30)


def compute_lien(unit, days_accrued):
    accrued_rent = daily_rent(unit) * days_accrued
    return unit["past_due_balance_cents"] + accrued_rent + LATE_FEE_CENTS + LIEN_ADMIN_FEE_CENTS


def active_bids_for(auction_id):
    return [b for b in bids.values() if b["auction_id"] == auction_id and b["status"] == "ACTIVE"]


def select_high_bid(auction_id):
    candidates = active_bids_for(auction_id)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (-b["amount_cents"], b["placed_at"], b["_seq"]))
    return candidates[0]


def recompute_high_bid(auction):
    high = select_high_bid(auction["id"])
    if high is None:
        auction["high_bid_cents"] = 0
        auction["high_bid_id"] = None
    else:
        auction["high_bid_cents"] = high["amount_cents"]
        auction["high_bid_id"] = high["id"]


def waterfall(gross, lien_input, facility):
    lien_recovered = min(gross, lien_input)
    facility_fee = min(bps(gross, facility["facility_fee_bps"]), gross - lien_recovered)
    surplus = gross - lien_recovered - facility_fee
    return lien_recovered, facility_fee, surplus


def unit_for_auction(auction):
    return units[auction["unit_id"]]


def facility_for_auction(auction):
    return facilities[unit_for_auction(auction)["facility_id"]]


# =========================================================================
# FACILITIES
# =========================================================================
@app.post("/facilities")
def create_facility():
    auth(["PlatformAdmin"])
    b = get_body()
    need(b, ["name", "state_code", "sales_tax_rate_bps", "facility_fee_bps"])
    need_int(b, ["sales_tax_rate_bps", "facility_fee_bps"])
    obj = base_fields("Facility")
    obj.update({
        "name": b["name"],
        "state_code": b["state_code"],
        "sales_tax_rate_bps": b["sales_tax_rate_bps"],
        "facility_fee_bps": b["facility_fee_bps"],
        "recovery_balance_cents": 0,
    })
    facilities[obj["id"]] = obj
    return success(serialize(obj), 201)


@app.get("/facilities/<facility_id>")
def get_facility(facility_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    obj = fetch(facilities, facility_id, "Facility")
    return success(serialize(obj), 200)


@app.get("/facilities/<facility_id>/tenants")
def list_facility_tenants(facility_id):
    auth(["PlatformAdmin", "FacilityOperator"])
    fetch(facilities, facility_id, "Facility")
    items = sorted_by_creation([t for t in tenants.values() if t["facility_id"] == facility_id])
    return list_response(items)


# =========================================================================
# TENANTS
# =========================================================================
@app.post("/tenants")
def create_tenant():
    auth(["PlatformAdmin"])
    b = get_body()
    need(b, ["facility_id", "full_name", "email"])
    fetch(facilities, b["facility_id"], "Facility")
    obj = base_fields("Tenant")
    obj.update({
        "facility_id": b["facility_id"],
        "full_name": b["full_name"],
        "email": b["email"],
        "access_status": "ACTIVE",
        "surplus_balance_cents": 0,
    })
    tenants[obj["id"]] = obj
    return success(serialize(obj), 201)


@app.get("/tenants/<tenant_id>")
def get_tenant(tenant_id):
    auth(["PlatformAdmin", "FacilityOperator", "Tenant"])
    obj = fetch(tenants, tenant_id, "Tenant")
    return success(serialize(obj), 200)


# =========================================================================
# STORAGE UNITS
# =========================================================================
@app.post("/units")
def create_unit():
    auth(["PlatformAdmin"])
    b = get_body()
    need(b, ["facility_id", "tenant_id", "unit_number", "monthly_rent_cents"])
    need_int(b, ["monthly_rent_cents"])
    fetch(facilities, b["facility_id"], "Facility")
    fetch(tenants, b["tenant_id"], "Tenant")
    obj = base_fields("StorageUnit")
    obj.update({
        "facility_id": b["facility_id"],
        "tenant_id": b["tenant_id"],
        "unit_number": b["unit_number"],
        "monthly_rent_cents": b["monthly_rent_cents"],
        "past_due_balance_cents": 0,
        "status": "RENTED",
        "lien_amount_provisional_cents": 0,
        "lien_amount_final_cents": 0,
    })
    units[obj["id"]] = obj
    return success(serialize(obj), 201)


@app.get("/units/<unit_id>")
def get_unit(unit_id):
    auth(["PlatformAdmin", "FacilityOperator", "Tenant"])
    obj = fetch(units, unit_id, "StorageUnit")
    return success(serialize(obj), 200)


@app.get("/units")
def list_units():
    auth(["PlatformAdmin", "FacilityOperator", "Tenant"])
    facility_id = request.args.get("facility_id")
    tenant_id = request.args.get("tenant_id")
    status = request.args.get("status")
    items = list(units.values())
    if facility_id is not None:
        items = [u for u in items if u["facility_id"] == facility_id]
    if tenant_id is not None:
        items = [u for u in items if u["tenant_id"] == tenant_id]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return list_response(sorted_by_creation(items))


@app.post("/units/<unit_id>/lien-notices")
def create_lien_notice(unit_id):
    role, uid = auth(["FacilityOperator"])
    unit = fetch(units, unit_id, "StorageUnit")
    forbid_if(unit["facility_id"] != uid)
    b = get_body()
    need(b, ["past_due_balance_cents"])
    need_int(b, ["past_due_balance_cents"])
    if b["past_due_balance_cents"] <= 0:
        raise ApiError("ERR_VALIDATION", 422, "past_due_balance_cents must be > 0")
    if unit["status"] != "RENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Unit is not RENTED")

    ts = now()
    unit["past_due_balance_cents"] = b["past_due_balance_cents"]
    notice = base_fields("LienNotice")
    notice.update({
        "unit_id": unit_id,
        "notice_sent_at": ts,
        "cure_deadline": ts + timedelta(days=CURE_DAYS),
        "lien_amount_cents": 0,
        "status": "SENT",
    })
    provisional = compute_lien(unit, CURE_DAYS)
    unit["lien_amount_provisional_cents"] = provisional
    notice["lien_amount_cents"] = provisional
    lien_notices[notice["id"]] = notice

    unit["status"] = "LIEN_NOTICED"
    touch(unit)
    return success(serialize(notice), 201)


@app.post("/units/<unit_id>/cure")
def cure_unit(unit_id):
    role, uid = auth(["Tenant"])
    unit = fetch(units, unit_id, "StorageUnit")
    forbid_if(unit["tenant_id"] != uid)
    if unit["status"] != "LIEN_NOTICED":
        raise ApiError("ERR_INVALID_STATE", 409, "Unit is not LIEN_NOTICED")
    notice = _sent_notice_for_unit(unit_id)
    if notice is None or now() > notice["cure_deadline"]:
        raise ApiError("ERR_CURE_WINDOW_CLOSED", 409, "Cure window has closed")
    notice["status"] = "CURED"
    touch(notice)
    unit["past_due_balance_cents"] = 0
    unit["status"] = "RENTED"
    touch(unit)
    return success(serialize(unit), 200)


def _sent_notice_for_unit(unit_id):
    candidates = [n for n in lien_notices.values() if n["unit_id"] == unit_id and n["status"] == "SENT"]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (n["created_at"], n["_seq"]))
    return candidates[-1]


# =========================================================================
# LIEN NOTICES
# =========================================================================
@app.get("/lien-notices/<lien_notice_id>")
def get_lien_notice(lien_notice_id):
    auth(["PlatformAdmin", "FacilityOperator", "Tenant"])
    obj = fetch(lien_notices, lien_notice_id, "LienNotice")
    return success(serialize(obj), 200)


@app.get("/units/<unit_id>/lien-notices")
def list_unit_lien_notices(unit_id):
    auth(["PlatformAdmin", "FacilityOperator", "Tenant"])
    fetch(units, unit_id, "StorageUnit")
    items = sorted_by_creation([n for n in lien_notices.values() if n["unit_id"] == unit_id])
    return list_response(items)


@app.post("/lien-notices/<lien_notice_id>/mature")
def mature_lien_notice(lien_notice_id):
    role, uid = auth(["FacilityOperator"])
    notice = fetch(lien_notices, lien_notice_id, "LienNotice")
    unit = units[notice["unit_id"]]
    forbid_if(unit["facility_id"] != uid)
    if notice["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "LienNotice is not SENT")
    if now() <= notice["cure_deadline"]:
        raise ApiError("ERR_MATURE_TOO_EARLY", 409, "Cure window still open")

    elapsed_days = int((now() - notice["notice_sent_at"]).total_seconds() // 86400)
    final = compute_lien(unit, elapsed_days)
    unit["lien_amount_final_cents"] = final
    notice["lien_amount_cents"] = final
    notice["status"] = "MATURED"
    touch(notice)

    unit["status"] = "LIEN_MATURED"
    touch(unit)

    tenant = tenants.get(unit["tenant_id"])
    if tenant is not None:
        tenant["access_status"] = "REVOKED"
        touch(tenant)
    return success(serialize(notice), 200)


# =========================================================================
# AUCTIONS
# =========================================================================
@app.post("/auctions")
def create_auction():
    role, uid = auth(["FacilityOperator"])
    b = get_body()
    need(b, ["unit_id", "mode", "start_at", "end_at", "reserve_cents", "min_increment_cents"])
    need_enum(b, "mode", {"ONLINE", "ONSITE"})
    need_int(b, ["reserve_cents", "min_increment_cents"])
    try:
        start_at = parse_iso(b["start_at"])
        end_at = parse_iso(b["end_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "Invalid datetime")

    unit = fetch(units, b["unit_id"], "StorageUnit")
    forbid_if(unit["facility_id"] != uid)

    if unit["status"] != "LIEN_MATURED":
        raise ApiError("ERR_UNIT_NOT_MATURED", 409, "Unit is not LIEN_MATURED")
    if not (end_at > start_at and start_at >= now()):
        raise ApiError("ERR_INVALID_AUCTION_WINDOW", 422, "Invalid auction window")

    # per-unit overlap (half-open windows)
    for a in auctions.values():
        if a["unit_id"] == b["unit_id"] and a["status"] in ("SCHEDULED", "LIVE"):
            if start_at < a["end_at"] and a["start_at"] < end_at:
                raise ApiError("ERR_AUCTION_WINDOW_CONFLICT", 409, "Overlapping auction window on unit")

    # onsite facility spacing
    if b["mode"] == "ONSITE":
        for a in auctions.values():
            if a["mode"] != "ONSITE" or a["status"] not in ("SCHEDULED", "LIVE"):
                continue
            other_unit = units.get(a["unit_id"])
            if other_unit is None or other_unit["facility_id"] != unit["facility_id"]:
                continue
            if _onsite_conflict(start_at, end_at, a["start_at"], a["end_at"]):
                raise ApiError("ERR_ONSITE_SLOT_CONFLICT", 409, "Onsite auctions too close")

    obj = base_fields("Auction")
    obj.update({
        "unit_id": b["unit_id"],
        "mode": b["mode"],
        "start_at": start_at,
        "end_at": end_at,
        "reserve_cents": b["reserve_cents"],
        "min_increment_cents": b["min_increment_cents"],
        "high_bid_cents": 0,
        "high_bid_id": None,
        "status": "SCHEDULED",
    })
    auctions[obj["id"]] = obj
    return success(serialize(obj), 201)


def _onsite_conflict(s1, e1, s2, e2):
    if s1 >= e2:
        gap = s1 - e2
    elif s2 >= e1:
        gap = s2 - e1
    else:
        return True  # overlap
    return gap < ONSITE_BUFFER


@app.get("/auctions/<auction_id>")
def get_auction(auction_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    obj = fetch(auctions, auction_id, "Auction")
    return success(serialize(obj), 200)


@app.get("/units/<unit_id>/auctions")
def list_unit_auctions(unit_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    fetch(units, unit_id, "StorageUnit")
    items = sorted_by_creation([a for a in auctions.values() if a["unit_id"] == unit_id])
    return list_response(items)


@app.post("/auctions/<auction_id>/open")
def open_auction(auction_id):
    role, uid = auth(["FacilityOperator"])
    auction = fetch(auctions, auction_id, "Auction")
    unit = units[auction["unit_id"]]
    forbid_if(unit["facility_id"] != uid)
    if auction["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Auction is not SCHEDULED")
    if unit["status"] != "LIEN_MATURED":
        raise ApiError("ERR_INVALID_STATE", 409, "Unit is not LIEN_MATURED")
    if now() < auction["start_at"]:
        raise ApiError("ERR_OPEN_TOO_EARLY", 409, "Cannot open before start_at")

    auction["status"] = "LIVE"
    touch(auction)
    unit["status"] = "IN_AUCTION"
    touch(unit)
    return success(serialize(auction), 200)


@app.post("/auctions/<auction_id>/close")
def close_auction(auction_id):
    role, uid = auth(["FacilityOperator"])
    auction = fetch(auctions, auction_id, "Auction")
    unit = units[auction["unit_id"]]
    forbid_if(unit["facility_id"] != uid)
    if auction["status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Auction is not LIVE")
    if now() < auction["end_at"]:
        raise ApiError("ERR_AUCTION_NOT_ENDED", 409, "Auction window not ended")

    high = select_high_bid(auction_id)
    winning = high is not None and high["amount_cents"] >= auction["reserve_cents"]

    if winning:
        for b in active_bids_for(auction_id):
            if b["id"] == high["id"]:
                b["status"] = "WINNING"
            else:
                b["status"] = "LOST"
            touch(b)
        auction["high_bid_cents"] = high["amount_cents"]
        auction["high_bid_id"] = high["id"]
        _create_sale(auction, unit, high)
        unit["status"] = "SOLD"
        touch(unit)
    else:
        for b in active_bids_for(auction_id):
            b["status"] = "LOST"
            touch(b)
        recompute_high_bid(auction)
        unit["status"] = "LIEN_MATURED"
        touch(unit)

    auction["status"] = "CLOSED"
    touch(auction)
    return success(serialize(auction), 200)


def _create_sale(auction, unit, winning_bid):
    facility = facilities[unit["facility_id"]]
    winning_amount = auction["high_bid_cents"]
    buyer_premium = bps(winning_amount, BUYER_PREMIUM_BPS)
    sales_tax = bps(winning_amount + buyer_premium, facility["sales_tax_rate_bps"])
    total_due = winning_amount + buyer_premium + sales_tax
    _, _, est_surplus = waterfall(winning_amount, unit["lien_amount_provisional_cents"], facility)

    ts = now()
    sale = base_fields("Sale")
    sale.update({
        "auction_id": auction["id"],
        "buyer_id": winning_bid["buyer_id"],
        "winning_amount_cents": winning_amount,
        "buyer_premium_cents": buyer_premium,
        "sales_tax_cents": sales_tax,
        "total_due_cents": total_due,
        "estimated_surplus_cents": est_surplus,
        "payment_deadline": ts + timedelta(hours=PAYMENT_WINDOW_HOURS),
        "cleanout_deadline": ts + timedelta(days=CLEANOUT_DAYS),
        "payment_status": "UNPAID",
        "cleanout_status": "PENDING",
    })
    sales[sale["id"]] = sale

    buyer = buyers[winning_bid["buyer_id"]]
    buyer["deposit_available_cents"] -= DEPOSIT_REQUIRED_CENTS
    buyer["deposit_held_cents"] += DEPOSIT_REQUIRED_CENTS
    touch(buyer)
    return sale


@app.post("/auctions/<auction_id>/bids")
def place_bid(auction_id):
    role, uid = auth(["Buyer"])
    auction = fetch(auctions, auction_id, "Auction")
    b = get_body()
    need(b, ["buyer_id"])
    forbid_if(b["buyer_id"] != uid)
    buyer = fetch(buyers, b["buyer_id"], "Buyer")
    need(b, ["amount_cents", "expected_auction_version"])
    need_int(b, ["amount_cents", "expected_auction_version"])

    if auction["status"] != "LIVE":
        raise ApiError("ERR_AUCTION_NOT_LIVE", 409, "Auction is not LIVE")
    if b["expected_auction_version"] != auction["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale auction version")
    if auction["high_bid_id"] is not None and bids[auction["high_bid_id"]]["buyer_id"] == b["buyer_id"]:
        raise ApiError("ERR_ALREADY_HIGH_BIDDER", 409, "Already holding the high bid")
    if buyer["deposit_available_cents"] < DEPOSIT_REQUIRED_CENTS:
        raise ApiError("ERR_INSUFFICIENT_DEPOSIT", 402, "Insufficient deposit")
    if b["amount_cents"] < auction_min_next(auction):
        raise ApiError("ERR_BID_TOO_LOW", 409, "Bid below minimum next bid")

    prev_high_id = auction["high_bid_id"]
    bid = base_fields("Bid")
    bid.update({
        "auction_id": auction_id,
        "buyer_id": b["buyer_id"],
        "amount_cents": b["amount_cents"],
        "placed_at": now(),
        "status": "ACTIVE",
    })
    bids[bid["id"]] = bid

    if prev_high_id is not None:
        prev = bids[prev_high_id]
        prev["status"] = "OUTBID"
        touch(prev)

    auction["high_bid_cents"] = bid["amount_cents"]
    auction["high_bid_id"] = bid["id"]
    touch(auction)
    return success(serialize(bid), 201)


# =========================================================================
# BIDS
# =========================================================================
@app.get("/bids/<bid_id>")
def get_bid(bid_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer"])
    obj = fetch(bids, bid_id, "Bid")
    return success(serialize(obj), 200)


@app.get("/bids")
def list_bids():
    auth(["PlatformAdmin", "FacilityOperator", "Buyer"])
    auction_id = request.args.get("auction_id")
    buyer_id = request.args.get("buyer_id")
    status = request.args.get("status")
    items = list(bids.values())
    if auction_id is not None:
        items = [x for x in items if x["auction_id"] == auction_id]
    if buyer_id is not None:
        items = [x for x in items if x["buyer_id"] == buyer_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(sorted_by_creation(items))


@app.post("/bids/<bid_id>/retract")
def retract_bid(bid_id):
    role, uid = auth(["Buyer"])
    bid = fetch(bids, bid_id, "Bid")
    forbid_if(bid["buyer_id"] != uid)
    auction = auctions[bid["auction_id"]]
    if bid["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Bid is not ACTIVE")
    if auction["status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Auction is not LIVE")

    was_high = auction["high_bid_id"] == bid["id"]
    bid["status"] = "RETRACTED"
    touch(bid)
    if was_high:
        recompute_high_bid(auction)
        auction["updated_at"] = now()
    return success(serialize(bid), 200)


# =========================================================================
# BUYERS
# =========================================================================
@app.post("/buyers")
def create_buyer():
    auth(["PlatformAdmin"])
    b = get_body()
    need(b, ["full_name", "email"])
    obj = base_fields("Buyer")
    obj.update({
        "full_name": b["full_name"],
        "email": b["email"],
        "status": "REGISTERED",
        "deposit_available_cents": 0,
        "deposit_held_cents": 0,
        "deposit_forfeited_cents": 0,
    })
    buyers[obj["id"]] = obj
    return success(serialize(obj), 201)


@app.get("/buyers/<buyer_id>")
def get_buyer(buyer_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer"])
    obj = fetch(buyers, buyer_id, "Buyer")
    return success(serialize(obj), 200)


@app.post("/buyers/<buyer_id>/fund-deposit")
def fund_deposit(buyer_id):
    role, uid = auth(["Buyer"])
    buyer = fetch(buyers, buyer_id, "Buyer")
    forbid_if(buyer_id != uid)
    b = get_body()
    need(b, ["amount_cents"])
    need_int(b, ["amount_cents"])
    buyer["deposit_available_cents"] += b["amount_cents"]
    touch(buyer)
    return success(serialize(buyer), 200)


# =========================================================================
# SALES
# =========================================================================
@app.get("/sales/<sale_id>")
def get_sale(sale_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    obj = fetch(sales, sale_id, "Sale")
    return success(serialize(obj), 200)


@app.get("/sales")
def list_sales():
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    auction_id = request.args.get("auction_id")
    buyer_id = request.args.get("buyer_id")
    items = list(sales.values())
    if auction_id is not None:
        items = [x for x in items if x["auction_id"] == auction_id]
    if buyer_id is not None:
        items = [x for x in items if x["buyer_id"] == buyer_id]
    return list_response(sorted_by_creation(items))


@app.post("/sales/<sale_id>/pay")
def pay_sale(sale_id):
    role, uid = auth(["Buyer"])
    sale = fetch(sales, sale_id, "Sale")
    forbid_if(sale["buyer_id"] != uid)
    if sale["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Sale is not UNPAID")
    if now() > sale["payment_deadline"]:
        raise ApiError("ERR_PAYMENT_WINDOW_EXPIRED", 409, "Payment window expired")
    buyer = buyers[sale["buyer_id"]]
    if buyer["status"] == "SUSPENDED":
        raise ApiError("ERR_BUYER_SUSPENDED", 409, "Buyer is suspended")

    sale["payment_status"] = "PAID"
    touch(sale)

    buyer["deposit_held_cents"] -= DEPOSIT_REQUIRED_CENTS
    buyer["deposit_available_cents"] += DEPOSIT_REQUIRED_CENTS
    touch(buyer)

    auction = auctions[sale["auction_id"]]
    unit = units[auction["unit_id"]]
    facility = facilities[unit["facility_id"]]

    gross = sale["winning_amount_cents"]
    lien_recovered, facility_fee, surplus = waterfall(gross, unit["lien_amount_final_cents"], facility)
    settlement = base_fields("Settlement")
    settlement.update({
        "sale_id": sale["id"],
        "gross_proceeds_cents": gross,
        "lien_recovered_cents": lien_recovered,
        "facility_fee_cents": facility_fee,
        "surplus_cents": surplus,
        "status": "FINALIZED",
    })
    settlements[settlement["id"]] = settlement

    tenant = tenants[unit["tenant_id"]]
    tenant["surplus_balance_cents"] += surplus
    touch(tenant)

    facility["recovery_balance_cents"] += lien_recovered + facility_fee + sale["buyer_premium_cents"]
    touch(facility)

    auction["status"] = "SETTLED"
    touch(auction)
    return success(serialize(sale), 200)


@app.post("/sales/<sale_id>/cleanout")
def cleanout_sale(sale_id):
    role, uid = auth(["Buyer"])
    sale = fetch(sales, sale_id, "Sale")
    forbid_if(sale["buyer_id"] != uid)
    if sale["payment_status"] != "PAID":
        raise ApiError("ERR_SALE_NOT_PAID", 409, "Sale is not PAID")
    if sale["cleanout_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Cleanout not PENDING")

    sale["cleanout_status"] = "COMPLETED"
    touch(sale)
    auction = auctions[sale["auction_id"]]
    unit = units[auction["unit_id"]]
    unit["status"] = "CLEARED"
    touch(unit)
    return success(serialize(sale), 200)


@app.post("/sales/<sale_id>/forfeit")
def forfeit_sale(sale_id):
    role, uid = auth(["FacilityOperator"])
    sale = fetch(sales, sale_id, "Sale")
    auction = auctions[sale["auction_id"]]
    unit = units[auction["unit_id"]]
    forbid_if(unit["facility_id"] != uid)

    if sale["payment_status"] == "UNPAID":
        if now() <= sale["payment_deadline"]:
            raise ApiError("ERR_INVALID_STATE", 409, "Payment window not expired")
        sale["payment_status"] = "FORFEITED"
        sale["cleanout_status"] = "VOIDED"
        touch(sale)

        buyer = buyers[sale["buyer_id"]]
        buyer["deposit_held_cents"] -= DEPOSIT_REQUIRED_CENTS
        buyer["deposit_forfeited_cents"] += DEPOSIT_REQUIRED_CENTS
        buyer["status"] = "SUSPENDED"
        touch(buyer)

        facility = facilities[unit["facility_id"]]
        facility["recovery_balance_cents"] += DEPOSIT_REQUIRED_CENTS
        touch(facility)

        unit["status"] = "LIEN_MATURED"
        touch(unit)
    elif sale["payment_status"] == "PAID":
        if sale["cleanout_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "Cleanout not PENDING")
        if now() <= sale["cleanout_deadline"]:
            raise ApiError("ERR_INVALID_STATE", 409, "Cleanout deadline not passed")
        sale["cleanout_status"] = "OVERDUE"
        touch(sale)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Sale cannot be forfeited")

    return success(serialize(sale), 200)


# =========================================================================
# SETTLEMENTS
# =========================================================================
@app.get("/settlements/<settlement_id>")
def get_settlement(settlement_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    obj = fetch(settlements, settlement_id, "Settlement")
    return success(serialize(obj), 200)


@app.get("/sales/<sale_id>/settlement")
def get_sale_settlement(sale_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    fetch(sales, sale_id, "Sale")
    items = sorted_by_creation([s for s in settlements.values() if s["sale_id"] == sale_id])
    return list_response(items)


# =========================================================================
# DISPUTES
# =========================================================================
def _dispute_parties(subject_type, sale_id, settlement_id):
    """Return (buyer_id, tenant_id) for the disputed subject, or raise ERR_NOT_FOUND."""
    if subject_type == "SALE":
        sale = fetch(sales, sale_id, "Sale")
    else:
        settlement = fetch(settlements, settlement_id, "Settlement")
        sale = sales[settlement["sale_id"]]
    auction = auctions[sale["auction_id"]]
    unit = units[auction["unit_id"]]
    return sale["buyer_id"], unit["tenant_id"]


@app.post("/disputes")
def create_dispute():
    role, uid = auth(["Tenant", "Buyer"])
    b = get_body()
    need(b, ["subject_type", "raised_by", "reason"])
    need_enum(b, "subject_type", {"SALE", "SETTLEMENT"})
    need_enum(b, "raised_by", {"TENANT", "BUYER"})
    if b["subject_type"] == "SALE":
        need(b, ["sale_id"])
    else:
        need(b, ["settlement_id"])

    # role must match raised_by
    if (role == "Buyer" and b["raised_by"] != "BUYER") or (role == "Tenant" and b["raised_by"] != "TENANT"):
        raise ApiError("ERR_FORBIDDEN", 403, "raised_by does not match role")

    sale_id = b.get("sale_id")
    settlement_id = b.get("settlement_id")
    buyer_id, tenant_id = _dispute_parties(b["subject_type"], sale_id, settlement_id)

    # ownership: acting principal must be party to the subject
    if role == "Buyer":
        forbid_if(buyer_id != uid)
    else:
        forbid_if(tenant_id != uid)

    obj = base_fields("Dispute")
    obj.update({
        "subject_type": b["subject_type"],
        "sale_id": sale_id if b["subject_type"] == "SALE" else None,
        "settlement_id": settlement_id if b["subject_type"] == "SETTLEMENT" else None,
        "raised_by": b["raised_by"],
        "reason": b["reason"],
        "resolution": None,
        "status": "OPEN",
    })
    disputes[obj["id"]] = obj
    return success(serialize(obj), 201)


@app.get("/disputes/<dispute_id>")
def get_dispute(dispute_id):
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    obj = fetch(disputes, dispute_id, "Dispute")
    return success(serialize(obj), 200)


@app.get("/disputes")
def list_disputes():
    auth(["PlatformAdmin", "FacilityOperator", "Buyer", "Tenant"])
    sale_id = request.args.get("sale_id")
    settlement_id = request.args.get("settlement_id")
    status = request.args.get("status")
    items = list(disputes.values())
    if sale_id is not None:
        items = [x for x in items if x["sale_id"] == sale_id]
    if settlement_id is not None:
        items = [x for x in items if x["settlement_id"] == settlement_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(sorted_by_creation(items))


@app.post("/disputes/<dispute_id>/review")
def review_dispute(dispute_id):
    auth(["PlatformAdmin"])
    d = fetch(disputes, dispute_id, "Dispute")
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(serialize(d), 200)


@app.post("/disputes/<dispute_id>/request-info")
def request_info_dispute(dispute_id):
    auth(["PlatformAdmin"])
    d = fetch(disputes, dispute_id, "Dispute")
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW")
    d["status"] = "NEEDS_INFO"
    touch(d)
    return success(serialize(d), 200)


@app.post("/disputes/<dispute_id>/provide-info")
def provide_info_dispute(dispute_id):
    role, uid = auth(["Tenant", "Buyer"])
    d = fetch(disputes, dispute_id, "Dispute")
    # ownership: must be the party that raised the dispute
    buyer_id, tenant_id = _dispute_parties(d["subject_type"], d.get("sale_id"), d.get("settlement_id"))
    if d["raised_by"] == "BUYER":
        forbid_if(role != "Buyer" or uid != buyer_id)
    else:
        forbid_if(role != "Tenant" or uid != tenant_id)
    b = get_body()
    need(b, ["note"])
    if d["status"] != "NEEDS_INFO":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not NEEDS_INFO")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(serialize(d), 200)


@app.post("/disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    auth(["PlatformAdmin"])
    d = fetch(disputes, dispute_id, "Dispute")
    b = get_body()
    need(b, ["decision"])
    need_enum(b, "decision", {"UPHOLD", "DENY"})
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not UNDER_REVIEW")

    if b["decision"] == "UPHOLD":
        d["resolution"] = "UPHELD"
        d["status"] = "UPHELD"
        touch(d)
        _apply_uphold_cascade(d)
    else:
        d["resolution"] = "DENIED"
        d["status"] = "DENIED"
        touch(d)
    return success(serialize(d), 200)


def _apply_uphold_cascade(d):
    if d["subject_type"] == "SETTLEMENT":
        settlement = settlements[d["settlement_id"]]
        sale = sales[settlement["sale_id"]]
        auction = auctions[sale["auction_id"]]
        unit = units[auction["unit_id"]]
        tenant = tenants[unit["tenant_id"]]
        facility = facilities[unit["facility_id"]]

        settlement["status"] = "REVERSED"
        touch(settlement)
        tenant["surplus_balance_cents"] -= settlement["surplus_cents"]
        touch(tenant)
        facility["recovery_balance_cents"] -= (
            settlement["lien_recovered_cents"] + settlement["facility_fee_cents"] + sale["buyer_premium_cents"]
        )
        touch(facility)
    else:  # SALE
        sale = sales[d["sale_id"]]
        sale["payment_status"] = "REFUNDED"
        touch(sale)


# =========================================================================
# LOGICAL CLOCK
# =========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    auth(["PlatformAdmin"])
    b = get_body()
    need(b, ["to_iso8601"])
    try:
        _clock["now"] = parse_iso(b["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, "Invalid to_iso8601")
    return success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
