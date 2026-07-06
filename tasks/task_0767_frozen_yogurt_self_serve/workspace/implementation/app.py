import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_TICKET_CHARGE_CENTS = 100
POINTS_DIVISOR = 100
TOPPING_UNIT_COST_CENTS = 12
CATERING_DEPOSIT_PCT = Decimal("0.25")
PUNCH_THRESHOLD = 10
VOUCHER_VALUE_CENTS = 500
VOUCHER_TTL_HOURS = 720
# Not pinned to a numeric value in the scaffold/PRD (expressed by name with
# comparison semantics). Sensible operational defaults chosen here.
CLEAN_INTERVAL_HOURS = 4
MAINTENANCE_BUFFER_MINUTES = 60

ROLES = {"Cashier": 1, "ShiftLead": 2, "Manager": 3}
ALLERGENS = {"DAIRY", "NUTS", "SOY", "GLUTEN", "EGG"}
WASTE_REASONS = {"MELT", "SPILL", "EXPIRY", "MACHINE_FAULT"}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now_dt():
    return _clock["now"]


def fmt(dt):
    # ISO 8601 UTC with three fractional digits and 'Z'
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_str():
    return fmt(now_dt())


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store (empty on every boot)
# ---------------------------------------------------------------------------
DB = {
    "machines": {},
    "flavors": {},
    "toppings": {},
    "promotions": {},
    "loyalty_accounts": {},
    "vouchers": {},
    "tickets": {},
    "lines": {},
    "waste_events": {},
    "sanitation_logs": {},
    "windows": {},
    "resources": {},
    "catering_orders": {},
    "reconciliations": {},
}


def new_id():
    return str(uuid.uuid4())


def touch(e):
    e["updated_at"] = now_str()
    e["version"] = e["version"] + 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": now_str()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    resp = jsonify(body)
    resp.status_code = 405
    return resp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(min_level):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if ROLES[role] < min_level:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")
    return role


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool))


def req_str(b, key):
    if key not in b or not isinstance(b[key], str):
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid field: {key}")
    return b[key]


def req_int(b, key):
    if key not in b or not is_int(b[key]):
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid field: {key}")
    return b[key]


def req_num(b, key):
    if key not in b or not is_num(b[key]):
        raise ApiError("ERR_VALIDATION", 400, f"Missing or invalid field: {key}")
    return b[key]


def opt_num(b, key, default):
    if key not in b or b[key] is None:
        return default
    if not is_num(b[key]):
        raise ApiError("ERR_VALIDATION", 400, f"Invalid field: {key}")
    return b[key]


def opt_int(b, key, default):
    if key not in b or b[key] is None:
        return default
    if not is_int(b[key]):
        raise ApiError("ERR_VALIDATION", 400, f"Invalid field: {key}")
    return b[key]


def opt_str(b, key, default):
    if key not in b or b[key] is None:
        return default
    if not isinstance(b[key], str):
        raise ApiError("ERR_VALIDATION", 400, f"Invalid field: {key}")
    return b[key]


def opt_array(b, key, default):
    if key not in b or b[key] is None:
        return list(default)
    if not isinstance(b[key], list):
        raise ApiError("ERR_VALIDATION", 400, f"Invalid field: {key}")
    return b[key]


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(d):
    return int(D(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def get_or_404(store_key, rid, err_id):
    e = DB[store_key].get(rid)
    if e is None:
        raise ApiError(err_id, 404, f"{err_id}")
    return e


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def pagination_params():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid offset")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items):
    # items: already-filtered list of raw entities
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset: offset + limit]
    data = [serialize(e) for e in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok(data, 200, "array", pagination)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def active_discount(clock_dt):
    for p in DB["promotions"].values():
        s = parse_dt(p["starts_at"])
        e = parse_dt(p["ends_at"])
        if s <= clock_dt < e:
            return D(p["discount_pct"])
    return Decimal(0)


def evaluate_sanitation(machine):
    """If overdue and READY -> OUT_OF_SERVICE, cascade LOADED flavors -> SUSPENDED."""
    if machine["sanitation_status"] != "READY":
        return
    last = parse_dt(machine["last_cleaned_at"])
    if now_dt() >= last + timedelta(hours=CLEAN_INTERVAL_HOURS):
        machine["sanitation_status"] = "OUT_OF_SERVICE"
        touch(machine)
        for f in DB["flavors"].values():
            if f["machine_id"] == machine["id"] and f["status"] == "LOADED":
                f["status"] = "SUSPENDED"
                touch(f)


def ticket_lines(ticket_id):
    return sorted(
        [ln for ln in DB["lines"].values() if ln["ticket_id"] == ticket_id],
        key=lambda ln: ln["created_at"],
    )


def compute_finalized(ticket, clock_dt):
    lines = ticket_lines(ticket["id"])
    subtotal_base = 0
    for ln in lines:
        flavor = DB["flavors"].get(ln["flavor_id"])
        price = flavor["price_per_oz_cents"] if flavor else 0
        surch = 0
        for tid in ln["topping_ids"]:
            t = DB["toppings"].get(tid)
            if t:
                surch += t["surcharge_cents"]
        line_base = rhu(D(ln["net_weight_oz"]) * D(price)) + surch
        subtotal_base += line_base
    disc = active_discount(clock_dt)
    discounted = rhu(D(subtotal_base) * (Decimal(1) - disc))
    pre_voucher = max(MIN_TICKET_CHARGE_CENTS, discounted)
    if ticket["redeemed_voucher_id"]:
        final = max(MIN_TICKET_CHARGE_CENTS, pre_voucher - VOUCHER_VALUE_CENTS)
    else:
        final = pre_voucher
    return final


# ===========================================================================
# Logical clock endpoint
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(1)
    b = body()
    to_iso = req_str(b, "to_iso8601")
    try:
        _clock["now"] = parse_dt(to_iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    return ok({}, 200)


# ===========================================================================
# Machines
# ===========================================================================
@app.route("/machines", methods=["POST"])
def create_machine():
    auth(3)
    b = body()
    name = req_str(b, "name")
    mix_par = req_num(b, "mix_par_oz")
    initial = opt_num(b, "initial_mix_oz", mix_par)
    mid = new_id()
    m = {
        "id": mid,
        "name": name,
        "mix_par_oz": mix_par,
        "current_mix_level_oz": initial,
        "last_cleaned_at": now_str(),
        "next_maintenance_at": None,
        "sanitation_status": "READY",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["machines"][mid] = m
    return ok(serialize(m), 201)


@app.route("/machines", methods=["GET"])
def list_machines():
    auth(1)
    items = list(DB["machines"].values())
    st = request.args.get("sanitation_status")
    if st is not None:
        items = [m for m in items if m["sanitation_status"] == st]
    return list_response(items)


@app.route("/machines/<mid>", methods=["GET"])
def get_machine(mid):
    auth(1)
    m = get_or_404("machines", mid, "ERR_MACHINE_NOT_FOUND")
    return ok(serialize(m), 200)


@app.route("/machines/<mid>/start-cleaning", methods=["POST"])
def start_cleaning(mid):
    auth(2)
    m = get_or_404("machines", mid, "ERR_MACHINE_NOT_FOUND")
    if m["sanitation_status"] not in ("READY", "OUT_OF_SERVICE"):
        raise ApiError("ERR_MACHINE_INVALID_STATE", 409, "Machine not eligible for cleaning")
    m["sanitation_status"] = "CLEANING"
    touch(m)
    return ok(serialize(m), 200)


@app.route("/machines/<mid>/complete-cleaning", methods=["POST"])
def complete_cleaning(mid):
    auth(2)
    m = get_or_404("machines", mid, "ERR_MACHINE_NOT_FOUND")
    if m["sanitation_status"] != "CLEANING":
        raise ApiError("ERR_MACHINE_INVALID_STATE", 409, "Machine not in CLEANING state")
    cleaned = now_str()
    m["sanitation_status"] = "READY"
    m["last_cleaned_at"] = cleaned
    touch(m)
    # append sanitation log
    sid = new_id()
    log = {
        "id": sid,
        "machine_id": mid,
        "cleaned_at": cleaned,
        "previous_status": "CLEANING",
        "created_at": now_str(),
    }
    DB["sanitation_logs"][sid] = log
    # cascade suspended flavors -> loaded
    for f in DB["flavors"].values():
        if f["machine_id"] == mid and f["status"] == "SUSPENDED":
            f["status"] = "LOADED"
            touch(f)
    return ok(serialize(m), 200)


@app.route("/machines/<mid>/refill-mix", methods=["POST"])
def refill_mix(mid):
    auth(2)
    m = get_or_404("machines", mid, "ERR_MACHINE_NOT_FOUND")
    b = body()
    added = req_num(b, "added_oz")
    m["current_mix_level_oz"] = min(m["mix_par_oz"], m["current_mix_level_oz"] + added)
    touch(m)
    return ok(serialize(m), 200)


@app.route("/machines/<mid>/check-sanitation", methods=["POST"])
def check_sanitation(mid):
    auth(2)
    m = get_or_404("machines", mid, "ERR_MACHINE_NOT_FOUND")
    evaluate_sanitation(m)
    return ok(serialize(m), 200)


# ===========================================================================
# Flavors
# ===========================================================================
@app.route("/flavors", methods=["POST"])
def create_flavor():
    auth(2)
    b = body()
    machine_id = req_str(b, "machine_id")
    name = req_str(b, "name")
    price = req_int(b, "price_per_oz_cents")
    cost = req_int(b, "cost_per_oz_cents")
    tags = opt_array(b, "allergen_tags", [])
    get_or_404("machines", machine_id, "ERR_MACHINE_NOT_FOUND")
    fid = new_id()
    f = {
        "id": fid,
        "machine_id": machine_id,
        "name": name,
        "price_per_oz_cents": price,
        "cost_per_oz_cents": cost,
        "allergen_tags": tags,
        "status": "LOADED",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["flavors"][fid] = f
    return ok(serialize(f), 201)


@app.route("/flavors", methods=["GET"])
def list_flavors():
    auth(1)
    items = list(DB["flavors"].values())
    mid = request.args.get("machine_id")
    if mid is not None:
        items = [f for f in items if f["machine_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [f for f in items if f["status"] == st]
    return list_response(items)


@app.route("/flavors/<fid>", methods=["GET"])
def get_flavor(fid):
    auth(1)
    f = get_or_404("flavors", fid, "ERR_FLAVOR_NOT_FOUND")
    return ok(serialize(f), 200)


@app.route("/flavors/<fid>/rotate-out", methods=["POST"])
def rotate_flavor(fid):
    auth(2)
    f = get_or_404("flavors", fid, "ERR_FLAVOR_NOT_FOUND")
    if f["status"] != "LOADED":
        raise ApiError("ERR_FLAVOR_INVALID_STATE", 409, "Flavor not LOADED")
    f["status"] = "ROTATED_OUT"
    touch(f)
    return ok(serialize(f), 200)


# ===========================================================================
# Toppings
# ===========================================================================
@app.route("/toppings", methods=["POST"])
def create_topping():
    auth(2)
    b = body()
    name = req_str(b, "name")
    surcharge = req_int(b, "surcharge_cents")
    initial_units = req_int(b, "initial_units")
    tags = opt_array(b, "allergen_tags", [])
    tid = new_id()
    t = {
        "id": tid,
        "name": name,
        "surcharge_cents": surcharge,
        "on_hand_units": initial_units,
        "allergen_tags": tags,
        "status": "AVAILABLE",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["toppings"][tid] = t
    return ok(serialize(t), 201)


@app.route("/toppings", methods=["GET"])
def list_toppings():
    auth(1)
    items = list(DB["toppings"].values())
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    return list_response(items)


@app.route("/toppings/<tid>", methods=["GET"])
def get_topping(tid):
    auth(1)
    t = get_or_404("toppings", tid, "ERR_TOPPING_NOT_FOUND")
    return ok(serialize(t), 200)


@app.route("/toppings/<tid>/restock", methods=["POST"])
def restock_topping(tid):
    auth(2)
    t = get_or_404("toppings", tid, "ERR_TOPPING_NOT_FOUND")
    b = body()
    added = req_int(b, "added_units")
    t["on_hand_units"] = t["on_hand_units"] + added
    touch(t)
    return ok(serialize(t), 200)


@app.route("/toppings/<tid>/rotate-out", methods=["POST"])
def rotate_topping(tid):
    auth(2)
    t = get_or_404("toppings", tid, "ERR_TOPPING_NOT_FOUND")
    if t["status"] != "AVAILABLE":
        raise ApiError("ERR_TOPPING_INVALID_STATE", 409, "Topping not AVAILABLE")
    t["status"] = "ROTATED_OUT"
    touch(t)
    return ok(serialize(t), 200)


# ===========================================================================
# Seasonal Promotions
# ===========================================================================
@app.route("/seasonal-promotions", methods=["POST"])
def create_promotion():
    auth(3)
    b = body()
    name = req_str(b, "name")
    discount = req_num(b, "discount_pct")
    starts_at = req_str(b, "starts_at")
    ends_at = req_str(b, "ends_at")
    try:
        parse_dt(starts_at)
        parse_dt(ends_at)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    pid = new_id()
    p = {
        "id": pid,
        "name": name,
        "discount_pct": discount,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["promotions"][pid] = p
    return ok(serialize(p), 201)


@app.route("/seasonal-promotions", methods=["GET"])
def list_promotions():
    auth(1)
    return list_response(list(DB["promotions"].values()))


# ===========================================================================
# Loyalty Accounts
# ===========================================================================
@app.route("/loyalty-accounts", methods=["POST"])
def create_loyalty():
    auth(1)
    b = body()
    member_name = req_str(b, "member_name")
    phone = opt_str(b, "phone", None)
    initial_punch = opt_int(b, "initial_punch_count", 0)
    lid = new_id()
    acc = {
        "id": lid,
        "member_name": member_name,
        "phone": phone,
        "points_provisional": 0,
        "points_lifetime": 0,
        "punch_count": initial_punch,
        "status": "ACTIVE",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["loyalty_accounts"][lid] = acc
    return ok(serialize(acc), 201)


@app.route("/loyalty-accounts", methods=["GET"])
def list_loyalty():
    auth(1)
    items = list(DB["loyalty_accounts"].values())
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return list_response(items)


@app.route("/loyalty-accounts/<lid>", methods=["GET"])
def get_loyalty(lid):
    auth(1)
    acc = get_or_404("loyalty_accounts", lid, "ERR_LOYALTY_NOT_FOUND")
    return ok(serialize(acc), 200)


@app.route("/loyalty-accounts/<lid>/suspend", methods=["POST"])
def suspend_loyalty(lid):
    auth(3)
    acc = get_or_404("loyalty_accounts", lid, "ERR_LOYALTY_NOT_FOUND")
    if acc["status"] != "ACTIVE":
        raise ApiError("ERR_LOYALTY_INVALID_STATE", 409, "Loyalty account not ACTIVE")
    acc["status"] = "SUSPENDED"
    touch(acc)
    return ok(serialize(acc), 200)


# ===========================================================================
# Reward Vouchers (read-only)
# ===========================================================================
@app.route("/reward-vouchers", methods=["GET"])
def list_vouchers():
    auth(1)
    items = list(DB["vouchers"].values())
    lid = request.args.get("loyalty_account_id")
    if lid is not None:
        items = [v for v in items if v["loyalty_account_id"] == lid]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    return list_response(items)


@app.route("/reward-vouchers/<vid>", methods=["GET"])
def get_voucher(vid):
    auth(1)
    v = get_or_404("vouchers", vid, "ERR_VOUCHER_NOT_FOUND")
    return ok(serialize(v), 200)


# ===========================================================================
# Sale Tickets
# ===========================================================================
@app.route("/sale-tickets", methods=["POST"])
def create_ticket():
    auth(1)
    b = body()
    loyalty_id = opt_str(b, "loyalty_account_id", None)
    excluded = opt_array(b, "excluded_allergens", [])
    if loyalty_id is not None:
        get_or_404("loyalty_accounts", loyalty_id, "ERR_LOYALTY_NOT_FOUND")
    tid = new_id()
    t = {
        "id": tid,
        "loyalty_account_id": loyalty_id,
        "excluded_allergens": excluded,
        "reconciliation_id": None,
        "redeemed_voucher_id": None,
        "quoted_total_cents": None,
        "final_total_cents": None,
        "provisional_points": 0,
        "final_points": None,
        "payment_status": "OPEN",
        "reconciliation_status": "UNRECONCILED",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["tickets"][tid] = t
    return ok(serialize(t), 201)


@app.route("/sale-tickets", methods=["GET"])
def list_tickets():
    auth(1)
    items = list(DB["tickets"].values())
    for key in ("loyalty_account_id", "reconciliation_id", "redeemed_voucher_id", "payment_status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t[key] == val]
    return list_response(items)


@app.route("/sale-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    auth(1)
    t = get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")
    return ok(serialize(t), 200)


@app.route("/sale-tickets/<tid>/lines", methods=["POST"])
def add_line(tid):
    auth(1)
    t = get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")
    b = body()
    flavor_id = req_str(b, "flavor_id")
    gross = req_num(b, "gross_weight_oz")
    tare = opt_num(b, "container_tare_oz", 0.0)
    topping_ids = opt_array(b, "topping_ids", [])
    # existence (body FKs, left-to-right)
    flavor = get_or_404("flavors", flavor_id, "ERR_FLAVOR_NOT_FOUND")
    toppings = []
    for topid in topping_ids:
        toppings.append(get_or_404("toppings", topid, "ERR_TOPPING_NOT_FOUND"))
    # ticket must be OPEN
    if t["payment_status"] != "OPEN":
        raise ApiError("ERR_TICKET_NOT_OPEN", 409, "Ticket not OPEN")
    # 1) allergen guard
    excluded = set(t["excluded_allergens"])
    for top in toppings:
        if excluded.intersection(set(top["allergen_tags"])):
            raise ApiError("ERR_ALLERGEN_CONFLICT", 409, "Topping introduces an excluded allergen")
    # 2) sanitation gate
    machine = DB["machines"].get(flavor["machine_id"])
    if machine is not None:
        evaluate_sanitation(machine)
    if machine is None or machine["sanitation_status"] != "READY":
        raise ApiError("ERR_MACHINE_NOT_READY", 409, "Machine not READY")
    # 3) availability
    if flavor["status"] != "LOADED":
        raise ApiError("ERR_TOPPING_UNAVAILABLE", 409, "Flavor not LOADED")
    for top in toppings:
        if top["status"] != "AVAILABLE" or top["on_hand_units"] < 1:
            raise ApiError("ERR_TOPPING_UNAVAILABLE", 409, "Topping unavailable")
    # 4) net weight
    net = D(gross) - D(tare)
    if net <= 0:
        raise ApiError("ERR_INVALID_WEIGHT", 400, "Net weight must be > 0")
    # 5) mix sufficiency
    if net > D(machine["current_mix_level_oz"]):
        raise ApiError("ERR_INSUFFICIENT_MIX", 402, "Insufficient mix")
    # commit
    net_val = gross - tare
    machine["current_mix_level_oz"] = machine["current_mix_level_oz"] - net_val
    touch(machine)
    for top in toppings:
        top["on_hand_units"] = top["on_hand_units"] - 1
        touch(top)
    disc = active_discount(now_dt())
    surch = sum(top["surcharge_cents"] for top in toppings)
    line_quoted = rhu(D(net_val) * D(flavor["price_per_oz_cents"]) * (Decimal(1) - disc)) + surch
    lid = new_id()
    line = {
        "id": lid,
        "ticket_id": tid,
        "flavor_id": flavor_id,
        "gross_weight_oz": gross,
        "container_tare_oz": tare,
        "net_weight_oz": net_val,
        "topping_ids": topping_ids,
        "line_quoted_cents": line_quoted,
        "created_at": now_str(),
    }
    DB["lines"][lid] = line
    return ok(serialize(line), 201)


@app.route("/sale-tickets/<tid>/lines", methods=["GET"])
def list_ticket_lines(tid):
    auth(1)
    get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")
    items = [ln for ln in DB["lines"].values() if ln["ticket_id"] == tid]
    return list_response(items)


@app.route("/sale-tickets/<tid>/checkout", methods=["POST"])
def checkout(tid):
    auth(1)
    t = get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")
    b = body()
    voucher_id = opt_str(b, "voucher_id", None)
    voucher = None
    if voucher_id is not None:
        voucher = get_or_404("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    # state
    if t["payment_status"] != "OPEN":
        raise ApiError("ERR_TICKET_NOT_OPEN", 409, "Ticket not OPEN")
    lines = ticket_lines(tid)
    if len(lines) < 1:
        raise ApiError("ERR_EMPTY_TICKET", 409, "Ticket has no lines")
    # loyalty suspended
    if t["loyalty_account_id"] is not None:
        acc = DB["loyalty_accounts"].get(t["loyalty_account_id"])
        if acc is not None and acc["status"] != "ACTIVE":
            raise ApiError("ERR_LOYALTY_ACCOUNT_SUSPENDED", 409, "Loyalty account suspended")
    # voucher
    if voucher is not None:
        if voucher["status"] != "ISSUED":
            raise ApiError("ERR_VOUCHER_NOT_REDEEMABLE", 409, "Voucher not redeemable")
        if now_dt() >= parse_dt(voucher["expires_at"]):
            raise ApiError("ERR_VOUCHER_EXPIRED", 409, "Voucher expired")
    # pricing (QUOTED)
    subtotal = sum(ln["line_quoted_cents"] for ln in lines)
    pre_voucher = max(MIN_TICKET_CHARGE_CENTS, subtotal)
    if voucher is not None:
        quoted_total = max(MIN_TICKET_CHARGE_CENTS, pre_voucher - VOUCHER_VALUE_CENTS)
    else:
        quoted_total = pre_voucher
    provisional_points = quoted_total // POINTS_DIVISOR
    # side effects
    t["quoted_total_cents"] = quoted_total
    t["provisional_points"] = provisional_points
    if voucher is not None:
        voucher["status"] = "REDEEMED"
        touch(voucher)
        t["redeemed_voucher_id"] = voucher["id"]
    if t["loyalty_account_id"] is not None:
        acc = DB["loyalty_accounts"].get(t["loyalty_account_id"])
        if acc is not None:
            acc["points_provisional"] = acc["points_provisional"] + provisional_points
            touch(acc)
    t["payment_status"] = "CHARGED"
    touch(t)
    return ok(serialize(t), 200)


@app.route("/sale-tickets/<tid>/void", methods=["POST"])
def void_ticket(tid):
    auth(2)
    t = get_or_404("tickets", tid, "ERR_TICKET_NOT_FOUND")
    if t["payment_status"] != "CHARGED":
        raise ApiError("ERR_TICKET_NOT_CHARGED", 409, "Ticket not CHARGED")
    if t["reconciliation_status"] != "UNRECONCILED":
        raise ApiError("ERR_TICKET_ALREADY_RECONCILED", 409, "Ticket already reconciled")
    lines = ticket_lines(tid)
    # restore toppings
    for ln in lines:
        for topid in ln["topping_ids"]:
            top = DB["toppings"].get(topid)
            if top is not None:
                top["on_hand_units"] = top["on_hand_units"] + 1
                touch(top)
    # restore mix per machine (capped at par)
    machine_restore = {}
    for ln in lines:
        flavor = DB["flavors"].get(ln["flavor_id"])
        if flavor is None:
            continue
        mid = flavor["machine_id"]
        machine_restore[mid] = machine_restore.get(mid, 0) + ln["net_weight_oz"]
    for mid, amt in machine_restore.items():
        m = DB["machines"].get(mid)
        if m is not None:
            m["current_mix_level_oz"] = min(m["mix_par_oz"], m["current_mix_level_oz"] + amt)
            touch(m)
    # reverse provisional points
    if t["loyalty_account_id"] is not None:
        acc = DB["loyalty_accounts"].get(t["loyalty_account_id"])
        if acc is not None:
            acc["points_provisional"] = acc["points_provisional"] - t["provisional_points"]
            touch(acc)
    # un-redeem voucher
    if t["redeemed_voucher_id"] is not None:
        v = DB["vouchers"].get(t["redeemed_voucher_id"])
        if v is not None:
            v["status"] = "ISSUED"
            touch(v)
    t["payment_status"] = "VOIDED"
    touch(t)
    return ok(serialize(t), 200)


# ===========================================================================
# Sale Lines (flat reads)
# ===========================================================================
@app.route("/sale-lines", methods=["GET"])
def list_sale_lines():
    auth(1)
    items = list(DB["lines"].values())
    fid = request.args.get("flavor_id")
    if fid is not None:
        items = [ln for ln in items if ln["flavor_id"] == fid]
    tid = request.args.get("ticket_id")
    if tid is not None:
        items = [ln for ln in items if ln["ticket_id"] == tid]
    return list_response(items)


@app.route("/sale-lines/<lid>", methods=["GET"])
def get_sale_line(lid):
    auth(1)
    ln = get_or_404("lines", lid, "ERR_LINE_NOT_FOUND")
    return ok(serialize(ln), 200)


# ===========================================================================
# Waste Events
# ===========================================================================
@app.route("/waste-events", methods=["POST"])
def create_waste():
    auth(2)
    b = body()
    reason = req_str(b, "reason")
    if reason not in WASTE_REASONS:
        raise ApiError("ERR_VALIDATION", 400, "Invalid reason")
    machine_id = opt_str(b, "machine_id", None)
    flavor_id = opt_str(b, "flavor_id", None)
    topping_id = opt_str(b, "topping_id", None)
    waste_weight_oz = opt_num(b, "waste_weight_oz", None)
    waste_units = opt_int(b, "waste_units", None)

    is_topping = topping_id is not None or (flavor_id is None and waste_units is not None)

    if is_topping:
        if topping_id is None:
            raise ApiError("ERR_VALIDATION", 400, "topping_id required for topping waste")
        if waste_units is None:
            raise ApiError("ERR_VALIDATION", 400, "waste_units required for topping waste")
        top = get_or_404("toppings", topping_id, "ERR_TOPPING_NOT_FOUND")
        cogs = waste_units * TOPPING_UNIT_COST_CENTS
        retail = waste_units * top["surcharge_cents"]
        top["on_hand_units"] = top["on_hand_units"] - waste_units
        touch(top)
        machine_id = None
        flavor_id = None
        waste_weight_oz = None
    else:
        if machine_id is None:
            raise ApiError("ERR_VALIDATION", 400, "machine_id required for mix waste")
        if flavor_id is None:
            raise ApiError("ERR_VALIDATION", 400, "flavor_id required for mix waste")
        if waste_weight_oz is None:
            raise ApiError("ERR_VALIDATION", 400, "waste_weight_oz required for mix waste")
        machine = get_or_404("machines", machine_id, "ERR_MACHINE_NOT_FOUND")
        flavor = get_or_404("flavors", flavor_id, "ERR_FLAVOR_NOT_FOUND")
        cogs = rhu(D(waste_weight_oz) * D(flavor["cost_per_oz_cents"]))
        retail = rhu(D(waste_weight_oz) * D(flavor["price_per_oz_cents"]))
        machine["current_mix_level_oz"] = machine["current_mix_level_oz"] - waste_weight_oz
        touch(machine)
        topping_id = None
        waste_units = None

    wid = new_id()
    w = {
        "id": wid,
        "machine_id": machine_id,
        "flavor_id": flavor_id,
        "topping_id": topping_id,
        "waste_weight_oz": waste_weight_oz,
        "waste_units": waste_units,
        "reason": reason,
        "cogs_value_cents": cogs,
        "retail_value_cents": retail,
        "created_at": now_str(),
    }
    DB["waste_events"][wid] = w
    return ok(serialize(w), 201)


@app.route("/waste-events", methods=["GET"])
def list_waste():
    auth(2)
    items = list(DB["waste_events"].values())
    for key in ("machine_id", "flavor_id", "topping_id"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w[key] == val]
    return list_response(items)


@app.route("/waste-events/<wid>", methods=["GET"])
def get_waste(wid):
    auth(2)
    w = get_or_404("waste_events", wid, "ERR_WASTE_NOT_FOUND")
    return ok(serialize(w), 200)


# ===========================================================================
# Sanitation Logs (read-only)
# ===========================================================================
@app.route("/sanitation-logs", methods=["GET"])
def list_sanitation():
    auth(2)
    items = list(DB["sanitation_logs"].values())
    mid = request.args.get("machine_id")
    if mid is not None:
        items = [s for s in items if s["machine_id"] == mid]
    return list_response(items)


@app.route("/sanitation-logs/<sid>", methods=["GET"])
def get_sanitation(sid):
    auth(2)
    s = get_or_404("sanitation_logs", sid, "ERR_SANITATION_LOG_NOT_FOUND")
    return ok(serialize(s), 200)


# ===========================================================================
# Maintenance Windows (OCC on Machine)
# ===========================================================================
@app.route("/maintenance-windows", methods=["POST"])
def create_window():
    auth(2)
    b = body()
    machine_id = req_str(b, "machine_id")
    window_start = req_str(b, "window_start")
    window_end = req_str(b, "window_end")
    expected_version = req_int(b, "expected_machine_version")
    machine = get_or_404("machines", machine_id, "ERR_MACHINE_NOT_FOUND")
    try:
        ws = parse_dt(window_start)
        we = parse_dt(window_end)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid window datetime")
    if we <= ws:
        raise ApiError("ERR_INVALID_WINDOW", 400, "window_end must be after window_start")
    # spacing guard (priority 10) — against SCHEDULED windows on same machine
    buffer = timedelta(minutes=MAINTENANCE_BUFFER_MINUTES)
    for w in DB["windows"].values():
        if w["machine_id"] != machine_id or w["status"] != "SCHEDULED":
            continue
        es = parse_dt(w["window_start"])
        ee = parse_dt(w["window_end"])
        # conflict if gap < buffer on both orderings (i.e. not separated by >= buffer)
        if (ws - ee) < buffer and (es - we) < buffer:
            raise ApiError("ERR_MAINTENANCE_WINDOW_CONFLICT", 409, "Maintenance window conflict")
    # OCC guard (priority 13)
    if expected_version != machine["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale machine version")
    wid = new_id()
    w = {
        "id": wid,
        "machine_id": machine_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["windows"][wid] = w
    # supersede machine's next_maintenance_at + bump version
    machine["next_maintenance_at"] = window_start
    touch(machine)
    return ok(serialize(w), 201)


@app.route("/maintenance-windows", methods=["GET"])
def list_windows():
    auth(2)
    items = list(DB["windows"].values())
    mid = request.args.get("machine_id")
    if mid is not None:
        items = [w for w in items if w["machine_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [w for w in items if w["status"] == st]
    return list_response(items)


@app.route("/maintenance-windows/<wid>", methods=["GET"])
def get_window(wid):
    auth(2)
    w = get_or_404("windows", wid, "ERR_WINDOW_NOT_FOUND")
    return ok(serialize(w), 200)


@app.route("/maintenance-windows/<wid>/cancel", methods=["POST"])
def cancel_window(wid):
    auth(2)
    w = get_or_404("windows", wid, "ERR_WINDOW_NOT_FOUND")
    if w["status"] != "SCHEDULED":
        raise ApiError("ERR_WINDOW_INVALID_STATE", 409, "Window not SCHEDULED")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(serialize(w), 200)


# ===========================================================================
# Catering Resources
# ===========================================================================
@app.route("/catering-resources", methods=["POST"])
def create_resource():
    auth(3)
    b = body()
    name = req_str(b, "name")
    capacity = opt_int(b, "capacity", 0)
    rid = new_id()
    r = {
        "id": rid,
        "name": name,
        "capacity": capacity,
        "status": "AVAILABLE",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["resources"][rid] = r
    return ok(serialize(r), 201)


@app.route("/catering-resources", methods=["GET"])
def list_resources():
    auth(1)
    return list_response(list(DB["resources"].values()))


# ===========================================================================
# Catering Orders
# ===========================================================================
def validate_line_items(items):
    if not isinstance(items, list):
        raise ApiError("ERR_VALIDATION", 400, "line_items must be an array")
    for it in items:
        if not isinstance(it, dict):
            raise ApiError("ERR_VALIDATION", 400, "line_item must be an object")
        if not is_int(it.get("qty")):
            raise ApiError("ERR_VALIDATION", 400, "line_item.qty invalid")
        if not is_int(it.get("unit_price_cents")):
            raise ApiError("ERR_VALIDATION", 400, "line_item.unit_price_cents invalid")
        if not is_num(it.get("discount_pct")):
            raise ApiError("ERR_VALIDATION", 400, "line_item.discount_pct invalid")
    return items


@app.route("/catering-orders", methods=["POST"])
def create_catering():
    auth(1)
    b = body()
    resource_id = req_str(b, "resource_id")
    event_start = req_str(b, "event_start")
    event_end = req_str(b, "event_end")
    guest_count = req_int(b, "guest_count")
    if "line_items" not in b:
        raise ApiError("ERR_VALIDATION", 400, "Missing line_items")
    line_items = validate_line_items(b["line_items"])
    loyalty_id = opt_str(b, "loyalty_account_id", None)
    get_or_404("resources", resource_id, "ERR_RESOURCE_NOT_FOUND")
    if loyalty_id is not None:
        get_or_404("loyalty_accounts", loyalty_id, "ERR_LOYALTY_NOT_FOUND")
    try:
        es = parse_dt(event_start)
        ee = parse_dt(event_end)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid event datetime")
    if ee <= es:
        raise ApiError("ERR_INVALID_WINDOW", 400, "event_end must be after event_start")
    cid = new_id()
    o = {
        "id": cid,
        "resource_id": resource_id,
        "loyalty_account_id": loyalty_id,
        "event_start": event_start,
        "event_end": event_end,
        "guest_count": guest_count,
        "line_items": line_items,
        "invoice_total_cents": None,
        "required_deposit_cents": None,
        "deposit_paid_cents": 0,
        "status": "DRAFT",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["catering_orders"][cid] = o
    return ok(serialize(o), 201)


@app.route("/catering-orders", methods=["GET"])
def list_catering():
    auth(1)
    items = list(DB["catering_orders"].values())
    for key in ("resource_id", "loyalty_account_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    return list_response(items)


@app.route("/catering-orders/<cid>", methods=["GET"])
def get_catering(cid):
    auth(1)
    o = get_or_404("catering_orders", cid, "ERR_CATERING_NOT_FOUND")
    return ok(serialize(o), 200)


@app.route("/catering-orders/<cid>/quote", methods=["POST"])
def quote_catering(cid):
    auth(3)
    o = get_or_404("catering_orders", cid, "ERR_CATERING_NOT_FOUND")
    if o["status"] != "DRAFT":
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "Order not DRAFT")
    total = 0
    for it in o["line_items"]:
        line_cents = rhu(D(it["qty"]) * D(it["unit_price_cents"]) * (Decimal(1) - D(it["discount_pct"])))
        total += line_cents
    o["invoice_total_cents"] = total
    o["required_deposit_cents"] = rhu(D(total) * CATERING_DEPOSIT_PCT)
    o["status"] = "QUOTED"
    touch(o)
    return ok(serialize(o), 200)


@app.route("/catering-orders/<cid>/confirm", methods=["POST"])
def confirm_catering(cid):
    auth(3)
    o = get_or_404("catering_orders", cid, "ERR_CATERING_NOT_FOUND")
    b = body()
    deposit_paid = req_int(b, "deposit_paid_cents")
    if o["status"] != "QUOTED":
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "Order not QUOTED")
    # double-booking check (priority 9)
    es = parse_dt(o["event_start"])
    ee = parse_dt(o["event_end"])
    for other in DB["catering_orders"].values():
        if other["id"] == cid:
            continue
        if other["resource_id"] != o["resource_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "FULFILLED"):
            continue
        os_ = parse_dt(other["event_start"])
        oe = parse_dt(other["event_end"])
        # half-open overlap
        if es < oe and os_ < ee:
            raise ApiError("ERR_RESOURCE_DOUBLE_BOOKED", 409, "Resource double-booked")
    # deposit check (priority 11)
    if deposit_paid < o["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT", 402, "Deposit insufficient")
    o["deposit_paid_cents"] = deposit_paid
    o["status"] = "CONFIRMED"
    touch(o)
    return ok(serialize(o), 200)


@app.route("/catering-orders/<cid>/fulfill", methods=["POST"])
def fulfill_catering(cid):
    auth(3)
    o = get_or_404("catering_orders", cid, "ERR_CATERING_NOT_FOUND")
    if o["status"] != "CONFIRMED":
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "Order not CONFIRMED")
    o["status"] = "FULFILLED"
    touch(o)
    return ok(serialize(o), 200)


@app.route("/catering-orders/<cid>/cancel", methods=["POST"])
def cancel_catering(cid):
    auth(1)
    o = get_or_404("catering_orders", cid, "ERR_CATERING_NOT_FOUND")
    if o["status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise ApiError("ERR_CATERING_INVALID_STATE", 409, "Order not cancellable")
    o["status"] = "CANCELLED"
    touch(o)
    return ok(serialize(o), 200)


# ===========================================================================
# Daily Reconciliations
# ===========================================================================
@app.route("/daily-reconciliations", methods=["POST"])
def create_reconciliation():
    auth(3)
    b = body()
    business_date = req_str(b, "business_date")
    rid = new_id()
    r = {
        "id": rid,
        "business_date": business_date,
        "counted_cash_cents": None,
        "expected_revenue_cents": None,
        "cash_variance_cents": None,
        "adjustments": [],
        "status": "OPEN",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["reconciliations"][rid] = r
    return ok(serialize(r), 201)


@app.route("/daily-reconciliations", methods=["GET"])
def list_reconciliations():
    auth(3)
    items = list(DB["reconciliations"].values())
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    return list_response(items)


@app.route("/daily-reconciliations/<rid>", methods=["GET"])
def get_reconciliation(rid):
    auth(3)
    r = get_or_404("reconciliations", rid, "ERR_RECONCILIATION_NOT_FOUND")
    return ok(serialize(r), 200)


def rederive_reconciliation(r):
    swept_total = sum(
        t["final_total_cents"]
        for t in DB["tickets"].values()
        if t["reconciliation_id"] == r["id"] and t["final_total_cents"] is not None
    )
    adj_total = sum(a["amount_cents"] for a in r["adjustments"])
    expected = swept_total + adj_total
    r["expected_revenue_cents"] = expected
    if r["counted_cash_cents"] is not None:
        r["cash_variance_cents"] = r["counted_cash_cents"] - expected
    else:
        r["cash_variance_cents"] = None


@app.route("/daily-reconciliations/<rid>/close", methods=["POST"])
def close_reconciliation(rid):
    auth(3)
    r = get_or_404("reconciliations", rid, "ERR_RECONCILIATION_NOT_FOUND")
    b = body()
    counted = req_int(b, "counted_cash_cents")
    if r["status"] != "OPEN":
        raise ApiError("ERR_RECONCILIATION_INVALID_STATE", 409, "Reconciliation not OPEN")
    clock = now_dt()
    # sweep CHARGED + UNRECONCILED tickets in created_at order
    swept = sorted(
        [
            t for t in DB["tickets"].values()
            if t["payment_status"] == "CHARGED" and t["reconciliation_status"] == "UNRECONCILED"
        ],
        key=lambda t: t["created_at"],
    )
    for t in swept:
        final_total = compute_finalized(t, clock)
        t["final_total_cents"] = final_total
        t["reconciliation_id"] = rid
        t["reconciliation_status"] = "RECONCILED"
        t["final_points"] = final_total // POINTS_DIVISOR
        touch(t)
        if t["loyalty_account_id"] is not None:
            acc = DB["loyalty_accounts"].get(t["loyalty_account_id"])
            if acc is not None:
                acc["points_lifetime"] = acc["points_lifetime"] + t["final_points"]
                acc["points_provisional"] = acc["points_provisional"] - t["provisional_points"]
                acc["punch_count"] = acc["punch_count"] + 1
                if acc["punch_count"] >= PUNCH_THRESHOLD:
                    issue_voucher(acc, clock)
                    acc["punch_count"] = acc["punch_count"] - PUNCH_THRESHOLD
                touch(acc)
    r["counted_cash_cents"] = counted
    rederive_reconciliation(r)
    r["status"] = "CLOSED"
    touch(r)
    return ok(serialize(r), 200)


def issue_voucher(acc, clock):
    vid = new_id()
    v = {
        "id": vid,
        "loyalty_account_id": acc["id"],
        "value_cents": VOUCHER_VALUE_CENTS,
        "expires_at": fmt(clock + timedelta(hours=VOUCHER_TTL_HOURS)),
        "status": "ISSUED",
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
    }
    DB["vouchers"][vid] = v
    return v


@app.route("/daily-reconciliations/<rid>/adjustments", methods=["POST"])
def post_adjustment(rid):
    auth(3)
    r = get_or_404("reconciliations", rid, "ERR_RECONCILIATION_NOT_FOUND")
    b = body()
    amount = req_int(b, "amount_cents")
    reason = req_str(b, "reason")
    expected_version = req_int(b, "expected_daily_reconciliation_version")
    if expected_version != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale reconciliation version")
    r["adjustments"] = r["adjustments"] + [{"amount_cents": amount, "reason": reason}]
    touch(r)
    rederive_reconciliation(r)
    return ok(serialize(r), 201)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
