"""Core infrastructure: logical clock, envelope, errors, store, auth, helpers."""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ============================================================ logical clock
CLOCK = {"dt": datetime(2026, 5, 1, tzinfo=timezone.utc)}

def clock():
    return CLOCK["dt"]

def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def parse_dt(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")

def valid_period(p):
    return isinstance(p, str) and bool(PERIOD_RE.match(p))

def period_bounds(p):
    y, m = int(p[:4]), int(p[5:7])
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end

# ============================================================ errors
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message

def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)

def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)

def forbidden(msg="Forbidden"):
    return ApiError("ERR_FORBIDDEN", 403, msg)

def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)

# ============================================================ store (in-memory only)
STORE = {
    "clients": {}, "plans": {}, "revisions": {}, "bom_lines": {},
    "components": {}, "events": {}, "batches": {}, "subscribers": {},
    "runs": {}, "shipments": {}, "waves": {}, "return_cases": {},
    "statements": {},
}
SEQ = {"n": 0}

def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]

def base_record():
    t = iso(clock())
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t,
            "version": 1, "_seq": next_seq()}

def light_record():
    # KitBOMLine / InventoryEvent: id + created_at only
    return {"id": str(uuid.uuid4()), "created_at": iso(clock()), "_seq": next_seq()}

def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = iso(clock())

def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}

# ============================================================ envelope
def req_meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex,
            "api_request_timestamp": iso(clock())}

def ok(data, rtype="object", status=200, page=None):
    body = {"meta": req_meta(), "response_type": rtype, "data": data}
    if page is not None:
        body["meta"].update(page)
    return jsonify(body), status

def error_body(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status

# ============================================================ auth
ROLES = {"PlatformAdmin", "ClientOps", "WarehouseOps", "BillingAdmin", "CustomerService"}

def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unknown X-User-Role / X-User-ID header")
    return uid, role

def require_roles(*allowed):
    uid, role = actor()
    if role not in allowed:
        raise forbidden("Role not permitted on this endpoint")
    return uid, role

# ============================================================ ownership chains
def owner_of_plan(plan):
    return plan["client_id"]

def owner_of_revision(rev):
    return STORE["plans"][rev["plan_id"]]["client_id"]

def owner_of_batch(b):
    return STORE["plans"][b["plan_id"]]["client_id"]

def owner_of_subscriber(s):
    return STORE["plans"][s["plan_id"]]["client_id"]

def owner_of_run(r):
    return STORE["plans"][r["plan_id"]]["client_id"]

def owner_of_shipment(sh):
    return owner_of_subscriber(STORE["subscribers"][sh["subscriber_id"]])

def owner_of_case(rc):
    return owner_of_shipment(STORE["shipments"][rc["shipment_id"]])

def check_own(uid, role, owner_client_id):
    if role == "ClientOps" and uid != owner_client_id:
        raise forbidden("ClientOps may only act on their own client's resources")

# ============================================================ request body helpers
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)

def req_field(b, name):
    if name not in b or b[name] is None:
        raise bad_request(f"Missing required field: {name}")
    return b[name]

def req_str(b, name, allow_empty=False):
    v = req_field(b, name)
    if not isinstance(v, str) or (not allow_empty and not v):
        raise bad_request(f"Field {name} must be a string")
    return v

def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise bad_request(f"Field {name} must be a string")
    return v

def req_int(b, name):
    v = req_field(b, name)
    if not is_int(v):
        raise bad_request(f"Field {name} must be an integer")
    return v

def req_enum(b, name, allowed):
    v = req_field(b, name)
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"Field {name} must be one of {sorted(allowed)}")
    return v

# ============================================================ pagination
def page_params():
    lim, off = 10, 0
    raw_lim = request.args.get("limit")
    raw_off = request.args.get("offset")
    if raw_lim is not None:
        try:
            lim = int(raw_lim)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if lim < 1:
            lim = 1
        if lim > 100:
            lim = 100
    if raw_off is not None:
        try:
            off = int(raw_off)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if off < 0:
            off = 0
    return lim, off

def list_resp(records, serializer):
    records = sorted(records, key=lambda r: r["_seq"])
    lim, off = page_params()
    total = len(records)
    page = records[off:off + lim]
    meta = {"limit": lim, "offset": off, "total_count": total,
            "has_more": off + len(page) < total}
    return ok([serializer(r) for r in page], "array", 200, meta)

# ============================================================ domain lookups
def get_or_404(kind, rid):
    rec = STORE[kind].get(rid)
    if rec is None:
        raise not_found(f"{kind[:-1]} {rid} not found")
    return rec

def lines_of_revision(revision_id):
    return [l for l in STORE["bom_lines"].values() if l["revision_id"] == revision_id]

def subs_of_plan(plan_id):
    return [s for s in STORE["subscribers"].values() if s["plan_id"] == plan_id]

def shipments_of_run(run_id):
    return [s for s in STORE["shipments"].values() if s["run_id"] == run_id]

def find_statement(client_id, period):
    for st in STORE["statements"].values():
        if st["client_id"] == client_id and st["period"] == period:
            return st
    return None

# ============================================================ component derived figures
def comp_available(c):
    return c["on_hand_units"] - c["reserved_units"]

def comp_draft_demand(component_id):
    demand = 0
    for r in STORE["runs"].values():
        if r["status"] != "DRAFT":
            continue
        plan = STORE["plans"][r["plan_id"]]
        arid = plan.get("active_revision_id")
        if not arid:
            continue
        for line in lines_of_revision(arid):
            if line["component_id"] == component_id:
                active = sum(1 for s in subs_of_plan(plan["id"]) if s["status"] == "ACTIVE")
                demand += line["qty_per_box"] * active
    return demand

def ser_component(c):
    d = pub(c)
    avail = comp_available(c)
    d["available_units"] = avail
    d["projected_available_units"] = avail - comp_draft_demand(c["id"])
    d["stock_status"] = "LOW" if avail <= c["reorder_point_units"] else "OK"
    return d

def ser_wave(w):
    d = pub(w)
    d["assigned_count"] = sum(
        1 for s in STORE["shipments"].values()
        if s["wave_id"] == w["id"] and s["fulfill_status"] in ("ASSIGNED", "MANIFESTED"))
    return d

# ============================================================ inventory events
def append_event(component_id, run_id, event_type, delta, note=None):
    rec = light_record()
    rec.update({"component_id": component_id, "run_id": run_id,
                "event_type": event_type, "quantity_delta": delta, "note": note})
    STORE["events"][rec["id"]] = rec
    return rec

# ============================================================ statement calculation
def compute_statement(st, variant):
    """Return dict of computed amounts for the statement."""
    client_id, period = st["client_id"], st["period"]
    run_set = [r for r in STORE["runs"].values()
               if STORE["plans"][r["plan_id"]]["client_id"] == client_id
               and r["period"] == period and r["status"] in ("KITTED", "CLOSED")]
    key = "planned_box_count" if variant == "provisional" else "kitted_box_count"
    basis = sum(r[key] for r in run_set)
    discount = 10 if basis >= 500 else (5 if basis >= 200 else 0)
    box_charge = 0
    for r in run_set:
        plan = STORE["plans"][r["plan_id"]]
        line = (Decimal(plan["price_per_box_cents"]) * r[key] * (100 - discount)
                / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        box_charge += int(line)
    run_ids = {r["id"] for r in run_set}
    postage = sum(s["postage_cents"] for s in STORE["shipments"].values()
                  if s["run_id"] in run_ids and s["label_status"] == "PURCHASED")
    refund = 0
    for rc in STORE["return_cases"].values():
        if rc["status"] == "RESOLVED" and rc["resolution_applied"] == "REFUNDED":
            sh = STORE["shipments"].get(rc["shipment_id"])
            if sh and sh["run_id"] in run_ids:
                refund += rc["credit_cents"]
    net = box_charge + postage - refund - st["adjustment_credit_cents"]
    return {"box_charge_cents": box_charge, "postage_cents": postage,
            "refund_credit_cents": refund, "discount_pct": discount,
            "net_cents": net}

def recompute_provisional(st):
    """Full provisional recompute; bumps version only if amounts changed."""
    if st is None or st["status"] != "PROVISIONAL":
        return
    new = compute_statement(st, "provisional")
    if any(st[k] != v for k, v in new.items()):
        st.update(new)
        touch(st)

def statement_for_run(run):
    plan = STORE["plans"][run["plan_id"]]
    return find_statement(plan["client_id"], run["period"])

def recompute_statements_for_shipments(shipment_list):
    seen = set()
    for sh in shipment_list:
        run = STORE["runs"].get(sh["run_id"])
        if not run:
            continue
        st = statement_for_run(run)
        if st and st["id"] not in seen:
            seen.add(st["id"])
            recompute_provisional(st)

# ============================================================ postage
SERVICE_BASE = {"GROUND": 320, "EXPRESS": 745}
ZONE_RATE = {1: 25, 2: 40, 3: 55, 4: 75, 5: 95, 6: 120, 7: 150, 8: 185}
MIN_CHARGE = {"GROUND": 450, "EXPRESS": 990}
SLAB_GRAMS = 500
REMOTE_ZONE_MIN = 5
EXPRESS_REMOTE_SURCHARGE = 200

def postage_for(wave, subscriber, plan):
    slabs = -(-plan["shipping_weight_grams"] // SLAB_GRAMS)  # ceil
    raw = SERVICE_BASE[wave["service_level"]] + ZONE_RATE[subscriber["zone"]] * slabs
    p = max(MIN_CHARGE[wave["service_level"]], raw)
    if wave["service_level"] == "EXPRESS" and subscriber["zone"] >= REMOTE_ZONE_MIN:
        p += EXPRESS_REMOTE_SURCHARGE
    return p
