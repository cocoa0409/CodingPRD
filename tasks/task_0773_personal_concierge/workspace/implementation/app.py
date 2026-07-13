import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = {"Member", "ConciergeAgent", "AccountManager", "FinanceOps"}
CATEGORIES = {"ERRAND", "BOOKING", "TRAVEL", "GIFT"}
VIP_TIERS = {"STANDARD", "SILVER", "GOLD", "PLATINUM"}
CADENCES = {"NONE", "WEEKLY", "MONTHLY"}
BILLING_MODES = {"MARKUP", "PASS_THROUGH"}

TIER_OVERAGE_MULT = {"STANDARD": "1.00", "SILVER": "0.95", "GOLD": "0.90", "PLATINUM": "0.85"}
TIER_WEIGHT = {"STANDARD": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 5}
CATEGORY_WEIGHT = {"ERRAND": 0, "BOOKING": 1, "GIFT": 2, "TRAVEL": 3}
RUSH_BONUS = 2
CURRENT_STANDING_WINDOW = 3
VENDOR_BUFFER = timedelta(minutes=30)

# Category eligibility by tier
def category_eligible(vip_tier, category):
    if category == "TRAVEL":
        return vip_tier in {"GOLD", "PLATINUM"}
    if category == "GIFT":
        return vip_tier in {"SILVER", "GOLD", "PLATINUM"}
    return True  # ERRAND, BOOKING open to all


# =============================================================================
# In-memory store (wiped on every process start)
# =============================================================================
DB = {
    "members": {},
    "plans": {},
    "memberships": {},
    "cycles": {},
    "requests": {},
    "vendors": {},
    "engagements": {},
    "time_entries": {},
    "expenses": {},
    "ratings": {},
}
_SEQ = {"n": 0}
_RATING_SEQ = {}  # membership_id -> counter


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# =============================================================================
# Error handling
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# =============================================================================
# Time / id helpers
# =============================================================================
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


# =============================================================================
# Response envelope helpers
# =============================================================================
def respond_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_array(items, limit, offset, total, status=200):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(err: ApiError):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return respond_error(err)


@app.errorhandler(404)
def handle_404(_e):
    return respond_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return respond_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return respond_error(e)
    return respond_error(ApiError("ERR_INVALID_REQUEST", 400, str(e)))


# =============================================================================
# Auth / RBAC
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")
    return uid, role


# =============================================================================
# Common-field / mutation helpers
# =============================================================================
def base_entity(with_version=True):
    ts = now_iso()
    e = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_version:
        e["updated_at"] = ts
        e["version"] = 1
    return e


def touch(entity):
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = now_iso()


# =============================================================================
# Body-parsing validators
# =============================================================================
def get_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Body must be a JSON object")
    return data


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be a non-empty string")
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' below minimum")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' above maximum")
    return v


def require_number(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be a number")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' below minimum")
    return v


def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO datetime string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field '{field}' is not a valid datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


# =============================================================================
# Decimal helpers
# =============================================================================
def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =============================================================================
# Computation helpers
# =============================================================================
def cycle_consumed(cycle):
    total = 0
    for te in DB["time_entries"].values():
        if te["billing_cycle_id"] == cycle["id"] and te["status"] == "FINALIZED":
            total += te["minutes"]
    return total


def cycle_overage_charge(cycle):
    membership = DB["memberships"].get(cycle["membership_id"])
    plan = DB["plans"].get(membership["plan_id"]) if membership else None
    consumed = cycle_consumed(cycle)
    overage = max(0, consumed - cycle["included_minutes"])
    if overage == 0 or plan is None:
        return 0
    mult = Decimal(TIER_OVERAGE_MULT[membership["vip_tier"]])
    eff_rate = round_half_up_cents(Decimal(plan["overage_rate_cents_per_hour"]) * mult)
    charge = int((Decimal(overage * eff_rate) / Decimal(60)).quantize(Decimal("1"), rounding=ROUND_CEILING))
    return charge


def membership_cycles(membership_id):
    return [c for c in DB["cycles"].values() if c["membership_id"] == membership_id]


def membership_open_cycle(membership_id):
    for c in DB["cycles"].values():
        if c["membership_id"] == membership_id and c["status"] == "OPEN":
            return c
    return None


def membership_outstanding(membership):
    mid = membership["id"]
    overage_total = sum(cycle_overage_charge(c) for c in membership_cycles(mid))
    engagement_total = 0
    for e in DB["engagements"].values():
        if e["status"] not in {"CONFIRMED", "RECONCILED"}:
            continue
        sr = DB["requests"].get(e["service_request_id"])
        if sr and sr["membership_id"] == mid:
            engagement_total += e["client_charge_cents"]
    return overage_total + engagement_total


def membership_hour_bank_remaining(membership):
    oc = membership_open_cycle(membership["id"])
    if oc is None:
        return 0
    return max(0, oc["included_minutes"] - cycle_consumed(oc))


def membership_ratings(membership_id):
    return [r for r in DB["ratings"].values() if r["membership_id"] == membership_id]


def membership_satisfaction(membership_id):
    ratings = membership_ratings(membership_id)
    count = len(ratings)
    if count == 0:
        return None, None, 0
    scores = [r["score"] for r in ratings]
    lifetime = round_half_up_2(Decimal(sum(scores)) / Decimal(count))
    recent = sorted(ratings, key=lambda r: r["sequence_no"], reverse=True)[:CURRENT_STANDING_WINDOW]
    rscores = [r["score"] for r in recent]
    current = round_half_up_2(Decimal(sum(rscores)) / Decimal(len(rscores)))
    return float(lifetime), float(current), count


def member_lifetime(member_id):
    total = 0
    for m in DB["memberships"].values():
        if m["member_id"] == member_id:
            total += membership_outstanding(m)
    return total


def request_actual_minutes(request_id_):
    total = 0
    for te in DB["time_entries"].values():
        if te["service_request_id"] == request_id_ and te["status"] == "FINALIZED":
            total += te["minutes"]
    return total


def request_priority_score(sr):
    membership = DB["memberships"].get(sr["membership_id"])
    tier = membership["vip_tier"] if membership else "STANDARD"
    return TIER_WEIGHT[tier] + CATEGORY_WEIGHT[sr["category"]] + (RUSH_BONUS if sr["rush"] else 0)


# =============================================================================
# Serializers
# =============================================================================
COMMON = ("id", "created_at", "updated_at", "version")


def ser_member(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "status": m["status"],
        "lifetime_billed_cents": member_lifetime(m["id"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "monthly_retainer_cents": p["monthly_retainer_cents"],
        "included_hours": p["included_hours"],
        "overage_rate_cents_per_hour": p["overage_rate_cents_per_hour"],
        "default_markup_pct": p["default_markup_pct"],
        "max_pass_through_cents": p["max_pass_through_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_membership(m):
    lifetime, current, _count = membership_satisfaction(m["id"])
    return {
        "id": m["id"],
        "member_id": m["member_id"],
        "plan_id": m["plan_id"],
        "vip_tier": m["vip_tier"],
        "status": m["status"],
        "current_cycle_index": m["current_cycle_index"],
        "hour_bank_remaining_minutes": membership_hour_bank_remaining(m),
        "outstanding_balance_cents": membership_outstanding(m),
        "satisfaction_score": current,
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_cycle(c):
    consumed = cycle_consumed(c)
    overage_min = max(0, consumed - c["included_minutes"])
    return {
        "id": c["id"],
        "membership_id": c["membership_id"],
        "cycle_index": c["cycle_index"],
        "included_minutes": c["included_minutes"],
        "consumed_minutes": consumed,
        "overage_minutes": overage_min,
        "overage_charge_cents": cycle_overage_charge(c),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_request(s):
    return {
        "id": s["id"],
        "membership_id": s["membership_id"],
        "recurrence_parent_id": s["recurrence_parent_id"],
        "category": s["category"],
        "title": s["title"],
        "is_standing": s["is_standing"],
        "cadence": s["cadence"],
        "rush": s["rush"],
        "estimated_minutes": s["estimated_minutes"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "actual_minutes": request_actual_minutes(s["id"]),
        "priority_score": request_priority_score(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_vendor(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "category": v["category"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_engagement(e):
    return {
        "id": e["id"],
        "service_request_id": e["service_request_id"],
        "vendor_id": e["vendor_id"],
        "billing_mode": e["billing_mode"],
        "markup_pct": e["markup_pct"],
        "estimated_cost_lines": e["estimated_cost_lines"],
        "actual_cost_lines": e["actual_cost_lines"],
        "service_start": e["service_start"],
        "service_end": e["service_end"],
        "client_charge_cents": e["client_charge_cents"],
        "charge_basis": e["charge_basis"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_time_entry(t):
    return {
        "id": t["id"],
        "service_request_id": t["service_request_id"],
        "billing_cycle_id": t["billing_cycle_id"],
        "minutes": t["minutes"],
        "note": t["note"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_expense(x):
    return {
        "id": x["id"],
        "vendor_engagement_id": x["vendor_engagement_id"],
        "membership_id": x["membership_id"],
        "estimated_cents": x["estimated_cents"],
        "actual_cents": x["actual_cents"],
        "variance_cents": x["variance_cents"],
        "status": x["status"],
        "created_at": x["created_at"],
        "updated_at": x["updated_at"],
        "version": x["version"],
    }


def ser_rating(r):
    return {
        "id": r["id"],
        "service_request_id": r["service_request_id"],
        "membership_id": r["membership_id"],
        "score": r["score"],
        "comment": r["comment"],
        "sequence_no": r["sequence_no"],
        "created_at": r["created_at"],
    }


# =============================================================================
# Lookup helpers
# =============================================================================
def get_or_404(collection, id_):
    obj = DB[collection].get(id_)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


def membership_of_request(sr):
    return DB["memberships"].get(sr["membership_id"])


def require_owner(role, uid, member_id):
    if role == "Member" and member_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the owner of this resource")


def close_open_cycle(membership_id):
    oc = membership_open_cycle(membership_id)
    if oc is not None:
        oc["status"] = "CLOSED"
        touch(oc)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def list_sorted(collection, predicate):
    items = [o for o in DB[collection].values() if predicate(o)]
    items.sort(key=lambda o: o["_seq"])
    return items


# =============================================================================
# Member endpoints
# =============================================================================
@app.route("/concierge/members", methods=["POST"])
def create_member():
    authorize({"AccountManager"})
    data = get_json()
    full_name = require_str(data, "full_name")
    email = require_str(data, "email")
    for m in DB["members"].values():
        if m["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", 409, "Email already in use")
    m = base_entity()
    m.update({"full_name": full_name, "email": email, "status": "PENDING"})
    DB["members"][m["id"]] = m
    return respond_object(ser_member(m), 201)


@app.route("/concierge/members/<id_>", methods=["GET"])
def get_member(id_):
    authorize(ROLES)
    m = get_or_404("members", id_)
    return respond_object(ser_member(m), 200)


@app.route("/concierge/members/<id_>/activate", methods=["POST"])
def activate_member(id_):
    authorize({"AccountManager"})
    m = get_or_404("members", id_)
    if m["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not PENDING")
    m["status"] = "ACTIVE"
    touch(m)
    return respond_object(ser_member(m), 200)


@app.route("/concierge/members/<id_>/suspend", methods=["POST"])
def suspend_member(id_):
    authorize({"AccountManager"})
    m = get_or_404("members", id_)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    m["status"] = "SUSPENDED"
    for ms in DB["memberships"].values():
        if ms["member_id"] == m["id"] and ms["status"] in {"ACTIVE", "PAUSED"}:
            ms["status"] = "CANCELLED"
            close_open_cycle(ms["id"])
            touch(ms)
    touch(m)
    return respond_object(ser_member(m), 200)


# =============================================================================
# RetainerPlan endpoints
# =============================================================================
@app.route("/concierge/retainer-plans", methods=["POST"])
def create_plan():
    authorize({"AccountManager"})
    data = get_json()
    name = require_str(data, "name")
    monthly = require_int(data, "monthly_retainer_cents", minimum=1)
    included_hours = require_int(data, "included_hours", minimum=1)
    overage_rate = require_int(data, "overage_rate_cents_per_hour", minimum=1)
    max_pt = require_int(data, "max_pass_through_cents", minimum=1)
    if "default_markup_pct" in data and data["default_markup_pct"] is not None:
        markup = require_number(data, "default_markup_pct", minimum=0)
    else:
        markup = 0.15
    p = base_entity()
    p.update({
        "name": name,
        "monthly_retainer_cents": monthly,
        "included_hours": included_hours,
        "overage_rate_cents_per_hour": overage_rate,
        "default_markup_pct": markup,
        "max_pass_through_cents": max_pt,
    })
    DB["plans"][p["id"]] = p
    return respond_object(ser_plan(p), 201)


@app.route("/concierge/retainer-plans/<id_>", methods=["GET"])
def get_plan(id_):
    authorize(ROLES)
    p = get_or_404("plans", id_)
    return respond_object(ser_plan(p), 200)


# =============================================================================
# Vendor endpoints
# =============================================================================
@app.route("/concierge/vendors", methods=["POST"])
def create_vendor():
    authorize({"AccountManager"})
    data = get_json()
    name = require_str(data, "name")
    category = require_str(data, "category")
    if category not in CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid category")
    v = base_entity()
    v.update({"name": name, "category": category, "status": "ACTIVE"})
    DB["vendors"][v["id"]] = v
    return respond_object(ser_vendor(v), 201)


@app.route("/concierge/vendors/<id_>", methods=["GET"])
def get_vendor(id_):
    authorize(ROLES)
    v = get_or_404("vendors", id_)
    return respond_object(ser_vendor(v), 200)


@app.route("/concierge/vendors/<id_>/suspend", methods=["POST"])
def suspend_vendor(id_):
    authorize({"AccountManager"})
    v = get_or_404("vendors", id_)
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Vendor is not ACTIVE")
    v["status"] = "SUSPENDED"
    touch(v)
    return respond_object(ser_vendor(v), 200)


# =============================================================================
# Membership endpoints
# =============================================================================
@app.route("/concierge/members/<id_>/memberships", methods=["POST"])
def create_membership(id_):
    authorize({"AccountManager"})
    member = get_or_404("members", id_)
    data = get_json()
    plan_id = data.get("plan_id")
    if not isinstance(plan_id, str) or plan_id == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "plan_id required")
    if "expected_member_version" not in data or not is_int(data.get("expected_member_version")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_member_version required")
    vip_tier = data.get("vip_tier", "STANDARD")
    if vip_tier is None:
        vip_tier = "STANDARD"
    if vip_tier not in VIP_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid vip_tier")
    expected_version = data["expected_member_version"]
    plan = DB["plans"].get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Plan not found")
    # business
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION", 412, "Stale member version")
    # supersede prior ACTIVE membership(s)
    for prior in DB["memberships"].values():
        if prior["member_id"] == member["id"] and prior["status"] == "ACTIVE":
            prior["status"] = "CANCELLED"
            close_open_cycle(prior["id"])
            touch(prior)
    # new membership
    ms = base_entity()
    ms.update({
        "member_id": member["id"],
        "plan_id": plan_id,
        "vip_tier": vip_tier,
        "status": "ACTIVE",
        "current_cycle_index": 0,
    })
    DB["memberships"][ms["id"]] = ms
    # open first cycle
    cyc = base_entity()
    cyc.update({
        "membership_id": ms["id"],
        "cycle_index": 0,
        "included_minutes": plan["included_hours"] * 60,
        "status": "OPEN",
    })
    DB["cycles"][cyc["id"]] = cyc
    # bump member version
    touch(member)
    return respond_object(ser_membership(ms), 201)


@app.route("/concierge/memberships/<id_>", methods=["GET"])
def get_membership(id_):
    _uid, role = authorize(ROLES)
    ms = get_or_404("memberships", id_)
    require_owner(role, _uid, ms["member_id"])
    return respond_object(ser_membership(ms), 200)


@app.route("/concierge/memberships", methods=["GET"])
def list_memberships():
    authorize(ROLES)
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")

    def pred(m):
        if member_id is not None and m["member_id"] != member_id:
            return False
        if plan_id is not None and m["plan_id"] != plan_id:
            return False
        if status is not None and m["status"] != status:
            return False
        return True

    items = list_sorted("memberships", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_membership(m) for m in page], limit, offset, total, 200)


@app.route("/concierge/memberships/<id_>/satisfaction", methods=["GET"])
def get_satisfaction(id_):
    _uid, role = authorize(ROLES)
    ms = get_or_404("memberships", id_)
    require_owner(role, _uid, ms["member_id"])
    lifetime, current, count = membership_satisfaction(id_)
    return respond_object({
        "lifetime_average": lifetime,
        "current_standing": current,
        "rating_count": count,
    }, 200)


@app.route("/concierge/memberships/<id_>/pause", methods=["POST"])
def pause_membership(id_):
    authorize({"AccountManager"})
    ms = get_or_404("memberships", id_)
    if ms["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Membership is not ACTIVE")
    ms["status"] = "PAUSED"
    touch(ms)
    return respond_object(ser_membership(ms), 200)


@app.route("/concierge/memberships/<id_>/resume", methods=["POST"])
def resume_membership(id_):
    authorize({"AccountManager"})
    ms = get_or_404("memberships", id_)
    if ms["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Membership is not PAUSED")
    ms["status"] = "ACTIVE"
    touch(ms)
    return respond_object(ser_membership(ms), 200)


@app.route("/concierge/memberships/<id_>/cancel", methods=["POST"])
def cancel_membership(id_):
    authorize({"AccountManager"})
    ms = get_or_404("memberships", id_)
    if ms["status"] not in {"ACTIVE", "PAUSED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Membership cannot be cancelled")
    for sr in DB["requests"].values():
        if sr["membership_id"] == ms["id"] and sr["status"] in {"SUBMITTED", "IN_PROGRESS", "ON_HOLD"}:
            raise ApiError("ERR_CYCLE_HAS_ACTIVE_REQUESTS", 409, "Membership has active requests")
    ms["status"] = "CANCELLED"
    close_open_cycle(ms["id"])
    touch(ms)
    return respond_object(ser_membership(ms), 200)


# =============================================================================
# BillingCycle endpoints
# =============================================================================
@app.route("/concierge/billing-cycles/<id_>", methods=["GET"])
def get_cycle(id_):
    authorize(ROLES)
    c = get_or_404("cycles", id_)
    return respond_object(ser_cycle(c), 200)


@app.route("/concierge/billing-cycles", methods=["GET"])
def list_cycles():
    authorize(ROLES)
    limit, offset = parse_pagination()
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")

    def pred(c):
        if membership_id is not None and c["membership_id"] != membership_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    items = list_sorted("cycles", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_cycle(c) for c in page], limit, offset, total, 200)


@app.route("/concierge/billing-cycles/<id_>/close", methods=["POST"])
def close_cycle(id_):
    authorize({"FinanceOps"})
    c = get_or_404("cycles", id_)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Cycle is not OPEN")
    membership = DB["memberships"].get(c["membership_id"])
    for sr in DB["requests"].values():
        if sr["membership_id"] == c["membership_id"] and sr["status"] in {"SUBMITTED", "IN_PROGRESS", "ON_HOLD"}:
            raise ApiError("ERR_CYCLE_HAS_ACTIVE_REQUESTS", 409, "Membership has active requests")
    c["status"] = "CLOSED"
    touch(c)
    # open successor
    plan = DB["plans"].get(membership["plan_id"])
    succ = base_entity()
    succ.update({
        "membership_id": membership["id"],
        "cycle_index": c["cycle_index"] + 1,
        "included_minutes": plan["included_hours"] * 60,
        "status": "OPEN",
    })
    DB["cycles"][succ["id"]] = succ
    membership["current_cycle_index"] = succ["cycle_index"]
    touch(membership)
    return respond_object(ser_cycle(c), 200)


# =============================================================================
# ServiceRequest endpoints
# =============================================================================
@app.route("/concierge/service-requests", methods=["POST"])
def create_service_request():
    uid, role = authorize({"Member"})
    data = get_json()
    membership_id = data.get("membership_id")
    # ownership + existence on membership
    if isinstance(membership_id, str) and membership_id != "":
        ms = DB["memberships"].get(membership_id)
        if ms is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Membership not found")
        require_owner(role, uid, ms["member_id"])
    else:
        ms = None
    # body validation
    if ms is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "membership_id required")
    category = data.get("category")
    if category not in CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid category")
    title = require_str(data, "title")
    is_standing = data.get("is_standing", False)
    if not isinstance(is_standing, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "is_standing must be boolean")
    cadence = data.get("cadence", "NONE")
    if cadence is None:
        cadence = "NONE"
    if cadence not in CADENCES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid cadence")
    rush = data.get("rush", False)
    if not isinstance(rush, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "rush must be boolean")
    estimated_minutes = data.get("estimated_minutes", 0)
    if estimated_minutes is None:
        estimated_minutes = 0
    if not is_int(estimated_minutes) or estimated_minutes < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "estimated_minutes must be >= 0")
    # business
    if ms["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Membership is not ACTIVE")
    if not category_eligible(ms["vip_tier"], category):
        raise ApiError("ERR_CATEGORY_NOT_ELIGIBLE", 422, "Tier not eligible for category")
    sr = base_entity()
    sr.update({
        "membership_id": membership_id,
        "recurrence_parent_id": None,
        "category": category,
        "title": title,
        "is_standing": is_standing,
        "cadence": cadence,
        "rush": rush,
        "estimated_minutes": estimated_minutes,
        "scheduled_start": None,
        "scheduled_end": None,
        "status": "SUBMITTED",
    })
    DB["requests"][sr["id"]] = sr
    return respond_object(ser_request(sr), 201)


@app.route("/concierge/service-requests/<id_>", methods=["GET"])
def get_service_request(id_):
    uid, role = authorize(ROLES)
    sr = get_or_404("requests", id_)
    ms = membership_of_request(sr)
    if ms is not None:
        require_owner(role, uid, ms["member_id"])
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests", methods=["GET"])
def list_service_requests():
    authorize(ROLES)
    limit, offset = parse_pagination()
    membership_id = request.args.get("membership_id")
    recurrence_parent_id = request.args.get("recurrence_parent_id")
    status = request.args.get("status")
    category = request.args.get("category")

    def pred(s):
        if membership_id is not None and s["membership_id"] != membership_id:
            return False
        if recurrence_parent_id is not None and s["recurrence_parent_id"] != recurrence_parent_id:
            return False
        if status is not None and s["status"] != status:
            return False
        if category is not None and s["category"] != category:
            return False
        return True

    items = list_sorted("requests", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_request(s) for s in page], limit, offset, total, 200)


@app.route("/concierge/service-requests/<id_>/accept", methods=["POST"])
def accept_service_request(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    data = get_json()
    if "scheduled_start" not in data or "scheduled_end" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_start and scheduled_end required")
    start = parse_dt(data.get("scheduled_start"), "scheduled_start")
    end = parse_dt(data.get("scheduled_end"), "scheduled_end")
    if sr["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not SUBMITTED")
    if not (end > start):
        raise ApiError("ERR_INVALID_WINDOW", 400, "scheduled_end must be after scheduled_start")
    # schedule conflict
    for other in DB["requests"].values():
        if other["id"] == sr["id"]:
            continue
        if other["membership_id"] != sr["membership_id"]:
            continue
        if other["status"] not in {"IN_PROGRESS", "ON_HOLD"}:
            continue
        if other["scheduled_start"] is None or other["scheduled_end"] is None:
            continue
        os_ = parse_dt(other["scheduled_start"], "scheduled_start")
        oe = parse_dt(other["scheduled_end"], "scheduled_end")
        # half-open overlap
        if start < oe and os_ < end:
            raise ApiError("ERR_MEMBER_SCHEDULE_CONFLICT", 409, "Schedule conflict")
    sr["scheduled_start"] = data["scheduled_start"]
    sr["scheduled_end"] = data["scheduled_end"]
    sr["status"] = "IN_PROGRESS"
    touch(sr)
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests/<id_>/hold", methods=["POST"])
def hold_service_request(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    if sr["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not IN_PROGRESS")
    sr["status"] = "ON_HOLD"
    touch(sr)
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests/<id_>/resume", methods=["POST"])
def resume_service_request(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    if sr["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not ON_HOLD")
    sr["status"] = "IN_PROGRESS"
    touch(sr)
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests/<id_>/fulfill", methods=["POST"])
def fulfill_service_request(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    if sr["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not IN_PROGRESS")
    sr["status"] = "FULFILLED"
    touch(sr)
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests/<id_>/cancel", methods=["POST"])
def cancel_service_request(id_):
    uid, role = authorize({"ConciergeAgent", "Member"})
    sr = get_or_404("requests", id_)
    ms = membership_of_request(sr)
    if ms is not None:
        require_owner(role, uid, ms["member_id"])
    if sr["status"] not in {"SUBMITTED", "IN_PROGRESS", "ON_HOLD"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Request cannot be cancelled")
    sr["status"] = "CANCELLED"
    touch(sr)
    return respond_object(ser_request(sr), 200)


@app.route("/concierge/service-requests/<id_>/generate", methods=["POST"])
def generate_occurrence(id_):
    uid, role = authorize({"Member"})
    parent = get_or_404("requests", id_)
    ms = membership_of_request(parent)
    if ms is not None:
        require_owner(role, uid, ms["member_id"])
    data = get_json()
    # business (priority order: membership active, eligibility, not-standing)
    if ms is None or ms["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Membership is not ACTIVE")
    if not category_eligible(ms["vip_tier"], parent["category"]):
        raise ApiError("ERR_CATEGORY_NOT_ELIGIBLE", 422, "Tier not eligible for category")
    if not parent["is_standing"]:
        raise ApiError("ERR_NOT_STANDING", 422, "Request is not a standing template")
    title = data.get("title")
    if title is not None and (not isinstance(title, str) or title == ""):
        raise ApiError("ERR_INVALID_REQUEST", 400, "title must be a non-empty string")
    if title is None:
        title = parent["title"]
    sr = base_entity()
    sr.update({
        "membership_id": parent["membership_id"],
        "recurrence_parent_id": parent["id"],
        "category": parent["category"],
        "title": title,
        "is_standing": False,
        "cadence": "NONE",
        "rush": parent["rush"],
        "estimated_minutes": parent["estimated_minutes"],
        "scheduled_start": None,
        "scheduled_end": None,
        "status": "SUBMITTED",
    })
    DB["requests"][sr["id"]] = sr
    return respond_object(ser_request(sr), 201)


@app.route("/concierge/service-requests/<id_>/time-entries", methods=["POST"])
def create_time_entry(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    data = get_json()
    minutes = data.get("minutes")
    if not is_int(minutes) or minutes <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "minutes must be > 0")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "note must be a string")
    ms = membership_of_request(sr)
    if ms is None or ms["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Membership is not ACTIVE")
    oc = membership_open_cycle(ms["id"])
    te = base_entity()
    te.update({
        "service_request_id": sr["id"],
        "billing_cycle_id": oc["id"],
        "minutes": minutes,
        "note": note,
        "status": "FINALIZED",
    })
    DB["time_entries"][te["id"]] = te
    # cascade bumps
    touch(oc)
    touch(ms)
    member = DB["members"].get(ms["member_id"])
    if member:
        touch(member)
    return respond_object(ser_time_entry(te), 201)


@app.route("/concierge/service-requests/<id_>/ratings", methods=["POST"])
def create_rating(id_):
    uid, role = authorize({"Member"})
    sr = get_or_404("requests", id_)
    ms = membership_of_request(sr)
    if ms is not None:
        require_owner(role, uid, ms["member_id"])
    data = get_json()
    score = data.get("score")
    if not is_int(score) or score < 1 or score > 5:
        raise ApiError("ERR_INVALID_REQUEST", 400, "score must be between 1 and 5")
    comment = data.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "comment must be a string")
    if sr["status"] != "FULFILLED":
        raise ApiError("ERR_RATING_NOT_ALLOWED", 409, "Request is not FULFILLED")
    mid = sr["membership_id"]
    seq = _RATING_SEQ.get(mid, 0) + 1
    _RATING_SEQ[mid] = seq
    r = base_entity(with_version=False)
    r.update({
        "service_request_id": sr["id"],
        "membership_id": mid,
        "score": score,
        "comment": comment,
        "sequence_no": seq,
    })
    DB["ratings"][r["id"]] = r
    if ms is not None:
        touch(ms)
    return respond_object(ser_rating(r), 201)


# =============================================================================
# TimeEntry endpoints
# =============================================================================
@app.route("/concierge/time-entries/<id_>", methods=["GET"])
def get_time_entry(id_):
    authorize(ROLES)
    te = get_or_404("time_entries", id_)
    return respond_object(ser_time_entry(te), 200)


@app.route("/concierge/time-entries", methods=["GET"])
def list_time_entries():
    authorize(ROLES)
    limit, offset = parse_pagination()
    service_request_id = request.args.get("service_request_id")
    billing_cycle_id = request.args.get("billing_cycle_id")
    status = request.args.get("status")

    def pred(t):
        if service_request_id is not None and t["service_request_id"] != service_request_id:
            return False
        if billing_cycle_id is not None and t["billing_cycle_id"] != billing_cycle_id:
            return False
        if status is not None and t["status"] != status:
            return False
        return True

    items = list_sorted("time_entries", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_time_entry(t) for t in page], limit, offset, total, 200)


@app.route("/concierge/time-entries/<id_>/reverse", methods=["POST"])
def reverse_time_entry(id_):
    authorize({"ConciergeAgent"})
    te = get_or_404("time_entries", id_)
    if te["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "TimeEntry is not FINALIZED")
    te["status"] = "REVERSED"
    touch(te)
    cyc = DB["cycles"].get(te["billing_cycle_id"])
    if cyc:
        touch(cyc)
        ms = DB["memberships"].get(cyc["membership_id"])
        if ms:
            touch(ms)
            member = DB["members"].get(ms["member_id"])
            if member:
                touch(member)
    return respond_object(ser_time_entry(te), 200)


# =============================================================================
# VendorEngagement endpoints
# =============================================================================
@app.route("/concierge/service-requests/<id_>/engagements", methods=["POST"])
def create_engagement(id_):
    authorize({"ConciergeAgent"})
    sr = get_or_404("requests", id_)
    data = get_json()
    vendor_id = data.get("vendor_id")
    if not isinstance(vendor_id, str) or vendor_id == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "vendor_id required")
    vendor = DB["vendors"].get(vendor_id)
    if vendor is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found")
    billing_mode = data.get("billing_mode")
    if billing_mode not in BILLING_MODES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid billing_mode")
    lines = data.get("estimated_cost_lines")
    if not isinstance(lines, list) or any(not is_int(x) for x in lines):
        raise ApiError("ERR_INVALID_REQUEST", 400, "estimated_cost_lines must be an array of integers")
    if "service_start" not in data or "service_end" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "service_start and service_end required")
    parse_dt(data.get("service_start"), "service_start")
    parse_dt(data.get("service_end"), "service_end")
    markup_pct = data.get("markup_pct", 0)
    if markup_pct is None:
        markup_pct = 0
    if isinstance(markup_pct, bool) or not isinstance(markup_pct, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "markup_pct must be a number")
    if markup_pct < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "markup_pct must be >= 0")
    # business
    if vendor["category"] != sr["category"]:
        raise ApiError("ERR_VENDOR_CATEGORY_MISMATCH", 422, "Vendor category does not match request category")
    if billing_mode == "PASS_THROUGH":
        if markup_pct != 0:
            raise ApiError("ERR_MARKUP_ON_PASS_THROUGH", 422, "markup_pct must be 0 for PASS_THROUGH")
        membership = membership_of_request(sr)
        plan = DB["plans"].get(membership["plan_id"]) if membership else None
        max_pt = plan["max_pass_through_cents"] if plan else None
        if max_pt is not None:
            for line in lines:
                if line > max_pt:
                    raise ApiError("ERR_PASS_THROUGH_LIMIT_EXCEEDED", 422, "Pass-through line exceeds limit")
    e = base_entity()
    e.update({
        "service_request_id": sr["id"],
        "vendor_id": vendor_id,
        "billing_mode": billing_mode,
        "markup_pct": markup_pct,
        "estimated_cost_lines": lines,
        "actual_cost_lines": None,
        "service_start": data["service_start"],
        "service_end": data["service_end"],
        "client_charge_cents": 0,
        "charge_basis": None,
        "status": "PROPOSED",
    })
    DB["engagements"][e["id"]] = e
    return respond_object(ser_engagement(e), 201)


@app.route("/concierge/vendor-engagements/<id_>", methods=["GET"])
def get_engagement(id_):
    authorize(ROLES)
    e = get_or_404("engagements", id_)
    return respond_object(ser_engagement(e), 200)


@app.route("/concierge/vendor-engagements", methods=["GET"])
def list_engagements():
    authorize(ROLES)
    limit, offset = parse_pagination()
    service_request_id = request.args.get("service_request_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")

    def pred(e):
        if service_request_id is not None and e["service_request_id"] != service_request_id:
            return False
        if vendor_id is not None and e["vendor_id"] != vendor_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    items = list_sorted("engagements", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_engagement(e) for e in page], limit, offset, total, 200)


def compute_client_charge(billing_mode, markup_pct, lines):
    if billing_mode == "PASS_THROUGH":
        return sum(lines)
    total = 0
    factor = Decimal(1) + Decimal(str(markup_pct))
    for line in lines:
        total += round_half_up_cents(Decimal(line) * factor)
    return total


@app.route("/concierge/vendor-engagements/<id_>/confirm", methods=["POST"])
def confirm_engagement(id_):
    authorize({"ConciergeAgent"})
    e = get_or_404("engagements", id_)
    if e["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Engagement is not PROPOSED")
    vendor = DB["vendors"].get(e["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_INACTIVE", 409, "Vendor is not ACTIVE")
    # window conflict
    this_start = parse_dt(e["service_start"], "service_start")
    this_end = parse_dt(e["service_end"], "service_end")
    for other in DB["engagements"].values():
        if other["id"] == e["id"]:
            continue
        if other["vendor_id"] != e["vendor_id"]:
            continue
        if other["status"] not in {"CONFIRMED", "RECONCILED"}:
            continue
        os_ = parse_dt(other["service_start"], "service_start")
        oe = parse_dt(other["service_end"], "service_end")
        safe = (os_ - this_end > VENDOR_BUFFER) or (this_start - oe > VENDOR_BUFFER)
        if not safe:
            raise ApiError("ERR_VENDOR_WINDOW_CONFLICT", 409, "Vendor window conflict")
    e["status"] = "CONFIRMED"
    e["charge_basis"] = "PROVISIONAL"
    e["client_charge_cents"] = compute_client_charge(e["billing_mode"], e["markup_pct"], e["estimated_cost_lines"])
    touch(e)
    _bump_engagement_ledger(e)
    return respond_object(ser_engagement(e), 200)


def _bump_engagement_ledger(e):
    sr = DB["requests"].get(e["service_request_id"])
    if not sr:
        return
    ms = DB["memberships"].get(sr["membership_id"])
    if ms:
        touch(ms)
        member = DB["members"].get(ms["member_id"])
        if member:
            touch(member)


@app.route("/concierge/vendor-engagements/<id_>/reconcile", methods=["POST"])
def reconcile_engagement(id_):
    authorize({"FinanceOps"})
    e = get_or_404("engagements", id_)
    data = get_json()
    actual = data.get("actual_cost_lines")
    if not isinstance(actual, list) or len(actual) == 0 or any(not is_int(x) for x in actual):
        raise ApiError("ERR_INVALID_REQUEST", 400, "actual_cost_lines must be a non-empty array of integers")
    if e["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Engagement is not CONFIRMED")
    provisional = e["client_charge_cents"]
    final = compute_client_charge(e["billing_mode"], e["markup_pct"], actual)
    e["status"] = "RECONCILED"
    e["charge_basis"] = "FINAL"
    e["actual_cost_lines"] = actual
    e["client_charge_cents"] = final
    touch(e)
    # create expense
    sr = DB["requests"].get(e["service_request_id"])
    membership_id = sr["membership_id"] if sr else None
    x = base_entity()
    x.update({
        "vendor_engagement_id": e["id"],
        "membership_id": membership_id,
        "estimated_cents": provisional,
        "actual_cents": final,
        "variance_cents": final - provisional,
        "status": "RECONCILED",
    })
    DB["expenses"][x["id"]] = x
    _bump_engagement_ledger(e)
    return respond_object(ser_engagement(e), 200)


@app.route("/concierge/vendor-engagements/<id_>/void", methods=["POST"])
def void_engagement(id_):
    authorize({"ConciergeAgent"})
    e = get_or_404("engagements", id_)
    if e["status"] not in {"PROPOSED", "CONFIRMED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Engagement cannot be voided")
    was_confirmed = e["status"] == "CONFIRMED"
    e["status"] = "VOID"
    touch(e)
    if was_confirmed:
        _bump_engagement_ledger(e)
    return respond_object(ser_engagement(e), 200)


# =============================================================================
# Expense endpoints
# =============================================================================
@app.route("/concierge/expenses/<id_>", methods=["GET"])
def get_expense(id_):
    authorize(ROLES)
    x = get_or_404("expenses", id_)
    return respond_object(ser_expense(x), 200)


@app.route("/concierge/expenses", methods=["GET"])
def list_expenses():
    authorize(ROLES)
    limit, offset = parse_pagination()
    vendor_engagement_id = request.args.get("vendor_engagement_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")

    def pred(x):
        if vendor_engagement_id is not None and x["vendor_engagement_id"] != vendor_engagement_id:
            return False
        if membership_id is not None and x["membership_id"] != membership_id:
            return False
        if status is not None and x["status"] != status:
            return False
        return True

    items = list_sorted("expenses", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_expense(x) for x in page], limit, offset, total, 200)


@app.route("/concierge/expenses/<id_>/dispute", methods=["POST"])
def dispute_expense(id_):
    authorize({"FinanceOps"})
    x = get_or_404("expenses", id_)
    if x["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Expense is not RECONCILED")
    x["status"] = "DISPUTED"
    touch(x)
    return respond_object(ser_expense(x), 200)


@app.route("/concierge/expenses/<id_>/resolve", methods=["POST"])
def resolve_expense(id_):
    authorize({"FinanceOps"})
    x = get_or_404("expenses", id_)
    if x["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Expense is not DISPUTED")
    x["status"] = "RECONCILED"
    touch(x)
    return respond_object(ser_expense(x), 200)


# =============================================================================
# SatisfactionRating endpoints
# =============================================================================
@app.route("/concierge/satisfaction-ratings/<id_>", methods=["GET"])
def get_rating(id_):
    uid, role = authorize(ROLES)
    r = get_or_404("ratings", id_)
    require_owner(role, uid, DB["memberships"].get(r["membership_id"], {}).get("member_id"))
    return respond_object(ser_rating(r), 200)


@app.route("/concierge/satisfaction-ratings", methods=["GET"])
def list_ratings():
    authorize(ROLES)
    limit, offset = parse_pagination()
    service_request_id = request.args.get("service_request_id")
    membership_id = request.args.get("membership_id")

    def pred(r):
        if service_request_id is not None and r["service_request_id"] != service_request_id:
            return False
        if membership_id is not None and r["membership_id"] != membership_id:
            return False
        return True

    items = list_sorted("ratings", pred)
    page, total = paginate(items, limit, offset)
    return respond_array([ser_rating(r) for r in page], limit, offset, total, 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
