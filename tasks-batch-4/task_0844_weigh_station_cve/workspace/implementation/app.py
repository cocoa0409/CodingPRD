"""
Weigh-Station & Commercial-Vehicle Enforcement (CVE) API — Python/Flask.

In-memory only. The store starts empty on every boot. Every entity a test needs
is created via the declared API surface. A single global lock serializes all
mutating handlers so optimistic-concurrency races resolve deterministically.
"""
import os
import re
import uuid
import random
import string
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §constants / PRD §2.7, §3)
# ---------------------------------------------------------------------------
ISS_REVIEW_THRESHOLD = 10
OOS_ORDER_THRESHOLD = 20
FINE_HOLD_THRESHOLD_CENTS = 100000
FINE_CAP_CENTS = 200000
RATE_T1, RATE_T2, RATE_T3 = 10, 25, 50
FLAT_FINE = {"CREDENTIAL": 25000, "HAZMAT": 100000, "HOS": 50000, "EQUIPMENT": 15000}
ISS_OOS_MULT = Decimal("1.5")
ISS_WINDOW_N = 5
HOS_DRIVING_LIMIT_MIN = 660
HOS_RESET_MIN = 600
DEFAULT_GROSS_WEIGHT_LIMIT_LBS = 80000
DEFAULT_SINGLE_AXLE_LIMIT_LBS = 20000
DEFAULT_ISS_BYPASS_THRESHOLD = 50

ROLES = {"ComplianceAdmin", "Screener", "Inspector", "EnforcementOfficer", "CarrierRep"}
ALL_READ = ["ComplianceAdmin", "Screener", "Inspector", "EnforcementOfficer", "CarrierRep"]

CRED_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "carriers": {}, "drivers": {}, "stations": {}, "bays": {},
    "screenings": {}, "inspections": {}, "violations": {}, "citations": {},
    "duty_logs": {}, "snapshots": {},
}
SEQ = 0

# Logical clock: startup default is 2026-03-01T00:00:00Z
CLOCK = datetime(2026, 3, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def err(error_id, http, message=None):
    raise ApiError(error_id, http, message)


# ---------------------------------------------------------------------------
# Timestamps / ids
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(CLOCK)


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def listing(items):
    return [serialize(i) for i in items]


# ---------------------------------------------------------------------------
# Base fields / mutation
# ---------------------------------------------------------------------------
def base_fields():
    global SEQ
    SEQ += 1
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": SEQ}


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


CARRIER_TRACKED = ["oos_points", "unpaid_fines_cents", "iss_score", "certified_iss_score",
                   "prism_flagged", "registration_hold", "status"]
DRIVER_TRACKED = ["hos_status", "driving_minutes_window", "status"]


def snap(entity, fields):
    return {k: entity[k] for k in fields}


def commit(entity, before, fields):
    if any(entity[k] != before[k] for k in fields):
        touch(entity)


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _isint(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 422, f"'{key}' is required and must be a non-empty string")
    return v


def req_int(body, key):
    v = body.get(key)
    if not _isint(v):
        err("ERR_VALIDATION", 422, f"'{key}' is required and must be an integer")
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, f"'{key}' is required and must be a boolean")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_VALIDATION", 422, f"'{key}' must be one of {sorted(allowed)}")
    return v


def opt_int(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not _isint(v):
        err("ERR_VALIDATION", 422, f"'{key}' must be an integer")
    return v


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, f"'{key}' must be a boolean")
    return v


def opt_str(body, key, default=""):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, f"'{key}' must be a string")
    return v


def opt_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if v not in allowed:
        err("ERR_VALIDATION", 422, f"'{key}' must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, uid, role, body):
        self.uid = uid
        self.role = role
        self.body = body


def endpoint(roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(**path):
            with LOCK:
                try:
                    uid = request.headers.get("X-User-ID")
                    role = request.headers.get("X-User-Role")
                    if not uid or not role or role not in ROLES:
                        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown auth headers")
                    if role not in roles:
                        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
                    ctx = Ctx(uid, role, get_body())
                    return fn(ctx, **path)
                except ApiError as e:
                    body = {"meta": _meta(), "response_type": "error",
                            "data": {"error_id": e.error_id, "message": e.message}}
                    return jsonify(body), e.http
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_carrier(cid):
    c = db["carriers"].get(cid)
    if not c:
        err("ERR_CARRIER_NOT_FOUND", 404, "Carrier not found")
    return c


def get_station(sid):
    s = db["stations"].get(sid)
    if not s:
        err("ERR_STATION_NOT_FOUND", 404, "Station not found")
    return s


def get_bay(bid):
    b = db["bays"].get(bid)
    if not b:
        err("ERR_BAY_NOT_FOUND", 404, "Bay not found")
    return b


def get_driver(did):
    d = db["drivers"].get(did)
    if not d:
        err("ERR_DRIVER_NOT_FOUND", 404, "Driver not found")
    return d


def get_screening(sid):
    s = db["screenings"].get(sid)
    if not s:
        err("ERR_SCREENING_NOT_FOUND", 404, "Screening not found")
    return s


def get_inspection(iid):
    i = db["inspections"].get(iid)
    if not i:
        err("ERR_INSPECTION_NOT_FOUND", 404, "Inspection not found")
    return i


def get_citation(cid):
    c = db["citations"].get(cid)
    if not c:
        err("ERR_CITATION_NOT_FOUND", 404, "Citation not found")
    return c


def violations_of(insp_id):
    return [v for v in db["violations"].values() if v["inspection_id"] == insp_id]


def carrier_of_inspection(insp):
    scr = db["screenings"].get(insp["screening_id"])
    return db["carriers"].get(scr["carrier_id"]) if scr else None


def by_seq(items):
    return sorted(items, key=lambda x: x["_seq"])


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    items = by_seq(items)
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return listing(page), meta


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def rhu(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tiered(excess):
    b1 = min(excess, 2000)
    b2 = min(max(excess - 2000, 0), 3000)
    b3 = max(excess - 5000, 0)
    return b1 * RATE_T1 + b2 * RATE_T2 + b3 * RATE_T3


def overweight_fine(gross_lbs, axle_lbs, gross_limit, axle_limit):
    ge = max(0, gross_lbs - gross_limit)
    ae = max(0, axle_lbs - axle_limit)
    return max(tiered(ge), tiered(ae))


def compute_iss(carrier_id, variant):
    if variant == "provisional":
        statuses = {"IN_PROGRESS", "REINSPECTION", "CLEARED", "OOS_ISSUED"}
    else:
        statuses = {"CLEARED", "OOS_ISSUED"}
    insp = [i for i in db["inspections"].values()
            if i["status"] in statuses
            and (db["screenings"].get(i["screening_id"]) or {}).get("carrier_id") == carrier_id]
    insp = by_seq(insp)
    included = insp[-ISS_WINDOW_N:]
    if not included:
        return 0, 0
    points = []
    for i in included:
        sev = sum(v["severity_weight"] for v in violations_of(i["id"]))
        mult = ISS_OOS_MULT if i["oos_flag"] else Decimal("1")
        raw = Decimal(sev) * mult
        capped = min(raw, Decimal("100"))
        points.append(rhu(capped))
    avg = Decimal(sum(points)) / Decimal(len(included))
    score = rhu(avg)
    score = min(100, max(0, score))
    return score, len(included)


# ---------------------------------------------------------------------------
# Score snapshots + carrier status propagation
# ---------------------------------------------------------------------------
def mint_snapshot(carrier, method):
    if method == "PROVISIONAL":
        score, count = compute_iss(carrier["id"], "provisional")
    else:
        score, count = compute_iss(carrier["id"], "certified")
    for s in db["snapshots"].values():
        if s["carrier_id"] == carrier["id"] and s["is_current"]:
            s["is_current"] = False
            touch(s)
    snapshot = base_fields()
    snapshot.update({
        "carrier_id": carrier["id"], "method": method, "iss_score": score,
        "inspection_count": count, "is_current": True, "computed_at": now_iso(),
    })
    db["snapshots"][snapshot["id"]] = snapshot
    return snapshot


def recompute_provisional(carrier):
    score, _ = compute_iss(carrier["id"], "provisional")
    carrier["iss_score"] = score


def propagate_up(carrier):
    """Upward carrier status transitions after a provisional recompute."""
    entered_review = False
    if carrier["status"] == "ACTIVE" and carrier["iss_score"] >= ISS_REVIEW_THRESHOLD:
        carrier["status"] = "UNDER_REVIEW"
        entered_review = True
    if carrier["oos_points"] >= OOS_ORDER_THRESHOLD and carrier["status"] in ("ACTIVE", "UNDER_REVIEW"):
        carrier["status"] = "OOS_ORDERED"
    if entered_review:
        carrier["prism_flagged"] = True
        mint_snapshot(carrier, "PROVISIONAL")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ComplianceAdmin"])
def set_clock(ctx):
    global CLOCK
    to_iso = ctx.body.get("to_iso8601")
    dt = parse_dt(to_iso)
    if dt is None:
        err("ERR_VALIDATION", 422, "'to_iso8601' must be a valid ISO 8601 timestamp")
    CLOCK = dt
    return ok({}, 200)


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
@app.route("/carriers", methods=["POST"])
@endpoint(["ComplianceAdmin"])
def create_carrier(ctx):
    b = ctx.body
    usdot = req_str(b, "usdot_number")
    legal = req_str(b, "legal_name")
    irp = req_enum(b, "irp_status", CRED_STATUSES)
    ifta = req_enum(b, "ifta_status", CRED_STATUSES)
    ucr = req_enum(b, "ucr_status", CRED_STATUSES)
    if any(c["usdot_number"] == usdot for c in db["carriers"].values()):
        err("ERR_DUPLICATE_USDOT", 409, "usdot_number already registered")
    c = base_fields()
    c.update({
        "usdot_number": usdot, "legal_name": legal, "irp_status": irp,
        "ifta_status": ifta, "ucr_status": ucr, "oos_points": 0,
        "unpaid_fines_cents": 0, "iss_score": 0, "certified_iss_score": 0,
        "prism_flagged": False, "registration_hold": False, "status": "ACTIVE",
    })
    db["carriers"][c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/carriers", methods=["GET"])
@endpoint(ALL_READ)
def list_carriers(ctx):
    items = list(db["carriers"].values())
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/carriers/<cid>", methods=["GET"])
@endpoint(ALL_READ)
def get_carrier_ep(ctx, cid):
    return ok(serialize(get_carrier(cid)), 200)


@app.route("/carriers/<cid>/drivers", methods=["POST"])
@endpoint(["ComplianceAdmin", "CarrierRep"])
def create_driver(ctx, cid):
    carrier = get_carrier(cid)
    if ctx.role == "CarrierRep" and ctx.uid != carrier["id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "CarrierRep does not own this carrier")
    b = ctx.body
    cdl = req_str(b, "cdl_number")
    name = req_str(b, "full_name")
    d = base_fields()
    d.update({
        "carrier_id": carrier["id"], "cdl_number": cdl, "full_name": name,
        "hos_status": "COMPLIANT", "driving_minutes_window": 0, "status": "ACTIVE",
    })
    db["drivers"][d["id"]] = d
    return ok(serialize(d), 201)


@app.route("/carriers/<cid>/drivers", methods=["GET"])
@endpoint(ALL_READ)
def list_drivers(ctx, cid):
    get_carrier(cid)
    items = [d for d in db["drivers"].values() if d["carrier_id"] == cid]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/carriers/<cid>/score-snapshots", methods=["POST"])
@endpoint(["ComplianceAdmin"])
def create_score_snapshot(ctx, cid):
    carrier = get_carrier(cid)
    expected = req_int(ctx.body, "expected_carrier_version")
    if expected != carrier["version"]:
        err("ERR_STALE_CARRIER_VERSION", 412, "expected_carrier_version does not match")
    score, count = compute_iss(carrier["id"], "certified")
    for s in db["snapshots"].values():
        if s["carrier_id"] == carrier["id"] and s["is_current"]:
            s["is_current"] = False
            touch(s)
    snapshot = base_fields()
    snapshot.update({
        "carrier_id": carrier["id"], "method": "CERTIFIED", "iss_score": score,
        "inspection_count": count, "is_current": True, "computed_at": now_iso(),
    })
    db["snapshots"][snapshot["id"]] = snapshot
    carrier["certified_iss_score"] = score
    if (carrier["status"] in ("UNDER_REVIEW", "OOS_ORDERED")
            and score < ISS_REVIEW_THRESHOLD and carrier["oos_points"] < OOS_ORDER_THRESHOLD):
        carrier["status"] = "ACTIVE"
        carrier["prism_flagged"] = False
    touch(carrier)  # certified snapshot always increments carrier version
    return ok(serialize(snapshot), 201)


@app.route("/carriers/<cid>/score-snapshots", methods=["GET"])
@endpoint(ALL_READ)
def list_score_snapshots(ctx, cid):
    get_carrier(cid)
    items = [s for s in db["snapshots"].values() if s["carrier_id"] == cid]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


# ---------------------------------------------------------------------------
# Stations / bays
# ---------------------------------------------------------------------------
@app.route("/stations", methods=["POST"])
@endpoint(["ComplianceAdmin"])
def create_station(ctx):
    b = ctx.body
    name = req_str(b, "name")
    state = req_str(b, "state_code")
    gross = opt_int(b, "gross_weight_limit_lbs", DEFAULT_GROSS_WEIGHT_LIMIT_LBS)
    axle = opt_int(b, "single_axle_limit_lbs", DEFAULT_SINGLE_AXLE_LIMIT_LBS)
    thr = opt_int(b, "iss_bypass_threshold", DEFAULT_ISS_BYPASS_THRESHOLD)
    if not (0 <= thr <= 100):
        err("ERR_VALIDATION", 422, "iss_bypass_threshold must be between 0 and 100")
    s = base_fields()
    s.update({
        "name": name, "state_code": state, "gross_weight_limit_lbs": gross,
        "single_axle_limit_lbs": axle, "iss_bypass_threshold": thr,
    })
    db["stations"][s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/stations/<sid>", methods=["GET"])
@endpoint(ALL_READ)
def get_station_ep(ctx, sid):
    return ok(serialize(get_station(sid)), 200)


@app.route("/stations/<sid>/bays", methods=["POST"])
@endpoint(["ComplianceAdmin"])
def create_bay(ctx, sid):
    station = get_station(sid)
    b = ctx.body
    label = req_str(b, "label")
    status = opt_enum(b, "status", {"AVAILABLE", "OUT_OF_ORDER"}, "AVAILABLE")
    bay = base_fields()
    bay.update({
        "station_id": station["id"], "label": label, "reserved_minutes": 0,
        "status": status,
    })
    db["bays"][bay["id"]] = bay
    return ok(serialize(bay), 201)


@app.route("/stations/<sid>/bays", methods=["GET"])
@endpoint(ALL_READ)
def list_bays(ctx, sid):
    get_station(sid)
    items = [b for b in db["bays"].values() if b["station_id"] == sid]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


# ---------------------------------------------------------------------------
# Drivers / duty logs
# ---------------------------------------------------------------------------
@app.route("/drivers/<did>", methods=["GET"])
@endpoint(ALL_READ)
def get_driver_ep(ctx, did):
    return ok(serialize(get_driver(did)), 200)


def _minutes(a, b):
    return int((b - a).total_seconds() // 60)


@app.route("/drivers/<did>/duty-logs", methods=["POST"])
@endpoint(["CarrierRep", "ComplianceAdmin"])
def create_duty_log(ctx, did):
    driver = get_driver(did)
    if ctx.role == "CarrierRep" and ctx.uid != driver["carrier_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "CarrierRep does not own this driver's carrier")
    b = ctx.body
    entry_type = req_enum(b, "entry_type", {"DRIVING", "ON_DUTY", "OFF_DUTY", "SLEEPER"})
    start = parse_dt(b.get("start_utc"))
    end = parse_dt(b.get("end_utc"))
    if start is None or end is None:
        err("ERR_VALIDATION", 422, "start_utc and end_utc must be valid timestamps")
    if not (end > start):
        err("ERR_VALIDATION", 422, "end_utc must be strictly after start_utc")
    duration = _minutes(start, end)

    existing = [e for e in db["duty_logs"].values() if e["driver_id"] == did]

    # Priority 7 (basis): DRIVING cumulative window limit
    if entry_type == "DRIVING":
        prospective = driver["driving_minutes_window"] + duration
        if prospective > HOS_DRIVING_LIMIT_MIN:
            driver["hos_status"] = "VIOLATION"
            if driver["status"] == "ACTIVE":
                driver["status"] = "OOS"
            touch(driver)
            err("ERR_HOS_DRIVING_LIMIT", 422, "DRIVING would exceed the cumulative driving limit")

    # Priority 9 (temporal): overlap
    for e in existing:
        es, ee = parse_dt(e["start_utc"]), parse_dt(e["end_utc"])
        if es < end and start < ee:
            err("ERR_DUTY_LOG_OVERLAP", 409, "Entry overlaps an existing duty-log entry")

    # Priority 9 (temporal): off-duty reset buffer between driving shifts
    if entry_type == "DRIVING":
        prior_drives = [e for e in existing
                        if e["entry_type"] == "DRIVING" and parse_dt(e["end_utc"]) <= start]
        if prior_drives:
            prev = max(prior_drives, key=lambda e: parse_dt(e["end_utc"]))
            prev_end = parse_dt(prev["end_utc"])
            if prev_end < start:
                offs = [e for e in existing if e["entry_type"] == "OFF_DUTY"
                        and parse_dt(e["start_utc"]) >= prev_end
                        and parse_dt(e["end_utc"]) <= start]
                if offs and not any(_minutes(parse_dt(o["start_utc"]), parse_dt(o["end_utc"])) >= HOS_RESET_MIN
                                    for o in offs):
                    err("ERR_HOS_RESET_REQUIRED", 409,
                        "A new driving shift lacks the required off-duty reset buffer")

    entry = base_fields()
    entry.update({
        "driver_id": did, "entry_type": entry_type,
        "start_utc": b["start_utc"], "end_utc": b["end_utc"],
    })
    db["duty_logs"][entry["id"]] = entry

    before = snap(driver, DRIVER_TRACKED)
    if entry_type == "DRIVING":
        driver["driving_minutes_window"] += duration
    elif entry_type == "OFF_DUTY" and duration >= HOS_RESET_MIN:
        driver["driving_minutes_window"] = 0
        driver["hos_status"] = "COMPLIANT"
        if driver["status"] == "OOS":
            driver["status"] = "ACTIVE"
    commit(driver, before, DRIVER_TRACKED)
    return ok(serialize(entry), 201)


@app.route("/drivers/<did>/duty-logs", methods=["GET"])
@endpoint(ALL_READ)
def list_duty_logs(ctx, did):
    get_driver(did)
    items = [e for e in db["duty_logs"].values() if e["driver_id"] == did]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


# ---------------------------------------------------------------------------
# Screenings
# ---------------------------------------------------------------------------
@app.route("/screenings", methods=["POST"])
@endpoint(["Screener"])
def create_screening(ctx):
    b = ctx.body
    # existence (body FKs, left-to-right)
    station = get_station(b["station_id"]) if isinstance(b.get("station_id"), str) else None
    if station is None:
        err("ERR_VALIDATION", 422, "station_id is required")
    carrier = get_carrier(b["carrier_id"]) if isinstance(b.get("carrier_id"), str) else None
    if carrier is None:
        err("ERR_VALIDATION", 422, "carrier_id is required")
    driver = get_driver(b["driver_id"]) if isinstance(b.get("driver_id"), str) else None
    if driver is None:
        err("ERR_VALIDATION", 422, "driver_id is required")
    # field validation
    plate = req_str(b, "vehicle_plate")
    axle_count = req_int(b, "axle_count")
    if axle_count < 2:
        err("ERR_VALIDATION", 422, "axle_count must be >= 2")
    gross = req_int(b, "gross_weight_lbs")
    heaviest = req_int(b, "heaviest_axle_lbs")
    hazmat = req_bool(b, "hazmat_placarded")
    oversize = opt_bool(b, "oversize", False)

    overweight = (gross > station["gross_weight_limit_lbs"]
                  or heaviest > station["single_axle_limit_lbs"])
    credentials_valid = all(carrier[f] == "ACTIVE"
                            for f in ("irp_status", "ifta_status", "ucr_status"))
    prism = (carrier["status"] != "ACTIVE"
             or carrier["certified_iss_score"] >= station["iss_bypass_threshold"])
    pull_in = prism or overweight or oversize or (not credentials_valid) or hazmat

    if pull_in:
        decision, status = "PULL_IN", "REFERRED"
        if prism:
            reason = "PRISM_TARGET"
        elif overweight:
            reason = "OVERWEIGHT"
        elif oversize:
            reason = "OVERSIZE"
        elif not credentials_valid:
            reason = "CREDENTIAL"
        elif hazmat:
            reason = "HAZMAT"
        else:
            reason = "NONE"
    else:
        decision, status, reason = "BYPASS", "CLEARED", "NONE"

    s = base_fields()
    s.update({
        "station_id": station["id"], "carrier_id": carrier["id"], "driver_id": driver["id"],
        "vehicle_plate": plate, "axle_count": axle_count, "gross_weight_lbs": gross,
        "heaviest_axle_lbs": heaviest, "hazmat_placarded": hazmat, "oversize": oversize,
        "overweight": overweight, "credentials_valid": credentials_valid,
        "decision": decision, "referral_reason": reason, "status": status,
    })
    db["screenings"][s["id"]] = s
    return ok(serialize(s), 201)


@app.route("/screenings", methods=["GET"])
@endpoint(ALL_READ)
def list_screenings(ctx):
    items = list(db["screenings"].values())
    for key in ("station_id", "carrier_id", "driver_id", "status"):
        val = request.args.get(key)
        if val:
            items = [x for x in items if x[key] == val]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/screenings/<sid>", methods=["GET"])
@endpoint(ALL_READ)
def get_screening_ep(ctx, sid):
    return ok(serialize(get_screening(sid)), 200)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
def _window_minutes(insp):
    return _minutes(parse_dt(insp["scheduled_start"]), parse_dt(insp["scheduled_end"]))


def _bay_conflict(bay_id, start, end, exclude_id=None):
    for i in db["inspections"].values():
        if i["bay_id"] != bay_id or i["id"] == exclude_id:
            continue
        if i["status"] not in ("IN_PROGRESS", "REINSPECTION"):
            continue
        istart, iend = parse_dt(i["scheduled_start"]), parse_dt(i["scheduled_end"])
        if start < iend and istart < end:
            return True
    return False


@app.route("/inspections", methods=["POST"])
@endpoint(["Inspector"])
def create_inspection(ctx):
    b = ctx.body
    screening = get_screening(b["screening_id"]) if isinstance(b.get("screening_id"), str) else None
    if screening is None:
        err("ERR_VALIDATION", 422, "screening_id is required")
    bay = get_bay(b["bay_id"]) if isinstance(b.get("bay_id"), str) else None
    if bay is None:
        err("ERR_VALIDATION", 422, "bay_id is required")
    # state
    if screening["status"] != "REFERRED":
        err("ERR_SCREENING_NOT_REFERRED", 409, "Screening is not in REFERRED status")
    # datetimes
    start = parse_dt(b.get("scheduled_start"))
    end = parse_dt(b.get("scheduled_end"))
    if start is None or end is None:
        err("ERR_VALIDATION", 422, "scheduled_start and scheduled_end must be valid timestamps")
    if not (end > start):
        err("ERR_VALIDATION", 422, "scheduled_end must be strictly after scheduled_start")
    # temporal: window conflict
    if _bay_conflict(bay["id"], start, end):
        err("ERR_BAY_WINDOW_CONFLICT", 409, "Bay window overlaps another active window")
    # field validity
    level = req_enum(b, "level", {"LEVEL_I", "LEVEL_II", "LEVEL_III"})
    # bay availability
    if bay["status"] == "OUT_OF_ORDER":
        err("ERR_BAY_UNAVAILABLE", 409, "Bay is out of order")

    insp = base_fields()
    insp.update({
        "screening_id": screening["id"], "driver_id": screening["driver_id"],
        "bay_id": bay["id"], "level": level,
        "scheduled_start": b["scheduled_start"], "scheduled_end": b["scheduled_end"],
        "result": "NONE", "oos_flag": False, "reinspection_count": 0,
        "oos_points_applied": 0, "status": "IN_PROGRESS",
    })
    db["inspections"][insp["id"]] = insp
    bres = bay["reserved_minutes"]
    bay["reserved_minutes"] += _minutes(start, end)
    if bay["reserved_minutes"] != bres:
        touch(bay)
    return ok(serialize(insp), 201)


@app.route("/inspections", methods=["GET"])
@endpoint(ALL_READ)
def list_inspections(ctx):
    items = list(db["inspections"].values())
    for key in ("screening_id", "driver_id", "bay_id", "status"):
        val = request.args.get(key)
        if val:
            items = [x for x in items if x[key] == val]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/inspections/<iid>", methods=["GET"])
@endpoint(ALL_READ)
def get_inspection_ep(ctx, iid):
    return ok(serialize(get_inspection(iid)), 200)


@app.route("/inspections/<iid>/violations", methods=["POST"])
@endpoint(["Inspector"])
def create_violation(ctx, iid):
    insp = get_inspection(iid)
    if insp["status"] not in ("IN_PROGRESS", "REINSPECTION"):
        err("ERR_INSPECTION_INVALID_STATE", 409, "Inspection is not open for violations")
    b = ctx.body
    code = req_str(b, "code")
    category = req_enum(b, "category",
                        {"VEHICLE", "DRIVER", "HAZMAT", "HOS", "CREDENTIAL", "WEIGHT"})
    severity = req_int(b, "severity_weight")
    if not (1 <= severity <= 10):
        err("ERR_VALIDATION", 422, "severity_weight must be between 1 and 10")
    oos = req_bool(b, "oos")
    description = opt_str(b, "description", "")
    v = base_fields()
    v.update({
        "inspection_id": insp["id"], "code": code, "category": category,
        "severity_weight": severity, "oos": oos, "description": description,
    })
    db["violations"][v["id"]] = v
    carrier = carrier_of_inspection(insp)
    if carrier:
        before = snap(carrier, CARRIER_TRACKED)
        recompute_provisional(carrier)
        propagate_up(carrier)
        commit(carrier, before, CARRIER_TRACKED)
    return ok(serialize(v), 201)


@app.route("/inspections/<iid>/violations", methods=["GET"])
@endpoint(ALL_READ)
def list_violations(ctx, iid):
    get_inspection(iid)
    items = [v for v in db["violations"].values() if v["inspection_id"] == iid]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/inspections/<iid>/finalize", methods=["POST"])
@endpoint(["Inspector"])
def finalize_inspection(ctx, iid):
    insp = get_inspection(iid)
    if insp["status"] not in ("IN_PROGRESS", "REINSPECTION"):
        err("ERR_INSPECTION_INVALID_STATE", 409, "Inspection cannot be finalized from its state")
    result = ctx.body.get("result")
    # compliance basis (priority 7) — before generic field validation
    oos_viols = [v for v in violations_of(iid) if v["oos"]]
    if result == "OOS" and not oos_viols:
        err("ERR_NO_OOS_BASIS", 422, "OOS finalize requires at least one OOS violation")
    if result not in ("CLEAR", "OOS"):
        err("ERR_VALIDATION", 422, "result must be CLEAR or OOS")

    carrier = carrier_of_inspection(insp)
    bay = db["bays"].get(insp["bay_id"])
    screening = db["screenings"].get(insp["screening_id"])
    window = _window_minutes(insp)
    cbefore = snap(carrier, CARRIER_TRACKED) if carrier else None
    bres = bay["reserved_minutes"] if bay else None

    cur = insp["status"]
    if cur == "IN_PROGRESS" and result == "CLEAR":
        insp["status"] = "CLEARED"
        insp["result"] = "CLEAR"
        if bay:
            bay["reserved_minutes"] -= window
        if screening and screening["status"] == "REFERRED":
            screening["status"] = "INSPECTED"
            touch(screening)
        if carrier:
            recompute_provisional(carrier)
            propagate_up(carrier)
    elif cur == "IN_PROGRESS" and result == "OOS":
        insp["status"] = "OOS_ISSUED"
        insp["result"] = "OOS"
        insp["oos_flag"] = True
        pts = sum(v["severity_weight"] for v in oos_viols)
        if carrier:
            carrier["oos_points"] += pts
        insp["oos_points_applied"] = pts
        if any(v["category"] in ("DRIVER", "HOS") for v in oos_viols):
            drv = db["drivers"].get(insp["driver_id"])
            if drv and drv["status"] == "ACTIVE":
                drv["status"] = "OOS"
                touch(drv)
        if bay:
            bay["reserved_minutes"] -= window
        if screening and screening["status"] == "REFERRED":
            screening["status"] = "INSPECTED"
            touch(screening)
        if carrier:
            recompute_provisional(carrier)
            propagate_up(carrier)
    elif cur == "REINSPECTION" and result == "CLEAR":
        insp["status"] = "CLEARED"
        insp["result"] = "CLEAR"
        if carrier:
            carrier["oos_points"] -= insp["oos_points_applied"]
        insp["oos_points_applied"] = 0
        if bay:
            bay["reserved_minutes"] -= window
        if carrier:
            recompute_provisional(carrier)
            if (carrier["status"] in ("UNDER_REVIEW", "OOS_ORDERED")
                    and carrier["oos_points"] < OOS_ORDER_THRESHOLD
                    and carrier["certified_iss_score"] < ISS_REVIEW_THRESHOLD):
                carrier["status"] = "ACTIVE"
    elif cur == "REINSPECTION" and result == "OOS":
        insp["status"] = "OOS_ISSUED"
        insp["result"] = "OOS"
        insp["oos_flag"] = True
        if bay:
            bay["reserved_minutes"] -= window

    touch(insp)
    if carrier:
        commit(carrier, cbefore, CARRIER_TRACKED)
    if bay and bay["reserved_minutes"] != bres:
        touch(bay)
    return ok(serialize(insp), 200)


@app.route("/inspections/<iid>/reinspect", methods=["POST"])
@endpoint(["Inspector"])
def reinspect(ctx, iid):
    insp = get_inspection(iid)
    if insp["status"] != "OOS_ISSUED":
        err("ERR_INSPECTION_INVALID_STATE", 409, "Only an OOS_ISSUED inspection can be reinspected")
    start = parse_dt(insp["scheduled_start"])
    end = parse_dt(insp["scheduled_end"])
    if _bay_conflict(insp["bay_id"], start, end, exclude_id=insp["id"]):
        err("ERR_BAY_WINDOW_CONFLICT", 409, "Bay window overlaps another active window")
    bay = db["bays"].get(insp["bay_id"])
    insp["reinspection_count"] += 1
    insp["status"] = "REINSPECTION"
    touch(insp)
    if bay:
        bay["reserved_minutes"] += _minutes(start, end)
        touch(bay)
    return ok(serialize(insp), 200)


@app.route("/inspections/<iid>/cancel", methods=["POST"])
@endpoint(["Inspector"])
def cancel_inspection(ctx, iid):
    insp = get_inspection(iid)
    if insp["status"] != "IN_PROGRESS":
        err("ERR_INSPECTION_INVALID_STATE", 409, "Only an IN_PROGRESS inspection can be cancelled")
    bay = db["bays"].get(insp["bay_id"])
    window = _window_minutes(insp)
    insp["status"] = "CANCELLED"
    touch(insp)
    if bay:
        bres = bay["reserved_minutes"]
        bay["reserved_minutes"] -= window
        if bay["reserved_minutes"] != bres:
            touch(bay)
    carrier = carrier_of_inspection(insp)
    if carrier:
        before = snap(carrier, CARRIER_TRACKED)
        recompute_provisional(carrier)
        commit(carrier, before, CARRIER_TRACKED)
    return ok(serialize(insp), 200)


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------
@app.route("/citations", methods=["POST"])
@endpoint(["EnforcementOfficer"])
def create_citation(ctx):
    b = ctx.body
    insp = get_inspection(b["inspection_id"]) if isinstance(b.get("inspection_id"), str) else None
    if insp is None:
        err("ERR_VALIDATION", 422, "inspection_id is required")
    carrier = get_carrier(b["carrier_id"]) if isinstance(b.get("carrier_id"), str) else None
    if carrier is None:
        err("ERR_VALIDATION", 422, "carrier_id is required")
    screening = db["screenings"].get(insp["screening_id"])
    station = db["stations"].get(screening["station_id"]) if screening else None
    kind = b.get("kind")

    # compliance basis (priority 7)
    if kind == "OVERWEIGHT" and not (screening and screening["overweight"]):
        err("ERR_OVERWEIGHT_BASIS_MISSING", 422, "Screening is not overweight")
    if kind == "HAZMAT" and not any(v["category"] == "HAZMAT" for v in violations_of(insp["id"])):
        err("ERR_HAZMAT_BASIS_MISSING", 422, "Inspection has no HAZMAT-category violation")

    # referential (priority 8)
    if screening and carrier["id"] != screening["carrier_id"]:
        err("ERR_CARRIER_MISMATCH", 409, "carrier_id does not match the inspection's screening carrier")

    # field validity (priority 10)
    kind = req_enum(b, "kind", {"OVERWEIGHT", "CREDENTIAL", "HAZMAT", "HOS", "EQUIPMENT"})

    if kind == "OVERWEIGHT":
        assessed = overweight_fine(screening["gross_weight_lbs"], screening["heaviest_axle_lbs"],
                                   station["gross_weight_limit_lbs"], station["single_axle_limit_lbs"])
    else:
        assessed = FLAT_FINE[kind]

    # fiscal (priority 11)
    if carrier["unpaid_fines_cents"] + assessed >= FINE_CAP_CENTS:
        err("ERR_FINE_CAP_EXCEEDED", 422, "Fine cap would be reached or exceeded")

    c = base_fields()
    c.update({
        "inspection_id": insp["id"], "carrier_id": carrier["id"], "kind": kind,
        "assessed_fine_cents": assessed, "final_fine_cents": 0,
        "certified_gross_lbs": 0, "certified_axle_lbs": 0, "contest_reason": "",
        "issued_by_user_id": ctx.uid, "adjudicated_by_user_id": "", "status": "ASSESSED",
    })
    db["citations"][c["id"]] = c

    before = snap(carrier, CARRIER_TRACKED)
    carrier["unpaid_fines_cents"] += assessed
    if carrier["unpaid_fines_cents"] >= FINE_HOLD_THRESHOLD_CENTS:
        carrier["registration_hold"] = True
    commit(carrier, before, CARRIER_TRACKED)
    return ok(serialize(c), 201)


@app.route("/citations", methods=["GET"])
@endpoint(ALL_READ)
def list_citations(ctx):
    items = list(db["citations"].values())
    for key in ("inspection_id", "carrier_id", "status"):
        val = request.args.get(key)
        if val:
            items = [x for x in items if x[key] == val]
    data, meta = paginate(items)
    return ok(data, 200, "array", meta)


@app.route("/citations/<cid>", methods=["GET"])
@endpoint(ALL_READ)
def get_citation_ep(ctx, cid):
    return ok(serialize(get_citation(cid)), 200)


@app.route("/citations/<cid>/contest", methods=["POST"])
@endpoint(["CarrierRep"])
def contest_citation(ctx, cid):
    citation = get_citation(cid)
    if ctx.uid != citation["carrier_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "CarrierRep does not own this citation")
    if citation["status"] != "ASSESSED":
        err("ERR_CITATION_INVALID_STATE", 409, "Only an ASSESSED citation can be contested")
    reason = req_str(ctx.body, "contest_reason")
    citation["contest_reason"] = reason
    citation["status"] = "CONTESTED"
    touch(citation)
    return ok(serialize(citation), 200)


@app.route("/citations/<cid>/adjudicate", methods=["POST"])
@endpoint(["EnforcementOfficer"])
def adjudicate_citation(ctx, cid):
    citation = get_citation(cid)
    # SoD (priority 5)
    if ctx.uid == citation["issued_by_user_id"]:
        err("ERR_SOD_CONFLICT", 403, "Adjudicating officer must differ from the issuing officer")
    # state (priority 6)
    if citation["status"] != "CONTESTED":
        err("ERR_CITATION_INVALID_STATE", 409, "Only a CONTESTED citation can be adjudicated")
    result = req_enum(ctx.body, "result", {"UPHOLD", "DISMISS"})

    carrier = db["carriers"].get(citation["carrier_id"])
    before = snap(carrier, CARRIER_TRACKED) if carrier else None

    if result == "UPHOLD":
        cgross = opt_int(ctx.body, "certified_gross_lbs", 0)
        caxle = opt_int(ctx.body, "certified_axle_lbs", 0)
        citation["certified_gross_lbs"] = cgross
        citation["certified_axle_lbs"] = caxle
        citation["adjudicated_by_user_id"] = ctx.uid
        if citation["kind"] == "OVERWEIGHT":
            insp = db["inspections"].get(citation["inspection_id"])
            screening = db["screenings"].get(insp["screening_id"]) if insp else None
            station = db["stations"].get(screening["station_id"]) if screening else None
            final = overweight_fine(cgross, caxle,
                                    station["gross_weight_limit_lbs"],
                                    station["single_axle_limit_lbs"])
        else:
            final = citation["assessed_fine_cents"]
        citation["final_fine_cents"] = final
        if carrier:
            carrier["unpaid_fines_cents"] += (final - citation["assessed_fine_cents"])
        citation["status"] = "UPHELD"
    else:  # DISMISS
        citation["adjudicated_by_user_id"] = ctx.uid
        citation["final_fine_cents"] = 0
        if carrier:
            carrier["unpaid_fines_cents"] -= citation["assessed_fine_cents"]
        citation["status"] = "DISMISSED"

    touch(citation)
    if carrier:
        commit(carrier, before, CARRIER_TRACKED)
    return ok(serialize(citation), 200)


@app.route("/citations/<cid>/settle", methods=["POST"])
@endpoint(["CarrierRep"])
def settle_citation(ctx, cid):
    citation = get_citation(cid)
    if ctx.uid != citation["carrier_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "CarrierRep does not own this citation")
    if citation["status"] not in ("ASSESSED", "UPHELD"):
        err("ERR_CITATION_INVALID_STATE", 409, "Only ASSESSED or UPHELD citations can be settled")
    payment = req_int(ctx.body, "payment_cents")
    outstanding = (citation["assessed_fine_cents"] if citation["status"] == "ASSESSED"
                   else citation["final_fine_cents"])
    if payment != outstanding:
        err("ERR_SETTLEMENT_AMOUNT_MISMATCH", 422, "payment_cents must equal the outstanding fine")

    carrier = db["carriers"].get(citation["carrier_id"])
    before = snap(carrier, CARRIER_TRACKED) if carrier else None
    if citation["status"] == "ASSESSED":
        citation["final_fine_cents"] = citation["assessed_fine_cents"]
    if carrier:
        carrier["unpaid_fines_cents"] -= outstanding
    citation["status"] = "SETTLED"
    touch(citation)
    if carrier:
        commit(carrier, before, CARRIER_TRACKED)
    return ok(serialize(citation), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
