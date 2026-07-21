"""Quilt Shop & Longarm Service API — Python + Flask, in-memory store.

Boots empty on every start (per-test-server isolation). No seeding.
"""
import os
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Member", "Clerk", "Manager"}

LONGARM_TIER_RATES = {
    "EDGE_TO_EDGE": Decimal("0.02"),
    "CUSTOM": Decimal("0.035"),
    "HEIRLOOM": Decimal("0.05"),
}
LARGE_AREA_THRESHOLD = Decimal("7500")
LARGE_SURCHARGE = Decimal("1.1")
BATTING_FEE = Decimal("25")
THREAD_FEE = Decimal("12")
RUSH_MULTIPLIER = Decimal("1.25")
MIN_CHARGE = Decimal("30")

SPECIAL_ORDER_MARKUP = Decimal("1.5")
KIT_MARKUP = Decimal("1.4")

POINTS_PER_DOLLAR = Decimal("10")
SILVER_THRESHOLD = 1000
GOLD_THRESHOLD = 5000

SETUP_BUFFER = timedelta(minutes=30)

PATTERN_TIERS = {"EDGE_TO_EDGE", "CUSTOM", "HEIRLOOM"}
KIT_TYPES = {"KIT", "BOM", "BLOCK_OF_MONTH"}
EVENT_TYPES = {"CLASS", "RETREAT"}
MACHINE_STATUSES = {"AVAILABLE", "MAINTENANCE"}

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
DB = {
    "members": {},
    "bolts": {},
    "cuts": {},
    "kits": {},
    "machines": {},
    "jobs": {},
    "classes": {},
    "enrollments": {},
    "special_orders": {},
    "loyalty": {},
}
_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def gen_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def make_meta(pagination=None):
    meta = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, response_type="object", pagination=None):
    return jsonify({
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        err("ERR_VALIDATION", 422, "Invalid JSON body")
    if not isinstance(body, dict):
        err("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def to_decimal(v):
    return Decimal(str(v))


def req_str(body, key):
    if key not in body or body[key] is None:
        err("ERR_VALIDATION", 422, f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 422, f"Field {key} must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, f"Field {key} must be a string")
    return v


def req_number(body, key):
    if key not in body or body[key] is None:
        err("ERR_VALIDATION", 422, f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 422, f"Field {key} must be a number")
    return to_decimal(v)


def req_positive_number(body, key):
    d = req_number(body, key)
    if d <= 0:
        err("ERR_NON_POSITIVE_AMOUNT", 422, f"Field {key} must be greater than zero")
    return d


def opt_number(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 422, f"Field {key} must be a number")
    return to_decimal(v)


def req_positive_int(body, key):
    if key not in body or body[key] is None:
        err("ERR_VALIDATION", 422, f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 422, f"Field {key} must be an integer")
    if v <= 0:
        err("ERR_NON_POSITIVE_AMOUNT", 422, f"Field {key} must be greater than zero")
    return v


def req_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, f"Field {key} must be a boolean")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        err("ERR_VALIDATION", 422, f"Field {key} has an invalid value")
    return v


def money(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def points_from(price):
    return int((price * POINTS_PER_DOLLAR).to_integral_value(rounding=ROUND_FLOOR))


def num(d):
    if d is None:
        return None
    if isinstance(d, Decimal):
        return float(d)
    return d


def parse_dt(body, key):
    if key not in body or body[key] is None:
        err("ERR_VALIDATION", 422, f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, f"Field {key} must be an ISO 8601 datetime string")
    s = v.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        err("ERR_VALIDATION", 422, f"Field {key} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_stored_dt(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_member(mid):
    m = DB["members"].get(mid)
    if m is None:
        err("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    return m


def get_bolt(bid):
    b = DB["bolts"].get(bid)
    if b is None:
        err("ERR_BOLT_NOT_FOUND", 404, "Fabric bolt not found")
    return b


def get_cut(cid):
    c = DB["cuts"].get(cid)
    if c is None:
        err("ERR_CUT_NOT_FOUND", 404, "Fabric cut not found")
    return c


def get_kit(kid):
    k = DB["kits"].get(kid)
    if k is None:
        err("ERR_KIT_NOT_FOUND", 404, "Kit not found")
    return k


def get_machine(mid):
    m = DB["machines"].get(mid)
    if m is None:
        err("ERR_MACHINE_NOT_FOUND", 404, "Longarm machine not found")
    return m


def get_job(jid):
    j = DB["jobs"].get(jid)
    if j is None:
        err("ERR_JOB_NOT_FOUND", 404, "Longarm job not found")
    return j


def get_class(cid):
    c = DB["classes"].get(cid)
    if c is None:
        err("ERR_CLASS_NOT_FOUND", 404, "Class event not found")
    return c


def get_enrollment(eid):
    e = DB["enrollments"].get(eid)
    if e is None:
        err("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    return e


def get_order(oid):
    o = DB["special_orders"].get(oid)
    if o is None:
        err("ERR_SPECIAL_ORDER_NOT_FOUND", 404, "Special order not found")
    return o


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def recompute_bolt(bolt):
    used = Decimal("0")
    for c in DB["cuts"].values():
        if c["bolt_id"] == bolt["id"] and c["status"] == "CUT":
            used += c["yards_requested"]
    remaining = bolt["original_yards"] - used
    bolt["yards_remaining"] = remaining
    if bolt["status"] != "DISCONTINUED":
        if remaining <= 0:
            bolt["status"] = "DEPLETED"
        elif remaining <= bolt["reorder_threshold"]:
            bolt["status"] = "LOW_STOCK"
        else:
            bolt["status"] = "IN_STOCK"


def recompute_member(member):
    total = 0
    for lt in DB["loyalty"].values():
        if lt["member_id"] == member["id"]:
            total += lt["points"]
    member["points_balance"] = total
    if total < SILVER_THRESHOLD:
        member["loyalty_tier"] = "BRONZE"
    elif total < GOLD_THRESHOLD:
        member["loyalty_tier"] = "SILVER"
    else:
        member["loyalty_tier"] = "GOLD"


def add_loyalty(member, points, reason, source_type, source_id):
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "member_id": member["id"],
        "points": points,
        "reason": reason,
        "source_type": source_type,
        "source_id": source_id,
    }
    DB["loyalty"][rec["id"]] = rec
    return rec


def recompute_class_seats(cls):
    count = 0
    for e in DB["enrollments"].values():
        if e["class_event_id"] == cls["id"] and e["status"] == "CONFIRMED":
            count += 1
    cls["seats_taken"] = count


def longarm_price(width, length, tier, batting, thread, rush):
    area = width * length
    rate = LONGARM_TIER_RATES[tier]
    base = area * rate
    if area > LARGE_AREA_THRESHOLD:
        base = base * LARGE_SURCHARGE
    subtotal = base
    if batting:
        subtotal = subtotal + BATTING_FEE
    if thread:
        subtotal = subtotal + THREAD_FEE
    if rush:
        subtotal = subtotal * RUSH_MULTIPLIER
    price = subtotal if subtotal > MIN_CHARGE else MIN_CHARGE
    return money(price)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_member(m):
    return {
        "id": m["id"], "name": m["name"], "email": m["email"], "phone": m["phone"],
        "points_balance": m["points_balance"], "loyalty_tier": m["loyalty_tier"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def ser_bolt(b):
    return {
        "id": b["id"], "sku": b["sku"], "color": b["color"],
        "price_per_yard": num(b["price_per_yard"]), "original_yards": num(b["original_yards"]),
        "yards_remaining": num(b["yards_remaining"]), "reorder_threshold": num(b["reorder_threshold"]),
        "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
    }


def ser_cut(c):
    return {
        "id": c["id"], "bolt_id": c["bolt_id"], "member_id": c["member_id"],
        "yards_requested": num(c["yards_requested"]), "line_price": num(c["line_price"]),
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_kit(k):
    return {
        "id": k["id"], "name": k["name"], "kit_type": k["kit_type"],
        "components": k["components"], "materials_cost": num(k["materials_cost"]),
        "kit_price": num(k["kit_price"]), "status": k["status"],
        "created_at": k["created_at"], "updated_at": k["updated_at"], "version": k["version"],
    }


def ser_machine(m):
    return {
        "id": m["id"], "name": m["name"], "model": m["model"], "status": m["status"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


def ser_job(j):
    return {
        "id": j["id"], "member_id": j["member_id"], "machine_id": j["machine_id"],
        "quoted_width_in": num(j["quoted_width_in"]), "quoted_length_in": num(j["quoted_length_in"]),
        "pattern_tier": j["pattern_tier"], "batting_addon": j["batting_addon"],
        "thread_addon": j["thread_addon"], "rush": j["rush"],
        "measured_width_in": num(j["measured_width_in"]), "measured_length_in": num(j["measured_length_in"]),
        "scheduled_start": j["scheduled_start"], "scheduled_end": j["scheduled_end"],
        "estimated_price": num(j["estimated_price"]), "final_price": num(j["final_price"]),
        "status": j["status"],
        "created_at": j["created_at"], "updated_at": j["updated_at"], "version": j["version"],
    }


def ser_class(c):
    return {
        "id": c["id"], "title": c["title"], "event_type": c["event_type"],
        "instructor": c["instructor"], "start_time": c["start_time"], "end_time": c["end_time"],
        "capacity": c["capacity"], "fee": num(c["fee"]), "seats_taken": c["seats_taken"],
        "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"], "class_event_id": e["class_event_id"], "member_id": e["member_id"],
        "points_earned": e["points_earned"], "status": e["status"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def ser_order(o):
    return {
        "id": o["id"], "member_id": o["member_id"], "description": o["description"],
        "quantity": o["quantity"], "est_unit_cost": num(o["est_unit_cost"]),
        "quoted_price": num(o["quoted_price"]), "actual_unit_cost": num(o["actual_unit_cost"]),
        "shipping_cost": num(o["shipping_cost"]), "final_total": num(o["final_total"]),
        "status": o["status"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def ser_loyalty(lt):
    return {
        "id": lt["id"], "member_id": lt["member_id"], "points": lt["points"],
        "reason": lt["reason"], "source_type": lt["source_type"], "source_id": lt["source_id"],
        "created_at": lt["created_at"],
    }


# ---------------------------------------------------------------------------
# Pagination / list helpers
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def paginate_list(items, serializer):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda x: x["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok([serializer(x) for x in page], response_type="array", pagination=pagination)


# ===========================================================================
# Member endpoints
# ===========================================================================
@app.route("/api/members", methods=["POST"])
def create_member():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    phone = opt_str(body, "phone", None)
    for m in DB["members"].values():
        if m["email"] == email:
            err("ERR_VALIDATION", 422, "Email already in use")
    rec = new_common()
    rec.update({"name": name, "email": email, "phone": phone,
                "points_balance": 0, "loyalty_tier": "BRONZE"})
    DB["members"][rec["id"]] = rec
    return ok(ser_member(rec), 201)


@app.route("/api/members/<mid>", methods=["GET"])
def get_member_ep(mid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_member(get_member(mid)))


@app.route("/api/members/<mid>/loyalty-transactions", methods=["GET"])
def list_loyalty(mid):
    uid, role = authenticate()
    authorize(role, ROLES)
    get_member(mid)
    items = [lt for lt in DB["loyalty"].values() if lt["member_id"] == mid]
    return paginate_list(items, ser_loyalty)


# ===========================================================================
# FabricBolt endpoints
# ===========================================================================
@app.route("/api/fabric-bolts", methods=["POST"])
def create_bolt():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    sku = req_str(body, "sku")
    color = req_str(body, "color")
    price = req_number(body, "price_per_yard")
    original = req_number(body, "original_yards")
    threshold = opt_number(body, "reorder_threshold", Decimal("5"))
    rec = new_common()
    rec.update({"sku": sku, "color": color, "price_per_yard": price,
                "original_yards": original, "reorder_threshold": threshold,
                "yards_remaining": original, "status": "IN_STOCK"})
    DB["bolts"][rec["id"]] = rec
    recompute_bolt(rec)
    return ok(ser_bolt(rec), 201)


@app.route("/api/fabric-bolts/<bid>", methods=["GET"])
def get_bolt_ep(bid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_bolt(get_bolt(bid)))


@app.route("/api/fabric-bolts/<bid>/restock", methods=["POST"])
def restock_bolt(bid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    bolt = get_bolt(bid)
    body = get_body()
    added = req_number(body, "added_yards")
    bolt["original_yards"] = bolt["original_yards"] + added
    recompute_bolt(bolt)
    touch(bolt)
    return ok(ser_bolt(bolt))


@app.route("/api/fabric-bolts/<bid>/discontinue", methods=["POST"])
def discontinue_bolt(bid):
    uid, role = authenticate()
    authorize(role, {"Manager"})
    bolt = get_bolt(bid)
    if bolt["status"] == "DISCONTINUED":
        err("ERR_BOLT_DISCONTINUED", 409, "Bolt already discontinued")
    bolt["status"] = "DISCONTINUED"
    touch(bolt)
    for kit in DB["kits"].values():
        if any(comp.get("bolt_id") == bid for comp in kit["components"]):
            kit["status"] = "UNAVAILABLE"
            touch(kit)
    return ok(ser_bolt(bolt))


# ===========================================================================
# FabricCut endpoints
# ===========================================================================
@app.route("/api/fabric-cuts", methods=["POST"])
def create_cut():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    # Existence (left-to-right: bolt_id, member_id)
    bolt = None
    if "bolt_id" in body and body["bolt_id"] is not None:
        bolt = get_bolt(body["bolt_id"])
    member = None
    if "member_id" in body and body["member_id"] is not None:
        member = get_member(body["member_id"])
    # State precondition
    if bolt is not None and bolt["status"] == "DISCONTINUED":
        err("ERR_BOLT_DISCONTINUED", 409, "Cannot cut from a discontinued bolt")
    # Field-shape
    if bolt is None:
        err("ERR_VALIDATION", 422, "Missing required field: bolt_id")
    yards = req_positive_number(body, "yards_requested")
    # Quota
    if yards > bolt["yards_remaining"]:
        err("ERR_INSUFFICIENT_YARDAGE", 409, "Not enough yardage remaining")
    line_price = money(yards * bolt["price_per_yard"])
    rec = new_common()
    rec.update({"bolt_id": bolt["id"],
                "member_id": member["id"] if member else None,
                "yards_requested": yards, "line_price": line_price, "status": "CUT"})
    DB["cuts"][rec["id"]] = rec
    recompute_bolt(bolt)
    touch(bolt)
    return ok(ser_cut(rec), 201)


@app.route("/api/fabric-cuts", methods=["GET"])
def list_cuts():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(DB["cuts"].values())
    bolt_id = request.args.get("bolt_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if bolt_id is not None:
        items = [c for c in items if c["bolt_id"] == bolt_id]
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate_list(items, ser_cut)


@app.route("/api/fabric-cuts/<cid>", methods=["GET"])
def get_cut_ep(cid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_cut(get_cut(cid)))


@app.route("/api/fabric-cuts/<cid>/void", methods=["POST"])
def void_cut(cid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    cut = get_cut(cid)
    if cut["status"] != "CUT":
        err("ERR_CUT_NOT_VOIDABLE", 409, "Cut is not voidable")
    cut["status"] = "VOIDED"
    touch(cut)
    bolt = DB["bolts"].get(cut["bolt_id"])
    if bolt is not None:
        recompute_bolt(bolt)
        touch(bolt)
    return ok(ser_cut(cut))


# ===========================================================================
# Kit endpoints
# ===========================================================================
@app.route("/api/kits", methods=["POST"])
def create_kit():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    name = req_str(body, "name")
    kit_type = req_enum(body, "kit_type", KIT_TYPES)
    if "components" not in body or body["components"] is None:
        err("ERR_VALIDATION", 422, "Missing required field: components")
    components = body["components"]
    if not isinstance(components, list) or len(components) == 0:
        err("ERR_VALIDATION", 422, "components must be a non-empty list")
    # Existence pass (priority 3): validate referenced bolts before field shape
    for comp in components:
        if not isinstance(comp, dict):
            err("ERR_VALIDATION", 422, "Each component must be an object")
        bid = comp.get("bolt_id")
        if bid is not None:
            get_bolt(bid)
    # Field-shape pass + materials cost
    materials_cost = Decimal("0")
    any_discontinued = False
    for comp in components:
        bid = comp.get("bolt_id")
        if bid is None:
            err("ERR_VALIDATION", 422, "component missing bolt_id")
        bolt = get_bolt(bid)
        ypk = comp.get("yards_per_kit")
        qty = comp.get("quantity")
        if isinstance(ypk, bool) or not isinstance(ypk, (int, float)):
            err("ERR_VALIDATION", 422, "component yards_per_kit must be a number")
        if isinstance(qty, bool) or not isinstance(qty, int):
            err("ERR_VALIDATION", 422, "component quantity must be an integer")
        line = money(to_decimal(ypk) * bolt["price_per_yard"])
        materials_cost += line * qty
        if bolt["status"] == "DISCONTINUED":
            any_discontinued = True
    kit_price = money(materials_cost * KIT_MARKUP)
    rec = new_common()
    rec.update({"name": name, "kit_type": kit_type, "components": components,
                "materials_cost": materials_cost, "kit_price": kit_price,
                "status": "UNAVAILABLE" if any_discontinued else "AVAILABLE"})
    DB["kits"][rec["id"]] = rec
    return ok(ser_kit(rec), 201)


@app.route("/api/kits/<kid>", methods=["GET"])
def get_kit_ep(kid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_kit(get_kit(kid)))


# ===========================================================================
# LongarmMachine endpoints
# ===========================================================================
@app.route("/api/longarm-machines", methods=["POST"])
def create_machine():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    name = req_str(body, "name")
    model = req_str(body, "model")
    status = "AVAILABLE"
    if "status" in body and body["status"] is not None:
        status = req_enum(body, "status", MACHINE_STATUSES)
    rec = new_common()
    rec.update({"name": name, "model": model, "status": status})
    DB["machines"][rec["id"]] = rec
    return ok(ser_machine(rec), 201)


@app.route("/api/longarm-machines/<mid>", methods=["GET"])
def get_machine_ep(mid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_machine(get_machine(mid)))


# ===========================================================================
# LongarmJob endpoints
# ===========================================================================
@app.route("/api/longarm-jobs", methods=["POST"])
def create_job():
    uid, role = authenticate()
    authorize(role, ROLES)
    body = get_body()
    # Existence
    member = None
    if "member_id" in body and body["member_id"] is not None:
        member = get_member(body["member_id"])
    # Ownership
    if role == "Member" and member is not None and member["id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Member may only act on own resources")
    # Field-shape
    if member is None:
        err("ERR_VALIDATION", 422, "Missing required field: member_id")
    width = req_number(body, "quoted_width_in")
    length = req_number(body, "quoted_length_in")
    tier = req_enum(body, "pattern_tier", PATTERN_TIERS)
    batting = req_bool(body, "batting_addon", False)
    thread = req_bool(body, "thread_addon", False)
    rush = req_bool(body, "rush", False)
    estimated = longarm_price(width, length, tier, batting, thread, rush)
    rec = new_common()
    rec.update({"member_id": member["id"], "machine_id": None,
                "quoted_width_in": width, "quoted_length_in": length,
                "pattern_tier": tier, "batting_addon": batting,
                "thread_addon": thread, "rush": rush,
                "measured_width_in": None, "measured_length_in": None,
                "scheduled_start": None, "scheduled_end": None,
                "estimated_price": estimated, "final_price": None, "status": "QUEUED"})
    DB["jobs"][rec["id"]] = rec
    return ok(ser_job(rec), 201)


@app.route("/api/longarm-jobs", methods=["GET"])
def list_jobs():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(DB["jobs"].values())
    member_id = request.args.get("member_id")
    machine_id = request.args.get("machine_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [j for j in items if j["member_id"] == member_id]
    if machine_id is not None:
        items = [j for j in items if j["machine_id"] == machine_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    return paginate_list(items, ser_job)


@app.route("/api/longarm-jobs/<jid>", methods=["GET"])
def get_job_ep(jid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_job(get_job(jid)))


@app.route("/api/longarm-jobs/<jid>/start", methods=["POST"])
def start_job(jid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    job = get_job(jid)
    body = get_body()
    # Existence: machine_id (body)
    machine = None
    if "machine_id" in body and body["machine_id"] is not None:
        machine = get_machine(body["machine_id"])
    # State: job QUEUED, then machine AVAILABLE
    if job["status"] != "QUEUED":
        err("ERR_JOB_NOT_QUEUED", 409, "Job is not queued")
    if machine is not None and machine["status"] != "AVAILABLE":
        err("ERR_MACHINE_UNAVAILABLE", 409, "Machine is not available")
    # Field-shape
    if machine is None:
        err("ERR_VALIDATION", 422, "Missing required field: machine_id")
    start = parse_dt(body, "scheduled_start")
    end = parse_dt(body, "scheduled_end")
    # Temporal
    if end <= start:
        err("ERR_INVALID_TIME_WINDOW", 409, "scheduled_end must be after scheduled_start")
    for other in DB["jobs"].values():
        if other["id"] == job["id"]:
            continue
        if other["machine_id"] != machine["id"]:
            continue
        if other["status"] not in ("IN_PROGRESS", "COMPLETED"):
            continue
        if other["scheduled_start"] is None or other["scheduled_end"] is None:
            continue
        os_ = parse_stored_dt(other["scheduled_start"])
        oe = parse_stored_dt(other["scheduled_end"])
        # Overlap?
        if start < oe and os_ < end:
            err("ERR_MACHINE_SCHEDULE_CONFLICT", 409, "Slot overlaps another job")
        # Gap check (< 30 min -> conflict)
        if start >= oe:
            gap = start - oe
        else:
            gap = os_ - end
        if gap < SETUP_BUFFER:
            err("ERR_MACHINE_SCHEDULE_CONFLICT", 409, "Slot within setup buffer of another job")
    job["machine_id"] = machine["id"]
    job["scheduled_start"] = body["scheduled_start"]
    job["scheduled_end"] = body["scheduled_end"]
    job["status"] = "IN_PROGRESS"
    touch(job)
    return ok(ser_job(job))


@app.route("/api/longarm-jobs/<jid>/complete", methods=["POST"])
def complete_job(jid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    job = get_job(jid)
    body = get_body()
    if job["status"] != "IN_PROGRESS":
        err("ERR_JOB_NOT_IN_PROGRESS", 409, "Job is not in progress")
    width = req_positive_number(body, "measured_width_in")
    length = req_positive_number(body, "measured_length_in")
    final = longarm_price(width, length, job["pattern_tier"],
                          job["batting_addon"], job["thread_addon"], job["rush"])
    job["measured_width_in"] = width
    job["measured_length_in"] = length
    job["final_price"] = final
    job["status"] = "COMPLETED"
    touch(job)
    member = DB["members"].get(job["member_id"])
    if member is not None:
        add_loyalty(member, points_from(final), "LONGARM_COMPLETE", "LongarmJob", job["id"])
        recompute_member(member)
        touch(member)
    return ok(ser_job(job))


# ===========================================================================
# ClassEvent endpoints
# ===========================================================================
@app.route("/api/classes", methods=["POST"])
def create_class():
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    body = get_body()
    title = req_str(body, "title")
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    instructor = req_str(body, "instructor")
    # Field-shape (capacity > 0) precedes temporal
    capacity = req_positive_int(body, "capacity")
    fee = req_number(body, "fee")
    start = parse_dt(body, "start_time")
    end = parse_dt(body, "end_time")
    if end <= start:
        err("ERR_INVALID_TIME_WINDOW", 409, "end_time must be after start_time")
    rec = new_common()
    rec.update({"title": title, "event_type": event_type, "instructor": instructor,
                "start_time": body["start_time"], "end_time": body["end_time"],
                "capacity": capacity, "fee": fee, "seats_taken": 0, "status": "OPEN"})
    DB["classes"][rec["id"]] = rec
    return ok(ser_class(rec), 201)


@app.route("/api/classes/<cid>", methods=["GET"])
def get_class_ep(cid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_class(get_class(cid)))


@app.route("/api/classes/<cid>/cancel", methods=["POST"])
def cancel_class(cid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    cls = get_class(cid)
    if cls["status"] not in ("OPEN", "FULL"):
        err("ERR_CLASS_NOT_OPEN", 409, "Class is not open")
    cls["status"] = "CANCELLED"
    touch(cls)
    for enr in DB["enrollments"].values():
        if enr["class_event_id"] == cls["id"] and enr["status"] == "CONFIRMED":
            enr["status"] = "CANCELLED"
            touch(enr)
            member = DB["members"].get(enr["member_id"])
            if member is not None:
                add_loyalty(member, -enr["points_earned"], "ENROLLMENT_CANCEL_REVERSAL",
                            "Enrollment", enr["id"])
                recompute_member(member)
                touch(member)
    recompute_class_seats(cls)
    return ok(ser_class(cls))


# ===========================================================================
# Enrollment endpoints
# ===========================================================================
@app.route("/api/enrollments", methods=["POST"])
def create_enrollment():
    uid, role = authenticate()
    authorize(role, ROLES)
    body = get_body()
    # Existence (left-to-right: class_event_id, member_id)
    cls = None
    if "class_event_id" in body and body["class_event_id"] is not None:
        cls = get_class(body["class_event_id"])
    member = None
    if "member_id" in body and body["member_id"] is not None:
        member = get_member(body["member_id"])
    # Ownership
    if role == "Member" and member is not None and member["id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Member may only enroll themselves")
    # State: class in {OPEN, FULL}
    if cls is not None and cls["status"] not in ("OPEN", "FULL"):
        err("ERR_CLASS_NOT_OPEN", 409, "Class is not open for enrollment")
    # Field-shape presence
    if cls is None:
        err("ERR_VALIDATION", 422, "Missing required field: class_event_id")
    if member is None:
        err("ERR_VALIDATION", 422, "Missing required field: member_id")
    # Temporal: member schedule conflict with other confirmed enrollments
    cls_start = parse_stored_dt(cls["start_time"])
    cls_end = parse_stored_dt(cls["end_time"])
    for enr in DB["enrollments"].values():
        if enr["member_id"] != member["id"] or enr["status"] != "CONFIRMED":
            continue
        if enr["class_event_id"] == cls["id"]:
            continue  # same class handled by duplicate check
        other = DB["classes"].get(enr["class_event_id"])
        if other is None:
            continue
        o_start = parse_stored_dt(other["start_time"])
        o_end = parse_stored_dt(other["end_time"])
        if cls_start < o_end and o_start < cls_end:
            err("ERR_MEMBER_SCHEDULE_CONFLICT", 409, "Overlaps another enrollment")
    # Duplicate enrollment
    for enr in DB["enrollments"].values():
        if (enr["member_id"] == member["id"] and enr["class_event_id"] == cls["id"]
                and enr["status"] == "CONFIRMED"):
            err("ERR_DUPLICATE_ENROLLMENT", 409, "Already enrolled in this class")
    # Capacity
    if cls["seats_taken"] >= cls["capacity"]:
        err("ERR_CLASS_FULL", 409, "Class is full")
    points_earned = points_from(cls["fee"])
    rec = new_common()
    rec.update({"class_event_id": cls["id"], "member_id": member["id"],
                "points_earned": points_earned, "status": "CONFIRMED"})
    DB["enrollments"][rec["id"]] = rec
    add_loyalty(member, points_earned, "ENROLLMENT_CONFIRM", "Enrollment", rec["id"])
    recompute_member(member)
    touch(member)
    recompute_class_seats(cls)
    if cls["seats_taken"] >= cls["capacity"]:
        cls["status"] = "FULL"
    touch(cls)
    return ok(ser_enrollment(rec), 201)


@app.route("/api/enrollments", methods=["GET"])
def list_enrollments():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(DB["enrollments"].values())
    member_id = request.args.get("member_id")
    class_event_id = request.args.get("class_event_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if class_event_id is not None:
        items = [e for e in items if e["class_event_id"] == class_event_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate_list(items, ser_enrollment)


@app.route("/api/enrollments/<eid>", methods=["GET"])
def get_enrollment_ep(eid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_enrollment(get_enrollment(eid)))


@app.route("/api/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    uid, role = authenticate()
    authorize(role, ROLES)
    enr = get_enrollment(eid)
    # Ownership
    if role == "Member" and enr["member_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Member may only cancel own enrollment")
    # State
    if enr["status"] != "CONFIRMED":
        err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not active")
    enr["status"] = "CANCELLED"
    touch(enr)
    member = DB["members"].get(enr["member_id"])
    if member is not None:
        add_loyalty(member, -enr["points_earned"], "ENROLLMENT_CANCEL_REVERSAL",
                    "Enrollment", enr["id"])
        recompute_member(member)
        touch(member)
    cls = DB["classes"].get(enr["class_event_id"])
    if cls is not None:
        recompute_class_seats(cls)
        if cls["status"] == "FULL" and cls["seats_taken"] < cls["capacity"]:
            cls["status"] = "OPEN"
        touch(cls)
    return ok(ser_enrollment(enr))


# ===========================================================================
# SpecialOrder endpoints
# ===========================================================================
@app.route("/api/special-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, ROLES)
    body = get_body()
    # Existence
    member = None
    if "member_id" in body and body["member_id"] is not None:
        member = get_member(body["member_id"])
    # Ownership
    if role == "Member" and member is not None and member["id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Member may only act on own resources")
    # Field-shape
    if member is None:
        err("ERR_VALIDATION", 422, "Missing required field: member_id")
    description = req_str(body, "description")
    quantity = req_positive_int(body, "quantity")
    est_unit_cost = req_positive_number(body, "est_unit_cost")
    quoted_price = money(est_unit_cost * quantity * SPECIAL_ORDER_MARKUP)
    rec = new_common()
    rec.update({"member_id": member["id"], "description": description,
                "quantity": quantity, "est_unit_cost": est_unit_cost,
                "quoted_price": quoted_price, "actual_unit_cost": None,
                "shipping_cost": Decimal("0"), "final_total": None, "status": "QUOTED"})
    DB["special_orders"][rec["id"]] = rec
    return ok(ser_order(rec), 201)


@app.route("/api/special-orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    authorize(role, ROLES)
    items = list(DB["special_orders"].values())
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate_list(items, ser_order)


@app.route("/api/special-orders/<oid>", methods=["GET"])
def get_order_ep(oid):
    uid, role = authenticate()
    authorize(role, ROLES)
    return ok(ser_order(get_order(oid)))


@app.route("/api/special-orders/<oid>/revise-quote", methods=["POST"])
def revise_order(oid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    order = get_order(oid)
    body = get_body()
    # State
    if order["status"] != "QUOTED":
        err("ERR_SPECIAL_ORDER_NOT_QUOTED", 409, "Order is not in QUOTED state")
    # Field-shape
    quantity = req_positive_int(body, "quantity")
    est_unit_cost = req_positive_number(body, "est_unit_cost")
    if "expected_special_order_version" not in body or body["expected_special_order_version"] is None:
        err("ERR_VALIDATION", 422, "Missing required field: expected_special_order_version")
    expected = body["expected_special_order_version"]
    # OCC (last check)
    if expected != order["version"]:
        err("ERR_STALE_VERSION", 412, "expected_special_order_version does not match")
    order["est_unit_cost"] = est_unit_cost
    order["quantity"] = quantity
    order["quoted_price"] = money(est_unit_cost * quantity * SPECIAL_ORDER_MARKUP)
    touch(order)
    return ok(ser_order(order))


@app.route("/api/special-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    uid, role = authenticate()
    authorize(role, {"Clerk", "Manager"})
    order = get_order(oid)
    body = get_body()
    if order["status"] != "QUOTED":
        err("ERR_SPECIAL_ORDER_NOT_QUOTED", 409, "Order is not in QUOTED state")
    actual_unit_cost = req_positive_number(body, "actual_unit_cost")
    shipping_cost = opt_number(body, "shipping_cost", Decimal("0"))
    final_total = money(actual_unit_cost * order["quantity"] * SPECIAL_ORDER_MARKUP + shipping_cost)
    order["actual_unit_cost"] = actual_unit_cost
    order["shipping_cost"] = shipping_cost
    order["final_total"] = final_total
    order["status"] = "FULFILLED"
    touch(order)
    member = DB["members"].get(order["member_id"])
    if member is not None:
        add_loyalty(member, points_from(final_total), "SPECIAL_ORDER_FULFILL",
                    "SpecialOrder", order["id"])
        recompute_member(member)
        touch(member)
    return ok(ser_order(order))


# ===========================================================================
# Health
# ===========================================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
