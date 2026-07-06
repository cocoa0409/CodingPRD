import os
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot — NO seeding)
# ---------------------------------------------------------------------------
KINDS = [
    "food_hall", "vendor", "stall", "lease", "permit", "inspection",
    "order", "seating", "event", "settlement",
]
STORE = {k: {} for k in KINDS}
STATE = {"seq": 0, "clock": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}

VALID_ROLES = {"HallManager", "Vendor", "HealthInspector", "POSOperator"}

NOT_FOUND = {
    "food_hall": "ERR_FOOD_HALL_NOT_FOUND",
    "vendor": "ERR_VENDOR_NOT_FOUND",
    "stall": "ERR_STALL_NOT_FOUND",
    "lease": "ERR_LEASE_NOT_FOUND",
    "permit": "ERR_PERMIT_NOT_FOUND",
    "inspection": "ERR_INSPECTION_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "seating": "ERR_SEATING_NOT_FOUND",
    "event": "ERR_EVENT_NOT_FOUND",
    "settlement": "ERR_SETTLEMENT_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class APIError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock():
    return STATE["clock"]


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def make(kind, fields):
    rid = str(uuid4())
    rec = dict(fields)
    rec["id"] = rid
    rec["created_at"] = now_ts()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    rec["_kind"] = kind
    STORE[kind][rid] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def all_of(kind):
    return sorted(STORE[kind].values(), key=lambda r: r["_seq"])


# ---- parsing / validation ----
def parse_iso_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("bad date")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def bad_request(msg="invalid request"):
    raise APIError("ERR_INVALID_REQUEST", 422, msg)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        bad_request(f"{field} is required")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not is_int(v):
        bad_request(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        bad_request(f"{field} below minimum")
    if maximum is not None and v > maximum:
        bad_request(f"{field} above maximum")
    return v


def get_body():
    b = request.get_json(silent=True, force=True)
    if not isinstance(b, dict):
        return {}
    return b


# ---- auth ----
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise APIError("ERR_UNAUTHENTICATED", 401, "missing or malformed auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise APIError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def get_or_404(kind, rid):
    rec = STORE[kind].get(rid)
    if rec is None:
        raise APIError(NOT_FOUND[kind], 404, f"{kind} not found")
    return rec


def fk_exists(kind, rid):
    # rid present; validate resolution
    rec = STORE[kind].get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise APIError(NOT_FOUND[kind], 404, f"{kind} not found")
    return rec


# ---- responses ----
def ok(data, code=200, list_meta=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_ts()}
    if list_meta:
        meta.update(list_meta)
    rtype = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": rtype, "data": data}), code


def paginate(items):
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    lim = 10
    if limit is not None:
        try:
            lim = int(limit)
        except (ValueError, TypeError):
            bad_request("invalid limit")
        if lim < 1:
            lim = 1
        if lim > 100:
            lim = 100
    off = 0
    if offset is not None:
        try:
            off = int(offset)
        except (ValueError, TypeError):
            bad_request("invalid offset")
        if off < 0:
            off = 0
    total = len(items)
    page = items[off:off + lim]
    meta = {"limit": lim, "offset": off, "total_count": total,
            "has_more": off + lim < total}
    return page, meta


def list_response(items):
    items = sorted(items, key=lambda r: r["_seq"])
    page, meta = paginate(items)
    return ok([public(r) for r in page], 200, list_meta=meta)


# ---- rounding ----
def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.errorhandler(APIError)
def handle_api_error(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_ts()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_ts()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_ts()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 405


# ===========================================================================
# Domain helpers: posture, cascades, rent
# ===========================================================================
def stalls_of_vendor(vendor_id):
    return [s for s in STORE["stall"].values() if s.get("current_vendor_id") == vendor_id]


def active_lease_of_stall(stall_id):
    for l in STORE["lease"].values():
        if l["stall_id"] == stall_id and l["status"] == "ACTIVE":
            return l
    return None


def latest_permit_of_stall(stall_id):
    permits = [p for p in STORE["permit"].values() if p["stall_id"] == stall_id]
    if not permits:
        return None
    return max(permits, key=lambda p: p["_seq"])


def latest_conducted_inspection(stall_id):
    cands = [i for i in STORE["inspection"].values()
             if i["stall_id"] == stall_id and i["status"] == "CONDUCTED"]
    if not cands:
        return None
    best = None
    for i in cands:
        if best is None:
            best = i
        elif i["conducted_at"] > best["conducted_at"]:
            best = i
        elif i["conducted_at"] == best["conducted_at"] and i["_seq"] < best["_seq"]:
            # tie-break: earlier created_at (smaller seq)
            best = i
    return best


def compute_posture_triple(stall):
    lease = active_lease_of_stall(stall["id"])
    if lease is None:
        return "SUSPENDED", None, None
    vendor = STORE["vendor"].get(lease["vendor_id"])
    cur_lease = lease["id"]
    cur_vendor = lease["vendor_id"]
    if vendor is None or vendor["status"] != "ACTIVE":
        return "SUSPENDED", cur_lease, cur_vendor
    permit = latest_permit_of_stall(stall["id"])
    if permit is None or permit["status"] != "ISSUED":
        return "SUSPENDED", cur_lease, cur_vendor
    insp = latest_conducted_inspection(stall["id"])
    if insp is not None and insp["result"] == "FAIL":
        return "SUSPENDED", cur_lease, cur_vendor
    if insp is not None and insp["result"] == "CONDITIONAL":
        return "RESTRICTED", cur_lease, cur_vendor
    return "OPEN", cur_lease, cur_vendor


def recompute_posture(stall):
    posture, cur_lease, cur_vendor = compute_posture_triple(stall)
    changed = (stall.get("operational_posture") != posture
               or stall.get("current_lease_id") != cur_lease
               or stall.get("current_vendor_id") != cur_vendor)
    if changed:
        stall["operational_posture"] = posture
        stall["current_lease_id"] = cur_lease
        stall["current_vendor_id"] = cur_vendor
        touch(stall)
    return changed


def reject_orders_and_release_seating(stall):
    for o in list(STORE["order"].values()):
        if o["stall_id"] == stall["id"] and o["status"] in ("ROUTED", "ACCEPTED"):
            o["status"] = "REJECTED"
            touch(o)
            release_order_seating(o["id"])


def release_order_seating(order_id):
    for a in STORE["seating"].values():
        if a.get("order_id") == order_id and a["status"] == "RESERVED":
            a["status"] = "RELEASED"
            touch(a)


# ---- rent ----
def prorated_base(lease, period_start, period_end):
    period_days = (period_end - period_start).days + 1
    ls = parse_date(lease["start_date"])
    le = parse_date(lease["end_date"])
    lo = max(period_start, ls)
    hi = min(period_end, le)
    active_days = (hi - lo).days + 1 if hi >= lo else 0
    if active_days < 0:
        active_days = 0
    return rhu(Decimal(lease["base_rent_cents"]) * Decimal(active_days) / Decimal(period_days))


def gross_sales(lease, period_start, period_end, status_set):
    total = 0
    for o in STORE["order"].values():
        if o["stall_id"] != lease["stall_id"]:
            continue
        if o["status"] not in status_set:
            continue
        pd = parse_date(o["placed_at"][:10])
        if period_start <= pd <= period_end:
            total += o["gross_amount_cents"]
    return total


def compute_rent(lease, period_start, period_end, status_set):
    S = gross_sales(lease, period_start, period_end, status_set)
    base = prorated_base(lease, period_start, period_end)
    rate = Decimal(str(lease["percentage_rate"]))
    excess = S - lease["natural_breakpoint_cents"]
    if excess < 0:
        excess = 0
    pct = rhu(rate * Decimal(excess))
    total = min(lease["rent_cap_cents"], base + pct)
    return S, base, pct, total


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    raw = body.get("to_iso8601")
    try:
        dt = parse_iso_dt(raw)
    except (ValueError, TypeError):
        bad_request("to_iso8601 must be a valid ISO 8601 datetime")
    STATE["clock"] = dt
    return ok({"current_utc": fmt_dt(dt)}, 200)


# ===========================================================================
# FoodHall
# ===========================================================================
@app.route("/food-halls", methods=["POST"])
def create_food_hall():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    name = req_str(body, "name")
    total_seating = req_int(body, "total_seating_capacity", minimum=1)
    common_area = req_int(body, "common_area_capacity", minimum=1)
    hall_open = req_int(body, "hall_open_minutes")
    hall_close = req_int(body, "hall_close_minutes")
    if not (0 <= hall_open < hall_close <= 1440):
        bad_request("invalid hall operating hours")
    buf = body.get("event_buffer_minutes", 60)
    if buf is None:
        buf = 60
    if not is_int(buf) or buf < 0:
        bad_request("event_buffer_minutes must be an integer >= 0")
    rec = make("food_hall", {
        "name": name,
        "total_seating_capacity": total_seating,
        "common_area_capacity": common_area,
        "hall_open_minutes": hall_open,
        "hall_close_minutes": hall_close,
        "event_buffer_minutes": buf,
    })
    return ok(public(rec), 201)


@app.route("/food-halls/<rid>", methods=["GET"])
def get_food_hall(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("food_hall", rid)), 200)


# ===========================================================================
# Vendor
# ===========================================================================
@app.route("/vendors", methods=["POST"])
def create_vendor():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    legal_name = req_str(body, "legal_name")
    contact_email = req_str(body, "contact_email")
    rec = make("vendor", {
        "legal_name": legal_name,
        "contact_email": contact_email,
        "status": "APPLIED",
    })
    return ok(public(rec), 201)


@app.route("/vendors/<rid>", methods=["GET"])
def get_vendor(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("vendor", rid)), 200)


@app.route("/vendors/<rid>/activate", methods=["POST"])
def activate_vendor(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    v = get_or_404("vendor", rid)
    if v["status"] != "APPLIED":
        raise APIError("ERR_INVALID_STATE", 409, "vendor not APPLIED")
    v["status"] = "ACTIVE"
    touch(v)
    return ok(public(v), 200)


@app.route("/vendors/<rid>/suspend", methods=["POST"])
def suspend_vendor(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    v = get_or_404("vendor", rid)
    if v["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", 409, "vendor not ACTIVE")
    v["status"] = "SUSPENDED"
    touch(v)
    for stall in stalls_of_vendor(v["id"]):
        recompute_posture(stall)
        if stall["operational_posture"] == "SUSPENDED":
            reject_orders_and_release_seating(stall)
    return ok(public(v), 200)


@app.route("/vendors/<rid>/reinstate", methods=["POST"])
def reinstate_vendor(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    v = get_or_404("vendor", rid)
    if v["status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", 409, "vendor not SUSPENDED")
    v["status"] = "ACTIVE"
    touch(v)
    for stall in stalls_of_vendor(v["id"]):
        recompute_posture(stall)
    return ok(public(v), 200)


# ===========================================================================
# Stall
# ===========================================================================
@app.route("/stalls", methods=["POST"])
def create_stall():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    if "food_hall_id" in body and body["food_hall_id"] is not None:
        fk_exists("food_hall", body["food_hall_id"])
    food_hall_id = req_str(body, "food_hall_id")
    fk_exists("food_hall", food_hall_id)
    stall_code = req_str(body, "stall_code")
    size_sqft = req_int(body, "size_sqft", minimum=1)
    open_m = req_int(body, "open_minutes")
    close_m = req_int(body, "close_minutes")
    if not (0 <= open_m < close_m <= 1440):
        bad_request("invalid stall operating hours")
    rec = make("stall", {
        "food_hall_id": food_hall_id,
        "stall_code": stall_code,
        "size_sqft": size_sqft,
        "open_minutes": open_m,
        "close_minutes": close_m,
        "operational_posture": "SUSPENDED",
        "current_lease_id": None,
        "current_vendor_id": None,
    })
    return ok(public(rec), 201)


@app.route("/stalls/<rid>", methods=["GET"])
def get_stall(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("stall", rid)), 200)


@app.route("/stalls", methods=["GET"])
def list_stalls():
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    items = list(STORE["stall"].values())
    fh = request.args.get("food_hall_id")
    posture = request.args.get("operational_posture")
    if fh is not None:
        items = [s for s in items if s["food_hall_id"] == fh]
    if posture is not None:
        items = [s for s in items if s["operational_posture"] == posture]
    return list_response(items)


@app.route("/stalls/<rid>/permits", methods=["GET"])
def list_stall_permits(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    get_or_404("stall", rid)
    items = [p for p in STORE["permit"].values() if p["stall_id"] == rid]
    return list_response(items)


@app.route("/stalls/<rid>/inspections", methods=["GET"])
def list_stall_inspections(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    get_or_404("stall", rid)
    items = [i for i in STORE["inspection"].values() if i["stall_id"] == rid]
    return list_response(items)


@app.route("/stalls/<rid>/compliance-grade", methods=["GET"])
def stall_compliance_grade(rid):
    _, role = authenticate()
    authorize(role, {"HallManager", "HealthInspector"})
    stall = get_or_404("stall", rid)
    method = request.args.get("method")
    if method not in ("LATEST", "WEIGHTED"):
        bad_request("method must be LATEST or WEIGHTED")
    insps = [i for i in STORE["inspection"].values()
             if i["stall_id"] == stall["id"] and i["status"] == "CONDUCTED"]
    insps.sort(key=lambda i: (i["conducted_at"], i["_seq"]), reverse=True)
    insps = insps[:3]
    if not insps:
        score = 0
    elif method == "LATEST":
        score = insps[0]["score"]
    else:
        n = len(insps)
        if n == 1:
            weights = [Decimal("1.0")]
        elif n == 2:
            weights = [Decimal("0.6"), Decimal("0.4")]
        else:
            weights = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
        acc = Decimal(0)
        for i in range(n):
            acc += weights[i] * Decimal(insps[i]["score"])
        score = rhu(acc)
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"
    return ok({"stall_id": stall["id"], "method": method,
               "score": score, "grade": grade}, 200)


# ===========================================================================
# Lease
# ===========================================================================
@app.route("/leases", methods=["POST"])
def create_lease():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    if "stall_id" in body and body["stall_id"] is not None:
        fk_exists("stall", body["stall_id"])
    if "vendor_id" in body and body["vendor_id"] is not None:
        fk_exists("vendor", body["vendor_id"])
    stall_id = req_str(body, "stall_id")
    fk_exists("stall", stall_id)
    vendor_id = req_str(body, "vendor_id")
    fk_exists("vendor", vendor_id)
    start_raw = req_str(body, "start_date")
    end_raw = req_str(body, "end_date")
    try:
        sd = parse_date(start_raw)
        ed = parse_date(end_raw)
    except (ValueError, TypeError):
        bad_request("invalid date format")
    base_rent = req_int(body, "base_rent_cents", minimum=0)
    rate = body.get("percentage_rate")
    if not is_num(rate) or rate < 0 or rate > 1:
        bad_request("percentage_rate must be a number in [0,1]")
    breakpoint_c = req_int(body, "natural_breakpoint_cents", minimum=0)
    rent_cap = req_int(body, "rent_cap_cents", minimum=0)
    deposit = req_int(body, "security_deposit_cents", minimum=0)
    # lease-term validity (specific error code)
    if ed <= sd:
        raise APIError("ERR_LEASE_TERM_INVALID", 422, "end_date must be after start_date")
    if rent_cap < base_rent:
        raise APIError("ERR_LEASE_TERM_INVALID", 422, "rent_cap_cents must be >= base_rent_cents")
    rec = make("lease", {
        "stall_id": stall_id,
        "vendor_id": vendor_id,
        "start_date": start_raw,
        "end_date": end_raw,
        "base_rent_cents": base_rent,
        "percentage_rate": rate,
        "natural_breakpoint_cents": breakpoint_c,
        "rent_cap_cents": rent_cap,
        "security_deposit_cents": deposit,
        "outstanding_balance_cents": 0,
        "status": "DRAFT",
    })
    return ok(public(rec), 201)


@app.route("/leases/<rid>", methods=["GET"])
def get_lease(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("lease", rid)), 200)


@app.route("/leases", methods=["GET"])
def list_leases():
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    items = list(STORE["lease"].values())
    for key in ("stall_id", "vendor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l[key] == val]
    return list_response(items)


@app.route("/leases/<rid>/activate", methods=["POST"])
def activate_lease(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    lease = get_or_404("lease", rid)
    if lease["status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE", 409, "lease not DRAFT")
    vendor = STORE["vendor"].get(lease["vendor_id"])
    if vendor is None or vendor["status"] != "ACTIVE":
        raise APIError("ERR_VENDOR_NOT_ACTIVE", 409, "vendor is not ACTIVE")
    permit = latest_permit_of_stall(lease["stall_id"])
    if permit is None or permit["status"] != "ISSUED":
        raise APIError("ERR_PERMIT_NOT_ISSUED", 409, "stall's latest permit is not ISSUED")
    for other in STORE["lease"].values():
        if other["id"] != lease["id"] and other["stall_id"] == lease["stall_id"] \
                and other["status"] == "ACTIVE":
            raise APIError("ERR_STALL_ALREADY_LEASED", 409, "stall already has an ACTIVE lease")
    sd = parse_date(lease["start_date"])
    ed = parse_date(lease["end_date"])
    for other in STORE["lease"].values():
        if other["id"] != lease["id"] and other["stall_id"] == lease["stall_id"] \
                and other["status"] == "ACTIVE":
            osd = parse_date(other["start_date"])
            oed = parse_date(other["end_date"])
            if sd <= oed and osd <= ed:
                raise APIError("ERR_LEASE_TERM_CONFLICT", 409, "overlapping lease term")
    lease["status"] = "ACTIVE"
    touch(lease)
    stall = STORE["stall"].get(lease["stall_id"])
    if stall is not None:
        recompute_posture(stall)
    return ok(public(lease), 200)


@app.route("/leases/<rid>/renew", methods=["POST"])
def renew_lease(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    lease = get_or_404("lease", rid)
    if lease["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", 409, "lease not ACTIVE")
    body = get_body()
    new_end_raw = req_str(body, "new_end_date")
    try:
        new_end = parse_date(new_end_raw)
    except (ValueError, TypeError):
        bad_request("invalid new_end_date")
    if new_end <= parse_date(lease["end_date"]):
        bad_request("new_end_date must be after current end_date")
    lease["end_date"] = new_end_raw
    touch(lease)
    return ok(public(lease), 200)


@app.route("/leases/<rid>/terminate", methods=["POST"])
def terminate_lease(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    lease = get_or_404("lease", rid)
    if lease["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", 409, "lease not ACTIVE")
    lease["status"] = "TERMINATED"
    touch(lease)
    stall = STORE["stall"].get(lease["stall_id"])
    if stall is not None:
        recompute_posture(stall)
    # deposit forfeiture
    today = clock().date()
    ed = parse_date(lease["end_date"])
    sd = parse_date(lease["start_date"])
    deposit = lease["security_deposit_cents"]
    if today >= ed:
        refund = deposit
    else:
        remaining_days = (ed - today).days + 1
        term_days = (ed - sd).days + 1
        forfeit = rhu(Decimal(deposit) * Decimal(remaining_days) / Decimal(term_days))
        refund = deposit - forfeit
    return ok({"lease": public(lease), "deposit_refund_cents": refund}, 200)


# ===========================================================================
# HealthPermit
# ===========================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    _, role = authenticate()
    authorize(role, {"HealthInspector"})
    body = get_body()
    if "stall_id" in body and body["stall_id"] is not None:
        fk_exists("stall", body["stall_id"])
    stall_id = req_str(body, "stall_id")
    fk_exists("stall", stall_id)
    permit_number = req_str(body, "permit_number")
    expires_raw = req_str(body, "expires_on")
    try:
        parse_date(expires_raw)
    except (ValueError, TypeError):
        bad_request("invalid expires_on")
    rec = make("permit", {
        "stall_id": stall_id,
        "permit_number": permit_number,
        "issued_on": None,
        "expires_on": expires_raw,
        "status": "PENDING",
    })
    return ok(public(rec), 201)


@app.route("/permits/<rid>", methods=["GET"])
def get_permit(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("permit", rid)), 200)


@app.route("/permits/<rid>/issue", methods=["POST"])
def issue_permit(rid):
    _, role = authenticate()
    authorize(role, {"HealthInspector"})
    permit = get_or_404("permit", rid)
    if permit["status"] != "PENDING":
        raise APIError("ERR_INVALID_STATE", 409, "permit not PENDING")
    permit["issued_on"] = clock().date().isoformat()
    permit["status"] = "ISSUED"
    touch(permit)
    stall = STORE["stall"].get(permit["stall_id"])
    if stall is not None:
        recompute_posture(stall)
    return ok(public(permit), 200)


@app.route("/permits/<rid>/revoke", methods=["POST"])
def revoke_permit(rid):
    _, role = authenticate()
    authorize(role, {"HealthInspector"})
    permit = get_or_404("permit", rid)
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise APIError("ERR_INVALID_STATE", 409, "permit not ISSUED/SUSPENDED")
    permit["status"] = "REVOKED"
    touch(permit)
    stall = STORE["stall"].get(permit["stall_id"])
    if stall is not None:
        recompute_posture(stall)
    return ok(public(permit), 200)


# ===========================================================================
# Inspection
# ===========================================================================
@app.route("/inspections", methods=["POST"])
def create_inspection():
    _, role = authenticate()
    authorize(role, {"HealthInspector"})
    body = get_body()
    if "stall_id" in body and body["stall_id"] is not None:
        fk_exists("stall", body["stall_id"])
    stall_id = req_str(body, "stall_id")
    fk_exists("stall", stall_id)
    scheduled_raw = req_str(body, "scheduled_for")
    try:
        parse_iso_dt(scheduled_raw)
    except (ValueError, TypeError):
        bad_request("invalid scheduled_for")
    rec = make("inspection", {
        "stall_id": stall_id,
        "scheduled_for": scheduled_raw,
        "conducted_at": None,
        "score": None,
        "result": None,
        "status": "SCHEDULED",
    })
    return ok(public(rec), 201)


@app.route("/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("inspection", rid)), 200)


@app.route("/inspections/<rid>/conduct", methods=["POST"])
def conduct_inspection(rid):
    _, role = authenticate()
    authorize(role, {"HealthInspector"})
    insp = get_or_404("inspection", rid)
    if insp["status"] != "SCHEDULED":
        raise APIError("ERR_INVALID_STATE", 409, "inspection not SCHEDULED")
    body = get_body()
    score = req_int(body, "score", minimum=0, maximum=100)
    insp["conducted_at"] = fmt_dt(clock())
    if score >= 85:
        result = "PASS"
    elif score >= 70:
        result = "CONDITIONAL"
    else:
        result = "FAIL"
    insp["score"] = score
    insp["result"] = result
    insp["status"] = "CONDUCTED"
    touch(insp)
    stall = STORE["stall"].get(insp["stall_id"])
    if stall is not None:
        if result == "FAIL":
            permit = latest_permit_of_stall(stall["id"])
            if permit is not None and permit["status"] == "ISSUED":
                permit["status"] = "SUSPENDED"
                touch(permit)
            recompute_posture(stall)
            if stall["operational_posture"] == "SUSPENDED":
                reject_orders_and_release_seating(stall)
        elif result == "PASS":
            permit = latest_permit_of_stall(stall["id"])
            if permit is not None and permit["status"] == "SUSPENDED":
                permit["status"] = "ISSUED"
                touch(permit)
            recompute_posture(stall)
        else:  # CONDITIONAL
            recompute_posture(stall)
    return ok(public(insp), 200)


# ===========================================================================
# Order
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    authorize(role, {"POSOperator"})
    body = get_body()
    if "food_hall_id" in body and body["food_hall_id"] is not None:
        fk_exists("food_hall", body["food_hall_id"])
    if "stall_id" in body and body["stall_id"] is not None:
        fk_exists("stall", body["stall_id"])
    food_hall_id = req_str(body, "food_hall_id")
    hall = fk_exists("food_hall", food_hall_id)
    stall_id = req_str(body, "stall_id")
    stall = fk_exists("stall", stall_id)
    gross = req_int(body, "gross_amount_cents", minimum=1)
    item_count = req_int(body, "item_count", minimum=1)
    # routing checks
    if stall["food_hall_id"] != food_hall_id:
        raise APIError("ERR_STALL_NOT_IN_HALL", 409, "stall does not belong to the hall")
    if stall["operational_posture"] == "SUSPENDED":
        raise APIError("ERR_STALL_SUSPENDED", 409, "stall is SUSPENDED")
    c = clock()
    minute = c.hour * 60 + c.minute
    lower = max(stall["open_minutes"], hall["hall_open_minutes"])
    upper = min(stall["close_minutes"], hall["hall_close_minutes"])
    if not (lower <= minute < upper):
        raise APIError("ERR_OUTSIDE_OPERATING_HOURS", 409, "outside operating hours")
    rec = make("order", {
        "food_hall_id": food_hall_id,
        "stall_id": stall_id,
        "gross_amount_cents": gross,
        "item_count": item_count,
        "placed_at": fmt_dt(c),
        "status": "ROUTED",
    })
    return ok(public(rec), 201)


@app.route("/orders/<rid>", methods=["GET"])
def get_order(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("order", rid)), 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    items = list(STORE["order"].values())
    for key in ("stall_id", "food_hall_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    return list_response(items)


def _vendor_owns_order(uid, order):
    stall = STORE["stall"].get(order["stall_id"])
    if stall is None or stall.get("current_vendor_id") != uid:
        raise APIError("ERR_UNAUTHORIZED", 403, "acting vendor does not own this stall")


@app.route("/orders/<rid>/accept", methods=["POST"])
def accept_order(rid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    order = get_or_404("order", rid)
    _vendor_owns_order(uid, order)
    if order["status"] != "ROUTED":
        raise APIError("ERR_INVALID_STATE", 409, "order not ROUTED")
    order["status"] = "ACCEPTED"
    touch(order)
    return ok(public(order), 200)


@app.route("/orders/<rid>/fulfill", methods=["POST"])
def fulfill_order(rid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    order = get_or_404("order", rid)
    _vendor_owns_order(uid, order)
    if order["status"] != "ACCEPTED":
        raise APIError("ERR_INVALID_STATE", 409, "order not ACCEPTED")
    order["status"] = "FULFILLED"
    touch(order)
    return ok(public(order), 200)


@app.route("/orders/<rid>/reject", methods=["POST"])
def reject_order(rid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    order = get_or_404("order", rid)
    _vendor_owns_order(uid, order)
    if order["status"] not in ("ROUTED", "ACCEPTED"):
        raise APIError("ERR_INVALID_STATE", 409, "order not ROUTED/ACCEPTED")
    order["status"] = "REJECTED"
    touch(order)
    release_order_seating(order["id"])
    return ok(public(order), 200)


# ===========================================================================
# SeatingAllocation
# ===========================================================================
def concurrent_seats(food_hall_id, start_dt, end_dt, exclude_id=None):
    total = 0
    for a in STORE["seating"].values():
        if a["food_hall_id"] != food_hall_id or a["status"] != "RESERVED":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        a_start = parse_iso_dt(a["start_time"])
        a_end = parse_iso_dt(a["end_time"])
        # half-open overlap
        if a_start < end_dt and start_dt < a_end:
            total += a["seats"]
    return total


@app.route("/seating-allocations", methods=["POST"])
def create_seating():
    _, role = authenticate()
    authorize(role, {"POSOperator"})
    body = get_body()
    if "food_hall_id" in body and body["food_hall_id"] is not None:
        fk_exists("food_hall", body["food_hall_id"])
    order_id = body.get("order_id")
    if order_id is not None:
        fk_exists("order", order_id)
    food_hall_id = req_str(body, "food_hall_id")
    hall = fk_exists("food_hall", food_hall_id)
    seats = req_int(body, "seats", minimum=1)
    start_raw = req_str(body, "start_time")
    end_raw = req_str(body, "end_time")
    try:
        start_dt = parse_iso_dt(start_raw)
        end_dt = parse_iso_dt(end_raw)
    except (ValueError, TypeError):
        bad_request("invalid start_time/end_time")
    if start_dt >= end_dt:
        raise APIError("ERR_INTERVAL_INVALID", 422, "start_time must be before end_time")
    used = concurrent_seats(food_hall_id, start_dt, end_dt)
    if used + seats > hall["total_seating_capacity"]:
        raise APIError("ERR_SEATING_CAPACITY_EXCEEDED", 409, "seating capacity exceeded")
    rec = make("seating", {
        "food_hall_id": food_hall_id,
        "order_id": order_id,
        "seats": seats,
        "start_time": start_raw,
        "end_time": end_raw,
        "status": "RESERVED",
    })
    return ok(public(rec), 201)


@app.route("/seating-allocations/<rid>", methods=["GET"])
def get_seating(rid):
    _, role = authenticate()
    authorize(role, {"HallManager", "POSOperator"})
    return ok(public(get_or_404("seating", rid)), 200)


@app.route("/seating-allocations", methods=["GET"])
def list_seating():
    _, role = authenticate()
    authorize(role, {"HallManager", "POSOperator"})
    items = list(STORE["seating"].values())
    for key in ("food_hall_id", "order_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    return list_response(items)


@app.route("/seating-allocations/<rid>/release", methods=["POST"])
def release_seating(rid):
    _, role = authenticate()
    authorize(role, {"POSOperator"})
    a = get_or_404("seating", rid)
    if a["status"] != "RESERVED":
        raise APIError("ERR_INVALID_STATE", 409, "allocation not RESERVED")
    a["status"] = "RELEASED"
    touch(a)
    return ok(public(a), 200)


# ===========================================================================
# MarketingEvent
# ===========================================================================
@app.route("/marketing-events", methods=["POST"])
def create_event():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    if "food_hall_id" in body and body["food_hall_id"] is not None:
        fk_exists("food_hall", body["food_hall_id"])
    food_hall_id = req_str(body, "food_hall_id")
    fk_exists("food_hall", food_hall_id)
    name = req_str(body, "name")
    start_raw = req_str(body, "start_time")
    end_raw = req_str(body, "end_time")
    try:
        start_dt = parse_iso_dt(start_raw)
        end_dt = parse_iso_dt(end_raw)
    except (ValueError, TypeError):
        bad_request("invalid start_time/end_time")
    if start_dt >= end_dt:
        raise APIError("ERR_INTERVAL_INVALID", 422, "start_time must be before end_time")
    reserved_capacity = req_int(body, "reserved_capacity", minimum=1)
    expected_footfall = req_int(body, "expected_footfall", minimum=0)
    rec = make("event", {
        "food_hall_id": food_hall_id,
        "name": name,
        "start_time": start_raw,
        "end_time": end_raw,
        "reserved_capacity": reserved_capacity,
        "expected_footfall": expected_footfall,
        "status": "PLANNED",
    })
    return ok(public(rec), 201)


@app.route("/marketing-events/<rid>", methods=["GET"])
def get_event(rid):
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    return ok(public(get_or_404("event", rid)), 200)


@app.route("/marketing-events", methods=["GET"])
def list_events():
    _, role = authenticate()
    authorize(role, VALID_ROLES)
    items = list(STORE["event"].values())
    for key in ("food_hall_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    return list_response(items)


@app.route("/marketing-events/<rid>/schedule", methods=["POST"])
def schedule_event(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    event = get_or_404("event", rid)
    if event["status"] != "PLANNED":
        raise APIError("ERR_INVALID_STATE", 409, "event not PLANNED")
    hall = STORE["food_hall"].get(event["food_hall_id"])
    if event["reserved_capacity"] > hall["common_area_capacity"]:
        raise APIError("ERR_COMMON_AREA_CAPACITY_EXCEEDED", 409, "reserved_capacity exceeds common area")
    buf = timedelta(minutes=hall["event_buffer_minutes"])
    c_start = parse_iso_dt(event["start_time"])
    c_end = parse_iso_dt(event["end_time"])
    for other in STORE["event"].values():
        if other["id"] == event["id"] or other["food_hall_id"] != event["food_hall_id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        e_start = parse_iso_dt(other["start_time"])
        e_end = parse_iso_dt(other["end_time"])
        if c_start < e_end + buf and e_start < c_end + buf:
            raise APIError("ERR_EVENT_TIME_CONFLICT", 409, "event conflicts with buffer window")
    event["status"] = "SCHEDULED"
    touch(event)
    return ok(public(event), 200)


@app.route("/marketing-events/<rid>/cancel", methods=["POST"])
def cancel_event(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    event = get_or_404("event", rid)
    if event["status"] not in ("PLANNED", "SCHEDULED"):
        raise APIError("ERR_INVALID_STATE", 409, "event not PLANNED/SCHEDULED")
    event["status"] = "CANCELLED"
    touch(event)
    return ok(public(event), 200)


# ===========================================================================
# Settlement
# ===========================================================================
@app.route("/settlements", methods=["POST"])
def create_settlement():
    _, role = authenticate()
    authorize(role, {"HallManager"})
    body = get_body()
    if "lease_id" in body and body["lease_id"] is not None:
        fk_exists("lease", body["lease_id"])
    lease_id = req_str(body, "lease_id")
    lease = fk_exists("lease", lease_id)
    ps_raw = req_str(body, "period_start")
    pe_raw = req_str(body, "period_end")
    try:
        ps = parse_date(ps_raw)
        pe = parse_date(pe_raw)
    except (ValueError, TypeError):
        bad_request("invalid period dates")
    if ps > pe:
        bad_request("period_start must be <= period_end")
    expected = body.get("expected_lease_version")
    if not is_int(expected):
        bad_request("expected_lease_version is required")
    # OCC
    if expected != lease["version"]:
        raise APIError("ERR_STALE_LEASE_VERSION", 412, "lease version mismatch")
    S, base, pct, total = compute_rent(lease, ps, pe, {"ACCEPTED", "FULFILLED"})
    # supersede prior PROVISIONAL settlements for same lease+period
    for other in STORE["settlement"].values():
        if other["lease_id"] == lease_id and other["status"] == "PROVISIONAL" \
                and other["period_start"] == ps_raw and other["period_end"] == pe_raw:
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(lease)  # bump lease version on successful create
    rec = make("settlement", {
        "lease_id": lease_id,
        "period_start": ps_raw,
        "period_end": pe_raw,
        "gross_sales_cents": S,
        "base_rent_charged_cents": base,
        "percentage_rent_cents": pct,
        "total_rent_cents": total,
        "status": "PROVISIONAL",
    })
    return ok(public(rec), 201)


@app.route("/settlements/<rid>", methods=["GET"])
def get_settlement(rid):
    _, role = authenticate()
    authorize(role, {"HallManager", "Vendor"})
    return ok(public(get_or_404("settlement", rid)), 200)


@app.route("/settlements", methods=["GET"])
def list_settlements():
    _, role = authenticate()
    authorize(role, {"HallManager", "Vendor"})
    items = list(STORE["settlement"].values())
    for key in ("lease_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    return list_response(items)


@app.route("/settlements/<rid>/finalize", methods=["POST"])
def finalize_settlement(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    stl = get_or_404("settlement", rid)
    if stl["status"] != "PROVISIONAL":
        raise APIError("ERR_SETTLEMENT_NOT_PROVISIONAL", 409, "settlement not PROVISIONAL")
    lease = STORE["lease"].get(stl["lease_id"])
    ps = parse_date(stl["period_start"])
    pe = parse_date(stl["period_end"])
    S, base, pct, total = compute_rent(lease, ps, pe, {"FULFILLED"})
    stl["gross_sales_cents"] = S
    stl["base_rent_charged_cents"] = base
    stl["percentage_rent_cents"] = pct
    stl["total_rent_cents"] = total
    stl["status"] = "FINALIZED"
    touch(stl)
    lease["outstanding_balance_cents"] += total
    touch(lease)
    return ok(public(stl), 200)


@app.route("/settlements/<rid>/dispute", methods=["POST"])
def dispute_settlement(rid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    stl = get_or_404("settlement", rid)
    lease = STORE["lease"].get(stl["lease_id"])
    if lease is None or lease["vendor_id"] != uid:
        raise APIError("ERR_UNAUTHORIZED", 403, "acting vendor does not own this settlement")
    if stl["status"] != "PROVISIONAL":
        raise APIError("ERR_SETTLEMENT_NOT_PROVISIONAL", 409, "settlement not PROVISIONAL")
    stl["status"] = "DISPUTED"
    touch(stl)
    return ok(public(stl), 200)


@app.route("/settlements/<rid>/resolve-dispute", methods=["POST"])
def resolve_dispute(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    stl = get_or_404("settlement", rid)
    if stl["status"] != "DISPUTED":
        raise APIError("ERR_INVALID_STATE", 409, "settlement not DISPUTED")
    stl["status"] = "PROVISIONAL"
    touch(stl)
    return ok(public(stl), 200)


@app.route("/settlements/<rid>/void", methods=["POST"])
def void_settlement(rid):
    _, role = authenticate()
    authorize(role, {"HallManager"})
    stl = get_or_404("settlement", rid)
    if stl["status"] != "FINALIZED":
        raise APIError("ERR_SETTLEMENT_NOT_PROVISIONAL", 409, "settlement not FINALIZED")
    lease = STORE["lease"].get(stl["lease_id"])
    stl["status"] = "VOIDED"
    touch(stl)
    lease["outstanding_balance_cents"] -= stl["total_rent_cents"]
    touch(lease)
    return ok(public(stl), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
