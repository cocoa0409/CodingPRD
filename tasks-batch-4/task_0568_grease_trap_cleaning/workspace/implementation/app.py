import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory data store (starts empty on every boot; NEVER seeded)
# =============================================================================
DB = {
    "customers": {},
    "sites": {},
    "equipment": {},
    "contracts": {},
    "technicians": {},
    "workorders": {},
    "manifests": {},
    "certificates": {},
    "reports": {},
    "invoices": {},
}

_SEQ = {"n": 0}

# Logical service clock — startup default per PRD 2.5; never falls back to wall clock.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

ROLES = {"Admin", "Dispatcher", "Technician", "ComplianceOfficer", "BillingClerk"}


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# =============================================================================
# Time helpers
# =============================================================================
def wall_now():
    return datetime.now(timezone.utc)


def logical_now():
    return CLOCK["now"]


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip()
    try:
        if t.endswith("Z") or t.endswith("z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Response envelope
# =============================================================================
def meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": iso(wall_now())}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# =============================================================================
# Auth / RBAC
# =============================================================================
def principal():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-Role")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# =============================================================================
# Body / field helpers
# =============================================================================
def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, "Missing or invalid field: %s" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, "Invalid field: %s" % key)
    return v


def req_int(body, key):
    v = body.get(key)
    if not is_int(v):
        err("ERR_VALIDATION", 400, "Missing or invalid integer field: %s" % key)
    return v


def opt_int(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not is_int(v):
        err("ERR_VALIDATION", 400, "Invalid integer field: %s" % key)
    return v


def req_number(body, key):
    v = body.get(key)
    if not is_number(v):
        err("ERR_VALIDATION", 400, "Missing or invalid number field: %s" % key)
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 400, "Missing or invalid boolean field: %s" % key)
    return v


def req_enum(body, key, choices):
    v = body.get(key)
    if v not in choices:
        err("ERR_VALIDATION", 400, "Missing or invalid enum field: %s" % key)
    return v


def opt_enum(body, key, choices, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if v not in choices:
        err("ERR_VALIDATION", 400, "Invalid enum field: %s" % key)
    return v


def req_dt(body, key, error_id="ERR_VALIDATION", http=400):
    raw = body.get(key)
    dt = parse_dt(raw)
    if dt is None:
        err(error_id, http, "Missing or invalid datetime field: %s" % key)
    return dt


# =============================================================================
# Common entity helpers
# =============================================================================
def base_entity():
    now = wall_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = wall_now()
    entity["version"] += 1


def common_out(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


# =============================================================================
# Existence lookups
# =============================================================================
def lookup(coll, _id):
    e = DB[coll].get(_id)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Resource not found: %s" % _id)
    return e


# =============================================================================
# Pagination
# =============================================================================
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_PAGINATION_INVALID", 400, "Invalid limit")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_PAGINATION_INVALID", 400, "Invalid offset")
    if limit < 1 or limit > 100:
        err("ERR_PAGINATION_INVALID", 400, "limit out of range")
    if offset < 0:
        err("ERR_PAGINATION_INVALID", 400, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pag


# =============================================================================
# Domain computations
# =============================================================================
def equipment_last_service(eq):
    comps = [
        wo["completed_at"]
        for wo in DB["workorders"].values()
        if wo["equipment_id"] == eq["id"]
        and wo["status"] == "COMPLETED"
        and wo["completed_at"] is not None
    ]
    return max(comps) if comps else None


def equipment_next_due(eq):
    last = equipment_last_service(eq)
    if last is None:
        return None
    return last + timedelta(days=eq["nominal_frequency_days"])


def equipment_service_state(eq):
    now = logical_now()
    nd = equipment_next_due(eq)
    if nd is None or nd < now:
        return "OVERDUE"
    if nd < now + timedelta(days=7):
        return "DUE_SOON"
    return "CURRENT"


def equipment_lifetime_pumped(eq):
    total = 0
    for m in DB["manifests"].values():
        if m["status"] != "RECORDED":
            continue
        wo = DB["workorders"].get(m["work_order_id"])
        if wo is not None and wo["equipment_id"] == eq["id"]:
            total += m["volume_gallons"]
    return total


def site_grade(site):
    now = logical_now()
    overdue = 0
    due7 = 0
    due30 = 0
    for eq in DB["equipment"].values():
        if eq["site_id"] != site["id"] or eq["status"] != "ACTIVE":
            continue
        nd = equipment_next_due(eq)
        if nd is None or nd < now:
            overdue += 1
        else:
            if nd < now + timedelta(days=7):
                due7 += 1
            if nd < now + timedelta(days=30):
                due30 += 1
    compliance = "NON_COMPLIANT" if overdue > 0 else ("AT_RISK" if due7 > 0 else "COMPLIANT")
    projected = "NON_COMPLIANT" if overdue > 0 else ("AT_RISK" if due30 > 0 else "COMPLIANT")
    return compliance, projected


def customer_outstanding_balance(customer_id):
    total = 0
    for inv in DB["invoices"].values():
        if inv["customer_id"] == customer_id and inv["status"] == "ISSUED":
            total += inv["total_amount_cents"] or 0
    return total


def reconcile_customer(customer_id):
    c = DB["customers"].get(customer_id)
    if c is None or c["account_status"] == "CLOSED":
        return
    has_nc = any(
        site_grade(s)[0] == "NON_COMPLIANT"
        for s in DB["sites"].values()
        if s["customer_id"] == customer_id
    )
    if has_nc and c["account_status"] == "ACTIVE":
        c["account_status"] = "SUSPENDED"
        touch(c)
    elif not has_nc and c["account_status"] == "SUSPENDED":
        c["account_status"] = "ACTIVE"
        touch(c)


# =============================================================================
# Serializers
# =============================================================================
def out_customer(c):
    d = common_out(c)
    d.update({
        "business_name": c["business_name"],
        "billing_email": c["billing_email"],
        "credit_limit_cents": c["credit_limit_cents"],
        "account_status": c["account_status"],
        "outstanding_balance_cents": customer_outstanding_balance(c["id"]),
    })
    return d


def out_site(s):
    compliance, projected = site_grade(s)
    d = common_out(s)
    d.update({
        "customer_id": s["customer_id"],
        "address": s["address"],
        "municipality_code": s["municipality_code"],
        "permit_number": s["permit_number"],
        "compliance_status": compliance,
        "projected_compliance_status": projected,
        "last_certified_at": iso(s["last_certified_at"]),
    })
    return d


def out_equipment(eq):
    d = common_out(eq)
    d.update({
        "site_id": eq["site_id"],
        "equipment_type": eq["equipment_type"],
        "capacity_gallons": eq["capacity_gallons"],
        "nominal_frequency_days": eq["nominal_frequency_days"],
        "status": eq["status"],
        "last_service_at": iso(equipment_last_service(eq)),
        "next_service_due_at": iso(equipment_next_due(eq)),
        "service_state": equipment_service_state(eq),
        "lifetime_pumped_gallons": equipment_lifetime_pumped(eq),
    })
    return d


def out_contract(c):
    d = common_out(c)
    d.update({
        "customer_id": c["customer_id"],
        "billing_cycle": c["billing_cycle"],
        "base_rate_cents": c["base_rate_cents"],
        "tax_rate_bps": c["tax_rate_bps"],
        "status": c["status"],
    })
    return d


def out_technician(t):
    d = common_out(t)
    d.update({
        "full_name": t["full_name"],
        "certification_level": t["certification_level"],
        "status": t["status"],
    })
    return d


def out_workorder(w):
    d = common_out(w)
    d.update({
        "site_id": w["site_id"],
        "equipment_id": w["equipment_id"],
        "contract_id": w["contract_id"],
        "technician_id": w["technician_id"],
        "service_type": w["service_type"],
        "priority": w["priority"],
        "planned_start": iso(w["planned_start"]),
        "planned_end": iso(w["planned_end"]),
        "status": w["status"],
        "actual_hours": w["actual_hours"],
        "service_fee_cents": w["service_fee_cents"],
        "emergency_surcharge_cents": w["emergency_surcharge_cents"],
        "completed_at": iso(w["completed_at"]),
    })
    return d


def out_manifest(m):
    d = common_out(m)
    d.update({
        "work_order_id": m["work_order_id"],
        "disposal_facility_name": m["disposal_facility_name"],
        "disposal_facility_permit": m["disposal_facility_permit"],
        "hazmat_certified": m["hazmat_certified"],
        "volume_gallons": m["volume_gallons"],
        "fog_percentage": m["fog_percentage"],
        "manifest_number": m["manifest_number"],
        "compliance_flag": m["compliance_flag"],
        "disposal_fee_cents": m["disposal_fee_cents"],
        "status": m["status"],
    })
    return d


def out_certificate(c):
    d = common_out(c)
    d.update({
        "work_order_id": c["work_order_id"],
        "cleanliness_grade": c["cleanliness_grade"],
        "sticker_number": c["sticker_number"],
        "issued_at": iso(c["issued_at"]),
        "valid_until": iso(c["valid_until"]),
    })
    return d


def out_report(r):
    if r["status"] == "DRAFT":
        pumped, count = compute_report_aggregates(r)
    else:
        pumped, count = r["pumped_gallons_total"], r["included_manifest_count"]
    d = common_out(r)
    d.update({
        "site_id": r["site_id"],
        "municipality_code": r["municipality_code"],
        "period_start": iso(r["period_start"]),
        "period_end": iso(r["period_end"]),
        "status": r["status"],
        "pumped_gallons_total": pumped,
        "included_manifest_count": count,
        "decision_note": r["decision_note"],
    })
    return d


def out_invoice(inv):
    d = common_out(inv)
    d.update({
        "customer_id": inv["customer_id"],
        "contract_id": inv["contract_id"],
        "period_start": iso(inv["period_start"]),
        "period_end": iso(inv["period_end"]),
        "status": inv["status"],
        "provisional_total_cents": inv["provisional_total_cents"],
        "subtotal_cents": inv["subtotal_cents"],
        "tax_cents": inv["tax_cents"],
        "total_amount_cents": inv["total_amount_cents"],
        "amount_paid_cents": inv["amount_paid_cents"],
    })
    return d


# =============================================================================
# Report aggregate computation
# =============================================================================
def compute_report_aggregates(report):
    ps = report["period_start"]
    pe = report["period_end"]
    site_id = report["site_id"]
    pumped = 0
    count = 0
    for m in DB["manifests"].values():
        if m["status"] != "RECORDED":
            continue
        wo = DB["workorders"].get(m["work_order_id"])
        if wo is None or wo["site_id"] != site_id:
            continue
        ca = wo["completed_at"]
        if ca is None:
            continue
        if ps <= ca < pe:
            pumped += m["volume_gallons"]
            count += 1
    return pumped, count


# =============================================================================
# Invoice valuation
# =============================================================================
def workorder_customer_id(wo):
    site = DB["sites"].get(wo["site_id"])
    return site["customer_id"] if site else None


def invoice_lines(customer_id, ps, pe, contract, variant):
    lines = []
    if contract is not None and contract["status"] == "ACTIVE" and contract["base_rate_cents"] > 0:
        lines.append(contract["base_rate_cents"])
    for wo in DB["workorders"].values():
        if workorder_customer_id(wo) != customer_id:
            continue
        if variant == "provisional":
            if wo["status"] not in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS", "COMPLETED"):
                continue
            if not (ps <= wo["planned_start"] < pe):
                continue
        else:  # final
            if wo["status"] != "COMPLETED" or wo["completed_at"] is None:
                continue
            if not (ps <= wo["completed_at"] < pe):
                continue
        lines.append(wo["service_fee_cents"] + wo["emergency_surcharge_cents"])
    return lines


def value_invoice(customer_id, ps, pe, contract, variant):
    lines = invoice_lines(customer_id, ps, pe, contract, variant)
    tax_bps = contract["tax_rate_bps"] if contract is not None else 0
    subtotal = sum(lines)
    tax = 0
    for a in lines:
        tax += round_half_up(Decimal(a) * Decimal(tax_bps) / Decimal(10000))
    total = subtotal + tax
    return len(lines), subtotal, tax, total


# =============================================================================
# Customer endpoints
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    business_name = req_str(body, "business_name")
    billing_email = req_str(body, "billing_email")
    credit_limit = opt_int(body, "credit_limit_cents", 500000)
    c = base_entity()
    c.update({
        "business_name": business_name,
        "billing_email": billing_email,
        "credit_limit_cents": credit_limit,
        "account_status": "ACTIVE",
    })
    DB["customers"][c["id"]] = c
    return ok(out_customer(c), status=201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = principal()
    require_role(role, ROLES)
    c = lookup("customers", cid)
    return ok(out_customer(c))


@app.route("/customers/<cid>/sites", methods=["GET"])
def list_customer_sites(cid):
    _, role = principal()
    require_role(role, ROLES)
    lookup("customers", cid)
    limit, offset = parse_pagination()
    items = [s for s in DB["sites"].values() if s["customer_id"] == cid]
    page, pag = paginate(items, limit, offset)
    return ok([out_site(s) for s in page], response_type="array", pagination=pag)


@app.route("/customers/<cid>/contracts", methods=["GET"])
def list_customer_contracts(cid):
    _, role = principal()
    require_role(role, {"Admin", "BillingClerk"})
    lookup("customers", cid)
    limit, offset = parse_pagination()
    items = [c for c in DB["contracts"].values() if c["customer_id"] == cid]
    page, pag = paginate(items, limit, offset)
    return ok([out_contract(c) for c in page], response_type="array", pagination=pag)


@app.route("/customers/<cid>/close", methods=["POST"])
def close_customer(cid):
    _, role = principal()
    require_role(role, {"Admin"})
    c = lookup("customers", cid)
    if c["account_status"] == "CLOSED":
        err("ERR_INVALID_STATE", 409, "Customer already closed")
    if c["account_status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Invalid from-state")
    if customer_outstanding_balance(cid) != 0:
        err("ERR_INVALID_STATE", 409, "Outstanding balance must be zero to close")
    c["account_status"] = "CLOSED"
    touch(c)
    return ok(out_customer(c))


# =============================================================================
# Site endpoints
# =============================================================================
@app.route("/sites", methods=["POST"])
def create_site():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    lookup("customers", customer_id)
    address = req_str(body, "address")
    municipality_code = req_str(body, "municipality_code")
    permit_number = req_str(body, "permit_number")
    s = base_entity()
    s.update({
        "customer_id": customer_id,
        "address": address,
        "municipality_code": municipality_code,
        "permit_number": permit_number,
        "last_certified_at": None,
    })
    DB["sites"][s["id"]] = s
    return ok(out_site(s), status=201)


@app.route("/sites/<sid>", methods=["GET"])
def get_site(sid):
    _, role = principal()
    require_role(role, ROLES)
    s = lookup("sites", sid)
    return ok(out_site(s))


@app.route("/sites/<sid>/equipment", methods=["GET"])
def list_site_equipment(sid):
    _, role = principal()
    require_role(role, ROLES)
    lookup("sites", sid)
    limit, offset = parse_pagination()
    items = [e for e in DB["equipment"].values() if e["site_id"] == sid]
    page, pag = paginate(items, limit, offset)
    return ok([out_equipment(e) for e in page], response_type="array", pagination=pag)


@app.route("/sites/<sid>/compliance-reports", methods=["GET"])
def list_site_reports(sid):
    _, role = principal()
    require_role(role, {"Admin", "ComplianceOfficer"})
    lookup("sites", sid)
    limit, offset = parse_pagination()
    items = [r for r in DB["reports"].values() if r["site_id"] == sid]
    page, pag = paginate(items, limit, offset)
    return ok([out_report(r) for r in page], response_type="array", pagination=pag)


# =============================================================================
# Equipment endpoints
# =============================================================================
@app.route("/equipment", methods=["POST"])
def create_equipment():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    site_id = req_str(body, "site_id")
    site = lookup("sites", site_id)
    equipment_type = req_enum(body, "equipment_type", {"GREASE_TRAP", "HOOD"})
    capacity = req_number(body, "capacity_gallons")
    freq = req_int(body, "nominal_frequency_days")
    eq = base_entity()
    eq.update({
        "site_id": site_id,
        "equipment_type": equipment_type,
        "capacity_gallons": capacity,
        "nominal_frequency_days": freq,
        "status": "ACTIVE",
    })
    before = site_grade(site)
    DB["equipment"][eq["id"]] = eq
    after = site_grade(site)
    if before != after:
        touch(site)
    reconcile_customer(site["customer_id"])
    return ok(out_equipment(eq), status=201)


@app.route("/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    _, role = principal()
    require_role(role, ROLES)
    eq = lookup("equipment", eid)
    return ok(out_equipment(eq))


@app.route("/equipment/<eid>/work-orders", methods=["GET"])
def list_equipment_workorders(eid):
    _, role = principal()
    require_role(role, {"Admin", "Dispatcher", "Technician"})
    lookup("equipment", eid)
    limit, offset = parse_pagination()
    items = [w for w in DB["workorders"].values() if w["equipment_id"] == eid]
    page, pag = paginate(items, limit, offset)
    return ok([out_workorder(w) for w in page], response_type="array", pagination=pag)


@app.route("/equipment/<eid>/decommission", methods=["POST"])
def decommission_equipment(eid):
    _, role = principal()
    require_role(role, {"Admin"})
    eq = lookup("equipment", eid)
    if eq["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Equipment not ACTIVE")
    for w in DB["workorders"].values():
        if w["equipment_id"] == eid and w["status"] in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS"):
            err("ERR_INVALID_STATE", 409, "Open work order references this equipment")
    site = DB["sites"].get(eq["site_id"])
    before = site_grade(site) if site else None
    eq["status"] = "DECOMMISSIONED"
    touch(eq)
    if site is not None:
        after = site_grade(site)
        if before != after:
            touch(site)
        reconcile_customer(site["customer_id"])
    return ok(out_equipment(eq))


# =============================================================================
# ServiceContract endpoints
# =============================================================================
@app.route("/service-contracts", methods=["POST"])
def create_contract():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    lookup("customers", customer_id)
    billing_cycle = req_enum(body, "billing_cycle", {"MONTHLY", "QUARTERLY"})
    base_rate = req_int(body, "base_rate_cents")
    tax_rate = req_int(body, "tax_rate_bps")
    c = base_entity()
    c.update({
        "customer_id": customer_id,
        "billing_cycle": billing_cycle,
        "base_rate_cents": base_rate,
        "tax_rate_bps": tax_rate,
        "status": "DRAFT",
    })
    DB["contracts"][c["id"]] = c
    return ok(out_contract(c), status=201)


@app.route("/service-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    _, role = principal()
    require_role(role, {"Admin", "BillingClerk"})
    c = lookup("contracts", cid)
    return ok(out_contract(c))


CONTRACT_TRANSITIONS = {
    ("DRAFT", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "CANCELLED"),
}


@app.route("/service-contracts/<cid>/transition", methods=["POST"])
def transition_contract(cid):
    _, role = principal()
    require_role(role, {"Admin"})
    c = lookup("contracts", cid)
    body = get_body()
    to_status = req_enum(body, "to_status", {"ACTIVE", "SUSPENDED", "CANCELLED"})
    if (c["status"], to_status) not in CONTRACT_TRANSITIONS:
        err("ERR_INVALID_STATE", 409, "Invalid contract transition")
    c["status"] = to_status
    touch(c)
    return ok(out_contract(c))


# =============================================================================
# Technician endpoints
# =============================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    cert = req_enum(body, "certification_level", {"BASIC", "NFPA96_CERTIFIED"})
    t = base_entity()
    t.update({
        "full_name": full_name,
        "certification_level": cert,
        "status": "AVAILABLE",
    })
    DB["technicians"][t["id"]] = t
    return ok(out_technician(t), status=201)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    _, role = principal()
    require_role(role, {"Admin", "Dispatcher", "Technician"})
    t = lookup("technicians", tid)
    return ok(out_technician(t))


# =============================================================================
# WorkOrder endpoints
# =============================================================================
SERVICE_FEE = {"GREASE_TRAP": 12500, "HOOD": 17500}
EMERGENCY_SURCHARGE = 8000
BUFFER = timedelta(hours=24)


@app.route("/work-orders", methods=["POST"])
def create_workorder():
    _, role = principal()
    require_role(role, {"Dispatcher"})
    body = get_body()
    site_id = req_str(body, "site_id")
    equipment_id = req_str(body, "equipment_id")
    site = lookup("sites", site_id)
    eq = lookup("equipment", equipment_id)
    contract_id = opt_str(body, "contract_id", None)
    if contract_id is not None:
        lookup("contracts", contract_id)
    service_type = req_enum(body, "service_type", {"SCHEDULED", "EMERGENCY"})
    priority = opt_enum(body, "priority", {"ROUTINE", "URGENT"}, "ROUTINE")
    planned_start = req_dt(body, "planned_start")
    planned_end = req_dt(body, "planned_end")
    if not (planned_end > planned_start):
        err("ERR_VALIDATION", 400, "planned_end must be after planned_start")

    # Equipment 24h service buffer against other non-CANCELLED orders on same equipment
    for w in DB["workorders"].values():
        if w["equipment_id"] != equipment_id or w["status"] == "CANCELLED":
            continue
        separation = max(planned_start - w["planned_end"], w["planned_start"] - planned_end)
        if separation < BUFFER:
            err("ERR_EQUIPMENT_SERVICE_TOO_SOON", 409, "Within 24h buffer of another order")

    w = base_entity()
    w.update({
        "site_id": site_id,
        "equipment_id": equipment_id,
        "contract_id": contract_id,
        "technician_id": None,
        "service_type": service_type,
        "priority": priority,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "status": "SCHEDULED",
        "actual_hours": None,
        "service_fee_cents": SERVICE_FEE[eq["equipment_type"]],
        "emergency_surcharge_cents": EMERGENCY_SURCHARGE if service_type == "EMERGENCY" else 0,
        "completed_at": None,
    })
    DB["workorders"][w["id"]] = w
    return ok(out_workorder(w), status=201)


@app.route("/work-orders/<wid>", methods=["GET"])
def get_workorder(wid):
    _, role = principal()
    require_role(role, ROLES)
    w = lookup("workorders", wid)
    return ok(out_workorder(w))


@app.route("/work-orders", methods=["GET"])
def list_workorders():
    _, role = principal()
    require_role(role, {"Admin", "Dispatcher", "Technician", "BillingClerk"})
    limit, offset = parse_pagination()
    items = list(DB["workorders"].values())
    for key, field in (("site_id", "site_id"), ("equipment_id", "equipment_id"),
                       ("technician_id", "technician_id"), ("contract_id", "contract_id"),
                       ("status", "status")):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w[field] == val]
    page, pag = paginate(items, limit, offset)
    return ok([out_workorder(w) for w in page], response_type="array", pagination=pag)


@app.route("/work-orders/<wid>/pump-out-manifests", methods=["GET"])
def list_workorder_manifests(wid):
    _, role = principal()
    require_role(role, {"Admin", "Dispatcher", "Technician", "ComplianceOfficer"})
    lookup("workorders", wid)
    limit, offset = parse_pagination()
    items = [m for m in DB["manifests"].values() if m["work_order_id"] == wid]
    page, pag = paginate(items, limit, offset)
    return ok([out_manifest(m) for m in page], response_type="array", pagination=pag)


@app.route("/work-orders/<wid>/hood-certificates", methods=["GET"])
def list_workorder_certificates(wid):
    _, role = principal()
    require_role(role, {"Admin", "Dispatcher", "Technician", "ComplianceOfficer"})
    lookup("workorders", wid)
    limit, offset = parse_pagination()
    items = [c for c in DB["certificates"].values() if c["work_order_id"] == wid]
    page, pag = paginate(items, limit, offset)
    return ok([out_certificate(c) for c in page], response_type="array", pagination=pag)


@app.route("/work-orders/<wid>/transition", methods=["POST"])
def transition_workorder(wid):
    uid, role = principal()
    require_role(role, {"Dispatcher", "Technician"})
    w = lookup("workorders", wid)
    body = get_body()
    to_status = req_enum(body, "to_status", {"DISPATCHED", "SCHEDULED", "IN_PROGRESS", "CANCELLED"})

    if to_status in ("DISPATCHED", "SCHEDULED", "CANCELLED"):
        # Dispatcher-driven transitions
        if role != "Dispatcher":
            err("ERR_FORBIDDEN", 403, "Only Dispatcher may perform this transition")
        if to_status == "DISPATCHED":
            return _dispatch_workorder(w, body)
        if to_status == "SCHEDULED":
            if w["status"] != "DISPATCHED":
                err("ERR_INVALID_STATE", 409, "Recall requires DISPATCHED")
            w["status"] = "SCHEDULED"
            w["technician_id"] = None
            touch(w)
            return ok(out_workorder(w))
        if to_status == "CANCELLED":
            if w["status"] not in ("SCHEDULED", "DISPATCHED"):
                err("ERR_INVALID_STATE", 409, "Cancel requires SCHEDULED or DISPATCHED")
            was_dispatched = w["status"] == "DISPATCHED"
            w["status"] = "CANCELLED"
            if was_dispatched:
                w["technician_id"] = None
            touch(w)
            return ok(out_workorder(w))
    else:  # IN_PROGRESS
        if role != "Technician":
            err("ERR_FORBIDDEN", 403, "Only Technician may start an order")
        if w["technician_id"] != uid:
            err("ERR_FORBIDDEN", 403, "Technician does not own this order")
        if w["status"] != "DISPATCHED":
            err("ERR_INVALID_STATE", 409, "Start requires DISPATCHED")
        w["status"] = "IN_PROGRESS"
        touch(w)
        return ok(out_workorder(w))


def _dispatch_workorder(w, body):
    technician_id = body.get("technician_id")
    if not isinstance(technician_id, str) or technician_id == "":
        err("ERR_VALIDATION", 400, "technician_id required for dispatch")
    tech = lookup("technicians", technician_id)
    if w["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Dispatch requires SCHEDULED")
    eq = DB["equipment"].get(w["equipment_id"])
    # Safety: NFPA96 certification for HOOD
    if eq is not None and eq["equipment_type"] == "HOOD" and tech["certification_level"] != "NFPA96_CERTIFIED":
        err("ERR_TECHNICIAN_NOT_CERTIFIED", 422, "Technician not NFPA96 certified for HOOD")
    # Technician schedule conflict (half-open overlap)
    for other in DB["workorders"].values():
        if other["id"] == w["id"]:
            continue
        if other["technician_id"] != technician_id:
            continue
        if other["status"] not in ("DISPATCHED", "IN_PROGRESS"):
            continue
        if w["planned_start"] < other["planned_end"] and other["planned_start"] < w["planned_end"]:
            err("ERR_TECHNICIAN_SCHEDULE_CONFLICT", 409, "Technician schedule conflict")
    # Equipment availability
    if eq is None or eq["status"] != "ACTIVE":
        err("ERR_EQUIPMENT_DECOMMISSIONED", 409, "Equipment not ACTIVE")
    w["status"] = "DISPATCHED"
    w["technician_id"] = technician_id
    touch(w)
    return ok(out_workorder(w))


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_workorder(wid):
    uid, role = principal()
    require_role(role, {"Technician"})
    w = lookup("workorders", wid)
    if w["technician_id"] != uid:
        err("ERR_FORBIDDEN", 403, "Technician does not own this order")
    body = get_body()
    actual_hours = req_number(body, "actual_hours")
    if w["status"] != "IN_PROGRESS":
        err("ERR_INVALID_STATE", 409, "Complete requires IN_PROGRESS")
    eq = DB["equipment"].get(w["equipment_id"])
    if eq is not None and eq["equipment_type"] == "GREASE_TRAP":
        has_manifest = any(
            m["work_order_id"] == wid and m["status"] == "RECORDED"
            for m in DB["manifests"].values()
        )
        if not has_manifest:
            err("ERR_MANIFEST_REQUIRED", 422, "GREASE_TRAP order requires a RECORDED manifest")
    elif eq is not None and eq["equipment_type"] == "HOOD":
        tech = DB["technicians"].get(uid)
        if tech is None or tech["certification_level"] != "NFPA96_CERTIFIED":
            err("ERR_TECHNICIAN_NOT_CERTIFIED", 422, "Technician not NFPA96 certified for HOOD")
        certs = [c for c in DB["certificates"].values() if c["work_order_id"] == wid]
        if not certs:
            err("ERR_CERTIFICATE_REQUIRED", 422, "HOOD order requires a certificate")
        if not any(c["cleanliness_grade"] != "FAILING" for c in certs):
            err("ERR_CLEANLINESS_FAILED", 422, "Certificate cleanliness grade is FAILING")

    # Execute completion + cascade
    now = logical_now()
    w["status"] = "COMPLETED"
    w["actual_hours"] = actual_hours
    w["completed_at"] = now
    touch(w)

    if eq is not None:
        site = DB["sites"].get(eq["site_id"])
        before = site_grade(site) if site else None
        touch(eq)  # L1: equipment service schedule recomputed
        if site is not None:
            after = site_grade(site)
            if before != after:
                touch(site)  # L2: site compliance recomputed
            reconcile_customer(site["customer_id"])  # L3
    return ok(out_workorder(w))


# =============================================================================
# PumpOutManifest endpoints
# =============================================================================
@app.route("/pump-out-manifests", methods=["POST"])
def create_manifest():
    uid, role = principal()
    require_role(role, {"Technician"})
    body = get_body()
    work_order_id = req_str(body, "work_order_id")
    wo = lookup("workorders", work_order_id)
    disposal_facility_name = req_str(body, "disposal_facility_name")
    # disposal_facility_permit shape: present string (well-formedness checked at referential stage)
    permit = body.get("disposal_facility_permit")
    hazmat = req_bool(body, "hazmat_certified")
    volume = req_number(body, "volume_gallons")
    fog = req_number(body, "fog_percentage")

    # Referential type integrity (priority 6)
    eq = DB["equipment"].get(wo["equipment_id"])
    if eq is None or eq["equipment_type"] != "GREASE_TRAP":
        err("ERR_EQUIPMENT_TYPE_MISMATCH", 422, "Work order is not GREASE_TRAP")
    if not isinstance(permit, str) or not permit.startswith("FAC-"):
        err("ERR_DISPOSAL_FACILITY_INVALID", 422, "disposal_facility_permit must start with FAC-")

    compliance_flag = "COMPLIANT" if fog < 25.0 else "NON_COMPLIANT"
    disposal_fee = compute_disposal_fee(volume, fog, hazmat)

    m = base_entity()
    m.update({
        "work_order_id": work_order_id,
        "disposal_facility_name": disposal_facility_name,
        "disposal_facility_permit": permit,
        "hazmat_certified": hazmat,
        "volume_gallons": volume,
        "fog_percentage": fog,
        "manifest_number": "MFT-" + m["id"][:8].upper(),
        "compliance_flag": compliance_flag,
        "disposal_fee_cents": disposal_fee,
        "status": "RECORDED",
    })
    DB["manifests"][m["id"]] = m

    if eq is not None:
        site = DB["sites"].get(eq["site_id"])
        before = site_grade(site) if site else None
        touch(eq)  # lifetime_pumped_gallons changed
        if site is not None:
            after = site_grade(site)
            if before != after:
                touch(site)
            reconcile_customer(site["customer_id"])
    return ok(out_manifest(m), status=201)


def compute_disposal_fee(volume, fog, hazmat):
    g = Decimal(str(volume))
    t1 = min(g, Decimal(500))
    t2 = max(Decimal(0), min(g, Decimal(1500)) - Decimal(500))
    t3 = max(Decimal(0), g - Decimal(1500))
    gallons_cost = t1 * 40 + t2 * 35 + t3 * 30
    fog_surcharge = round_half_up(gallons_cost * Decimal("0.20")) if fog >= 25.0 else 0
    hazmat_flat = 5000 if hazmat else 0
    total = gallons_cost + Decimal(fog_surcharge) + Decimal(hazmat_flat)
    return int(total)


@app.route("/pump-out-manifests/<mid>/void", methods=["POST"])
def void_manifest(mid):
    _, role = principal()
    require_role(role, {"Technician", "ComplianceOfficer"})
    m = lookup("manifests", mid)
    if m["status"] == "VOIDED":
        err("ERR_MANIFEST_ALREADY_VOIDED", 409, "Manifest already voided")
    if m["status"] != "RECORDED":
        err("ERR_INVALID_STATE", 409, "Manifest not RECORDED")
    m["status"] = "VOIDED"
    touch(m)
    wo = DB["workorders"].get(m["work_order_id"])
    if wo is not None:
        eq = DB["equipment"].get(wo["equipment_id"])
        if eq is not None:
            site = DB["sites"].get(eq["site_id"])
            before = site_grade(site) if site else None
            touch(eq)  # lifetime_pumped_gallons restored
            if site is not None:
                after = site_grade(site)
                if before != after:
                    touch(site)
                reconcile_customer(site["customer_id"])
    return ok(out_manifest(m))


# =============================================================================
# HoodCertificate endpoints
# =============================================================================
@app.route("/hood-certificates", methods=["POST"])
def create_certificate():
    uid, role = principal()
    require_role(role, {"Technician"})
    body = get_body()
    work_order_id = req_str(body, "work_order_id")
    wo = lookup("workorders", work_order_id)
    grade = req_enum(body, "cleanliness_grade", {"BARE_METAL_CLEAN", "ACCEPTABLE", "FAILING"})

    eq = DB["equipment"].get(wo["equipment_id"])
    if eq is None or eq["equipment_type"] != "HOOD":
        err("ERR_EQUIPMENT_TYPE_MISMATCH", 422, "Work order is not HOOD")
    tech = DB["technicians"].get(uid)
    if tech is None or tech["certification_level"] != "NFPA96_CERTIFIED":
        err("ERR_TECHNICIAN_NOT_CERTIFIED", 422, "Technician not NFPA96 certified")

    now = logical_now()
    c = base_entity()
    c.update({
        "work_order_id": work_order_id,
        "cleanliness_grade": grade,
        "sticker_number": "NFPA96-" + c["id"][:8].upper(),
        "issued_at": now,
        "valid_until": now + timedelta(days=eq["nominal_frequency_days"]),
    })
    DB["certificates"][c["id"]] = c
    return ok(out_certificate(c), status=201)


# =============================================================================
# ComplianceReport endpoints
# =============================================================================
@app.route("/compliance-reports", methods=["POST"])
def create_report():
    _, role = principal()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    site_id = req_str(body, "site_id")
    lookup("sites", site_id)
    municipality_code = req_str(body, "municipality_code")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if not (period_end > period_start):
        err("ERR_REPORT_PERIOD_INVALID", 422, "period_end must be after period_start")
    r = base_entity()
    r.update({
        "site_id": site_id,
        "municipality_code": municipality_code,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "pumped_gallons_total": None,
        "included_manifest_count": None,
        "decision_note": None,
    })
    DB["reports"][r["id"]] = r
    return ok(out_report(r), status=201)


@app.route("/compliance-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    _, role = principal()
    require_role(role, {"ComplianceOfficer"})
    r = lookup("reports", rid)
    if r["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Submit requires DRAFT")
    site = DB["sites"].get(r["site_id"])
    if site is not None and site_grade(site)[0] == "NON_COMPLIANT":
        err("ERR_INVALID_STATE", 409, "Cannot submit while site is NON_COMPLIANT")
    pumped, count = compute_report_aggregates(r)
    r["pumped_gallons_total"] = pumped
    r["included_manifest_count"] = count
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(out_report(r))


@app.route("/compliance-reports/<rid>/record-decision", methods=["POST"])
def record_decision(rid):
    _, role = principal()
    require_role(role, {"ComplianceOfficer"})
    r = lookup("reports", rid)
    body = get_body()
    decision = req_enum(body, "decision", {"ACCEPTED", "REJECTED"})
    decision_note = opt_str(body, "decision_note", None)
    if r["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Decision requires SUBMITTED")
    r["decision_note"] = decision_note
    if decision == "ACCEPTED":
        r["status"] = "ACCEPTED"
        touch(r)
        site = DB["sites"].get(r["site_id"])
        if site is not None:
            site["last_certified_at"] = logical_now()
            touch(site)  # L1: last_certified_at set + compliance recomputed
            reconcile_customer(site["customer_id"])  # L2
    else:
        r["status"] = "REJECTED"
        touch(r)
    return ok(out_report(r))


@app.route("/compliance-reports/<rid>/revise", methods=["POST"])
def revise_report(rid):
    _, role = principal()
    require_role(role, {"ComplianceOfficer"})
    r = lookup("reports", rid)
    if r["status"] != "REJECTED":
        err("ERR_INVALID_STATE", 409, "Revise requires REJECTED")
    r["status"] = "DRAFT"
    touch(r)
    return ok(out_report(r))


@app.route("/compliance-reports/<rid>/transition", methods=["POST"])
def transition_report(rid):
    _, role = principal()
    require_role(role, {"ComplianceOfficer"})
    r = lookup("reports", rid)
    body = get_body()
    to_status = req_enum(body, "to_status", {"CANCELLED"})
    if r["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Cancel requires DRAFT")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(out_report(r))


# =============================================================================
# Invoice endpoints
# =============================================================================
@app.route("/invoices", methods=["POST"])
def create_invoice():
    _, role = principal()
    require_role(role, {"BillingClerk"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    customer = lookup("customers", customer_id)
    contract_id = opt_str(body, "contract_id", None)
    contract = None
    if contract_id is not None:
        contract = lookup("contracts", contract_id)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    # OCC field required (shape stage) -> ERR_VERSION_REQUIRED
    if "expected_customer_version" not in body or body.get("expected_customer_version") is None:
        err("ERR_VERSION_REQUIRED", 400, "expected_customer_version required")
    expected_version = body.get("expected_customer_version")
    if not is_int(expected_version):
        err("ERR_VALIDATION", 400, "expected_customer_version must be an integer")
    if not (period_end > period_start):
        err("ERR_REPORT_PERIOD_INVALID", 422, "period_end must be after period_start")
    # OCC check (priority 14)
    if expected_version != customer["version"]:
        err("ERR_STALE_VERSION", 412, "Stale customer version")

    _, _, _, provisional = value_invoice(customer_id, period_start, period_end, contract, "provisional")

    # Supersede prior DRAFT invoice for same customer + period
    for inv in DB["invoices"].values():
        if (inv["customer_id"] == customer_id and inv["status"] == "DRAFT"
                and inv["period_start"] == period_start and inv["period_end"] == period_end):
            inv["status"] = "VOID"
            touch(inv)

    inv = base_entity()
    inv.update({
        "customer_id": customer_id,
        "contract_id": contract_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "provisional_total_cents": provisional,
        "subtotal_cents": None,
        "tax_cents": None,
        "total_amount_cents": None,
        "amount_paid_cents": 0,
    })
    DB["invoices"][inv["id"]] = inv
    touch(customer)  # invoice creation advances customer version
    return ok(out_invoice(inv), status=201)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _, role = principal()
    require_role(role, {"Admin", "BillingClerk"})
    inv = lookup("invoices", iid)
    return ok(out_invoice(inv))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = principal()
    require_role(role, {"Admin", "BillingClerk"})
    limit, offset = parse_pagination()
    items = list(DB["invoices"].values())
    for key in ("customer_id", "contract_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    page, pag = paginate(items, limit, offset)
    return ok([out_invoice(i) for i in page], response_type="array", pagination=pag)


@app.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    _, role = principal()
    require_role(role, {"BillingClerk"})
    inv = lookup("invoices", iid)
    if inv["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Issue requires DRAFT")
    customer = DB["customers"].get(inv["customer_id"])
    contract = DB["contracts"].get(inv["contract_id"]) if inv["contract_id"] else None
    n_lines, subtotal, tax, total = value_invoice(
        inv["customer_id"], inv["period_start"], inv["period_end"], contract, "final")
    if n_lines < 1:
        err("ERR_NO_BILLABLE_ACTIVITY", 422, "No billable activity")
    if customer is not None and customer["account_status"] == "CLOSED":
        err("ERR_CUSTOMER_CLOSED", 409, "Customer is closed")
    outstanding = customer_outstanding_balance(inv["customer_id"])
    if customer is not None and outstanding + total > customer["credit_limit_cents"]:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402, "Credit limit exceeded")
    inv["subtotal_cents"] = subtotal
    inv["tax_cents"] = tax
    inv["total_amount_cents"] = total
    inv["status"] = "ISSUED"
    touch(inv)
    if customer is not None:
        touch(customer)  # balance debit -> version increment
    return ok(out_invoice(inv))


@app.route("/invoices/<iid>/record-payment", methods=["POST"])
def record_payment(iid):
    _, role = principal()
    require_role(role, {"BillingClerk"})
    inv = lookup("invoices", iid)
    body = get_body()
    amount = req_int(body, "amount_cents")
    if inv["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "Payment requires ISSUED")
    if amount != inv["total_amount_cents"]:
        err("ERR_VALIDATION", 400, "amount_cents must equal total_amount_cents")
    inv["status"] = "PAID"
    inv["amount_paid_cents"] = amount
    touch(inv)
    customer = DB["customers"].get(inv["customer_id"])
    if customer is not None:
        touch(customer)  # balance credit -> version increment
    return ok(out_invoice(inv))


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _, role = principal()
    require_role(role, {"BillingClerk"})
    inv = lookup("invoices", iid)
    if inv["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "Void requires ISSUED")
    inv["status"] = "VOID"
    touch(inv)
    customer = DB["customers"].get(inv["customer_id"])
    if customer is not None:
        touch(customer)  # reverse debit -> version increment
    return ok(out_invoice(inv))


# =============================================================================
# Logical clock control
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = principal()
    require_role(role, {"Admin"})
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    CLOCK["now"] = dt
    return ok({})


# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
