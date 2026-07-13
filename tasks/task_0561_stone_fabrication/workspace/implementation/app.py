import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ShopManager", "SalesRep", "Fabricator", "Installer"}

MATERIAL_GRADES = {"STANDARD", "PREMIUM", "EXOTIC"}
EDGE_PROFILES = {"EASED", "BEVELED", "BULLNOSE", "OGEE"}
CUTOUT_TYPES = {"SINK", "FAUCET", "COOKTOP"}

MATERIAL_RATE_CENTS = {"STANDARD": 4500, "PREMIUM": 6500, "EXOTIC": 9500}
EDGE_RATE_CENTS = {"EASED": 0, "BEVELED": 800, "BULLNOSE": 1200, "OGEE": 2000}
CUTOUT_CHARGE_CENTS = {"SINK": 15000, "FAUCET": 3500, "COOKTOP": 12000}
MIN_JOB_CENTS = 80000
TAX_RATE = Decimal("0.0875")
TAX_MULT = Decimal("1") + TAX_RATE
DEPOSIT_PCT = Decimal("0.50")
STD_WASTE_FACTOR = Decimal("0.15")
KERF_SQFT_PER_PIECE = Decimal("0.10")
TRAVEL_BUFFER_DAYS = 1
WARRANTY_DAYS = 365

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.projects = {}
        self.quotes = {}
        self.templates = {}
        self.cutouts = {}
        self.slabs = {}
        self.remnants = {}
        self.bays = {}
        self.crews = {}
        self.fab_orders = {}
        self.install_jobs = {}
        self.payments = {}
        self.change_orders = {}
        self.warranty_claims = {}
        self.clock = DEFAULT_CLOCK


db = DB()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers: time / ids / rounding
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def rhu_int(x):
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(x):
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def envelope_object(data, status):
    body = {"meta": meta_base(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def envelope_array(items, limit, offset, total, status=200):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = offset + len(items) < total
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.before_request
def auth_gate():
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role.")
    g.role = role
    g.user_id = request.headers.get("X-User-ID")


def require_roles(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")


ALL_READERS = ("ShopManager", "SalesRep", "Fabricator", "Installer")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON.")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object.")
        return data
    return {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' is required and must be a non-empty string.")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must be one of {sorted(allowed)}.")
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' is required and must be an integer.")
    return v


def req_number_nonneg(body, field):
    v = body.get(field)
    if not is_number(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' is required and must be a number.")
    if v < 0:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must not be negative.")
    return v


def req_int_nonneg(body, field):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' is required and must be an integer.")
    if v < 0:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{field}' must not be negative.")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_project(pid):
    p = db.projects.get(pid)
    if p is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project id not found.")
    return p


def get_template(tid):
    t = db.templates.get(tid)
    if t is None:
        raise ApiError("ERR_TEMPLATE_NOT_FOUND", 404, "Template id not found.")
    return t


def get_slab(sid):
    s = db.slabs.get(sid)
    if s is None:
        raise ApiError("ERR_SLAB_NOT_FOUND", 404, "Slab id not found.")
    return s


def get_bay(bid):
    b = db.bays.get(bid)
    if b is None:
        raise ApiError("ERR_BAY_NOT_FOUND", 404, "Bay id not found.")
    return b


def get_crew(cid):
    c = db.crews.get(cid)
    if c is None:
        raise ApiError("ERR_CREW_NOT_FOUND", 404, "Crew id not found.")
    return c


def get_fab(fid):
    f = db.fab_orders.get(fid)
    if f is None:
        raise ApiError("ERR_FAB_ORDER_NOT_FOUND", 404, "FabricationOrder id not found.")
    return f


def get_install(iid):
    j = db.install_jobs.get(iid)
    if j is None:
        raise ApiError("ERR_INSTALL_JOB_NOT_FOUND", 404, "InstallJob id not found.")
    return j


def get_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise ApiError("ERR_PAYMENT_NOT_FOUND", 404, "Payment id not found.")
    return p


def get_change_order(cid):
    c = db.change_orders.get(cid)
    if c is None:
        raise ApiError("ERR_CHANGE_ORDER_NOT_FOUND", 404, "ChangeOrder id not found.")
    return c


def get_warranty(wid):
    w = db.warranty_claims.get(wid)
    if w is None:
        raise ApiError("ERR_WARRANTY_CLAIM_NOT_FOUND", 404, "WarrantyClaim id not found.")
    return w


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Business recomputation
# ---------------------------------------------------------------------------
def active_quote(pid):
    for q in db.quotes.values():
        if q["project_id"] == pid and q["status"] == "ACTIVE":
            return q
    return None


def deposit_required(project):
    return rhu_int(Decimal(str(project["quoted_total_cents"])) * DEPOSIT_PCT)


def captured_amount(pid):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["project_id"] == pid and p["status"] == "CAPTURED")


def approved_template(pid):
    for t in db.templates.values():
        if t["project_id"] == pid and t["status"] == "APPROVED":
            return t
    return None


def compute_final_invoice(project):
    tmpl = approved_template(project["id"])
    if tmpl is None:
        return None
    lines = []
    lines.append(Decimal(MATERIAL_RATE_CENTS[project["material_grade"]]) * Decimal(str(tmpl["measured_sqft"])))
    lines.append(Decimal(EDGE_RATE_CENTS[tmpl["edge_profile"]]) * Decimal(str(tmpl["edge_linear_ft"])))
    for c in db.cutouts.values():
        if c["template_id"] == tmpl["id"]:
            lines.append(Decimal(c["charge_cents"]))
    for co in db.change_orders.values():
        if co["project_id"] == project["id"] and co["status"] == "APPLIED":
            lines.append(Decimal(co["delta_cents"]))
    total = 0
    for line in lines:
        total += rhu_int(line * TAX_MULT)
    return total


def balance_basis(project):
    if project["final_invoice_cents"] is not None:
        return project["final_invoice_cents"]
    return project["quoted_total_cents"]


def recompute_quoted_total(project):
    aq = active_quote(project["id"])
    project["quoted_total_cents"] = aq["quote_total_cents"] if aq else 0
    project["balance_due_cents"] = balance_basis(project) - project["amount_paid_cents"]


def recompute_invoice(project):
    project["final_invoice_cents"] = compute_final_invoice(project)
    project["balance_due_cents"] = balance_basis(project) - project["amount_paid_cents"]


def recompute_ledger(project):
    paid = captured_amount(project["id"])
    project["amount_paid_cents"] = paid
    basis = balance_basis(project)
    project["balance_due_cents"] = basis - paid
    if paid >= basis:
        project["payment_status"] = "PAID_IN_FULL"
    elif paid >= deposit_required(project):
        project["payment_status"] = "DEPOSIT_PAID"
    else:
        project["payment_status"] = "UNPAID"


def release_slab(slab):
    slab["status"] = "IN_STOCK"
    slab["reserved_sqft"] = 0
    slab["remaining_sqft"] = slab["nominal_sqft"]
    touch(slab)


# ===========================================================================
# Config / inventory endpoints
# ===========================================================================
@app.route("/bays", methods=["POST"])
def create_bay():
    require_roles("ShopManager")
    body = get_body()
    name = req_str(body, "name")
    bid = new_id()
    bay = {"id": bid, "created_at": now_iso(), "name": name}
    db.bays[bid] = bay
    return envelope_object(public(bay), 201)


@app.route("/crews", methods=["POST"])
def create_crew():
    require_roles("ShopManager")
    body = get_body()
    name = req_str(body, "name")
    cid = new_id()
    crew = {"id": cid, "created_at": now_iso(), "name": name}
    db.crews[cid] = crew
    return envelope_object(public(crew), 201)


@app.route("/slabs", methods=["POST"])
def create_slab():
    require_roles("ShopManager", "Fabricator")
    body = get_body()
    label = req_str(body, "slab_label")
    grade = req_enum(body, "material_grade", MATERIAL_GRADES)
    nominal = body.get("nominal_sqft")
    if not is_number(nominal):
        raise ApiError("ERR_VALIDATION", 400, "Field 'nominal_sqft' is required and must be a number.")
    if nominal <= 0:
        raise ApiError("ERR_VALIDATION", 400, "Field 'nominal_sqft' must be strictly positive.")
    nominal = rhu2(nominal)
    sid = new_id()
    ts = now_iso()
    slab = {
        "id": sid, "created_at": ts, "updated_at": ts, "version": 1,
        "slab_label": label, "material_grade": grade, "nominal_sqft": nominal,
        "status": "IN_STOCK", "reserved_sqft": 0, "remaining_sqft": nominal,
        "estimated_yield_sqft": rhu2(Decimal(str(nominal)) * (Decimal("1") - STD_WASTE_FACTOR)),
    }
    db.slabs[sid] = slab
    return envelope_object(public(slab), 201)


@app.route("/slabs/<sid>", methods=["GET"])
def read_slab(sid):
    require_roles(*ALL_READERS)
    return envelope_object(public(get_slab(sid)), 200)


@app.route("/slabs/<sid>/remnants", methods=["GET"])
def list_remnants(sid):
    require_roles(*ALL_READERS)
    get_slab(sid)
    items = [public(r) for r in db.remnants.values() if r["slab_id"] == sid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


# ===========================================================================
# Projects
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    require_roles("SalesRep", "ShopManager")
    body = get_body()
    customer = req_str(body, "customer_name")
    address = req_str(body, "address")
    grade = req_enum(body, "material_grade", MATERIAL_GRADES)
    pid = new_id()
    ts = now_iso()
    project = {
        "id": pid, "created_at": ts, "updated_at": ts, "version": 1,
        "customer_name": customer, "address": address, "material_grade": grade,
        "status": "INTAKE", "payment_status": "UNPAID",
        "quoted_total_cents": 0, "final_invoice_cents": None,
        "amount_paid_cents": 0, "balance_due_cents": 0,
    }
    db.projects[pid] = project
    return envelope_object(public(project), 201)


@app.route("/projects/<pid>", methods=["GET"])
def read_project(pid):
    require_roles(*ALL_READERS)
    return envelope_object(public(get_project(pid)), 200)


# ===========================================================================
# Quotes
# ===========================================================================
def check_project_closed(project):
    if project["status"] == "CLOSED":
        raise ApiError("ERR_PROJECT_CLOSED", 409, "Mutation attempted on a CLOSED Project.")


def check_occ(project, body):
    expected = body.get("expected_project_version")
    if not is_int(expected):
        raise ApiError("ERR_VALIDATION", 400, "Field 'expected_project_version' is required and must be an integer.")
    if expected != project["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_project_version does not match current Project.version.")


@app.route("/projects/<pid>/quotes", methods=["POST"])
def create_quote(pid):
    require_roles("SalesRep", "ShopManager")
    project = get_project(pid)
    check_project_closed(project)
    body = get_body()
    check_occ(project, body)
    est_sqft = req_number_nonneg(body, "est_sqft")
    grade = req_enum(body, "material_grade", MATERIAL_GRADES)
    edge_profile = req_enum(body, "edge_profile", EDGE_PROFILES)
    edge_linear_ft = req_number_nonneg(body, "edge_linear_ft")
    sink = req_int_nonneg(body, "sink_count")
    faucet = req_int_nonneg(body, "faucet_count")
    cooktop = req_int_nonneg(body, "cooktop_count")

    material_charge = rhu_int(Decimal(MATERIAL_RATE_CENTS[grade]) * Decimal(str(est_sqft)))
    edge_charge = rhu_int(Decimal(EDGE_RATE_CENTS[edge_profile]) * Decimal(str(edge_linear_ft)))
    cutout_charge = (sink * CUTOUT_CHARGE_CENTS["SINK"]
                     + faucet * CUTOUT_CHARGE_CENTS["FAUCET"]
                     + cooktop * CUTOUT_CHARGE_CENTS["COOKTOP"])
    subtotal = material_charge + edge_charge + cutout_charge
    quote_total = max(subtotal, MIN_JOB_CENTS)

    # supersede prior active quote
    prev = active_quote(pid)
    if prev is not None:
        prev["status"] = "SUPERSEDED"
        touch(prev)

    qid = new_id()
    ts = now_iso()
    quote = {
        "id": qid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": pid, "est_sqft": est_sqft, "material_grade": grade,
        "edge_profile": edge_profile, "edge_linear_ft": edge_linear_ft,
        "sink_count": sink, "faucet_count": faucet, "cooktop_count": cooktop,
        "subtotal_cents": subtotal, "quote_total_cents": quote_total, "status": "ACTIVE",
    }
    db.quotes[qid] = quote

    recompute_quoted_total(project)
    touch(project)
    return envelope_object(public(quote), 201)


@app.route("/projects/<pid>/quotes", methods=["GET"])
def list_quotes(pid):
    require_roles(*ALL_READERS)
    get_project(pid)
    items = [public(q) for q in db.quotes.values() if q["project_id"] == pid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/projects/<pid>/payments", methods=["POST"])
def create_payment(pid):
    require_roles("SalesRep", "ShopManager")
    project = get_project(pid)
    check_project_closed(project)
    body = get_body()
    amount = req_int(body, "amount_cents")
    kind = req_enum(body, "kind", {"DEPOSIT", "BALANCE"})

    # business_fiscal checks in priority order
    if active_quote(pid) is None:
        raise ApiError("ERR_QUOTE_REQUIRED", 409, "Payment requires an ACTIVE Quote.")
    if amount <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0.")

    existing = captured_amount(pid)
    new_total = existing + amount

    if kind == "DEPOSIT":
        if new_total < deposit_required(project):
            raise ApiError("ERR_DEPOSIT_TOO_LOW", 422, "Deposit does not reach the required minimum.")

    if new_total > balance_basis(project):
        raise ApiError("ERR_OVERPAYMENT", 422, "Payment would exceed the balance basis.")

    payid = new_id()
    ts = now_iso()
    payment = {
        "id": payid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": pid, "amount_cents": amount, "kind": kind, "status": "CAPTURED",
    }
    db.payments[payid] = payment

    recompute_ledger(project)
    touch(project)
    return envelope_object(public(payment), 201)


@app.route("/payments/<payid>/refund", methods=["POST"])
def refund_payment(payid):
    require_roles("SalesRep", "ShopManager")
    payment = get_payment(payid)
    if payment["status"] != "CAPTURED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Only CAPTURED payments can be refunded.")
    payment["status"] = "REFUNDED"
    touch(payment)
    project = db.projects.get(payment["project_id"])
    if project is not None:
        recompute_ledger(project)
        touch(project)
    return envelope_object(public(payment), 200)


@app.route("/projects/<pid>/payments", methods=["GET"])
def list_payments(pid):
    require_roles(*ALL_READERS)
    get_project(pid)
    items = [public(p) for p in db.payments.values() if p["project_id"] == pid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


# ===========================================================================
# Change orders
# ===========================================================================
@app.route("/projects/<pid>/change-orders", methods=["POST"])
def create_change_order(pid):
    require_roles("SalesRep", "ShopManager")
    project = get_project(pid)
    check_project_closed(project)
    body = get_body()
    check_occ(project, body)
    description = req_str(body, "description")
    delta = req_int(body, "delta_cents")
    reopens = body.get("reopens_template", True)
    if not isinstance(reopens, bool):
        raise ApiError("ERR_VALIDATION", 400, "Field 'reopens_template' must be a boolean.")

    cid = new_id()
    ts = now_iso()
    co = {
        "id": cid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": pid, "description": description, "delta_cents": delta,
        "reopens_template": reopens, "status": "DRAFT",
    }
    db.change_orders[cid] = co
    touch(project)  # scaffold: increments Project.version by 1
    return envelope_object(public(co), 201)


@app.route("/change-orders/<cid>/approve", methods=["POST"])
def approve_change_order(cid):
    require_roles("ShopManager")
    co = get_change_order(cid)
    if co["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Change order is not in DRAFT.")
    project = get_project(co["project_id"])
    check_project_closed(project)

    co["status"] = "APPLIED"
    touch(co)

    recompute_invoice(project)

    if co["reopens_template"]:
        tmpl = approved_template(project["id"])
        if tmpl is not None:
            tmpl["status"] = "MEASURED"
            touch(tmpl)
        # cancel linked non-terminal fabrication order(s), release slab
        for fo in db.fab_orders.values():
            if fo["project_id"] == project["id"] and fo["status"] in (
                "SCHEDULED", "CUTTING", "RECUTTING", "QC_PASSED"):
                fo["status"] = "CANCELLED"
                touch(fo)
                slab = db.slabs.get(fo["slab_id"])
                if slab is not None and slab["status"] == "RESERVED":
                    release_slab(slab)
        project["status"] = "ON_HOLD"

    touch(project)
    return envelope_object(public(co), 200)


@app.route("/projects/<pid>/change-orders", methods=["GET"])
def list_change_orders(pid):
    require_roles(*ALL_READERS)
    get_project(pid)
    items = [public(c) for c in db.change_orders.values() if c["project_id"] == pid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


# ===========================================================================
# Templates + cutouts
# ===========================================================================
@app.route("/projects/<pid>/templates", methods=["POST"])
def create_template(pid):
    require_roles("Fabricator", "ShopManager")
    project = get_project(pid)
    check_project_closed(project)
    body = get_body()
    measured = req_number_nonneg(body, "measured_sqft")
    edge_profile = req_enum(body, "edge_profile", EDGE_PROFILES)
    edge_linear_ft = req_number_nonneg(body, "edge_linear_ft")

    # supersede prior non-SUPERSEDED template
    for t in db.templates.values():
        if t["project_id"] == pid and t["status"] != "SUPERSEDED":
            t["status"] = "SUPERSEDED"
            touch(t)

    tid = new_id()
    ts = now_iso()
    tmpl = {
        "id": tid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": pid, "measured_sqft": measured, "edge_profile": edge_profile,
        "edge_linear_ft": edge_linear_ft, "status": "MEASURED",
    }
    db.templates[tid] = tmpl
    return envelope_object(public(tmpl), 201)


@app.route("/projects/<pid>/templates", methods=["GET"])
def list_templates(pid):
    require_roles(*ALL_READERS)
    get_project(pid)
    items = [public(t) for t in db.templates.values() if t["project_id"] == pid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


@app.route("/templates/<tid>", methods=["GET"])
def read_template(tid):
    require_roles(*ALL_READERS)
    return envelope_object(public(get_template(tid)), 200)


@app.route("/templates/<tid>/cutouts", methods=["POST"])
def create_cutout(tid):
    require_roles("Fabricator", "ShopManager")
    get_template(tid)
    body = get_body()
    ctype = req_enum(body, "cutout_type", CUTOUT_TYPES)
    coid = new_id()
    cutout = {
        "id": coid, "created_at": now_iso(),
        "template_id": tid, "cutout_type": ctype,
        "charge_cents": CUTOUT_CHARGE_CENTS[ctype],
    }
    db.cutouts[coid] = cutout
    return envelope_object(public(cutout), 201)


@app.route("/templates/<tid>/cutouts", methods=["GET"])
def list_cutouts(tid):
    require_roles(*ALL_READERS)
    get_template(tid)
    items = [public(c) for c in db.cutouts.values() if c["template_id"] == tid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


@app.route("/templates/<tid>/approve", methods=["POST"])
def approve_template(tid):
    require_roles("Fabricator", "ShopManager")
    tmpl = get_template(tid)
    if tmpl["status"] != "MEASURED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Template is not in MEASURED.")
    if not (tmpl["measured_sqft"] > 0):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Template measured_sqft must be greater than zero.")
    tmpl["status"] = "APPROVED"
    touch(tmpl)
    project = db.projects.get(tmpl["project_id"])
    if project is not None:
        recompute_invoice(project)
        touch(project)
    return envelope_object(public(tmpl), 200)


# ===========================================================================
# Fabrication orders
# ===========================================================================
def bay_overlaps(bay_id, start, end, exclude_id=None):
    for fo in db.fab_orders.values():
        if fo["bay_id"] != bay_id:
            continue
        if fo["status"] == "CANCELLED":
            continue
        if fo["id"] == exclude_id:
            continue
        fstart = parse_dt(fo["scheduled_start"])
        fend = parse_dt(fo["scheduled_end"])
        # half-open overlap: start < fend AND fstart < end
        if start < fend and fstart < end:
            return True
    return False


@app.route("/fabrication-orders", methods=["POST"])
def create_fab_order():
    require_roles("Fabricator", "ShopManager")
    body = get_body()

    # existence (left-to-right): project, template, slab, bay
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'project_id' is required.")
    project = get_project(project_id)

    template_id = body.get("template_id")
    if not isinstance(template_id, str) or template_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'template_id' is required.")
    template = get_template(template_id)

    slab_id = body.get("slab_id")
    if not isinstance(slab_id, str) or slab_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'slab_id' is required.")
    slab = get_slab(slab_id)

    bay_id = body.get("bay_id")
    if not isinstance(bay_id, str) or bay_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'bay_id' is required.")
    get_bay(bay_id)

    # basic field validation
    ss_raw = body.get("scheduled_start")
    se_raw = body.get("scheduled_end")
    try:
        start = parse_dt(ss_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Field 'scheduled_start' must be an ISO 8601 datetime.")
    try:
        end = parse_dt(se_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Field 'scheduled_end' must be an ISO 8601 datetime.")

    pieces = body.get("pieces")
    if pieces is None or not isinstance(pieces, list):
        raise ApiError("ERR_VALIDATION", 400, "Field 'pieces' is required and must be an array.")
    for p in pieces:
        if not isinstance(p, dict):
            raise ApiError("ERR_VALIDATION", 400, "Each piece must be an object.")
        if not isinstance(p.get("label"), str):
            raise ApiError("ERR_VALIDATION", 400, "Each piece requires a string 'label'.")
        if not is_number(p.get("sqft")) or p.get("sqft") <= 0:
            raise ApiError("ERR_VALIDATION", 400, "Each piece requires a positive 'sqft'.")

    # business checks in priority order
    # 6: template APPROVED
    if template["status"] != "APPROVED":
        raise ApiError("ERR_TEMPLATE_NOT_APPROVED", 409, "Referenced Template is not APPROVED.")
    # 8: deposit paid (only enforced when advancing from INTAKE)
    if project["status"] == "INTAKE":
        if project["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
            raise ApiError("ERR_DEPOSIT_NOT_PAID", 409, "Project deposit is not paid.")
    # 9: pieces non-empty
    if len(pieces) < 1:
        raise ApiError("ERR_NO_PIECES", 422, "pieces must contain at least one piece.")
    # 10: slab IN_STOCK
    if slab["status"] != "IN_STOCK":
        raise ApiError("ERR_SLAB_NOT_AVAILABLE", 409, "Referenced Slab is not IN_STOCK.")
    # 11: interval
    if not (end > start):
        raise ApiError("ERR_INVALID_INTERVAL", 422, "scheduled_end must be after scheduled_start.")
    # 12: bay overlap
    if bay_overlaps(bay_id, start, end):
        raise ApiError("ERR_BAY_UNAVAILABLE", 409, "Bay is not available for the requested window.")

    consumed = rhu2(sum(Decimal(str(p["sqft"])) for p in pieces) + KERF_SQFT_PER_PIECE * len(pieces))

    fid = new_id()
    ts = now_iso()
    fo = {
        "id": fid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": project_id, "template_id": template_id, "slab_id": slab_id,
        "bay_id": bay_id, "scheduled_start": ss_raw, "scheduled_end": se_raw,
        "pieces": pieces, "actual_consumed_sqft": consumed, "status": "SCHEDULED",
    }
    db.fab_orders[fid] = fo

    # reserve slab
    slab["status"] = "RESERVED"
    slab["reserved_sqft"] = consumed
    slab["remaining_sqft"] = rhu2(Decimal(str(slab["nominal_sqft"])) - Decimal(str(consumed)))
    touch(slab)

    # advance project posture
    if project["status"] in ("INTAKE", "ON_HOLD"):
        project["status"] = "IN_PRODUCTION"
        touch(project)

    return envelope_object(public(fo), 201)


@app.route("/fabrication-orders/<fid>", methods=["GET"])
def read_fab_order(fid):
    require_roles(*ALL_READERS)
    return envelope_object(public(get_fab(fid)), 200)


@app.route("/fabrication-orders", methods=["GET"])
def list_fab_orders():
    require_roles(*ALL_READERS)
    items = []
    for fo in db.fab_orders.values():
        if request.args.get("project_id") and fo["project_id"] != request.args.get("project_id"):
            continue
        if request.args.get("template_id") and fo["template_id"] != request.args.get("template_id"):
            continue
        if request.args.get("slab_id") and fo["slab_id"] != request.args.get("slab_id"):
            continue
        if request.args.get("bay_id") and fo["bay_id"] != request.args.get("bay_id"):
            continue
        items.append(public(fo))
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


@app.route("/fabrication-orders/<fid>/start-cut", methods=["POST"])
def start_cut(fid):
    require_roles("Fabricator", "ShopManager")
    fo = get_fab(fid)
    if fo["status"] not in ("SCHEDULED", "RECUTTING"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Cannot start cut from current state.")
    fo["status"] = "CUTTING"
    touch(fo)
    return envelope_object(public(fo), 200)


@app.route("/fabrication-orders/<fid>/qc", methods=["POST"])
def qc_fab_order(fid):
    require_roles("Fabricator", "ShopManager")
    fo = get_fab(fid)
    if fo["status"] != "CUTTING":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "QC only allowed from CUTTING.")
    body = get_body()
    result = req_enum(body, "result", {"PASS", "FAIL"})
    fo["status"] = "QC_PASSED" if result == "PASS" else "RECUTTING"
    touch(fo)
    return envelope_object(public(fo), 200)


@app.route("/fabrication-orders/<fid>/complete", methods=["POST"])
def complete_fab_order(fid):
    require_roles("Fabricator", "ShopManager")
    fo = get_fab(fid)
    if fo["status"] != "QC_PASSED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Complete only allowed from QC_PASSED.")
    fo["status"] = "COMPLETE"
    touch(fo)
    slab = db.slabs.get(fo["slab_id"])
    if slab is not None:
        slab["status"] = "CONSUMED"
        touch(slab)
        rid = new_id()
        area = rhu2(Decimal(str(slab["nominal_sqft"])) - Decimal(str(fo["actual_consumed_sqft"])))
        remnant = {
            "id": rid, "created_at": now_iso(),
            "slab_id": slab["id"], "area_sqft": area, "status": "AVAILABLE",
        }
        db.remnants[rid] = remnant
    return envelope_object(public(fo), 200)


@app.route("/fabrication-orders/<fid>/cancel", methods=["POST"])
def cancel_fab_order(fid):
    require_roles("Fabricator", "ShopManager")
    fo = get_fab(fid)
    if fo["status"] not in ("SCHEDULED", "CUTTING", "RECUTTING", "QC_PASSED"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Cannot cancel from current state.")
    fo["status"] = "CANCELLED"
    touch(fo)
    slab = db.slabs.get(fo["slab_id"])
    if slab is not None and slab["status"] == "RESERVED":
        release_slab(slab)
    return envelope_object(public(fo), 200)


# ===========================================================================
# Install jobs
# ===========================================================================
def crew_conflict(crew_id, when):
    for j in db.install_jobs.values():
        if j["crew_id"] != crew_id:
            continue
        try:
            other = parse_date(j["install_date"])
        except (ValueError, TypeError):
            continue
        if abs((when - other).days) <= TRAVEL_BUFFER_DAYS:
            return True
    return False


@app.route("/install-jobs", methods=["POST"])
def create_install_job():
    require_roles("Installer", "ShopManager")
    body = get_body()

    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'project_id' is required.")
    get_project(project_id)

    fab_id = body.get("fabrication_order_id")
    if not isinstance(fab_id, str) or fab_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'fabrication_order_id' is required.")
    fab = get_fab(fab_id)

    crew_id = body.get("crew_id")
    if not isinstance(crew_id, str) or crew_id == "":
        raise ApiError("ERR_VALIDATION", 400, "Field 'crew_id' is required.")
    get_crew(crew_id)

    install_date_raw = body.get("install_date")
    try:
        when = parse_date(install_date_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Field 'install_date' must be a YYYY-MM-DD date.")

    # 7: fabrication order COMPLETE
    if fab["status"] != "COMPLETE":
        raise ApiError("ERR_FAB_NOT_COMPLETE", 409, "FabricationOrder is not COMPLETE.")
    # 13: crew availability
    if crew_conflict(crew_id, when):
        raise ApiError("ERR_CREW_UNAVAILABLE", 409, "Crew is not available around that date.")

    iid = new_id()
    ts = now_iso()
    job = {
        "id": iid, "created_at": ts, "updated_at": ts, "version": 1,
        "project_id": project_id, "fabrication_order_id": fab_id, "crew_id": crew_id,
        "install_date": install_date_raw, "status": "SCHEDULED", "completed_at": None,
    }
    db.install_jobs[iid] = job
    return envelope_object(public(job), 201)


@app.route("/install-jobs/<iid>", methods=["GET"])
def read_install_job(iid):
    require_roles(*ALL_READERS)
    return envelope_object(public(get_install(iid)), 200)


@app.route("/install-jobs", methods=["GET"])
def list_install_jobs():
    require_roles(*ALL_READERS)
    items = []
    for j in db.install_jobs.values():
        if request.args.get("project_id") and j["project_id"] != request.args.get("project_id"):
            continue
        if request.args.get("crew_id") and j["crew_id"] != request.args.get("crew_id"):
            continue
        if request.args.get("fabrication_order_id") and j["fabrication_order_id"] != request.args.get("fabrication_order_id"):
            continue
        items.append(public(j))
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


@app.route("/install-jobs/<iid>/start", methods=["POST"])
def start_install(iid):
    require_roles("Installer", "ShopManager")
    job = get_install(iid)
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Start only allowed from SCHEDULED.")
    job["status"] = "IN_PROGRESS"
    touch(job)
    return envelope_object(public(job), 200)


@app.route("/install-jobs/<iid>/complete", methods=["POST"])
def complete_install(iid):
    require_roles("Installer", "ShopManager")
    job = get_install(iid)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Complete only allowed from IN_PROGRESS.")
    job["status"] = "DONE"
    job["completed_at"] = fmt_dt(db.clock)
    touch(job)
    project = db.projects.get(job["project_id"])
    if project is not None and project["status"] == "IN_PRODUCTION":
        if project["payment_status"] == "PAID_IN_FULL":
            project["status"] = "CLOSED"
        else:
            project["status"] = "INSTALLED"
        touch(project)
    return envelope_object(public(job), 200)


# ===========================================================================
# Warranty claims
# ===========================================================================
@app.route("/install-jobs/<iid>/warranty-claims", methods=["POST"])
def create_warranty_claim(iid):
    require_roles("Installer", "ShopManager")
    job = get_install(iid)
    body = get_body()
    claim_type = req_enum(body, "claim_type", {"SEAL", "CHIP", "CRACK"})
    description = req_str(body, "description")

    # window check: must be DONE and current clock <= completed_at + WARRANTY_DAYS
    if job["status"] != "DONE" or job["completed_at"] is None:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422, "Install job is not within a valid warranty window.")
    completed = parse_dt(job["completed_at"])
    deadline = completed + timedelta(days=WARRANTY_DAYS)
    if db.clock > deadline:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422, "Warranty window has expired.")

    wid = new_id()
    ts = now_iso()
    claim = {
        "id": wid, "created_at": ts, "updated_at": ts, "version": 1,
        "install_job_id": iid, "claim_type": claim_type, "description": description,
        "resolution": None, "status": "SUBMITTED",
    }
    db.warranty_claims[wid] = claim
    return envelope_object(public(claim), 201)


@app.route("/install-jobs/<iid>/warranty-claims", methods=["GET"])
def list_warranty_claims(iid):
    require_roles(*ALL_READERS)
    get_install(iid)
    items = [public(w) for w in db.warranty_claims.values() if w["install_job_id"] == iid]
    page, limit, offset, total = paginate(items)
    return envelope_array(page, limit, offset, total)


@app.route("/warranty-claims/<wid>/resolve", methods=["POST"])
def resolve_warranty_claim(wid):
    require_roles("Installer", "ShopManager")
    claim = get_warranty(wid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Claim is not SUBMITTED.")
    body = get_body()
    resolution = req_enum(body, "resolution", {"SEAL_REPAIR", "REPLACEMENT", "REJECT"})

    if resolution == "SEAL_REPAIR":
        claim["resolution"] = "SEAL_REPAIR"
        claim["status"] = "RESOLVED"
    elif resolution == "REPLACEMENT":
        claim["resolution"] = "REPLACEMENT"
        claim["status"] = "RESOLVED"
        job = db.install_jobs.get(claim["install_job_id"])
        if job is not None:
            project = db.projects.get(job["project_id"])
            if project is not None:
                project["status"] = "IN_PRODUCTION"
                touch(project)
    else:  # REJECT
        claim["resolution"] = "REJECTED"
        claim["status"] = "REJECTED"
    touch(claim)
    return envelope_object(public(claim), 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ShopManager")
    body = get_body()
    to_iso = body.get("to_iso8601")
    try:
        db.clock = parse_dt(to_iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Field 'to_iso8601' must be an ISO 8601 datetime.")
    return envelope_object({}, 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
