#!/usr/bin/env python3
"""Home Medical Supply & DME Mail-Order API — in-memory Flask implementation."""
import os
import re
import uuid
import random
import string
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory store (empty at boot; all state is built via API calls)
# =============================================================================
STORE = {
    "payer_plans": {},
    "formulary_items": {},
    "patients": {},
    "prescriptions": {},
    "fit_profiles": {},
    "resupply_programs": {},
    "orders": {},
    "order_lines": {},
    "prior_authorizations": {},
    "shipments": {},
    "stock_levels": {},
    "backorder_reservations": {},
    "claims": {},
    "hsa_accounts": {},
    "hsa_entries": {},
    "fitting_samples": {},
}

# =============================================================================
# Logical clock
# =============================================================================
LOGICAL_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_last_stamp = None


def today():
    return LOGICAL_CLOCK.date()


def stamp():
    """Monotone ISO-8601 UTC timestamp with 3 fractional digits, driven by the
    logical clock so entity created_at/updated_at observe logical time."""
    global _last_stamp
    base = LOGICAL_CLOCK
    if _last_stamp is None or base > _last_stamp:
        ts = base
    else:
        ts = _last_stamp + timedelta(milliseconds=1)
    _last_stamp = ts
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ts.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


# =============================================================================
# Errors / envelope
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24)),
        "api_request_timestamp": stamp(),
    }


def js(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: js(x) for k, x in v.items()}
    if isinstance(v, list):
        return [js(x) for x in v]
    return v


def success(data, code=200, page=None):
    m = meta()
    if page is not None:
        m.update(page)
    return jsonify({
        "meta": m,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": js(data),
    }), code


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


@app.errorhandler(404)
def _not_found(e):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }), 404


@app.errorhandler(405)
def _method(e):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "method not allowed"},
    }), 405


@app.errorhandler(500)
def _internal(e):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "internal server error"},
    }), 500


# =============================================================================
# Auth
# =============================================================================
ROLES = {"Patient", "IntakeCoordinator", "PriorAuthSpecialist",
         "FulfillmentAgent", "BillingSpecialist", "PlatformAdmin"}


def auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        err("ERR_UNAUTHENTICATED", 401, "missing X-User-Role or X-User-ID header")
    if role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "unknown role")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "role not permitted on this endpoint")


def require_own(role, uid, patient_id):
    if role == "Patient" and uid != patient_id:
        err("ERR_FORBIDDEN", 403, "patient may only act on own resources")


# =============================================================================
# Body / field validation helpers
# =============================================================================
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    d = request.get_json(silent=True)
    if d is None:
        if request.data:
            err("ERR_INVALID_REQUEST", 400, "malformed JSON body")
        return {}
    if not isinstance(d, dict):
        err("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return d


def f_str(d, k, required=True):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return None
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400, "field %s must be a non-empty string" % k)
    return v


def f_int(d, k, required=True, minv=None):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "field %s must be an integer" % k)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", 400, "field %s must be >= %d" % (k, minv))
    return v


def f_num(d, k, required=True, minv=None):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 400, "field %s must be a number" % k)
    dv = Decimal(str(v))
    if minv is not None and dv < Decimal(str(minv)):
        err("ERR_INVALID_REQUEST", 400, "field %s must be >= %s" % (k, minv))
    return dv


def f_bool(d, k, required=True, default=None):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return default
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "field %s must be a boolean" % k)
    return v


def f_enum(d, k, allowed, required=True, default=None):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return default
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "field %s must be one of %s" % (k, allowed))
    return v


def f_date(d, k, required=True):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        err("ERR_INVALID_REQUEST", 400, "field %s must be an ISO date (YYYY-MM-DD)" % k)
    try:
        date.fromisoformat(v)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "field %s is not a valid calendar date" % k)
    return v


def f_list(d, k, required=True):
    v = d.get(k)
    if v is None:
        if required:
            err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % k)
        return None
    if not isinstance(v, list):
        err("ERR_INVALID_REQUEST", 400, "field %s must be an array" % k)
    return v


def parse_d(s):
    return date.fromisoformat(s)


# =============================================================================
# Entity helpers
# =============================================================================
def base_fields():
    t = stamp()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


def touch(e):
    e["updated_at"] = stamp()
    e["version"] += 1


def get_or_404(coll, id_):
    e = STORE[coll].get(id_)
    if e is None:
        err("ERR_NOT_FOUND", 404, "resource not found: %s" % id_)
    return e


def rnd2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def paginate(items):
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if offset < 0:
        err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page_items = items[offset:offset + limit]
    return page_items, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page_items)) < total,
    }


# =============================================================================
# Domain helpers
# =============================================================================
def rx_refresh(rx):
    """Lazy EXPIRED flip for prescriptions (read or validation reference)."""
    if rx["status"] == "ACTIVE" and today() >= parse_d(rx["expiration_date"]):
        rx["status"] = "EXPIRED"
        touch(rx)


def pa_refresh(pa):
    """Lazy EXPIRED flip for prior authorizations (direct reads only)."""
    if pa["status"] == "APPROVED" and today() > parse_d(pa["valid_to"]):
        pa["status"] = "EXPIRED"
        touch(pa)


def covering_rx(patient_id, hcpcs, need_window):
    out = []
    for rx in STORE["prescriptions"].values():
        if rx["patient_id"] == patient_id and rx["hcpcs_code"] == hcpcs:
            rx_refresh(rx)
            if rx["status"] != "ACTIVE":
                continue
            if need_window:
                if parse_d(rx["effective_date"]) <= today() < parse_d(rx["expiration_date"]):
                    out.append(rx)
            else:
                out.append(rx)
    out.sort(key=lambda r: (r["created_at"], r["id"]))
    return out


def approved_pa_covering(patient_id, hcpcs, on=None):
    on = on or today()
    cands = []
    for pa in STORE["prior_authorizations"].values():
        if (pa["patient_id"] == patient_id and pa["hcpcs_code"] == hcpcs
                and pa["status"] == "APPROVED"
                and parse_d(pa["valid_from"]) <= on <= parse_d(pa["valid_to"])):
            cands.append(pa)
    cands.sort(key=lambda p: (p["created_at"], p["id"]))
    return cands[0] if cands else None


def current_fit(patient_id, category):
    for fp in STORE["fit_profiles"].values():
        if (fp["patient_id"] == patient_id and fp["category"] == category
                and fp["status"] == "CURRENT"):
            return fp
    return None


def hsa_of_patient(patient_id):
    for a in STORE["hsa_accounts"].values():
        if a["patient_id"] == patient_id:
            return a
    return None


def hsa_balance(acct):
    bal = Decimal(str(acct["initial_credit_cents"]))
    for e in STORE["hsa_entries"].values():
        if e["hsa_account_id"] != acct["id"]:
            continue
        amt = Decimal(str(e["amount_cents"]))
        if e["entry_type"] == "DEBIT":
            bal -= amt
        else:  # CREDIT or REVERSAL
            bal += amt
    return rnd2(bal)


def refresh_hsa(acct):
    acct["balance_cents"] = hsa_balance(acct)


def stock_of_item(item_id):
    for s in STORE["stock_levels"].values():
        if s["formulary_item_id"] == item_id:
            return s
    return None


def stock_sync(stock):
    stock["available_qty"] = stock["on_hand_qty"] - stock["reserved_qty"]


def order_lines(order_id):
    return sorted(
        [l for l in STORE["order_lines"].values() if l["order_id"] == order_id],
        key=lambda l: (l["created_at"], l["id"]))


def order_shipments(order_id):
    return sorted(
        [s for s in STORE["shipments"].values() if s["order_id"] == order_id],
        key=lambda s: (s["created_at"], s["id"]))


def allowance(patient, plan, item):
    """resupply_quantity_allowance = min(rx_cap, item_cap, pa_cap)."""
    rxs = covering_rx(patient["id"], item["hcpcs_code"], True)
    if not rxs:
        rxs = covering_rx(patient["id"], item["hcpcs_code"], False)
    caps = []
    if rxs:
        caps.append(rxs[0]["monthly_quantity"] * plan["cycle_months"])
    caps.append(item["max_units_per_cycle"])
    if item["requires_pa"]:
        pa = approved_pa_covering(patient["id"], item["hcpcs_code"])
        if pa is not None:
            caps.append(pa["approved_units"])
    return min(caps)


def recompute_order_totals(order):
    patient = STORE["patients"].get(order["patient_id"])
    plan = STORE["payer_plans"].get(patient["payer_plan_id"]) if patient else None
    lines = order_lines(order["id"])
    total_allowed = Decimal("0")
    resp = Decimal("0")
    for l in lines:
        la = Decimal(str(l["line_allowed_cents"]))
        total_allowed += la
        if plan and plan["plan_type"] == "CASH_HSA":
            item = STORE["formulary_items"].get(l["formulary_item_id"])
            retail = Decimal(str(item["retail_price_cents"])) if item else Decimal("0")
            resp += rnd2(retail * l["quantity"])
        elif plan:
            resp += rnd2(la * Decimal(str(plan["coinsurance_pct"])))
    order["total_allowed_cents"] = rnd2(total_allowed)
    order["total_patient_resp_cents"] = rnd2(resp)


def recompute_adherence(program):
    start = parse_d(program["start_date"])
    if today() < start:
        program["adherence_score_provisional"] = None
        program["adherence_score_final"] = None
        return
    cycles_due = (today() - start).days // program["frequency_days"] + 1
    delivered = 0
    in_transit = 0
    for o in STORE["orders"].values():
        if (o["resupply_program_id"] == program["id"]
                and o["origin"] == "PROGRAM_CYCLE"
                and o["fulfillment_status"] != "CANCELLED"):
            sts = {s["status"] for s in order_shipments(o["id"])}
            if "DELIVERED" in sts:
                delivered += 1
            elif "SHIPPED" in sts:
                in_transit += 1
    program["adherence_score_final"] = rnd2(Decimal(delivered) / Decimal(cycles_due))
    program["adherence_score_provisional"] = rnd2(Decimal(delivered + in_transit) / Decimal(cycles_due))


def bubble_order(order):
    if order["fulfillment_status"] != "IN_FULFILLMENT":
        return
    ships = order_shipments(order["id"])
    if (any(s["status"] == "DELIVERED" for s in ships)
            and not any(s["status"] in ("CREATED", "BACKORDERED", "READY", "SHIPPED") for s in ships)):
        order["fulfillment_status"] = "FULFILLED"
        touch(order)


def line_reserved_units(line):
    pending = sum(r["quantity_pending"] for r in STORE["backorder_reservations"].values()
                  if r["order_line_id"] == line["id"])
    return line["quantity"] - pending


def maybe_suspend_low_adherence(program):
    score = program["adherence_score_final"]
    if (program["status"] == "ACTIVE" and score is not None
            and Decimal(str(score)) < Decimal("0.50")):
        program["status"] = "SUSPENDED"
        program["suspend_reason"] = "LOW_ADHERENCE"
        touch(program)


def run_backorder_allocation(stock, qty_added):
    remaining = qty_added
    item_id = stock["formulary_item_id"]
    cands = []
    for r in STORE["backorder_reservations"].values():
        if r["status"] not in ("PENDING", "PARTIALLY_ALLOCATED"):
            continue
        line = STORE["order_lines"].get(r["order_line_id"])
        if line is None or line["formulary_item_id"] != item_id:
            continue
        order = STORE["orders"].get(line["order_id"])
        cands.append((r["created_at"], order["created_at"] if order else "", r["id"], r))
    cands.sort(key=lambda t: (t[0], t[1], t[2]))
    for _, _, _, r in cands:
        if remaining <= 0:
            break
        alloc = min(r["quantity_pending"], remaining)
        if alloc <= 0:
            continue
        r["quantity_pending"] -= alloc
        r["quantity_allocated"] += alloc
        stock["reserved_qty"] += alloc
        remaining -= alloc
        r["status"] = "ALLOCATED" if r["quantity_pending"] == 0 else "PARTIALLY_ALLOCATED"
        touch(r)
    stock_sync(stock)
    # revive fully-covered BACKORDERED shipments
    for s in STORE["shipments"].values():
        if s["status"] != "BACKORDERED":
            continue
        lines = order_lines(s["order_id"])
        open_res = [r for r in STORE["backorder_reservations"].values()
                    if r["order_line_id"] in {l["id"] for l in lines}
                    and r["status"] in ("PENDING", "PARTIALLY_ALLOCATED")]
        if not open_res:
            s["status"] = "CREATED"
            touch(s)


def release_line_stock(line, stock):
    units = line_reserved_units(line)
    if units > 0:
        stock["on_hand_qty"] -= units
        stock["reserved_qty"] -= units
        stock_sync(stock)
        touch(stock)


# =============================================================================
# Clock (test-driving)
# =============================================================================
@app.post("/api/_clock/set_current_utc")
def set_clock():
    global LOGICAL_CLOCK, _last_stamp
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    d = body()
    iso = f_str(d, "to_iso8601")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    LOGICAL_CLOCK = dt.astimezone(timezone.utc)
    return success({}, 200)


# =============================================================================
# Payer plans
# =============================================================================
PLAN_TYPES = ["MEDICARE_DMEPOS", "COMMERCIAL", "CASH_HSA"]
CATEGORIES = ["OSTOMY", "INCONTINENCE", "WOUND"]


@app.post("/api/payer-plans")
def create_plan():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    d = body()
    name = f_str(d, "name")
    plan_type = f_enum(d, "plan_type", PLAN_TYPES)
    coins = f_num(d, "coinsurance_pct")
    if coins < 0 or coins > 1:
        err("ERR_INVALID_REQUEST", 400, "coinsurance_pct must be between 0 and 1")
    if plan_type == "CASH_HSA" and coins != Decimal("1"):
        err("ERR_INVALID_REQUEST", 400, "coinsurance_pct must be 1.00 for CASH_HSA plans")
    cycle_months = f_int(d, "cycle_months", minv=1)
    is_active = f_bool(d, "is_active", required=False, default=True)
    e = dict(base_fields())
    e.update({
        "name": name,
        "plan_type": plan_type,
        "coinsurance_pct": coins,
        "cycle_months": cycle_months,
        "is_active": is_active,
    })
    STORE["payer_plans"][e["id"]] = e
    return success(e, 201)


@app.get("/api/payer-plans/<pid>")
def get_plan(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist",
                        "FulfillmentAgent", "BillingSpecialist", "Patient"])
    return success(get_or_404("payer_plans", pid), 200)


@app.get("/api/payer-plans/<pid>/patients")
def plan_patients(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator"])
    get_or_404("payer_plans", pid)
    items = [p for p in STORE["patients"].values() if p["payer_plan_id"] == pid]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# =============================================================================
# Formulary items
# =============================================================================
@app.post("/api/formulary-items")
def create_item():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    d = body()
    hcpcs = f_str(d, "hcpcs_code")
    name = f_str(d, "name")
    category = f_enum(d, "category", CATEGORIES)
    covered = f_list(d, "covered_plan_ids")
    pack_fee = f_num(d, "pack_fee_cents", minv=0)
    pack_size = f_int(d, "pack_size", minv=1)
    retail = f_num(d, "retail_price_cents", minv=0)
    max_units = f_int(d, "max_units_per_cycle", minv=1)
    requires_pa = f_bool(d, "requires_pa", required=False, default=False)
    size_codes = f_list(d, "size_codes")
    status = f_enum(d, "status", ["ACTIVE", "DISCONTINUED"], required=False, default="ACTIVE")
    unit_allowance = rnd2(pack_fee / Decimal(pack_size))
    e = dict(base_fields())
    e.update({
        "hcpcs_code": hcpcs,
        "name": name,
        "category": category,
        "covered_plan_ids": covered,
        "pack_fee_cents": pack_fee,
        "pack_size": pack_size,
        "unit_allowance_cents": unit_allowance,
        "retail_price_cents": retail,
        "max_units_per_cycle": max_units,
        "requires_pa": requires_pa,
        "size_codes": size_codes,
        "status": status,
    })
    STORE["formulary_items"][e["id"]] = e
    return success(e, 201)


@app.get("/api/formulary-items/<iid>")
def get_item(iid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist",
                        "FulfillmentAgent", "BillingSpecialist", "Patient"])
    return success(get_or_404("formulary_items", iid), 200)


@app.get("/api/formulary-items")
def list_items():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist",
                        "FulfillmentAgent", "BillingSpecialist", "Patient"])
    cat = request.args.get("category")
    items = list(STORE["formulary_items"].values())
    if cat is not None:
        items = [i for i in items if i["category"] == cat]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/formulary-items/<iid>/order-lines")
def item_order_lines(iid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "FulfillmentAgent", "BillingSpecialist"])
    get_or_404("formulary_items", iid)
    items = [l for l in STORE["order_lines"].values() if l["formulary_item_id"] == iid]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/formulary-items/<iid>/stock-levels")
def item_stock(iid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "FulfillmentAgent"])
    get_or_404("formulary_items", iid)
    rows = [s for s in STORE["stock_levels"].values() if s["formulary_item_id"] == iid]
    rows.sort(key=lambda s: (s["created_at"], s["id"]))
    return success(rows, 200)


# =============================================================================
# Patients
# =============================================================================
@app.post("/api/patients")
def create_patient():
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    d = body()
    full_name = f_str(d, "full_name")
    dob = f_date(d, "date_of_birth")
    plan_id = f_str(d, "payer_plan_id")
    credit = f_num(d, "hsa_initial_credit_cents", minv=0)
    get_or_404("payer_plans", plan_id)
    e = dict(base_fields())
    e.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "payer_plan_id": plan_id,
        "status": "PENDING_VERIFICATION",
    })
    STORE["patients"][e["id"]] = e
    acct = dict(base_fields())
    acct.update({
        "patient_id": e["id"],
        "initial_credit_cents": rnd2(credit),
        "balance_cents": rnd2(credit),
    })
    STORE["hsa_accounts"][acct["id"]] = acct
    return success(e, 201)


@app.get("/api/patients/<pid>")
def get_patient(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist",
                        "FulfillmentAgent", "BillingSpecialist", "Patient"])
    require_own(role, uid, pid)
    return success(get_or_404("patients", pid), 200)


@app.get("/api/patients")
def list_patients():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "BillingSpecialist"])
    items = list(STORE["patients"].values())
    plan_id = request.args.get("payer_plan_id")
    status = request.args.get("status")
    if plan_id is not None:
        items = [p for p in items if p["payer_plan_id"] == plan_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.post("/api/patients/<pid>/verify-eligibility")
def verify_patient(pid):
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    p = get_or_404("patients", pid)
    d = body()
    eligible = f_bool(d, "eligible")
    if p["status"] != "PENDING_VERIFICATION":
        err("ERR_INVALID_STATE", 409, "patient is not PENDING_VERIFICATION")
    if eligible:
        plan = STORE["payer_plans"].get(p["payer_plan_id"])
        if plan is None or not plan["is_active"]:
            err("ERR_INVALID_STATE", 409, "payer plan does not accept new patients")
        p["status"] = "ACTIVE"
    else:
        p["status"] = "INELIGIBLE"
    touch(p)
    return success(p, 200)


@app.get("/api/patients/<pid>/prescriptions")
def patient_prescriptions(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [r for r in STORE["prescriptions"].values() if r["patient_id"] == pid]
    for r in items:
        rx_refresh(r)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/patients/<pid>/fit-profiles")
def patient_fit_profiles(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [f for f in STORE["fit_profiles"].values() if f["patient_id"] == pid]
    cat = request.args.get("category")
    status = request.args.get("status")
    if cat is not None:
        items = [f for f in items if f["category"] == cat]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/patients/<pid>/resupply-programs")
def patient_programs(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [p for p in STORE["resupply_programs"].values() if p["patient_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    for p in items:
        recompute_adherence(p)
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/patients/<pid>/orders")
def patient_orders(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "BillingSpecialist", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [o for o in STORE["orders"].values() if o["patient_id"] == pid]
    fs = request.args.get("fulfillment_status")
    if fs is not None:
        items = [o for o in items if o["fulfillment_status"] == fs]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/patients/<pid>/prior-authorizations")
def patient_pas(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [p for p in STORE["prior_authorizations"].values() if p["patient_id"] == pid]
    for p in items:
        pa_refresh(p)
    hcpcs = request.args.get("hcpcs_code")
    status = request.args.get("status")
    if hcpcs is not None:
        items = [p for p in items if p["hcpcs_code"] == hcpcs]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@app.get("/api/patients/<pid>/hsa-accounts")
def patient_hsa(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "BillingSpecialist", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    rows = [a for a in STORE["hsa_accounts"].values() if a["patient_id"] == pid]
    for a in rows:
        refresh_hsa(a)
    rows.sort(key=lambda a: (a["created_at"], a["id"]))
    return success(rows, 200)


@app.get("/api/patients/<pid>/fitting-samples")
def patient_samples(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    require_own(role, uid, pid)
    get_or_404("patients", pid)
    items = [s for s in STORE["fitting_samples"].values() if s["patient_id"] == pid]
    cat = request.args.get("category")
    if cat is not None:
        items = [s for s in items if s["category"] == cat]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# =============================================================================
# Prescriptions
# =============================================================================
@app.post("/api/prescriptions")
def create_rx():
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    d = body()
    patient_id = f_str(d, "patient_id")
    hcpcs = f_str(d, "hcpcs_code")
    npi = f_str(d, "prescriber_npi")
    diag = f_list(d, "diagnosis_codes", required=False)
    monthly_qty = f_int(d, "monthly_quantity", minv=1)
    eff = f_date(d, "effective_date")
    exp = f_date(d, "expiration_date")
    if parse_d(eff) >= parse_d(exp):
        err("ERR_INVALID_REQUEST", 400, "effective_date must be before expiration_date")
    patient = get_or_404("patients", patient_id)
    plan = STORE["payer_plans"].get(patient["payer_plan_id"])
    if plan and plan["plan_type"] == "MEDICARE_DMEPOS" and not diag:
        err("ERR_DIAGNOSIS_REQUIRED", 422,
            "at least one diagnosis code is required for MEDICARE_DMEPOS patients")
    eff_d, exp_d = parse_d(eff), parse_d(exp)
    for rx in STORE["prescriptions"].values():
        if rx["patient_id"] != patient_id or rx["hcpcs_code"] != hcpcs:
            continue
        rx_refresh(rx)
        if rx["status"] != "ACTIVE":
            continue
        # half-open overlap: new.eff < ex.exp and ex.eff < new.exp (adjacency allowed)
        if eff_d < parse_d(rx["expiration_date"]) and parse_d(rx["effective_date"]) < exp_d:
            err("ERR_PRESCRIPTION_WINDOW_OVERLAP", 409,
                "overlapping ACTIVE prescription window for patient+hcpcs")
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "hcpcs_code": hcpcs,
        "prescriber_npi": npi,
        "diagnosis_codes": diag,
        "monthly_quantity": monthly_qty,
        "effective_date": eff,
        "expiration_date": exp,
        "status": "ACTIVE",
    })
    STORE["prescriptions"][e["id"]] = e
    return success(e, 201)


@app.get("/api/prescriptions/<rid>")
def get_rx(rid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    rx = get_or_404("prescriptions", rid)
    require_own(role, uid, rx["patient_id"])
    rx_refresh(rx)
    return success(rx, 200)


@app.post("/api/prescriptions/<rid>/cancel")
def cancel_rx(rid):
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    rx = get_or_404("prescriptions", rid)
    rx_refresh(rx)
    if rx["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "only an ACTIVE prescription can be cancelled")
    rx["status"] = "CANCELLED"
    touch(rx)
    return success(rx, 200)


# =============================================================================
# Fit profiles
# =============================================================================
@app.post("/api/fit-profiles")
def create_fit_profile():
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    d = body()
    patient_id = f_str(d, "patient_id")
    category = f_enum(d, "category", CATEGORIES)
    size_code = f_str(d, "size_code")
    measured_on = f_date(d, "measured_on")
    expected = f_int(d, "expected_patient_version")
    patient = get_or_404("patients", patient_id)
    if expected != patient["version"]:
        err("ERR_STALE_VERSION", 412, "expected_patient_version does not match Patient.version")
    prior = current_fit(patient_id, category)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "category": category,
        "size_code": size_code,
        "measured_on": measured_on,
        "status": "CURRENT",
    })
    STORE["fit_profiles"][e["id"]] = e
    touch(patient)
    return success(e, 201)


@app.get("/api/fit-profiles/<fid>")
def get_fit_profile(fid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    fp = get_or_404("fit_profiles", fid)
    require_own(role, uid, fp["patient_id"])
    return success(fp, 200)


# =============================================================================
# Resupply programs
# =============================================================================
@app.post("/api/resupply-programs")
def create_program():
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    d = body()
    patient_id = f_str(d, "patient_id")
    category = f_enum(d, "category", CATEGORIES)
    freq = f_int(d, "frequency_days", minv=1)
    start = f_date(d, "start_date")
    patient = get_or_404("patients", patient_id)
    if patient["status"] != "ACTIVE":
        err("ERR_PATIENT_NOT_ACTIVE", 409, "patient must be ACTIVE")
    for p in STORE["resupply_programs"].values():
        if (p["patient_id"] == patient_id and p["category"] == category
                and p["status"] == "ACTIVE"):
            err("ERR_DUPLICATE_PROGRAM", 409,
                "an ACTIVE resupply program already exists for patient+category")
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "category": category,
        "frequency_days": freq,
        "start_date": start,
        "next_eligible_date": start,
        "last_delivered_date": None,
        "adherence_score_provisional": None,
        "adherence_score_final": None,
        "status": "ACTIVE",
        "suspend_reason": None,
    })
    STORE["resupply_programs"][e["id"]] = e
    recompute_adherence(e)
    return success(e, 201)


@app.get("/api/resupply-programs/<pid>")
def get_program(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    p = get_or_404("resupply_programs", pid)
    require_own(role, uid, p["patient_id"])
    recompute_adherence(p)
    return success(p, 200)


@app.post("/api/resupply-programs/<pid>/confirm-cycle")
def confirm_cycle(pid):
    uid, role = auth()
    require_role(role, ["Patient", "IntakeCoordinator"])
    program = get_or_404("resupply_programs", pid)
    require_own(role, uid, program["patient_id"])
    body()  # consume optional empty body
    if program["status"] != "ACTIVE":
        err("ERR_PROGRAM_SUSPENDED", 409, "program is not ACTIVE")
    patient = STORE["patients"].get(program["patient_id"])
    if patient is None or patient["status"] != "ACTIVE":
        err("ERR_PATIENT_NOT_ACTIVE", 409, "patient must be ACTIVE")
    if today() < parse_d(program["next_eligible_date"]):
        err("ERR_RESUPPLY_WINDOW_NOT_OPEN", 422,
            "current date is before next_eligible_date")
    plan = STORE["payer_plans"].get(patient["payer_plan_id"])
    fit = current_fit(patient["id"], program["category"])
    pool = []
    for item in STORE["formulary_items"].values():
        if item["status"] != "ACTIVE":
            continue
        if item["category"] != program["category"]:
            continue
        if patient["payer_plan_id"] not in item["covered_plan_ids"]:
            continue
        if fit is None or fit["size_code"] not in item["size_codes"]:
            continue
        if item["requires_pa"] and not approved_pa_covering(patient["id"], item["hcpcs_code"]):
            continue
        pool.append(item)
    if not pool:
        err("ERR_NO_ELIGIBLE_ITEM", 422, "no eligible formulary item for this cycle")
    pool.sort(key=lambda i: (Decimal(str(i["unit_allowance_cents"])), i["created_at"], i["id"]))
    item = pool[0]
    if not covering_rx(patient["id"], item["hcpcs_code"], True):
        err("ERR_NO_VALID_PRESCRIPTION", 422,
            "no ACTIVE, currently valid prescription covers the selected item")
    qty = allowance(patient, plan, item)
    if qty < 1:
        err("ERR_QUANTITY_EXCEEDS_ALLOWANCE", 422,
            "resupply quantity allowance is less than one unit")
    order = dict(base_fields())
    order.update({
        "patient_id": patient["id"],
        "resupply_program_id": program["id"],
        "origin": "PROGRAM_CYCLE",
        "fulfillment_status": "SUBMITTED",
        "billing_status": "UNBILLED",
        "total_allowed_cents": Decimal("0"),
        "total_patient_resp_cents": Decimal("0"),
    })
    STORE["orders"][order["id"]] = order
    line = dict(base_fields())
    line.update({
        "order_id": order["id"],
        "formulary_item_id": item["id"],
        "hcpcs_code": item["hcpcs_code"],
        "size_code": fit["size_code"],
        "quantity": qty,
        "unit_allowance_cents": item["unit_allowance_cents"],
        "line_allowed_cents": rnd2(Decimal(str(item["unit_allowance_cents"])) * qty),
    })
    STORE["order_lines"][line["id"]] = line
    recompute_order_totals(order)
    touch(program)
    return success(order, 201)


@app.post("/api/resupply-programs/<pid>/suspend")
def suspend_program(pid):
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    p = get_or_404("resupply_programs", pid)
    d = body()
    reason = f_str(d, "reason")
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "only an ACTIVE program can be suspended")
    p["status"] = "SUSPENDED"
    p["suspend_reason"] = reason
    touch(p)
    return success(p, 200)


@app.post("/api/resupply-programs/<pid>/resume")
def resume_program(pid):
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    p = get_or_404("resupply_programs", pid)
    body()
    if p["status"] != "SUSPENDED":
        err("ERR_PROGRAM_NOT_SUSPENDED", 409, "program is not SUSPENDED")
    p["status"] = "ACTIVE"
    p["suspend_reason"] = None
    touch(p)
    return success(p, 200)


@app.get("/api/resupply-programs/<pid>/orders")
def program_orders(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    p = get_or_404("resupply_programs", pid)
    require_own(role, uid, p["patient_id"])
    items = [o for o in STORE["orders"].values() if o["resupply_program_id"] == pid]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# =============================================================================
# Orders & order lines
# =============================================================================
@app.post("/api/orders")
def create_order():
    uid, role = auth()
    require_role(role, ["Patient", "IntakeCoordinator"])
    d = body()
    patient_id = f_str(d, "patient_id")
    require_own(role, uid, patient_id)
    prog_id = f_str(d, "resupply_program_id", required=False)
    patient = get_or_404("patients", patient_id)
    if prog_id is not None:
        get_or_404("resupply_programs", prog_id)
    if patient["status"] != "ACTIVE":
        err("ERR_PATIENT_NOT_ACTIVE", 409, "patient must be ACTIVE")
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "resupply_program_id": prog_id,
        "origin": "MANUAL_REORDER",
        "fulfillment_status": "DRAFT",
        "billing_status": "UNBILLED",
        "total_allowed_cents": Decimal("0"),
        "total_patient_resp_cents": Decimal("0"),
    })
    STORE["orders"][e["id"]] = e
    return success(e, 201)


@app.get("/api/orders/<oid>")
def get_order(oid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist",
                        "FulfillmentAgent", "BillingSpecialist", "Patient"])
    o = get_or_404("orders", oid)
    require_own(role, uid, o["patient_id"])
    return success(o, 200)


@app.post("/api/orders/<oid>/lines")
def add_line(oid):
    uid, role = auth()
    require_role(role, ["Patient", "IntakeCoordinator"])
    order = get_or_404("orders", oid)
    require_own(role, uid, order["patient_id"])
    d = body()
    item_id = f_str(d, "formulary_item_id")
    size_code = f_str(d, "size_code")
    quantity = f_int(d, "quantity", minv=1)
    expected = f_int(d, "expected_order_version")
    item = get_or_404("formulary_items", item_id)
    if expected != order["version"]:
        err("ERR_STALE_ORDER_VERSION", 412,
            "expected_order_version does not match SupplyOrder.version")
    if order["fulfillment_status"] != "DRAFT":
        err("ERR_ORDER_NOT_DRAFT", 409, "order is not in DRAFT fulfillment")
    patient = STORE["patients"].get(order["patient_id"])
    plan = STORE["payer_plans"].get(patient["payer_plan_id"]) if patient else None
    # PRD §2.10 priority bands: business-safety checks
    # (ERR_NO_VALID_PRESCRIPTION) precede business-constraint checks
    # (ERR_ITEM_NOT_ON_FORMULARY, ERR_SIZE_MISMATCH,
    # ERR_QUANTITY_EXCEEDS_ALLOWANCE).
    if not covering_rx(patient["id"], item["hcpcs_code"], False):
        err("ERR_NO_VALID_PRESCRIPTION", 422,
            "no ACTIVE prescription covers the line's hcpcs_code")
    if patient["payer_plan_id"] not in item["covered_plan_ids"]:
        err("ERR_ITEM_NOT_ON_FORMULARY", 422,
            "item is not covered by the patient's plan")
    fit = current_fit(patient["id"], item["category"])
    if size_code not in item["size_codes"] or fit is None or fit["size_code"] != size_code:
        err("ERR_SIZE_MISMATCH", 422,
            "size_code must be offered by the item and equal the CURRENT fit profile size")
    if quantity > allowance(patient, plan, item):
        err("ERR_QUANTITY_EXCEEDS_ALLOWANCE", 422,
            "quantity exceeds min(Rx cap, formulary cap, PA cap)")
    line = dict(base_fields())
    line.update({
        "order_id": order["id"],
        "formulary_item_id": item["id"],
        "hcpcs_code": item["hcpcs_code"],
        "size_code": size_code,
        "quantity": quantity,
        "unit_allowance_cents": item["unit_allowance_cents"],
        "line_allowed_cents": rnd2(Decimal(str(item["unit_allowance_cents"])) * quantity),
    })
    STORE["order_lines"][line["id"]] = line
    recompute_order_totals(order)
    touch(order)
    return success(line, 201)


@app.get("/api/orders/<oid>/lines")
def list_lines(oid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "FulfillmentAgent",
                        "BillingSpecialist", "Patient"])
    o = get_or_404("orders", oid)
    require_own(role, uid, o["patient_id"])
    page_items, page = paginate(order_lines(oid))
    return success(page_items, 200, page)


@app.get("/api/order-lines/<lid>")
def get_line(lid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "FulfillmentAgent",
                        "BillingSpecialist", "Patient"])
    line = get_or_404("order_lines", lid)
    order = STORE["orders"].get(line["order_id"])
    if order is not None:
        require_own(role, uid, order["patient_id"])
    return success(line, 200)


@app.post("/api/orders/<oid>/submit")
def submit_order(oid):
    uid, role = auth()
    require_role(role, ["Patient", "IntakeCoordinator"])
    order = get_or_404("orders", oid)
    require_own(role, uid, order["patient_id"])
    body()
    if order["fulfillment_status"] != "DRAFT":
        err("ERR_ORDER_NOT_DRAFT", 409, "order is not in DRAFT fulfillment")
    lines = order_lines(oid)
    if not lines:
        err("ERR_INVALID_REQUEST", 400, "order has no lines")
    patient = STORE["patients"].get(order["patient_id"])
    plan = STORE["payer_plans"].get(patient["payer_plan_id"]) if patient else None
    for line in lines:
        if not covering_rx(patient["id"], line["hcpcs_code"], True):
            err("ERR_NO_VALID_PRESCRIPTION", 422,
                "no ACTIVE, currently valid prescription covers a line")
    if plan and plan["plan_type"] == "CASH_HSA":
        est = Decimal("0")
        for line in lines:
            item = STORE["formulary_items"].get(line["formulary_item_id"])
            retail = Decimal(str(item["retail_price_cents"])) if item else Decimal("0")
            est += rnd2(retail * line["quantity"])
        acct = hsa_of_patient(patient["id"])
        bal = hsa_balance(acct) if acct else Decimal("0")
        if est > bal:
            err("ERR_INSUFFICIENT_HSA", 422,
                "estimated patient responsibility exceeds HSA balance")
    order["fulfillment_status"] = "SUBMITTED"
    recompute_order_totals(order)
    touch(order)
    return success(order, 200)


@app.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = auth()
    require_role(role, ["Patient", "IntakeCoordinator"])
    order = get_or_404("orders", oid)
    require_own(role, uid, order["patient_id"])
    body()
    fs = order["fulfillment_status"]
    if fs in ("DRAFT", "SUBMITTED"):
        order["fulfillment_status"] = "CANCELLED"
        touch(order)
        return success(order, 200)
    if fs == "IN_FULFILLMENT":
        ships = order_shipments(oid)
        if any(s["status"] not in ("CREATED", "BACKORDERED") for s in ships):
            err("ERR_INVALID_STATE", 409,
                "order cannot be cancelled once a shipment is READY or beyond")
        for s in ships:
            s["status"] = "CANCELLED"
            touch(s)
        for line in order_lines(oid):
            stock = stock_of_item(line["formulary_item_id"])
            if stock is not None:
                units = line_reserved_units(line)
                if units > 0:
                    stock["reserved_qty"] -= units
                    stock_sync(stock)
                    touch(stock)
            for r in STORE["backorder_reservations"].values():
                if (r["order_line_id"] == line["id"]
                        and r["status"] in ("PENDING", "PARTIALLY_ALLOCATED")):
                    r["status"] = "CANCELLED"
                    touch(r)
        order["fulfillment_status"] = "CANCELLED"
        touch(order)
        return success(order, 200)
    err("ERR_INVALID_STATE", 409, "order cannot be cancelled from its current state")


# =============================================================================
# Shipments & stock
# =============================================================================
@app.post("/api/shipments")
def create_shipment():
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    d = body()
    order_id = f_str(d, "order_id")
    order = get_or_404("orders", order_id)
    if order["fulfillment_status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "shipment can only be created for a SUBMITTED order")
    fully_reserved = True
    for line in order_lines(order_id):
        stock = stock_of_item(line["formulary_item_id"])
        available = (stock["on_hand_qty"] - stock["reserved_qty"]) if stock else 0
        take = min(line["quantity"], max(available, 0))
        if stock is not None and take > 0:
            stock["reserved_qty"] += take
            stock_sync(stock)
            touch(stock)
        shortage = line["quantity"] - take
        if shortage > 0:
            fully_reserved = False
            r = dict(base_fields())
            r.update({
                "order_line_id": line["id"],
                "quantity_pending": shortage,
                "quantity_allocated": 0,
                "status": "PENDING",
            })
            STORE["backorder_reservations"][r["id"]] = r
    order["fulfillment_status"] = "IN_FULFILLMENT"
    touch(order)
    s = dict(base_fields())
    s.update({
        "order_id": order_id,
        "status": "CREATED" if fully_reserved else "BACKORDERED",
        "shipped_date": None,
        "delivered_date": None,
    })
    STORE["shipments"][s["id"]] = s
    return success(s, 201)


@app.get("/api/shipments/<sid>")
def get_shipment(sid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "FulfillmentAgent", "Patient"])
    s = get_or_404("shipments", sid)
    order = STORE["orders"].get(s["order_id"])
    if order is not None:
        require_own(role, uid, order["patient_id"])
    return success(s, 200)


@app.get("/api/orders/<oid>/shipments")
def list_shipments(oid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "FulfillmentAgent", "Patient"])
    o = get_or_404("orders", oid)
    require_own(role, uid, o["patient_id"])
    return success(order_shipments(oid), 200)


@app.post("/api/shipments/<sid>/release")
def release_shipment(sid):
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    s = get_or_404("shipments", sid)
    body()
    if s["status"] == "BACKORDERED":
        err("ERR_SHIPMENT_BACKORDERED", 409, "shipment is BACKORDERED")
    if s["status"] != "CREATED":
        err("ERR_INVALID_STATE", 409, "only a CREATED shipment can be released")
    order = STORE["orders"].get(s["order_id"])
    patient_id = order["patient_id"] if order else None
    for line in order_lines(s["order_id"]):
        item = STORE["formulary_items"].get(line["formulary_item_id"])
        if item is None or not item["requires_pa"]:
            continue
        approved = [pa for pa in STORE["prior_authorizations"].values()
                    if pa["patient_id"] == patient_id
                    and pa["hcpcs_code"] == line["hcpcs_code"]
                    and pa["status"] == "APPROVED"]
        covering = [pa for pa in approved
                    if parse_d(pa["valid_from"]) <= today() <= parse_d(pa["valid_to"])]
        if covering:
            continue
        if any(today() > parse_d(pa["valid_to"]) for pa in approved):
            err("ERR_PRIOR_AUTH_EXPIRED", 422,
                "the covering APPROVED prior authorization window has passed")
        err("ERR_PRIOR_AUTH_REQUIRED", 422,
            "no APPROVED prior authorization for a requires_pa line")
    s["status"] = "READY"
    touch(s)
    return success(s, 200)


def _program_of_order(order):
    if order and order["resupply_program_id"]:
        return STORE["resupply_programs"].get(order["resupply_program_id"])
    return None


@app.post("/api/shipments/<sid>/ship")
def ship_shipment(sid):
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    s = get_or_404("shipments", sid)
    body()
    if s["status"] != "READY":
        err("ERR_INVALID_STATE", 409, "only a READY shipment can be shipped")
    s["status"] = "SHIPPED"
    s["shipped_date"] = today().isoformat()
    touch(s)
    for line in order_lines(s["order_id"]):
        stock = stock_of_item(line["formulary_item_id"])
        if stock is not None:
            release_line_stock(line, stock)
    order = STORE["orders"].get(s["order_id"])
    program = _program_of_order(order)
    if program is not None:
        recompute_adherence(program)
    return success(s, 200)


@app.post("/api/shipments/<sid>/deliver")
def deliver_shipment(sid):
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    s = get_or_404("shipments", sid)
    body()
    if s["status"] != "SHIPPED":
        err("ERR_INVALID_STATE", 409, "only a SHIPPED shipment can be delivered")
    s["status"] = "DELIVERED"
    s["delivered_date"] = today().isoformat()
    touch(s)
    order = STORE["orders"].get(s["order_id"])
    program = _program_of_order(order)
    if program is not None:
        program["last_delivered_date"] = s["delivered_date"]
        program["next_eligible_date"] = (
            today() + timedelta(days=program["frequency_days"])).isoformat()
        recompute_adherence(program)
        touch(program)
    if order is not None:
        bubble_order(order)
    return success(s, 200)


@app.post("/api/shipments/<sid>/return")
def return_shipment(sid):
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    s = get_or_404("shipments", sid)
    body()
    if s["status"] not in ("SHIPPED", "DELIVERED"):
        err("ERR_INVALID_STATE", 409,
            "only a SHIPPED or DELIVERED shipment can be returned")
    was = s["status"]
    s["status"] = "RETURNED"
    touch(s)
    order = STORE["orders"].get(s["order_id"])
    program = _program_of_order(order)
    if program is not None:
        recompute_adherence(program)
        maybe_suspend_low_adherence(program)
    if was == "SHIPPED" and order is not None:
        bubble_order(order)
    return success(s, 200)


@app.post("/api/stock-levels")
def create_stock():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    d = body()
    item_id = f_str(d, "formulary_item_id")
    on_hand = f_int(d, "on_hand_qty", minv=0)
    get_or_404("formulary_items", item_id)
    if stock_of_item(item_id) is not None:
        err("ERR_DUPLICATE_STOCK_LEVEL", 409,
            "a StockLevel already exists for this formulary_item_id")
    e = dict(base_fields())
    e.update({
        "formulary_item_id": item_id,
        "on_hand_qty": on_hand,
        "reserved_qty": 0,
        "available_qty": on_hand,
    })
    STORE["stock_levels"][e["id"]] = e
    return success(e, 201)


@app.get("/api/stock-levels/<sid>")
def get_stock(sid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "FulfillmentAgent"])
    return success(get_or_404("stock_levels", sid), 200)


@app.post("/api/stock-levels/<sid>/restock")
def restock(sid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    stock = get_or_404("stock_levels", sid)
    d = body()
    qty_added = f_int(d, "qty_added", minv=1)
    stock["on_hand_qty"] += qty_added
    stock_sync(stock)
    touch(stock)
    run_backorder_allocation(stock, qty_added)
    return success(stock, 200)


@app.get("/api/order-lines/<lid>/backorder-reservations")
def line_reservations(lid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "FulfillmentAgent"])
    get_or_404("order_lines", lid)
    rows = [r for r in STORE["backorder_reservations"].values()
            if r["order_line_id"] == lid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success(rows, 200)


# =============================================================================
# Prior authorizations
# =============================================================================
@app.post("/api/prior-authorizations")
def create_pa():
    uid, role = auth()
    require_role(role, ["PriorAuthSpecialist"])
    d = body()
    patient_id = f_str(d, "patient_id")
    hcpcs = f_str(d, "hcpcs_code")
    units = f_int(d, "approved_units", minv=1)
    vf = f_date(d, "valid_from")
    vt = f_date(d, "valid_to")
    if parse_d(vf) > parse_d(vt):
        err("ERR_INVALID_REQUEST", 400, "valid_from must be on or before valid_to")
    get_or_404("patients", patient_id)
    vf_d, vt_d = parse_d(vf), parse_d(vt)
    for pa in STORE["prior_authorizations"].values():
        if pa["patient_id"] != patient_id or pa["hcpcs_code"] != hcpcs:
            continue
        if pa["status"] not in ("SUBMITTED", "APPEALED", "APPROVED"):
            continue
        # closed-window overlap; adjacency counts as overlap
        if vf_d <= parse_d(pa["valid_to"]) and parse_d(pa["valid_from"]) <= vt_d:
            err("ERR_AUTH_WINDOW_OVERLAP", 409,
                "overlapping prior authorization window for patient+hcpcs")
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "hcpcs_code": hcpcs,
        "approved_units": units,
        "valid_from": vf,
        "valid_to": vt,
        "status": "SUBMITTED",
        "appeal_count": 0,
    })
    STORE["prior_authorizations"][e["id"]] = e
    return success(e, 201)


@app.get("/api/prior-authorizations/<pid>")
def get_pa(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "PriorAuthSpecialist", "Patient"])
    pa = get_or_404("prior_authorizations", pid)
    require_own(role, uid, pa["patient_id"])
    pa_refresh(pa)
    return success(pa, 200)


@app.post("/api/prior-authorizations/<pid>/decision")
def decide_pa(pid):
    uid, role = auth()
    require_role(role, ["PriorAuthSpecialist"])
    pa = get_or_404("prior_authorizations", pid)
    d = body()
    outcome = f_enum(d, "outcome", ["APPROVED", "DENIED"])
    if pa["status"] not in ("SUBMITTED", "APPEALED"):
        err("ERR_INVALID_STATE", 409,
            "a decision can only be recorded from SUBMITTED or APPEALED")
    pa["status"] = outcome
    touch(pa)
    return success(pa, 200)


@app.post("/api/prior-authorizations/<pid>/appeal")
def appeal_pa(pid):
    uid, role = auth()
    require_role(role, ["PriorAuthSpecialist"])
    pa = get_or_404("prior_authorizations", pid)
    body()
    if pa["status"] != "DENIED":
        err("ERR_INVALID_STATE", 409, "only a DENIED prior authorization can be appealed")
    pa["status"] = "APPEALED"
    pa["appeal_count"] += 1
    touch(pa)
    return success(pa, 200)


# =============================================================================
# Claims
# =============================================================================
def price_claim(order):
    patient = STORE["patients"].get(order["patient_id"])
    plan = STORE["payer_plans"].get(patient["payer_plan_id"]) if patient else None
    total = Decimal("0")
    resp = Decimal("0")
    for line in order_lines(order["id"]):
        if plan and plan["plan_type"] == "CASH_HSA":
            item = STORE["formulary_items"].get(line["formulary_item_id"])
            retail = Decimal(str(item["retail_price_cents"])) if item else Decimal("0")
            total += rnd2(retail * line["quantity"])
        else:
            la = Decimal(str(line["line_allowed_cents"]))
            total += la
            resp += rnd2(la * Decimal(str(plan["coinsurance_pct"])))
    total = rnd2(total)
    resp = rnd2(resp)
    if plan and plan["plan_type"] == "CASH_HSA":
        resp = total
    return total, resp


@app.post("/api/claims")
def create_claim():
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    d = body()
    order_id = f_str(d, "order_id")
    order = get_or_404("orders", order_id)
    existing = [c for c in STORE["claims"].values() if c["order_id"] == order_id]
    if (order["fulfillment_status"] != "FULFILLED"
            or order["billing_status"] != "UNBILLED" or existing):
        err("ERR_CLAIM_NOT_SUBMITTABLE", 409,
            "order must be FULFILLED and UNBILLED with no existing claim")
    total, resp = price_claim(order)
    e = dict(base_fields())
    e.update({
        "order_id": order_id,
        "status": "DRAFT",
        "total_allowed_cents": total,
        "insurer_paid_cents": Decimal("0"),
        "patient_resp_cents": resp,
        "adjudicated_at": None,
    })
    STORE["claims"][e["id"]] = e
    order["billing_status"] = "CLAIM_DRAFT"
    touch(order)
    return success(e, 201)


@app.get("/api/claims/<cid>")
def get_claim(cid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "BillingSpecialist"])
    return success(get_or_404("claims", cid), 200)


@app.get("/api/orders/<oid>/claims")
def order_claims(oid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "BillingSpecialist"])
    get_or_404("orders", oid)
    rows = [c for c in STORE["claims"].values() if c["order_id"] == oid]
    rows.sort(key=lambda c: (c["created_at"], c["id"]))
    return success(rows, 200)


@app.post("/api/claims/<cid>/submit")
def submit_claim(cid):
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    claim = get_or_404("claims", cid)
    body()
    if claim["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "only a DRAFT claim can be submitted")
    claim["status"] = "SUBMITTED"
    touch(claim)
    order = STORE["orders"].get(claim["order_id"])
    if order is not None:
        order["billing_status"] = "CLAIM_SUBMITTED"
        touch(order)
    return success(claim, 200)


@app.post("/api/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    claim = get_or_404("claims", cid)
    d = body()
    outcome = f_enum(d, "outcome", ["PAID", "DENIED"])
    order = STORE["orders"].get(claim["order_id"])
    if outcome == "PAID":
        if claim["status"] not in ("SUBMITTED", "APPEALED"):
            err("ERR_INVALID_STATE", 409,
                "a PAID outcome requires the claim to be SUBMITTED or APPEALED")
        claim["insurer_paid_cents"] = rnd2(
            Decimal(str(claim["total_allowed_cents"]))
            - Decimal(str(claim["patient_resp_cents"])))
        claim["status"] = "PAID"
        claim["adjudicated_at"] = stamp()
        touch(claim)
        if order is not None:
            order["billing_status"] = "PAID_SETTLED"
            touch(order)
        return success(claim, 200)
    # outcome == DENIED
    if claim["status"] == "SUBMITTED":
        claim["status"] = "DENIED"
        claim["adjudicated_at"] = stamp()
        touch(claim)
        if order is not None:
            order["billing_status"] = "CLAIM_DENIED"
            touch(order)
        return success(claim, 200)
    if claim["status"] == "APPEALED":
        # DENIED_FINAL: full allowed amount shifts to the patient
        patient_resp = Decimal(str(claim["total_allowed_cents"]))
        patient = STORE["patients"].get(order["patient_id"]) if order else None
        acct = hsa_of_patient(patient["id"]) if patient else None
        bal = hsa_balance(acct) if acct else Decimal("0")
        if patient_resp > bal:
            err("ERR_INSUFFICIENT_HSA", 422,
                "HSA balance cannot cover the denied claim debit")
        claim["status"] = "DENIED_FINAL"
        claim["patient_resp_cents"] = rnd2(patient_resp)
        claim["insurer_paid_cents"] = Decimal("0")
        claim["adjudicated_at"] = stamp()
        touch(claim)
        if order is not None:
            order["billing_status"] = "PATIENT_BILLED"
            touch(order)
        if acct is not None:
            entry = {
                "id": new_id(),
                "created_at": stamp(),
                "hsa_account_id": acct["id"],
                "entry_type": "DEBIT",
                "amount_cents": rnd2(patient_resp),
                "reason": "CLAIM_DENIED_FINAL",
                "related_order_id": claim["order_id"],
                "reverses_entry_id": None,
                "status": "POSTED",
            }
            STORE["hsa_entries"][entry["id"]] = entry
            refresh_hsa(acct)
            touch(acct)
            if Decimal(str(acct["balance_cents"])) < Decimal("500"):
                for p in STORE["resupply_programs"].values():
                    if p["patient_id"] == patient["id"] and p["status"] == "ACTIVE":
                        p["status"] = "SUSPENDED"
                        p["suspend_reason"] = "HSA_FLOOR_BREACH"
                        touch(p)
        return success(claim, 200)
    err("ERR_INVALID_STATE", 409,
        "a DENIED outcome is not available from the claim's current state")


@app.post("/api/claims/<cid>/appeal")
def appeal_claim(cid):
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    claim = get_or_404("claims", cid)
    body()
    if claim["status"] != "DENIED":
        err("ERR_INVALID_STATE", 409, "only a DENIED claim can be appealed")
    claim["status"] = "APPEALED"
    touch(claim)
    order = STORE["orders"].get(claim["order_id"])
    if order is not None:
        order["billing_status"] = "APPEAL_PENDING"
        touch(order)
    return success(claim, 200)


# =============================================================================
# HSA accounts & ledger
# =============================================================================
@app.get("/api/hsa-accounts/<aid>")
def get_hsa(aid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "BillingSpecialist", "Patient"])
    acct = get_or_404("hsa_accounts", aid)
    require_own(role, uid, acct["patient_id"])
    refresh_hsa(acct)
    return success(acct, 200)


@app.post("/api/hsa-accounts/<aid>/debits")
def post_debit(aid):
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    acct = get_or_404("hsa_accounts", aid)
    d = body()
    amount = f_num(d, "amount_cents")
    reason = f_str(d, "reason")
    related = f_str(d, "related_order_id", required=False)
    if amount <= 0:
        err("ERR_INVALID_REQUEST", 400, "amount_cents must be > 0")
    bal = hsa_balance(acct)
    if amount > bal:
        err("ERR_INSUFFICIENT_HSA", 422, "debit amount exceeds HSA balance")
    entry = {
        "id": new_id(),
        "created_at": stamp(),
        "hsa_account_id": acct["id"],
        "entry_type": "DEBIT",
        "amount_cents": rnd2(amount),
        "reason": reason,
        "related_order_id": related,
        "reverses_entry_id": None,
        "status": "POSTED",
    }
    STORE["hsa_entries"][entry["id"]] = entry
    refresh_hsa(acct)
    touch(acct)
    return success(entry, 201)


@app.post("/api/hsa-accounts/<aid>/credits")
def post_credit(aid):
    uid, role = auth()
    require_role(role, ["BillingSpecialist"])
    acct = get_or_404("hsa_accounts", aid)
    d = body()
    amount = f_num(d, "amount_cents")
    reason = f_str(d, "reason")
    reverses = f_str(d, "reverses_entry_id", required=False)
    if amount <= 0:
        err("ERR_INVALID_REQUEST", 400, "amount_cents must be > 0")
    entry_type = "CREDIT"
    if reverses is not None:
        target = STORE["hsa_entries"].get(reverses)
        if (target is None or target["hsa_account_id"] != acct["id"]
                or target["entry_type"] != "DEBIT" or target["status"] != "POSTED"):
            err("ERR_HSA_ENTRY_NOT_REVERSIBLE", 409,
                "reverses_entry_id must reference a POSTED DEBIT entry of the same account")
        entry_type = "REVERSAL"
    entry = {
        "id": new_id(),
        "created_at": stamp(),
        "hsa_account_id": acct["id"],
        "entry_type": entry_type,
        "amount_cents": rnd2(amount),
        "reason": reason,
        "related_order_id": None,
        "reverses_entry_id": reverses,
        "status": "POSTED",
    }
    STORE["hsa_entries"][entry["id"]] = entry
    refresh_hsa(acct)
    touch(acct)
    return success(entry, 201)


@app.get("/api/hsa-accounts/<aid>/entries")
def hsa_entries(aid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "BillingSpecialist", "Patient"])
    acct = get_or_404("hsa_accounts", aid)
    require_own(role, uid, acct["patient_id"])
    items = [e for e in STORE["hsa_entries"].values() if e["hsa_account_id"] == aid]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# =============================================================================
# Fitting samples
# =============================================================================
@app.post("/api/fitting-samples")
def create_sample():
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    d = body()
    patient_id = f_str(d, "patient_id")
    category = f_enum(d, "category", CATEGORIES)
    size_code = f_str(d, "size_code")
    item_name = f_str(d, "item_name")
    patient = get_or_404("patients", patient_id)
    if patient["status"] != "ACTIVE":
        err("ERR_PATIENT_NOT_ACTIVE", 409, "patient must be ACTIVE")
    window_start = today() - timedelta(days=90)
    count = 0
    for s in STORE["fitting_samples"].values():
        if s["patient_id"] != patient_id or s["category"] != category:
            continue
        created_date = parse_d(s["created_at"][:10])
        if window_start <= created_date <= today():
            count += 1
    if count >= 2:
        err("ERR_SAMPLE_LIMIT_EXCEEDED", 422,
            "at most 2 samples per patient+category within a rolling 90-day window")
    e = dict(base_fields())
    e.update({
        "patient_id": patient_id,
        "category": category,
        "size_code": size_code,
        "item_name": item_name,
        "unit_price_cents": 0,
        "status": "REQUESTED",
        "outcome": None,
    })
    STORE["fitting_samples"][e["id"]] = e
    return success(e, 201)


@app.get("/api/fitting-samples/<sid>")
def get_sample(sid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "IntakeCoordinator", "Patient"])
    s = get_or_404("fitting_samples", sid)
    require_own(role, uid, s["patient_id"])
    return success(s, 200)


@app.post("/api/fitting-samples/<sid>/ship")
def ship_sample(sid):
    uid, role = auth()
    require_role(role, ["FulfillmentAgent"])
    s = get_or_404("fitting_samples", sid)
    body()
    if s["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "only a REQUESTED sample can be shipped")
    s["status"] = "SHIPPED"
    touch(s)
    return success(s, 200)


@app.post("/api/fitting-samples/<sid>/record-outcome")
def record_outcome(sid):
    uid, role = auth()
    require_role(role, ["IntakeCoordinator"])
    s = get_or_404("fitting_samples", sid)
    d = body()
    outcome = f_enum(d, "outcome", ["CONVERTED", "NOT_CONVERTED"])
    if s["status"] != "SHIPPED":
        err("ERR_INVALID_STATE", 409,
            "outcome can only be recorded for a SHIPPED sample")
    s["status"] = "OUTCOME_RECORDED"
    s["outcome"] = outcome
    touch(s)
    return success(s, 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
