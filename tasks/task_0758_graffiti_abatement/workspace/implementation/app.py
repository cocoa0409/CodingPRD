import os
import uuid
import random
import string
from functools import wraps
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)
try:
    app.json.sort_keys = False
except Exception:
    pass

# =====================================================================
# Logical clock
# =====================================================================
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["now"]


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =====================================================================
# In-memory stores (empty at boot — no seeding)
# =====================================================================
property_owners = {}
sites = {}
reports = {}
crews = {}
work_orders = {}
material_reservations = {}
photos = {}
removal_logs = {}
materials = {}
cost_recoveries = {}
notices = {}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# =====================================================================
# Constants
# =====================================================================
ROLES = {
    "Resident", "IntakeClerk", "AbatementCoordinator", "CrewLead",
    "InventoryManager", "PropertyOwnerUser", "ProgramAdmin",
}
ALL_ROLES = set(ROLES)

SEVERITY_BASE = {"LOW": 10, "MEDIUM": 25, "HIGH": 50, "SEVERE": 80}
SURFACE_VISIBILITY = {"SIGN": 1.5, "WALL": 1.2, "VEHICLE": 1.1, "FENCE": 1.0, "SIDEWALK": 0.8}
OFFENSIVE_BONUS = 40
PUBLIC_PRIORITY_ADJ = 5
HOTSPOT_MULT = {"HOTSPOT": 1.5, "MONITORED": 1.2, "NORMAL": 1.0}
SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "SEVERE": 8}
WINDOW_DAYS = 90
LABOR_RATE_CENTS_PER_HOUR = 6500
ADMIN_FEE_PCT = Decimal("0.15")
SITE_BUFFER_HOURS = 24

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PROPERTY_OWNER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_MATERIAL_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_COST_RECOVERY_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CREW_UNAVAILABLE": 409,
    "ERR_RECOVERY_NOT_ASSESSED": 409,
    "ERR_CURE_WINDOW_NOT_ELAPSED": 409,
    "ERR_CREW_NOT_CERTIFIED": 422,
    "ERR_CREW_SCHEDULE_CONFLICT": 409,
    "ERR_SITE_ABATEMENT_BUFFER_CONFLICT": 409,
    "ERR_BEFORE_PHOTO_REQUIRED": 422,
    "ERR_AFTER_PHOTO_REQUIRED": 422,
    "ERR_PRIVATE_SITE_REQUIRES_OWNER": 422,
    "ERR_STALE_SITE_VERSION": 412,
    "ERR_INSUFFICIENT_MATERIAL": 409,
}


# =====================================================================
# Errors & response envelope
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": fmt(clock_now())}


def clean(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def success(data, response_type="object", extra_meta=None, status=200):
    meta = base_meta()
    if extra_meta:
        meta.update(extra_meta)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# =====================================================================
# Auth / authorization
# =====================================================================
def endpoint(allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            g.touched = set()
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers.")
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation.")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# =====================================================================
# Entity helpers
# =====================================================================
def new_common(**fields):
    now = clock_now()
    iso = fmt(now)
    e = {"id": str(uuid.uuid4())}
    e.update(fields)
    e["created_at"] = iso
    e["updated_at"] = iso
    e["version"] = 1
    e["_created"] = now
    e["_seq"] = next_seq()
    return e


def new_audit(**fields):
    now = clock_now()
    iso = fmt(now)
    e = {"id": str(uuid.uuid4())}
    e.update(fields)
    e["created_at"] = iso
    e["_created"] = now
    e["_seq"] = next_seq()
    return e


def touch(ent):
    key = ent["id"]
    ts = getattr(g, "touched", None)
    if ts is None:
        ts = set()
        g.touched = ts
    if key in ts:
        return
    ts.add(key)
    ent["updated_at"] = fmt(clock_now())
    ent["version"] = ent.get("version", 0) + 1


# =====================================================================
# Validation helpers
# =====================================================================
def get_body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", f"Missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", f"Invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", f"Missing or invalid enum: {field}")
    return v


def req_number(body, field):
    v = body.get(field)
    if not is_number(v):
        err("ERR_INVALID_REQUEST", f"Missing or invalid number: {field}")
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", f"Missing or invalid integer: {field}")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", f"Invalid boolean: {field}")
    return v


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_number(v):
        err("ERR_INVALID_REQUEST", f"Invalid number: {field}")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        err("ERR_INVALID_REQUEST", f"Invalid integer: {field}")
    return v


# =====================================================================
# Pagination & listing
# =====================================================================
def get_pagination():
    args = request.args
    try:
        limit = int(args["limit"]) if "limit" in args and args["limit"] != "" else 10
        offset = int(args["offset"]) if "offset" in args and args["offset"] != "" else 0
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", "Invalid pagination parameter.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda e: (e["_created"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    extra = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return success([clean(x) for x in page], "array", extra)


def filter_by(items, field):
    val = request.args.get(field)
    if val is None or val == "":
        return items
    return [x for x in items if str(x.get(field)) == val]


# =====================================================================
# Calculations
# =====================================================================
def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_priority(report, site):
    base = SEVERITY_BASE[report["severity"]]
    vis = SURFACE_VISIBILITY[report["surface_type"]]
    off = OFFENSIVE_BONUS if report["is_offensive"] else 0
    pub = PUBLIC_PRIORITY_ADJ if site["ownership_type"] == "PUBLIC" else 0
    mult = HOTSPOT_MULT[site["status"]]
    raw = (Decimal(base) * Decimal(str(vis)) + Decimal(off) + Decimal(pub)) * Decimal(str(mult))
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_cost(labor_hours, lines, ownership_type):
    # lines: list of (quantity, unit_cost_cents)
    labor = rhu(Decimal(str(labor_hours)) * Decimal(LABOR_RATE_CENTS_PER_HOUR))
    material = 0
    for qty, unit_cost in lines:
        material += rhu(Decimal(str(qty)) * Decimal(unit_cost))
    subtotal = labor + material
    admin = rhu(ADMIN_FEE_PCT * Decimal(subtotal))
    total = labor + material + admin
    recoverable = total if ownership_type == "PRIVATE" else 0
    return labor, material, admin, total, recoverable


def recompute_material_status(m):
    qa = m["quantity_available"]
    if qa <= 0:
        m["status"] = "DEPLETED"
    elif qa <= m["reorder_threshold"]:
        m["status"] = "LOW"
    else:
        m["status"] = "AVAILABLE"


SITE_STATE_FIELDS = [
    "status", "report_count_90d", "open_report_count",
    "hotspot_severity_index_rolling", "hotspot_severity_index_confirmed",
    "outstanding_recovery_cents", "lien_count", "active_notice_id",
]


def site_snapshot(site):
    return {f: site[f] for f in SITE_STATE_FIELDS}


def sync_site(site):
    now = clock_now()
    window_start = now - timedelta(days=WINDOW_DAYS)
    sid = site["id"]
    site_reports = [r for r in reports.values() if r["site_id"] == sid]
    in_window = [r for r in site_reports if window_start <= r["_created"] <= now]
    site["report_count_90d"] = len(in_window)
    site["open_report_count"] = len(
        [r for r in site_reports if r["status"] not in ("REMEDIATED", "CLOSED")]
    )
    site["hotspot_severity_index_rolling"] = sum(SEVERITY_WEIGHT[r["severity"]] for r in in_window)
    site["hotspot_severity_index_confirmed"] = sum(
        SEVERITY_WEIGHT[r["severity"]] for r in in_window if r["status"] == "REMEDIATED"
    )
    c = site["report_count_90d"]
    site["status"] = "HOTSPOT" if c >= 3 else ("MONITORED" if c == 2 else "NORMAL")
    site_crs = [cr for cr in cost_recoveries.values() if cr["site_id"] == sid]
    site["outstanding_recovery_cents"] = sum(
        cr["recoverable_cents"] for cr in site_crs
        if cr["status"] in ("ASSESSED", "DISPUTED", "LIEN_PENDING")
    )
    site["lien_count"] = len([cr for cr in site_crs if cr["status"] == "LIEN_PENDING"])


def reconcile_site(site, snap):
    sync_site(site)
    if any(site[f] != snap[f] for f in SITE_STATE_FIELDS):
        touch(site)


def find_cost_recovery(work_order_id):
    for cr in cost_recoveries.values():
        if cr["work_order_id"] == work_order_id:
            return cr
    return None


def add_removal_log(work_order_id, action, note, logged_by):
    log = new_audit(work_order_id=work_order_id, action=action, note=note, logged_by=logged_by)
    removal_logs[log["id"]] = log
    return log


def release_reservations(work_order_id):
    touched_m = set()
    for r in material_reservations.values():
        if r["work_order_id"] == work_order_id and r["status"] == "RESERVED":
            m = materials[r["material_id"]]
            m["quantity_available"] += r["quantity_reserved"]
            m["quantity_reserved"] -= r["quantity_reserved"]
            recompute_material_status(m)
            if m["id"] not in touched_m:
                touch(m)
                touched_m.add(m["id"])
            r["status"] = "RELEASED"
            touch(r)


# =====================================================================
# Routes
# =====================================================================
@app.get("/")
def root():
    return success({}, "object", status=200)


# ---- Logical clock -------------------------------------------------
@app.post("/_clock/set_current_utc")
@endpoint({"ProgramAdmin"})
def set_clock():
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        err("ERR_INVALID_REQUEST", "Missing to_iso8601.")
    try:
        CLOCK["now"] = parse_iso(raw)
    except Exception:
        err("ERR_INVALID_REQUEST", "Invalid to_iso8601 value.")
    return success({}, "object", status=200)


# ---- Property owners -----------------------------------------------
@app.post("/abatement/property-owners")
@endpoint({"AbatementCoordinator", "ProgramAdmin"})
def create_property_owner():
    body = get_body()
    name = req_str(body, "name")
    mailing_address = req_str(body, "mailing_address")
    contact_email = req_str(body, "contact_email")
    po = new_common(name=name, mailing_address=mailing_address, contact_email=contact_email)
    property_owners[po["id"]] = po
    return success(clean(po), "object", status=201)


@app.get("/abatement/property-owners/<pid>")
@endpoint(ALL_ROLES)
def get_property_owner(pid):
    po = property_owners.get(pid)
    if not po:
        err("ERR_PROPERTY_OWNER_NOT_FOUND", "Property owner not found.")
    return success(clean(po), "object", status=200)


# ---- Sites ---------------------------------------------------------
@app.post("/abatement/sites")
@endpoint({"IntakeClerk", "AbatementCoordinator", "ProgramAdmin"})
def create_site():
    body = get_body()
    ownership_type = req_enum(body, "ownership_type", ("PUBLIC", "PRIVATE"))
    address = req_str(body, "address")
    latitude = req_number(body, "latitude")
    longitude = req_number(body, "longitude")
    property_owner_id = opt_str(body, "property_owner_id", None)
    # existence (priority 4)
    if property_owner_id is not None and property_owner_id not in property_owners:
        err("ERR_PROPERTY_OWNER_NOT_FOUND", "Property owner not found.")
    # business (priority 15)
    if ownership_type == "PRIVATE" and property_owner_id is None:
        err("ERR_PRIVATE_SITE_REQUIRES_OWNER", "PRIVATE site requires a property_owner_id.")
    if ownership_type == "PUBLIC" and property_owner_id is not None:
        err("ERR_PRIVATE_SITE_REQUIRES_OWNER", "PUBLIC site must not carry a property_owner_id.")
    site = new_common(
        address=address, latitude=latitude, longitude=longitude,
        ownership_type=ownership_type,
        property_owner_id=property_owner_id if ownership_type == "PRIVATE" else None,
        status="NORMAL", report_count_90d=0, open_report_count=0,
        hotspot_severity_index_rolling=0, hotspot_severity_index_confirmed=0,
        outstanding_recovery_cents=0, lien_count=0, active_notice_id=None,
    )
    sites[site["id"]] = site
    return success(clean(site), "object", status=201)


@app.get("/abatement/sites/<sid>")
@endpoint(ALL_ROLES)
def get_site(sid):
    site = sites.get(sid)
    if not site:
        err("ERR_SITE_NOT_FOUND", "Site not found.")
    return success(clean(site), "object", status=200)


@app.get("/abatement/sites")
@endpoint(ALL_ROLES)
def list_sites():
    items = list(sites.values())
    items = filter_by(items, "property_owner_id")
    items = filter_by(items, "status")
    return list_response(items)


# ---- Reports -------------------------------------------------------
@app.post("/abatement/reports")
@endpoint({"Resident", "IntakeClerk"})
def create_report():
    body = get_body()
    site_id = req_str(body, "site_id")
    reported_via = req_enum(body, "reported_via", ("PHONE_311", "WEB", "MOBILE_APP"))
    surface_type = req_enum(body, "surface_type", ("WALL", "FENCE", "SIGN", "SIDEWALK", "VEHICLE"))
    severity = req_enum(body, "severity", ("LOW", "MEDIUM", "HIGH", "SEVERE"))
    description = req_str(body, "description")
    is_offensive = opt_bool(body, "is_offensive", False)
    latitude = opt_number(body, "latitude", None)
    longitude = opt_number(body, "longitude", None)
    reporter_contact = opt_str(body, "reporter_contact", None)
    # existence
    site = sites.get(site_id)
    if not site:
        err("ERR_SITE_NOT_FOUND", "Site not found.")
    report = new_common(
        site_id=site_id, reported_via=reported_via, reporter_contact=reporter_contact,
        surface_type=surface_type, severity=severity, is_offensive=is_offensive,
        description=description, latitude=latitude, longitude=longitude,
        priority_score=None, status="SUBMITTED",
    )
    reports[report["id"]] = report
    snap = site_snapshot(site)
    reconcile_site(site, snap)
    return success(clean(report), "object", status=201)


@app.get("/abatement/reports/<rid>")
@endpoint(ALL_ROLES)
def get_report(rid):
    r = reports.get(rid)
    if not r:
        err("ERR_REPORT_NOT_FOUND", "Report not found.")
    return success(clean(r), "object", status=200)


@app.get("/abatement/reports")
@endpoint(ALL_ROLES)
def list_reports():
    items = list(reports.values())
    items = filter_by(items, "site_id")
    items = filter_by(items, "status")
    items = filter_by(items, "severity")
    return list_response(items)


@app.post("/abatement/reports/<rid>/triage")
@endpoint({"IntakeClerk", "AbatementCoordinator"})
def triage_report(rid):
    report = reports.get(rid)
    if not report:
        err("ERR_REPORT_NOT_FOUND", "Report not found.")
    if report["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Report is not SUBMITTED.")
    site = sites[report["site_id"]]
    snap = site_snapshot(site)
    report["priority_score"] = compute_priority(report, site)
    report["status"] = "TRIAGED"
    touch(report)
    reconcile_site(site, snap)
    return success(clean(report), "object", status=200)


# ---- Crews ---------------------------------------------------------
@app.post("/abatement/crews")
@endpoint({"AbatementCoordinator", "ProgramAdmin"})
def create_crew():
    body = get_body()
    name = req_str(body, "name")
    crew_type = req_enum(body, "crew_type", ("CITY", "CONTRACTOR"))
    is_offensive_certified = opt_bool(body, "is_offensive_certified", False)
    crew = new_common(name=name, crew_type=crew_type,
                      is_offensive_certified=is_offensive_certified, status="AVAILABLE")
    crews[crew["id"]] = crew
    return success(clean(crew), "object", status=201)


@app.get("/abatement/crews/<cid>")
@endpoint(ALL_ROLES)
def get_crew(cid):
    c = crews.get(cid)
    if not c:
        err("ERR_CREW_NOT_FOUND", "Crew not found.")
    return success(clean(c), "object", status=200)


# ---- Work orders (dispatch) ----------------------------------------
def wo_site(wo):
    return sites[reports[wo["report_id"]]["site_id"]]


def non_terminal_wos():
    return [w for w in work_orders.values() if w["status"] in ("SCHEDULED", "IN_PROGRESS")]


@app.post("/abatement/work-orders")
@endpoint({"AbatementCoordinator"})
def create_work_order():
    body = get_body()
    report_id = req_str(body, "report_id")
    crew_id = req_str(body, "crew_id")
    scheduled_start = req_str(body, "scheduled_start")
    scheduled_end = req_str(body, "scheduled_end")
    method = req_enum(body, "method", ("PAINT_OVER", "PRESSURE_WASH", "CHEMICAL"))
    estimated_labor_hours = req_number(body, "estimated_labor_hours")
    try:
        start_dt = parse_iso(scheduled_start)
        end_dt = parse_iso(scheduled_end)
    except Exception:
        err("ERR_INVALID_REQUEST", "Invalid scheduled_start/scheduled_end.")
    if not (end_dt > start_dt):
        err("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")
    # material lines well-formedness
    raw_lines = body.get("material_lines", [])
    if raw_lines is None:
        raw_lines = []
    if not isinstance(raw_lines, list):
        err("ERR_INVALID_REQUEST", "material_lines must be a list.")
    parsed_lines = []
    for line in raw_lines:
        if not isinstance(line, dict):
            err("ERR_INVALID_REQUEST", "Invalid material line.")
        mid = line.get("material_id")
        if not isinstance(mid, str) or mid == "":
            err("ERR_INVALID_REQUEST", "Invalid material_id in material line.")
        qty = line.get("quantity", line.get("quantity_reserved"))
        if not is_number(qty) or qty <= 0:
            err("ERR_INVALID_REQUEST", "Invalid quantity in material line.")
        parsed_lines.append((mid, qty))
    # existence (priority 4): report, crew, materials (left to right)
    report = reports.get(report_id)
    if not report:
        err("ERR_REPORT_NOT_FOUND", "Report not found.")
    crew = crews.get(crew_id)
    if not crew:
        err("ERR_CREW_NOT_FOUND", "Crew not found.")
    for mid, _ in parsed_lines:
        if mid not in materials:
            err("ERR_MATERIAL_NOT_FOUND", "Material not found.")
    # state guard (priority 6): report TRIAGED
    if report["status"] != "TRIAGED":
        err("ERR_INVALID_STATE", "Report is not TRIAGED.")
    site = sites[report["site_id"]]
    # business rules in priority order
    # 7 crew available
    if crew["status"] != "AVAILABLE":
        err("ERR_CREW_UNAVAILABLE", "Crew is not AVAILABLE.")
    # 10 offensive certification
    if report["is_offensive"] and not crew["is_offensive_certified"]:
        err("ERR_CREW_NOT_CERTIFIED", "Crew is not offensive-certified.")
    # 11 crew schedule conflict (half-open overlap)
    for o in non_terminal_wos():
        if o["crew_id"] == crew_id:
            if start_dt < o["_end"] and o["_start"] < end_dt:
                err("ERR_CREW_SCHEDULE_CONFLICT", "Crew has a conflicting work order.")
    # 12 site buffer conflict (PRIVATE only)
    if site["ownership_type"] == "PRIVATE":
        buf = timedelta(hours=SITE_BUFFER_HOURS)
        for o in non_terminal_wos():
            if reports[o["report_id"]]["site_id"] == site["id"]:
                if start_dt < o["_end"] + buf and o["_start"] < end_dt + buf:
                    err("ERR_SITE_ABATEMENT_BUFFER_CONFLICT", "Site abatement buffer conflict.")
    # 17 insufficient material (cumulative per material across request)
    agg = {}
    for mid, qty in parsed_lines:
        agg[mid] = agg.get(mid, 0) + qty
    for mid, total_qty in agg.items():
        if total_qty > materials[mid]["quantity_available"]:
            err("ERR_INSUFFICIENT_MATERIAL", "Insufficient material available.")
    # ---- perform cascade ----
    wo = new_common(
        report_id=report_id, crew_id=crew_id,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        method=method, estimated_labor_hours=estimated_labor_hours,
        actual_labor_hours=None, status="SCHEDULED",
    )
    wo["_start"] = start_dt
    wo["_end"] = end_dt
    work_orders[wo["id"]] = wo
    reservations = []
    touched_m = set()
    for mid, qty in parsed_lines:
        m = materials[mid]
        m["quantity_available"] -= qty
        m["quantity_reserved"] += qty
        recompute_material_status(m)
        if m["id"] not in touched_m:
            touch(m)
            touched_m.add(m["id"])
        res = new_common(work_order_id=wo["id"], material_id=mid,
                         quantity_reserved=qty, quantity_consumed=None, status="RESERVED")
        material_reservations[res["id"]] = res
        reservations.append(res)
    labor, material_c, admin, total, recoverable = compute_cost(
        estimated_labor_hours,
        [(r["quantity_reserved"], materials[r["material_id"]]["unit_cost_cents"]) for r in reservations],
        site["ownership_type"],
    )
    cr = new_common(
        site_id=site["id"], work_order_id=wo["id"],
        estimated_cost_cents=total, final_cost_cents=None,
        labor_cost_cents=labor, material_cost_cents=material_c,
        admin_fee_cents=admin, recoverable_cents=recoverable, status="PENDING",
    )
    cost_recoveries[cr["id"]] = cr
    snap = site_snapshot(site)
    report["status"] = "DISPATCHED"
    touch(report)
    reconcile_site(site, snap)
    return success(clean(wo), "object", status=201)


@app.get("/abatement/work-orders/<wid>")
@endpoint(ALL_ROLES)
def get_work_order(wid):
    w = work_orders.get(wid)
    if not w:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    return success(clean(w), "object", status=200)


@app.get("/abatement/work-orders")
@endpoint(ALL_ROLES)
def list_work_orders():
    items = list(work_orders.values())
    items = filter_by(items, "report_id")
    items = filter_by(items, "crew_id")
    items = filter_by(items, "status")
    return list_response(items)


@app.post("/abatement/work-orders/<wid>/start")
@endpoint({"CrewLead"})
def start_work_order(wid):
    wo = work_orders.get(wid)
    if not wo:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    if wo["crew_id"] != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Crew does not own this work order.")
    if wo["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Work order is not SCHEDULED.")
    if not any(p for p in photos.values()
               if p["work_order_id"] == wid and p["phase"] == "BEFORE"):
        err("ERR_BEFORE_PHOTO_REQUIRED", "A BEFORE photo is required to start.")
    report = reports[wo["report_id"]]
    site = sites[report["site_id"]]
    snap = site_snapshot(site)
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    report["status"] = "IN_PROGRESS"
    touch(report)
    crew = crews[wo["crew_id"]]
    crew["status"] = "DISPATCHED"
    touch(crew)
    add_removal_log(wid, "STARTED", None, g.uid)
    reconcile_site(site, snap)
    return success(clean(wo), "object", status=200)


@app.post("/abatement/work-orders/<wid>/complete")
@endpoint({"CrewLead"})
def complete_work_order(wid):
    body = get_body()
    actual_labor_hours = req_number(body, "actual_labor_hours")
    wo = work_orders.get(wid)
    if not wo:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    if wo["crew_id"] != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Crew does not own this work order.")
    if wo["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", "Work order is not IN_PROGRESS.")
    if not any(p for p in photos.values()
               if p["work_order_id"] == wid and p["phase"] == "AFTER"):
        err("ERR_AFTER_PHOTO_REQUIRED", "An AFTER photo is required to complete.")
    report = reports[wo["report_id"]]
    site = sites[report["site_id"]]
    snap = site_snapshot(site)
    wo["status"] = "COMPLETED"
    wo["actual_labor_hours"] = actual_labor_hours
    touch(wo)
    res_list = [r for r in material_reservations.values()
                if r["work_order_id"] == wid and r["status"] == "RESERVED"]
    touched_m = set()
    for r in res_list:
        r["quantity_consumed"] = r["quantity_reserved"]
        r["status"] = "CONSUMED"
        touch(r)
        m = materials[r["material_id"]]
        m["quantity_reserved"] -= r["quantity_reserved"]
        recompute_material_status(m)
        if m["id"] not in touched_m:
            touch(m)
            touched_m.add(m["id"])
    crew = crews[wo["crew_id"]]
    crew["status"] = "AVAILABLE"
    touch(crew)
    # final cost assessment
    cr = find_cost_recovery(wid)
    if cr and cr["status"] == "PENDING":
        labor, material_c, admin, total, recoverable = compute_cost(
            actual_labor_hours,
            [(r["quantity_consumed"], materials[r["material_id"]]["unit_cost_cents"]) for r in res_list],
            site["ownership_type"],
        )
        cr["labor_cost_cents"] = labor
        cr["material_cost_cents"] = material_c
        cr["admin_fee_cents"] = admin
        cr["final_cost_cents"] = total
        cr["recoverable_cents"] = recoverable
        cr["status"] = "ASSESSED"
        touch(cr)
    # report -> REMEDIATED (auto CLOSED for PUBLIC sites)
    if site["ownership_type"] == "PUBLIC":
        report["status"] = "CLOSED"
    else:
        report["status"] = "REMEDIATED"
    touch(report)
    add_removal_log(wid, "COMPLETED", None, g.uid)
    reconcile_site(site, snap)
    return success(clean(wo), "object", status=200)


@app.post("/abatement/work-orders/<wid>/cancel")
@endpoint({"AbatementCoordinator"})
def cancel_work_order(wid):
    wo = work_orders.get(wid)
    if not wo:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    if wo["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Work order is not SCHEDULED.")
    report = reports[wo["report_id"]]
    site = sites[report["site_id"]]
    snap = site_snapshot(site)
    wo["status"] = "CANCELLED"
    touch(wo)
    release_reservations(wid)
    report["status"] = "TRIAGED"
    touch(report)
    cr = find_cost_recovery(wid)
    if cr and cr["status"] == "PENDING":
        cr["status"] = "VOID"
        touch(cr)
    reconcile_site(site, snap)
    return success(clean(wo), "object", status=200)


@app.post("/abatement/work-orders/<wid>/recall")
@endpoint({"AbatementCoordinator"})
def recall_work_order(wid):
    body = get_body()
    reason = opt_str(body, "reason", None)
    wo = work_orders.get(wid)
    if not wo:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    if wo["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", "Work order is not IN_PROGRESS.")
    report = reports[wo["report_id"]]
    site = sites[report["site_id"]]
    snap = site_snapshot(site)
    wo["status"] = "RECALLED"
    touch(wo)
    release_reservations(wid)
    crew = crews[wo["crew_id"]]
    crew["status"] = "AVAILABLE"
    touch(crew)
    report["status"] = "TRIAGED"
    touch(report)
    cr = find_cost_recovery(wid)
    if cr and cr["status"] == "PENDING":
        cr["status"] = "VOID"
        touch(cr)
    add_removal_log(wid, "RECALLED", reason, g.uid)
    reconcile_site(site, snap)
    return success(clean(wo), "object", status=200)


@app.post("/abatement/work-orders/<wid>/photos")
@endpoint({"CrewLead"})
def add_photo(wid):
    body = get_body()
    phase = req_enum(body, "phase", ("BEFORE", "AFTER"))
    url = req_str(body, "url")
    wo = work_orders.get(wid)
    if not wo:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    if wo["crew_id"] != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Crew does not own this work order.")
    photo = new_audit(work_order_id=wid, phase=phase, url=url, captured_at=fmt(clock_now()))
    photos[photo["id"]] = photo
    return success(clean(photo), "object", status=201)


@app.get("/abatement/work-orders/<wid>/photos")
@endpoint(ALL_ROLES)
def list_photos(wid):
    if wid not in work_orders:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    items = [p for p in photos.values() if p["work_order_id"] == wid]
    return list_response(items)


@app.get("/abatement/work-orders/<wid>/removal-logs")
@endpoint(ALL_ROLES)
def list_removal_logs(wid):
    if wid not in work_orders:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    items = [r for r in removal_logs.values() if r["work_order_id"] == wid]
    return list_response(items)


@app.get("/abatement/work-orders/<wid>/material-reservations")
@endpoint(ALL_ROLES)
def list_wo_reservations(wid):
    if wid not in work_orders:
        err("ERR_WORK_ORDER_NOT_FOUND", "Work order not found.")
    items = [r for r in material_reservations.values() if r["work_order_id"] == wid]
    return list_response(items)


# ---- Materials -----------------------------------------------------
@app.post("/abatement/materials")
@endpoint({"InventoryManager", "ProgramAdmin"})
def create_material():
    body = get_body()
    name = req_str(body, "name")
    category = req_enum(body, "category", ("PAINT", "SOLVENT", "ABRASIVE"))
    unit = req_enum(body, "unit", ("LITERS", "GALLONS"))
    unit_cost_cents = req_int(body, "unit_cost_cents")
    quantity_available = req_number(body, "quantity_available")
    color = opt_str(body, "color", None)
    reorder_threshold = opt_number(body, "reorder_threshold", 0)
    m = new_common(
        name=name, category=category, color=color, unit=unit,
        unit_cost_cents=unit_cost_cents, quantity_available=quantity_available,
        quantity_reserved=0, reorder_threshold=reorder_threshold, status="AVAILABLE",
    )
    recompute_material_status(m)
    materials[m["id"]] = m
    return success(clean(m), "object", status=201)


@app.get("/abatement/materials/<mid>")
@endpoint(ALL_ROLES)
def get_material(mid):
    m = materials.get(mid)
    if not m:
        err("ERR_MATERIAL_NOT_FOUND", "Material not found.")
    return success(clean(m), "object", status=200)


@app.get("/abatement/materials/<mid>/material-reservations")
@endpoint(ALL_ROLES)
def list_material_reservations(mid):
    if mid not in materials:
        err("ERR_MATERIAL_NOT_FOUND", "Material not found.")
    items = [r for r in material_reservations.values() if r["material_id"] == mid]
    return list_response(items)


# ---- Notices -------------------------------------------------------
@app.post("/abatement/sites/<sid>/notices")
@endpoint({"AbatementCoordinator"})
def issue_notice(sid):
    body = get_body()
    # well-formedness (priority 3)
    notice_type = req_enum(body, "notice_type", ("ABATEMENT_NOTICE", "COST_RECOVERY_NOTICE"))
    cure_days = req_int(body, "cure_days")
    expected_site_version = req_int(body, "expected_site_version")
    cost_recovery_id = opt_str(body, "cost_recovery_id", None)
    if notice_type == "COST_RECOVERY_NOTICE" and cost_recovery_id is None:
        err("ERR_INVALID_REQUEST", "cost_recovery_id required for COST_RECOVERY_NOTICE.")
    # existence (priority 4): site, then cost_recovery
    site = sites.get(sid)
    if not site:
        err("ERR_SITE_NOT_FOUND", "Site not found.")
    cr = None
    if cost_recovery_id is not None:
        cr = cost_recoveries.get(cost_recovery_id)
        if not cr:
            err("ERR_COST_RECOVERY_NOT_FOUND", "Cost recovery not found.")
    # business: recovery assessed (priority 8)
    if notice_type == "COST_RECOVERY_NOTICE" and cr["status"] != "ASSESSED":
        err("ERR_RECOVERY_NOT_ASSESSED", "Linked cost recovery is not ASSESSED.")
    # business: OCC (priority 16)
    if expected_site_version != site["version"]:
        err("ERR_STALE_SITE_VERSION", "Stale site version.")
    snap = site_snapshot(site)
    # supersede prior SENT notices
    for n in notices.values():
        if n["site_id"] == site["id"] and n["status"] == "SENT":
            n["status"] = "WITHDRAWN"
            touch(n)
    sent = clock_now()
    deadline = sent + timedelta(days=cure_days)
    notice = new_common(
        site_id=site["id"], cost_recovery_id=cost_recovery_id,
        notice_type=notice_type, cure_days=cure_days,
        sent_at=fmt(sent), cure_deadline=fmt(deadline),
        response_at=None, status="SENT",
    )
    notice["_cure_deadline"] = deadline
    notices[notice["id"]] = notice
    site["active_notice_id"] = notice["id"]
    reconcile_site(site, snap)
    return success(clean(notice), "object", status=201)


@app.get("/abatement/notices/<nid>")
@endpoint(ALL_ROLES)
def get_notice(nid):
    n = notices.get(nid)
    if not n:
        err("ERR_NOTICE_NOT_FOUND", "Notice not found.")
    return success(clean(n), "object", status=200)


@app.get("/abatement/notices")
@endpoint(ALL_ROLES)
def list_notices():
    items = list(notices.values())
    items = filter_by(items, "site_id")
    items = filter_by(items, "cost_recovery_id")
    items = filter_by(items, "status")
    return list_response(items)


@app.post("/abatement/notices/<nid>/consent")
@endpoint({"PropertyOwnerUser"})
def consent_notice(nid):
    notice = notices.get(nid)
    if not notice:
        err("ERR_NOTICE_NOT_FOUND", "Notice not found.")
    site = sites[notice["site_id"]]
    if site.get("property_owner_id") != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Owner does not own this site's property owner.")
    if notice["status"] not in ("SENT", "DISPUTED"):
        err("ERR_INVALID_STATE", "Notice cannot be consented from its current state.")
    snap = site_snapshot(site)
    was = notice["status"]
    notice["status"] = "CONSENTED"
    notice["response_at"] = fmt(clock_now())
    touch(notice)
    if was == "DISPUTED" and notice["cost_recovery_id"]:
        cr = cost_recoveries.get(notice["cost_recovery_id"])
        if cr and cr["status"] == "DISPUTED":
            cr["status"] = "ASSESSED"
            touch(cr)
    if site.get("active_notice_id") == notice["id"]:
        site["active_notice_id"] = None
    reconcile_site(site, snap)
    return success(clean(notice), "object", status=200)


@app.post("/abatement/notices/<nid>/dispute")
@endpoint({"PropertyOwnerUser"})
def dispute_notice(nid):
    body = get_body()
    opt_str(body, "reason", None)
    notice = notices.get(nid)
    if not notice:
        err("ERR_NOTICE_NOT_FOUND", "Notice not found.")
    site = sites[notice["site_id"]]
    if site.get("property_owner_id") != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Owner does not own this site's property owner.")
    if notice["status"] != "SENT":
        err("ERR_INVALID_STATE", "Notice cannot be disputed from its current state.")
    snap = site_snapshot(site)
    notice["status"] = "DISPUTED"
    notice["response_at"] = fmt(clock_now())
    touch(notice)
    if notice["cost_recovery_id"]:
        cr = cost_recoveries.get(notice["cost_recovery_id"])
        if cr and cr["status"] == "ASSESSED":
            cr["status"] = "DISPUTED"
            touch(cr)
    reconcile_site(site, snap)
    return success(clean(notice), "object", status=200)


@app.post("/abatement/notices/<nid>/expire")
@endpoint({"AbatementCoordinator"})
def expire_notice(nid):
    notice = notices.get(nid)
    if not notice:
        err("ERR_NOTICE_NOT_FOUND", "Notice not found.")
    if notice["status"] != "SENT":
        err("ERR_INVALID_STATE", "Notice cannot be expired from its current state.")
    deadline = notice.get("_cure_deadline") or parse_iso(notice["cure_deadline"])
    if clock_now() < deadline:
        err("ERR_CURE_WINDOW_NOT_ELAPSED", "Cure window has not elapsed.")
    site = sites[notice["site_id"]]
    snap = site_snapshot(site)
    notice["status"] = "EXPIRED"
    touch(notice)
    if notice["cost_recovery_id"]:
        cr = cost_recoveries.get(notice["cost_recovery_id"])
        if cr and cr["status"] == "ASSESSED":
            cr["status"] = "LIEN_PENDING"
            touch(cr)
    if site.get("active_notice_id") == notice["id"]:
        site["active_notice_id"] = None
    reconcile_site(site, snap)
    return success(clean(notice), "object", status=200)


# ---- Cost recoveries -----------------------------------------------
@app.get("/abatement/cost-recoveries/<crid>")
@endpoint(ALL_ROLES)
def get_cost_recovery(crid):
    cr = cost_recoveries.get(crid)
    if not cr:
        err("ERR_COST_RECOVERY_NOT_FOUND", "Cost recovery not found.")
    return success(clean(cr), "object", status=200)


@app.get("/abatement/cost-recoveries")
@endpoint(ALL_ROLES)
def list_cost_recoveries():
    items = list(cost_recoveries.values())
    items = filter_by(items, "site_id")
    items = filter_by(items, "work_order_id")
    items = filter_by(items, "status")
    return list_response(items)


@app.post("/abatement/cost-recoveries/<crid>/pay")
@endpoint({"PropertyOwnerUser", "AbatementCoordinator"})
def pay_cost_recovery(crid):
    cr = cost_recoveries.get(crid)
    if not cr:
        err("ERR_COST_RECOVERY_NOT_FOUND", "Cost recovery not found.")
    site = sites[cr["site_id"]]
    if g.role == "PropertyOwnerUser" and site.get("property_owner_id") != g.uid:
        err("ERR_OWNERSHIP_MISMATCH", "Owner does not own this site's property owner.")
    if cr["status"] != "ASSESSED":
        err("ERR_INVALID_STATE", "Cost recovery is not ASSESSED.")
    snap = site_snapshot(site)
    cr["status"] = "PAID"
    touch(cr)
    wo = work_orders.get(cr["work_order_id"])
    if wo:
        report = reports.get(wo["report_id"])
        if report and report["status"] == "REMEDIATED":
            report["status"] = "CLOSED"
            touch(report)
    reconcile_site(site, snap)
    return success(clean(cr), "object", status=200)


@app.post("/abatement/cost-recoveries/<crid>/waive")
@endpoint({"ProgramAdmin"})
def waive_cost_recovery(crid):
    body = get_body()
    opt_str(body, "reason", None)
    cr = cost_recoveries.get(crid)
    if not cr:
        err("ERR_COST_RECOVERY_NOT_FOUND", "Cost recovery not found.")
    if cr["status"] != "ASSESSED":
        err("ERR_INVALID_STATE", "Cost recovery is not ASSESSED.")
    site = sites[cr["site_id"]]
    snap = site_snapshot(site)
    cr["status"] = "WAIVED"
    touch(cr)
    wo = work_orders.get(cr["work_order_id"])
    if wo:
        report = reports.get(wo["report_id"])
        if report and report["status"] == "REMEDIATED":
            report["status"] = "CLOSED"
            touch(report)
    reconcile_site(site, snap)
    return success(clean(cr), "object", status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
