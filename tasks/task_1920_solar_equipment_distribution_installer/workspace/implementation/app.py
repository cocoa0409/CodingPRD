#!/usr/bin/env python3
"""Solar Distribution Installer API — in-memory Flask implementation."""
import os
import re
import uuid
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; never seeded)
# ---------------------------------------------------------------------------
DB = {
    "products": {},
    "rules": {},
    "tariffs": {},
    "installers": {},
    "lots": {},
    "containers": {},
    "lines": {},
    "projects": {},
    "allocations": {},
    "invoices": {},
    "payments": {},
    "rmas": {},
    "packages": {},
    "claims": {},
}
_SEQ = itertools.count(1)

OBSOLESCENCE_GENERATION_LAG = 2
STRANDED_AGE_DAYS = 90
BP_BASE = 10000

ROLES = {"DistributionAdmin", "ChannelManager", "InstallerRep", "CreditOfficer"}


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(now()),
    }


def ok_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(500)
def handle_500(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Internal server error"},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers must be present and valid")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_INSUFFICIENT_PERMISSIONS", 403,
            "Role not permitted for this operation")


def own_installer(uid, role, installer_id):
    """InstallerRep may only act on resources owned by their own installer."""
    if role == "InstallerRep" and uid != installer_id:
        err("ERR_INSUFFICIENT_PERMISSIONS", 403,
            "InstallerRep may only act on their own installer's resources")


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' is required and must be a string")
    return v


def req_int(b, k):
    v = b.get(k)
    if not _is_int(v):
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' is required and must be an integer")
    return v


def opt_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' must be a string")
    return v


def opt_int(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not _is_int(v):
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' must be an integer")
    return v


def req_dt(b, k):
    v = b.get(k)
    if v is None:
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' is required")
    try:
        return parse_dt(v)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' must be an ISO 8601 timestamp")


def opt_dt(b, k):
    v = b.get(k)
    if v is None:
        return None
    try:
        return parse_dt(v)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, f"Field '{k}' must be an ISO 8601 timestamp")


def pagination():
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", "0"))
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity():
    t = iso(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next(_SEQ),
    }


def touch(e):
    e["updated_at"] = iso(now())
    e["version"] += 1


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def find(coll, _id, errid):
    e = DB[coll].get(_id)
    if e is None:
        err(errid, 404, f"Resource {_id} not found")
    return e


def rhu(num, den):
    """round half up of num/den to integer cents"""
    return int((Decimal(int(num)) / Decimal(int(den))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def lot_avail(lot):
    return lot["qty_on_hand"] - lot["qty_allocated"] - lot["qty_quarantined"]


def pub_lot(lot):
    d = pub(lot)
    d["qty_available"] = lot_avail(lot)
    return d


# ---------------------------------------------------------------------------
# Tariff lookup
# ---------------------------------------------------------------------------
def tariff_bp_at(hts_code, instant):
    cands = []
    for r in DB["tariffs"].values():
        if r["hts_code"] != hts_code or r["status"] != "ACTIVE":
            continue
        ef = parse_dt(r["effective_from"])
        et = parse_dt(r["effective_to"]) if r["effective_to"] else None
        if ef <= instant and (et is None or instant < et):
            cands.append(r)
    if not cands:
        return 0
    cands.sort(key=lambda r: (r["effective_from"], r["_seq"]))
    return cands[-1]["duty_rate_bp"]


# ---------------------------------------------------------------------------
# Landed cost waterfall
# ---------------------------------------------------------------------------
def container_lines(container_id):
    lines = [l for l in DB["lines"].values() if l["container_id"] == container_id]
    return sorted(lines, key=lambda l: (l["created_at"], l["_seq"]))


def compute_unit_costs(container, when, final, receipts=None):
    """Return {line_id: unit_cost_cents}. final=True divides by qty_received."""
    lines = container_lines(container["id"])
    total_declared = sum(l["qty_booked"] * l["declared_unit_value_cents"] for l in lines)
    out = {}
    for l in lines:
        base = l["qty_booked"] * l["declared_unit_value_cents"]
        prod = DB["products"].get(l["product_id"])
        bp = tariff_bp_at(prod["hts_code"], when) if prod else 0
        duty = rhu(base * bp, BP_BASE)
        freight = rhu(container["freight_cost_cents"] * base, total_declared) if total_declared else 0
        ins = rhu(container["insurance_cost_cents"] * base, total_declared) if total_declared else 0
        landed = base + duty + freight + ins
        denom = l["qty_received"] if final else l["qty_booked"]
        out[l["id"]] = rhu(landed, denom) if denom > 0 else landed
    return out


def recompute_provisional(container):
    """Recompute provisional landed cost on every attached lot (booking-time tariff)."""
    costs = compute_unit_costs(container, parse_dt(container["created_at"]), final=False)
    for line in container_lines(container["id"]):
        lot = DB["lots"].get(line["inventory_lot_id"])
        if lot is None or lot["status"] not in ("IN_TRANSIT",):
            continue
        new_val = costs[line["id"]]
        if lot["unit_cost_cents_provisional"] != new_val:
            lot["unit_cost_cents_provisional"] = new_val
            touch(lot)


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def recompute_installer(inst):
    exp = 0
    for inv in DB["invoices"].values():
        if (inv["installer_id"] == inst["id"]
                and inv["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE")
                and inv["invoice_kind"] != "WRITE_OFF"):
            exp += inv["balance_due_cents"]
    hold = exp >= inst["credit_limit_cents"]
    if inst["credit_exposure_cents"] != exp or inst["credit_hold"] != hold:
        inst["credit_exposure_cents"] = exp
        inst["credit_hold"] = hold
        touch(inst)


def recompute_project(p):
    avc = 0
    for a in DB["allocations"].values():
        if a["project_id"] == p["id"] and a["status"] in ("OPEN", "SHIPPED"):
            avc += a["qty_allocated"] * a["unit_cost_cents_at_allocation"]
    invoiced = 0
    paid = 0
    for inv in DB["invoices"].values():
        if inv["project_id"] != p["id"]:
            continue
        if inv["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE"):
            invoiced += inv["amount_cents"]
    for pay in DB["payments"].values():
        inv = DB["invoices"].get(pay["invoice_id"])
        if inv and inv["project_id"] == p["id"] and pay["status"] == "POSTED":
            paid += pay["amount_cents"]
    changed = False
    if p["allocated_value_cents"] != avc:
        p["allocated_value_cents"] = avc
        changed = True
    if p["invoiced_value_cents"] != invoiced:
        p["invoiced_value_cents"] = invoiced
        changed = True
    if p["paid_value_cents"] != paid:
        p["paid_value_cents"] = paid
        changed = True
    if changed:
        touch(p)


def project_invoices(project_id):
    invs = [i for i in DB["invoices"].values() if i["project_id"] == project_id]
    return sorted(invs, key=lambda i: (i["created_at"], i["_seq"]))


def eval_payment_status(p):
    ps = p["payment_status"]
    invs = project_invoices(p["id"])
    if ps == "PTO_BILLED":
        billed = sum(i["amount_cents"] for i in invs
                     if i["invoice_kind"] in ("PROGRESS", "PTO") and i["status"] != "VOID")
        outstanding = sum(i["balance_due_cents"] for i in invs
                          if i["invoice_kind"] in ("PROGRESS", "PTO")
                          and i["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE"))
        if billed > 0 and outstanding == 0:
            p["payment_status"] = "PAID_IN_FULL"
            touch(p)
    elif ps == "PROGRESS_BILLED":
        if invs and all(i["status"] in ("PAID", "VOID") for i in invs) \
                and any(i["invoice_kind"] == "CREDIT_MEMO" for i in invs):
            p["payment_status"] = "PAID_IN_FULL"
            touch(p)
    elif ps == "PAID_IN_FULL":
        outstanding = sum(i["balance_due_cents"] for i in invs
                          if i["invoice_kind"] in ("PROGRESS", "PTO")
                          and i["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE"))
        if outstanding > 0:
            has_pto = any(i["invoice_kind"] == "PTO" and i["status"] != "VOID" for i in invs)
            p["payment_status"] = "PTO_BILLED" if has_pto else "PROGRESS_BILLED"
            touch(p)


def create_invoice(project, installer, kind, amount):
    inv = new_entity()
    t = now()
    inv.update({
        "project_id": project["id"],
        "installer_id": installer["id"],
        "invoice_kind": kind,
        "amount_cents": amount,
        "balance_due_cents": amount,
        "invoice_date": iso(t),
        "due_date": iso(t + timedelta(days=installer["payment_terms_days"])),
        "status": "OPEN",
    })
    DB["invoices"][inv["id"]] = inv
    return inv


def maybe_issue_progress_invoice(p):
    if p["payment_status"] != "UNBILLED":
        return
    inst = DB["installers"][p["installer_id"]]
    recompute_project(p)
    avc = p["allocated_value_cents"]
    amount = rhu(avc * inst["progress_payment_pct_bp"], BP_BASE)
    inv = create_invoice(p, inst, "PROGRESS", amount)
    p["payment_status"] = "PROGRESS_BILLED"
    touch(p)
    recompute_project(p)
    recompute_installer(inst)
    return inv


def eval_fulfillment(p):
    fs = p["fulfillment_status"]
    if fs not in ("ALLOCATED", "PARTIALLY_SHIPPED"):
        return
    allocs = [a for a in DB["allocations"].values() if a["project_id"] == p["id"]]
    has_open = any(a["status"] == "OPEN" for a in allocs)
    has_shipped = any(a["status"] == "SHIPPED" for a in allocs)
    non_cancelled = [a for a in allocs if a["status"] != "CANCELLED"]
    if has_shipped and has_open:
        if fs != "PARTIALLY_SHIPPED":
            p["fulfillment_status"] = "PARTIALLY_SHIPPED"
            touch(p)
    elif has_shipped and not has_open and non_cancelled \
            and all(a["status"] == "SHIPPED" for a in non_cancelled):
        p["fulfillment_status"] = "SHIPPED"
        touch(p)
        maybe_issue_progress_invoice(p)


def cancel_allocation(alloc):
    if alloc["status"] != "OPEN":
        return
    alloc["status"] = "CANCELLED"
    touch(alloc)
    lot = DB["lots"].get(alloc["inventory_lot_id"])
    if lot is not None:
        lot["qty_allocated"] -= alloc["qty_allocated"]
        touch(lot)
    p = DB["projects"].get(alloc["project_id"])
    if p is not None:
        recompute_project(p)


def maybe_depleted(lot):
    if lot["status"] == "ON_HAND" and lot["qty_on_hand"] == 0 \
            and lot["qty_allocated"] == 0 and lot["qty_quarantined"] == 0:
        lot["status"] = "DEPLETED"
        touch(lot)


# ---------------------------------------------------------------------------
# Scheduled reconciliation: obsolescence sweep + past-due marking
# ---------------------------------------------------------------------------
def obsolescence_sweep():
    t = now()
    # Products DISCONTINUED -> OBSOLETE
    for p in list(DB["products"].values()):
        if p["status"] != "DISCONTINUED":
            continue
        max_gen = max((q["technology_generation"] for q in DB["products"].values()
                       if q["product_kind"] == p["product_kind"]), default=p["technology_generation"])
        lots_ref = any(l for l in DB["lots"].values()
                       if l["product_id"] == p["id"] and l["qty_on_hand"] > 0
                       and l["status"] != "WRITTEN_OFF")
        if p["technology_generation"] < max_gen - OBSOLESCENCE_GENERATION_LAG and not lots_ref:
            p["status"] = "OBSOLETE"
            touch(p)
            for lot in list(DB["lots"].values()):
                if lot["product_id"] != p["id"]:
                    continue
                for a in list(DB["allocations"].values()):
                    if a["inventory_lot_id"] == lot["id"] and a["status"] == "OPEN":
                        cancel_allocation(a)
    # Lots ON_HAND -> STRANDED
    for lot in list(DB["lots"].values()):
        if lot["status"] != "ON_HAND" or lot["qty_on_hand"] <= 0:
            continue
        prod = DB["products"].get(lot["product_id"])
        if prod is None or prod["status"] != "DISCONTINUED":
            continue
        disc = prod.get("_discontinued_at")
        if disc is None:
            continue
        if (t - disc) >= timedelta(days=STRANDED_AGE_DAYS):
            lot["status"] = "STRANDED"
            lot["stranded_at"] = iso(t)
            touch(lot)
            for a in list(DB["allocations"].values()):
                if a["inventory_lot_id"] == lot["id"] and a["status"] == "OPEN":
                    cancel_allocation(a)


def mark_past_due():
    t = now()
    for inv in list(DB["invoices"].values()):
        if inv["status"] in ("OPEN", "PARTIALLY_PAID") \
                and parse_dt(inv["due_date"]) < t and inv["balance_due_cents"] > 0:
            inv["status"] = "PAST_DUE"
            touch(inv)
            inst = DB["installers"].get(inv["installer_id"])
            if inst:
                recompute_installer(inst)


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------
@app.route("/solar-dist/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    b = body()
    t = req_dt(b, "to_iso8601")
    _CLOCK["now"] = t
    obsolescence_sweep()
    mark_past_due()
    return ok_obj({"current_utc": iso(now())})


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
PRODUCT_KINDS = {"MODULE", "INVERTER", "RACKING", "BOS"}


@app.route("/solar-dist/products", methods=["POST"])
def create_product():
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    b = body()
    sku = req_str(b, "sku")
    kind = req_str(b, "product_kind")
    if kind not in PRODUCT_KINDS:
        err("ERR_INVALID_REQUEST", 400, "product_kind must be MODULE|INVERTER|RACKING|BOS")
    manufacturer_name = req_str(b, "manufacturer_name")
    technology_generation = req_int(b, "technology_generation")
    hts_code = req_str(b, "hts_code")
    list_price_cents = req_int(b, "list_price_cents")
    if kind == "MODULE":
        wattage_w = req_int(b, "wattage_w")
    else:
        wattage_w = 0
    if kind == "INVERTER":
        ac_output_w = req_int(b, "ac_output_w")
        dc_input_max_w = req_int(b, "dc_input_max_w")
    else:
        ac_output_w = 0
        dc_input_max_w = 0
    if any(p["sku"] == sku for p in DB["products"].values()):
        err("ERR_INVALID_REQUEST", 400, "sku must be unique per product")
    p = new_entity()
    p.update({
        "sku": sku,
        "product_kind": kind,
        "manufacturer_name": manufacturer_name,
        "wattage_w": wattage_w,
        "ac_output_w": ac_output_w,
        "dc_input_max_w": dc_input_max_w,
        "technology_generation": technology_generation,
        "hts_code": hts_code,
        "list_price_cents": list_price_cents,
        "status": "ACTIVE",
        "_discontinued_at": None,
    })
    DB["products"][p["id"]] = p
    return ok_obj(pub(p), 201)


@app.route("/solar-dist/products", methods=["GET"])
def list_products():
    auth()
    items = list(DB["products"].values())
    args = request.args
    if "product_kind" in args:
        items = [p for p in items if p["product_kind"] == args["product_kind"]]
    if "status" in args:
        items = [p for p in items if p["status"] == args["status"]]
    if "manufacturer_name" in args:
        items = [p for p in items if p["manufacturer_name"] == args["manufacturer_name"]]
    return paginate(items)


@app.route("/solar-dist/products/<productId>", methods=["GET"])
def get_product(productId):
    auth()
    p = find("products", productId, "ERR_PRODUCT_NOT_FOUND")
    return ok_obj(pub(p))


@app.route("/solar-dist/products/<productId>/discontinue", methods=["POST"])
def discontinue_product(productId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    p = find("products", productId, "ERR_PRODUCT_NOT_FOUND")
    if p["status"] != "ACTIVE":
        err("ERR_PRODUCT_NOT_ACTIVE", 409, "Product must be ACTIVE to discontinue")
    p["status"] = "DISCONTINUED"
    p["_discontinued_at"] = now()
    touch(p)
    for r in list(DB["rules"].values()):
        if r["status"] == "ACTIVE" and (
                r["module_product_id"] == p["id"] or r["inverter_product_id"] == p["id"]):
            r["status"] = "RETIRED"
            r["effective_to"] = iso(now())
            touch(r)
    return ok_obj(pub(p))


# ---------------------------------------------------------------------------
# Compatibility rules
# ---------------------------------------------------------------------------
@app.route("/solar-dist/compatibility-rules", methods=["POST"])
def create_rule():
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    b = body()
    module_product_id = req_str(b, "module_product_id")
    inverter_product_id = req_str(b, "inverter_product_id")
    max_m = req_int(b, "max_modules_per_inverter")
    min_m = req_int(b, "min_modules_per_inverter")
    eff_from = req_dt(b, "effective_from")
    eff_to = opt_dt(b, "effective_to")
    mp = find("products", module_product_id, "ERR_PRODUCT_NOT_FOUND")
    ip = find("products", inverter_product_id, "ERR_PRODUCT_NOT_FOUND")
    if mp["product_kind"] != "MODULE" or ip["product_kind"] != "INVERTER":
        err("ERR_INVALID_REQUEST", 400,
            "module_product_id must reference a MODULE and inverter_product_id an INVERTER")
    if min_m < 0 or max_m < min_m:
        err("ERR_INVALID_REQUEST", 400, "Invalid min/max modules per inverter")
    if mp["status"] != "ACTIVE" or ip["status"] != "ACTIVE":
        err("ERR_PRODUCT_NOT_ACTIVE", 409, "Referenced products must be ACTIVE")
    r = new_entity()
    r.update({
        "module_product_id": module_product_id,
        "inverter_product_id": inverter_product_id,
        "max_modules_per_inverter": max_m,
        "min_modules_per_inverter": min_m,
        "effective_from": iso(eff_from),
        "effective_to": iso(eff_to) if eff_to else None,
        "status": "ACTIVE",
    })
    DB["rules"][r["id"]] = r
    return ok_obj(pub(r), 201)


@app.route("/solar-dist/compatibility-rules", methods=["GET"])
def list_rules():
    auth()
    items = list(DB["rules"].values())
    args = request.args
    for f in ("module_product_id", "inverter_product_id", "status"):
        if f in args:
            items = [r for r in items if r[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/compatibility-rules/<ruleId>", methods=["GET"])
def get_rule(ruleId):
    auth()
    r = find("rules", ruleId, "ERR_RULE_NOT_FOUND")
    return ok_obj(pub(r))


@app.route("/solar-dist/compatibility-rules/<ruleId>/retire", methods=["POST"])
def retire_rule(ruleId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    r = find("rules", ruleId, "ERR_RULE_NOT_FOUND")
    if r["status"] != "ACTIVE":
        err("ERR_RULE_NOT_ACTIVE", 409, "CompatibilityRule must be ACTIVE to retire")
    for p in DB["projects"].values():
        if p["compatibility_rule_id"] == r["id"] and p["design_locked_at"] is None:
            err("ERR_RULE_IN_USE", 409,
                "Cannot retire a rule referenced by an unlocked project design")
    r["status"] = "RETIRED"
    if r["effective_to"] is None:
        r["effective_to"] = iso(now())
    touch(r)
    return ok_obj(pub(r))


# ---------------------------------------------------------------------------
# Tariff rates
# ---------------------------------------------------------------------------
def windows_overlap(a_from, a_to, b_from, b_to):
    a_end = a_to if a_to is not None else datetime.max.replace(tzinfo=timezone.utc)
    b_end = b_to if b_to is not None else datetime.max.replace(tzinfo=timezone.utc)
    return a_from < b_end and b_from < a_end


@app.route("/solar-dist/tariff-rates", methods=["POST"])
def create_tariff():
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    b = body()
    hts_code = req_str(b, "hts_code")
    duty_rate_bp = req_int(b, "duty_rate_bp")
    eff_from = req_dt(b, "effective_from")
    eff_to = opt_dt(b, "effective_to")
    if eff_to is not None and eff_to <= eff_from:
        err("ERR_INVALID_REQUEST", 400, "effective_to must be after effective_from")
    for r in DB["tariffs"].values():
        if r["hts_code"] == hts_code and r["status"] == "ACTIVE":
            r_from = parse_dt(r["effective_from"])
            r_to = parse_dt(r["effective_to"]) if r["effective_to"] else None
            if windows_overlap(eff_from, eff_to, r_from, r_to):
                err("ERR_TARIFF_WINDOW_OVERLAP", 409,
                    "An ACTIVE TariffRate already covers this hts_code over the proposed window")
    r = new_entity()
    r.update({
        "hts_code": hts_code,
        "duty_rate_bp": duty_rate_bp,
        "effective_from": iso(eff_from),
        "effective_to": iso(eff_to) if eff_to else None,
        "status": "ACTIVE",
    })
    DB["tariffs"][r["id"]] = r
    return ok_obj(pub(r), 201)


@app.route("/solar-dist/tariff-rates", methods=["GET"])
def list_tariffs():
    auth()
    items = list(DB["tariffs"].values())
    args = request.args
    for f in ("hts_code", "status"):
        if f in args:
            items = [r for r in items if r[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/tariff-rates/<rateId>", methods=["GET"])
def get_tariff(rateId):
    auth()
    r = find("tariffs", rateId, "ERR_TARIFF_NOT_FOUND")
    return ok_obj(pub(r))


# ---------------------------------------------------------------------------
# Installers
# ---------------------------------------------------------------------------
@app.route("/solar-dist/installers", methods=["POST"])
def create_installer():
    _, role = auth()
    require_role(role, {"ChannelManager"})
    b = body()
    legal_name = req_str(b, "legal_name")
    license_number = req_str(b, "license_number")
    credit_limit_cents = req_int(b, "credit_limit_cents")
    progress_payment_pct_bp = req_int(b, "progress_payment_pct_bp")
    payment_terms_days = req_int(b, "payment_terms_days")
    inst = new_entity()
    inst.update({
        "legal_name": legal_name,
        "license_number": license_number,
        "credit_limit_cents": credit_limit_cents,
        "progress_payment_pct_bp": progress_payment_pct_bp,
        "payment_terms_days": payment_terms_days,
        "credit_exposure_cents": 0,
        "credit_hold": False,
        "status": "ONBOARDING",
    })
    DB["installers"][inst["id"]] = inst
    return ok_obj(pub(inst), 201)


@app.route("/solar-dist/installers", methods=["GET"])
def list_installers():
    auth()
    items = list(DB["installers"].values())
    if "status" in request.args:
        items = [i for i in items if i["status"] == request.args["status"]]
    return paginate(items)


@app.route("/solar-dist/installers/<installerId>", methods=["GET"])
def get_installer(installerId):
    auth()
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    return ok_obj(pub(inst))


@app.route("/solar-dist/installers/<installerId>/activate", methods=["POST"])
def activate_installer(installerId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    if inst["status"] != "ONBOARDING":
        err("ERR_INSTALLER_NOT_ACTIVE", 409, "Installer must be ONBOARDING to activate")
    if inst["credit_limit_cents"] <= 0:
        err("ERR_CREDIT_LIMIT_REQUIRED", 400, "credit_limit_cents must be > 0 at activation")
    if not (0 <= inst["progress_payment_pct_bp"] <= 10000):
        err("ERR_INVALID_PROGRESS_PCT", 400, "progress_payment_pct_bp outside [0, 10000]")
    if inst["payment_terms_days"] <= 0:
        err("ERR_INVALID_PAYMENT_TERMS", 400, "payment_terms_days must be > 0")
    inst["status"] = "ACTIVE"
    inst["credit_exposure_cents"] = 0
    inst["credit_hold"] = False
    touch(inst)
    return ok_obj(pub(inst))


@app.route("/solar-dist/installers/<installerId>/suspend", methods=["POST"])
def suspend_installer(installerId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    if inst["status"] != "ACTIVE":
        err("ERR_INSTALLER_NOT_ACTIVE", 409, "Installer must be ACTIVE to suspend")
    inst["status"] = "SUSPENDED"
    touch(inst)
    projects = [p for p in DB["projects"].values() if p["installer_id"] == inst["id"]]
    for p in projects:
        for a in list(DB["allocations"].values()):
            if a["project_id"] == p["id"] and a["status"] == "OPEN":
                cancel_allocation(a)
    for p in projects:
        allocs = [a for a in DB["allocations"].values() if a["project_id"] == p["id"]]
        all_terminal = all(a["status"] in ("SHIPPED", "RELEASED", "CANCELLED") for a in allocs)
        if all_terminal and p["payment_status"] == "UNBILLED" \
                and p["fulfillment_status"] not in ("COMPLETE", "CANCELLED"):
            p["fulfillment_status"] = "CANCELLED"
            touch(p)
    return ok_obj(pub(inst))


@app.route("/solar-dist/installers/<installerId>/reinstate", methods=["POST"])
def reinstate_installer(installerId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    if inst["status"] != "SUSPENDED":
        err("ERR_INSTALLER_NOT_SUSPENDED", 409, "Installer must be SUSPENDED to reinstate")
    if inst["credit_exposure_cents"] >= inst["credit_limit_cents"]:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402,
            "credit_exposure_cents must be strictly below credit_limit_cents")
    inst["status"] = "ACTIVE"
    touch(inst)
    return ok_obj(pub(inst))


@app.route("/solar-dist/installers/<installerId>/terminate", methods=["POST"])
def terminate_installer(installerId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    if inst["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INSTALLER_NOT_ACTIVE", 409,
            "Installer must be ACTIVE or SUSPENDED to terminate")
    if inst["credit_exposure_cents"] != 0:
        err("ERR_OUTSTANDING_BALANCE", 402,
            "Installer credit_exposure_cents must be 0 to terminate")
    for p in DB["projects"].values():
        if p["installer_id"] != inst["id"]:
            continue
        if p["payment_status"] not in ("PAID_IN_FULL", "WRITTEN_OFF") \
                or p["fulfillment_status"] not in ("COMPLETE", "CANCELLED"):
            err("ERR_OUTSTANDING_BALANCE", 402,
                "Installer has in-flight projects blocking termination")
    if inst["status"] == "ACTIVE":
        for p in DB["projects"].values():
            if p["installer_id"] != inst["id"]:
                continue
            for a in list(DB["allocations"].values()):
                if a["project_id"] == p["id"] and a["status"] == "OPEN":
                    cancel_allocation(a)
    inst["status"] = "TERMINATED"
    touch(inst)
    return ok_obj(pub(inst))


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
@app.route("/solar-dist/containers", methods=["POST"])
def create_container():
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    b = body()
    container_number = req_str(b, "container_number")
    bol_number = req_str(b, "bol_number")
    origin_port = req_str(b, "origin_port")
    eta = req_dt(b, "eta_utc")
    freight = req_int(b, "freight_cost_cents")
    insurance = req_int(b, "insurance_cost_cents")
    if any(c["container_number"] == container_number for c in DB["containers"].values()):
        err("ERR_INVALID_REQUEST", 400, "container_number must be unique per shipment")
    c = new_entity()
    c.update({
        "container_number": container_number,
        "bol_number": bol_number,
        "origin_port": origin_port,
        "eta_utc": iso(eta),
        "actual_arrival_utc": None,
        "freight_cost_cents": freight,
        "insurance_cost_cents": insurance,
        "status": "BOOKED",
    })
    DB["containers"][c["id"]] = c
    return ok_obj(pub(c), 201)


@app.route("/solar-dist/containers", methods=["GET"])
def list_containers():
    auth()
    items = list(DB["containers"].values())
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    return paginate(items)


@app.route("/solar-dist/containers/<containerId>", methods=["GET"])
def get_container(containerId):
    auth()
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>", methods=["PATCH"])
def patch_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    b = body()
    eta = opt_dt(b, "eta_utc")
    freight = opt_int(b, "freight_cost_cents")
    insurance = opt_int(b, "insurance_cost_cents")
    if c["status"] not in ("BOOKED", "IN_TRANSIT"):
        err("ERR_CONTAINER_NOT_UPDATABLE", 409,
            "Container fields may only be updated while BOOKED or IN_TRANSIT")
    changed = False
    if eta is not None:
        c["eta_utc"] = iso(eta)
        changed = True
    if freight is not None:
        c["freight_cost_cents"] = freight
        changed = True
    if insurance is not None:
        c["insurance_cost_cents"] = insurance
        changed = True
    if changed:
        touch(c)
        recompute_provisional(c)
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>/depart", methods=["POST"])
def depart_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    if c["status"] != "BOOKED":
        err("ERR_CONTAINER_NOT_BOOKED", 409, "Container must be BOOKED to depart")
    c["status"] = "IN_TRANSIT"
    touch(c)
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>/arrive", methods=["POST"])
def arrive_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    if c["status"] != "IN_TRANSIT":
        err("ERR_CONTAINER_NOT_IN_TRANSIT", 409, "Container must be IN_TRANSIT to arrive")
    c["status"] = "ARRIVED"
    c["actual_arrival_utc"] = iso(now())
    touch(c)
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>/receive", methods=["POST"])
def receive_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    b = body()
    line_receipts = b.get("line_receipts")
    if not isinstance(line_receipts, list):
        err("ERR_INVALID_REQUEST", 400, "line_receipts must be a list")
    expected_container_version = b.get("expected_container_version")
    if expected_container_version is not None and not _is_int(expected_container_version):
        err("ERR_INVALID_REQUEST", 400, "expected_container_version must be an integer")
    if c["status"] != "ARRIVED":
        err("ERR_CONTAINER_NOT_ARRIVED", 409, "Container must be ARRIVED to receive")
    lines = container_lines(c["id"])
    receipt_map = {}
    for lr in line_receipts:
        if not isinstance(lr, dict):
            err("ERR_INVALID_REQUEST", 400, "Each line receipt must be an object")
        lid = lr.get("container_line_id")
        if not isinstance(lid, str):
            err("ERR_INVALID_REQUEST", 400, "container_line_id is required")
        line = DB["lines"].get(lid)
        if line is None or line["container_id"] != c["id"]:
            err("ERR_LINE_NOT_FOUND", 404, f"ContainerLine {lid} not found")
        qr = lr.get("qty_received")
        qd = lr.get("qty_damaged")
        if not _is_int(qr) or not _is_int(qd) or qr < 0 or qd < 0:
            err("ERR_INVALID_REQUEST", 400,
                "qty_received and qty_damaged must be non-negative integers")
        receipt_map[lid] = (qr, qd)
    # Temporal reconciliation (all lines before any mutation — atomicity)
    for line in lines:
        if line["id"] not in receipt_map:
            err("ERR_RECEIPT_QTY_MISMATCH", 409,
                "Every line must have a receipt entry")
        qr, qd = receipt_map[line["id"]]
        if qr + qd != line["qty_booked"]:
            err("ERR_RECEIPT_QTY_MISMATCH", 409,
                "qty_received + qty_damaged must equal qty_booked on every line")
    # OCC last
    if expected_container_version is not None \
            and expected_container_version != c["version"]:
        err("ERR_STALE_CONTAINER_VERSION", 412,
            "expected_container_version does not match current Container.version")
    # Commit
    for line in lines:
        qr, qd = receipt_map[line["id"]]
        line["qty_received"] = qr
        line["qty_damaged"] = qd
        touch(line)
    arrival = parse_dt(c["actual_arrival_utc"])
    costs = compute_unit_costs(c, arrival, final=True)
    affected_lots = []
    for line in lines:
        qr, qd = receipt_map[line["id"]]
        lot = DB["lots"][line["inventory_lot_id"]]
        lot["qty_on_hand"] += qr
        lot["qty_quarantined"] += qd
        lot["unit_cost_cents_final"] = costs[line["id"]]
        lot["received_at"] = iso(now())
        lot["status"] = "ON_HAND"
        touch(lot)
        maybe_depleted(lot)
        affected_lots.append(lot["id"])
    c["status"] = "RECEIVED"
    touch(c)
    # Recompute allocated_value for projects holding OPEN allocations on these lots
    for a in DB["allocations"].values():
        if a["inventory_lot_id"] in affected_lots and a["status"] == "OPEN":
            p = DB["projects"].get(a["project_id"])
            if p:
                recompute_project(p)
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>/close", methods=["POST"])
def close_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    if c["status"] != "RECEIVED":
        err("ERR_CONTAINER_NOT_RECEIVED", 409, "Container must be RECEIVED to close")
    for cl in DB["claims"].values():
        if cl["container_id"] == c["id"] and cl["status"] not in ("SETTLED", "DENIED"):
            err("ERR_OPEN_DAMAGE_CLAIMS", 409,
                "Container cannot close while damage claims are unsettled")
    c["status"] = "CLOSED"
    touch(c)
    return ok_obj(pub(c))


@app.route("/solar-dist/containers/<containerId>/cancel", methods=["POST"])
def cancel_container(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    if c["status"] != "BOOKED":
        err("ERR_CONTAINER_NOT_CANCELLABLE", 409,
            "Container can only be cancelled while BOOKED")
    c["status"] = "CANCELLED"
    touch(c)
    for line in container_lines(c["id"]):
        lot = DB["lots"].get(line["inventory_lot_id"])
        if lot is not None and lot["status"] != "WRITTEN_OFF":
            lot["status"] = "WRITTEN_OFF"
            lot["qty_on_hand"] = 0
            touch(lot)
    return ok_obj(pub(c))


# ---------------------------------------------------------------------------
# Container lines
# ---------------------------------------------------------------------------
@app.route("/solar-dist/containers/<containerId>/lines", methods=["POST"])
def create_line(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    b = body()
    product_id = req_str(b, "product_id")
    qty_booked = req_int(b, "qty_booked")
    declared = req_int(b, "declared_unit_value_cents")
    if qty_booked <= 0 or declared < 0:
        err("ERR_INVALID_REQUEST", 400,
            "qty_booked must be > 0 and declared_unit_value_cents must be >= 0")
    prod = find("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    if c["status"] not in ("BOOKED", "IN_TRANSIT"):
        err("ERR_CONTAINER_NOT_UPDATABLE", 409,
            "Lines may only be added while the container is BOOKED or IN_TRANSIT")
    lot = new_entity()
    lot.update({
        "product_id": product_id,
        "lot_code": f"LOT-{lot['_seq']}",
        "qty_on_hand": 0,
        "qty_allocated": 0,
        "qty_quarantined": 0,
        "unit_cost_cents_provisional": 0,
        "unit_cost_cents_final": None,
        "received_at": None,
        "stranded_at": None,
        "status": "IN_TRANSIT",
    })
    DB["lots"][lot["id"]] = lot
    line = new_entity()
    line.update({
        "container_id": c["id"],
        "inventory_lot_id": lot["id"],
        "qty_booked": qty_booked,
        "qty_received": 0,
        "qty_damaged": 0,
        "product_id": product_id,
        "declared_unit_value_cents": declared,
    })
    DB["lines"][line["id"]] = line
    # Provisional landed cost for every attached lot (total declared value moved)
    recompute_provisional(c)
    return ok_obj(pub(line), 201)


@app.route("/solar-dist/containers/<containerId>/lines", methods=["GET"])
def list_lines(containerId):
    auth()
    find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    items = [l for l in DB["lines"].values() if l["container_id"] == containerId]
    return paginate(items)


@app.route("/solar-dist/containers/<containerId>/lines/<lineId>", methods=["GET"])
def get_line(containerId, lineId):
    auth()
    find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    line = DB["lines"].get(lineId)
    if line is None or line["container_id"] != containerId:
        err("ERR_LINE_NOT_FOUND", 404, f"ContainerLine {lineId} not found")
    return ok_obj(pub(line))


@app.route("/solar-dist/container-lines", methods=["GET"])
def list_all_lines():
    auth()
    items = list(DB["lines"].values())
    args = request.args
    for f in ("container_id", "inventory_lot_id", "product_id"):
        if f in args:
            items = [l for l in items if l[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/container-lines/<lineId>", methods=["GET"])
def get_line_top(lineId):
    auth()
    line = find("lines", lineId, "ERR_LINE_NOT_FOUND")
    return ok_obj(pub(line))


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------
@app.route("/solar-dist/inventory-lots", methods=["GET"])
def list_lots():
    auth()
    items = list(DB["lots"].values())
    args = request.args
    for f in ("product_id", "status"):
        if f in args:
            items = [l for l in items if l[f] == args[f]]
    limit, offset = pagination()
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub_lot(e) for e in page], total, limit, offset)


@app.route("/solar-dist/inventory-lots/<lotId>", methods=["GET"])
def get_lot(lotId):
    auth()
    lot = find("lots", lotId, "ERR_LOT_NOT_FOUND")
    return ok_obj(pub_lot(lot))


@app.route("/solar-dist/inventory-lots/<lotId>/write-off", methods=["POST"])
def writeoff_lot(lotId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    lot = find("lots", lotId, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "STRANDED":
        err("ERR_LOT_NOT_STRANDED", 409, "InventoryLot must be STRANDED for write-off")
    if lot["qty_allocated"] != 0:
        err("ERR_ALLOCATIONS_OUTSTANDING", 409,
            "Lot has non-terminal allocations blocking write-off")
    lot["qty_on_hand"] = 0
    lot["qty_quarantined"] = 0
    lot["status"] = "WRITTEN_OFF"
    touch(lot)
    return ok_obj(pub_lot(lot))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@app.route("/solar-dist/installers/<installerId>/projects", methods=["POST"])
def create_project(installerId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "ChannelManager"})
    b = body()
    project_name = req_str(b, "project_name")
    site_postal_code = req_str(b, "site_postal_code")
    module_product_id = req_str(b, "module_product_id")
    inverter_product_id = req_str(b, "inverter_product_id")
    module_qty = req_int(b, "module_qty")
    inverter_qty = req_int(b, "inverter_qty")
    if module_qty <= 0 or inverter_qty <= 0:
        err("ERR_INVALID_REQUEST", 400, "module_qty and inverter_qty must be > 0")
    inst = find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    own_installer(uid, role, installerId)
    find("products", module_product_id, "ERR_PRODUCT_NOT_FOUND")
    find("products", inverter_product_id, "ERR_PRODUCT_NOT_FOUND")
    if inst["status"] != "ACTIVE":
        err("ERR_INSTALLER_NOT_ACTIVE", 409, "Installer must be ACTIVE")
    p = new_entity()
    p.update({
        "installer_id": installerId,
        "project_name": project_name,
        "site_postal_code": site_postal_code,
        "system_size_kw_dc": None,
        "module_product_id": module_product_id,
        "inverter_product_id": inverter_product_id,
        "module_qty": module_qty,
        "inverter_qty": inverter_qty,
        "compatibility_rule_id": None,
        "design_locked_at": None,
        "allocated_value_cents": 0,
        "invoiced_value_cents": 0,
        "paid_value_cents": 0,
        "payment_status": "UNBILLED",
        "fulfillment_status": "DESIGN",
    })
    DB["projects"][p["id"]] = p
    return ok_obj(pub(p), 201)


@app.route("/solar-dist/installers/<installerId>/projects", methods=["GET"])
def list_installer_projects(installerId):
    auth()
    find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    items = [p for p in DB["projects"].values() if p["installer_id"] == installerId]
    args = request.args
    for f in ("fulfillment_status", "payment_status"):
        if f in args:
            items = [p for p in items if p[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/projects/<projectId>", methods=["GET"])
def get_project(projectId):
    auth()
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    return ok_obj(pub(p))


@app.route("/solar-dist/projects", methods=["GET"])
def list_projects():
    auth()
    items = list(DB["projects"].values())
    args = request.args
    for f in ("installer_id", "module_product_id", "inverter_product_id",
              "compatibility_rule_id", "fulfillment_status", "payment_status"):
        if f in args:
            items = [p for p in items if p[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/projects/<projectId>/lock-design", methods=["POST"])
def lock_design(projectId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "ChannelManager"})
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    own_installer(uid, role, p["installer_id"])
    if p["design_locked_at"] is not None:
        err("ERR_INVALID_REQUEST", 400, "Design is already locked")
    t = now()
    # Compatibility rule lookup
    cands = []
    for r in DB["rules"].values():
        if r["module_product_id"] != p["module_product_id"]:
            continue
        if r["inverter_product_id"] != p["inverter_product_id"]:
            continue
        if r["status"] != "ACTIVE":
            continue
        ef = parse_dt(r["effective_from"])
        et = parse_dt(r["effective_to"]) if r["effective_to"] else None
        if ef <= t and (et is None or t < et):
            cands.append(r)
    if not cands:
        err("ERR_NO_COMPATIBILITY_RULE", 422,
            "No ACTIVE CompatibilityRule covers the module-inverter pair at lock time")
    cands.sort(key=lambda r: (r["effective_from"], r["_seq"]))
    rule = cands[-1]
    if p["module_qty"] < rule["min_modules_per_inverter"] * p["inverter_qty"] \
            or p["module_qty"] > rule["max_modules_per_inverter"] * p["inverter_qty"]:
        err("ERR_STRING_SIZE_VIOLATION", 422,
            "module_qty / inverter_qty ratio outside [min, max] modules per inverter")
    module = DB["products"].get(p["module_product_id"])
    inverter = DB["products"].get(p["inverter_product_id"])
    if module is None or module["status"] != "ACTIVE" \
            or inverter is None or inverter["status"] != "ACTIVE":
        err("ERR_PRODUCT_NOT_ACTIVE", 409,
            "Module and inverter products must be ACTIVE at design lock")
    p["compatibility_rule_id"] = rule["id"]
    p["design_locked_at"] = iso(t)
    p["system_size_kw_dc"] = (module["wattage_w"] * p["module_qty"]) / 1000.0
    touch(p)
    # Auto-create permit package
    pkg = new_entity()
    pkg.update({
        "project_id": p["id"],
        "ahj_code": f"AHJ-{p['site_postal_code']}",
        "required_documents": [
            f"module-datasheet-{module['sku']}",
            f"module-install-guide-{module['sku']}",
            f"inverter-datasheet-{inverter['sku']}",
            f"inverter-install-guide-{inverter['sku']}",
        ],
        "submitted_documents": [],
        "submitted_at": None,
        "approved_at": None,
        "status": "ASSEMBLING",
    })
    DB["packages"][pkg["id"]] = pkg
    # DESIGN -> ALLOCATED if an OPEN allocation already exists
    if any(a["project_id"] == p["id"] and a["status"] == "OPEN"
           for a in DB["allocations"].values()):
        if p["fulfillment_status"] == "DESIGN":
            p["fulfillment_status"] = "ALLOCATED"
            touch(p)
    return ok_obj(pub(p))


@app.route("/solar-dist/projects/<projectId>/cancel", methods=["POST"])
def cancel_project(projectId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "ChannelManager"})
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    own_installer(uid, role, p["installer_id"])
    if p["fulfillment_status"] not in ("DESIGN", "ALLOCATED"):
        err("ERR_PROJECT_NOT_CANCELLABLE", 409,
            "Project in SHIPPED/PARTIALLY_SHIPPED/COMPLETE/CANCELLED cannot be cancelled")
    if any(a["project_id"] == p["id"] and a["status"] == "SHIPPED"
           for a in DB["allocations"].values()):
        err("ERR_SHIPPED_ALLOCATIONS_EXIST", 409,
            "Cannot cancel a project with SHIPPED allocations")
    for a in list(DB["allocations"].values()):
        if a["project_id"] == p["id"] and a["status"] == "OPEN":
            cancel_allocation(a)
    p["fulfillment_status"] = "CANCELLED"
    p["allocated_value_cents"] = 0
    touch(p)
    return ok_obj(pub(p))


def project_permit_approved(p):
    return any(pk for pk in DB["packages"].values()
               if pk["project_id"] == p["id"] and pk["status"] == "APPROVED")


@app.route("/solar-dist/projects/<projectId>/complete", methods=["POST"])
def complete_project(projectId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    own_installer(uid, role, p["installer_id"])
    if p["payment_status"] != "PAID_IN_FULL":
        err("ERR_UNPAID_BALANCE", 409,
            "Cannot complete project while payment_status != PAID_IN_FULL")
    if not project_permit_approved(p):
        err("ERR_PERMIT_NOT_APPROVED", 409,
            "PermitPackage must be APPROVED for project completion")
    if p["fulfillment_status"] != "SHIPPED":
        err("ERR_UNPAID_BALANCE", 409, "Project must be SHIPPED to complete")
    p["fulfillment_status"] = "COMPLETE"
    touch(p)
    return ok_obj(pub(p))


@app.route("/solar-dist/projects/<projectId>/invoice-pto", methods=["POST"])
def invoice_pto(projectId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    if p["payment_status"] != "PROGRESS_BILLED":
        err("ERR_PROGRESS_NOT_BILLED", 409,
            "PTO invoice requires payment_status=PROGRESS_BILLED")
    if not project_permit_approved(p):
        err("ERR_PERMIT_NOT_APPROVED", 409,
            "PermitPackage must be APPROVED for PTO invoice")
    if p["fulfillment_status"] != "SHIPPED":
        err("ERR_PROGRESS_NOT_BILLED", 409,
            "PTO invoice requires fulfillment_status=SHIPPED")
    inst = DB["installers"][p["installer_id"]]
    recompute_project(p)
    avc = p["allocated_value_cents"]
    prog = None
    for inv in project_invoices(p["id"]):
        if inv["invoice_kind"] == "PROGRESS" and inv["status"] != "VOID":
            prog = inv
    if prog is not None:
        progress_amount = prog["amount_cents"]
    else:
        progress_amount = rhu(avc * inst["progress_payment_pct_bp"], BP_BASE)
    pto_amount = avc - progress_amount
    inv = create_invoice(p, inst, "PTO", pto_amount)
    p["payment_status"] = "PTO_BILLED"
    touch(p)
    recompute_project(p)
    recompute_installer(inst)
    return ok_obj(pub(inv))


@app.route("/solar-dist/projects/<projectId>/write-off", methods=["POST"])
def writeoff_project(projectId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    if p["payment_status"] not in ("PROGRESS_BILLED", "PTO_BILLED"):
        err("ERR_PROGRESS_NOT_BILLED", 409,
            "Write-off requires payment_status PROGRESS_BILLED or PTO_BILLED")
    inst = DB["installers"][p["installer_id"]]
    if inst["status"] not in ("SUSPENDED", "TERMINATED"):
        err("ERR_INSTALLER_NOT_SUSPENDED", 409,
            "Installer must be SUSPENDED or TERMINATED for write-off")
    outstanding = sum(i["balance_due_cents"] for i in project_invoices(p["id"])
                      if i["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE")
                      and i["invoice_kind"] != "WRITE_OFF")
    if outstanding <= 0:
        err("ERR_INVALID_REQUEST", 400, "No outstanding balance to write off")
    inv = create_invoice(p, inst, "WRITE_OFF", outstanding)
    # Offset the outstanding invoices to zero net recognized: their balances are
    # extinguished by the write-off (the loss is recognized on the WRITE_OFF
    # invoice, which the exposure rule excludes).
    for other in project_invoices(p["id"]):
        if other["id"] != inv["id"] and other["invoice_kind"] != "WRITE_OFF" \
                and other["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE"):
            other["balance_due_cents"] = 0
            other["status"] = "PAID"
            touch(other)
    p["payment_status"] = "WRITTEN_OFF"
    touch(p)
    recompute_installer(inst)
    return ok_obj(pub(inv))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------
@app.route("/solar-dist/projects/<projectId>/allocations", methods=["POST"])
def create_allocation(projectId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "ChannelManager"})
    b = body()
    inventory_lot_id = req_str(b, "inventory_lot_id")
    qty_allocated = req_int(b, "qty_allocated")
    expected_lot_version = b.get("expected_lot_version")
    if expected_lot_version is not None and not _is_int(expected_lot_version):
        err("ERR_INVALID_REQUEST", 400, "expected_lot_version must be an integer")
    if qty_allocated <= 0:
        err("ERR_INVALID_REQUEST", 400, "qty_allocated must be > 0")
    p = find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    own_installer(uid, role, p["installer_id"])
    # State: design must be locked
    if p["design_locked_at"] is None:
        err("ERR_DESIGN_NOT_LOCKED", 409, "Design must be locked before allocation")
    # Referential: lot exists; installer non-terminal
    lot = find("lots", inventory_lot_id, "ERR_LOT_NOT_FOUND")
    inst = DB["installers"][p["installer_id"]]
    if inst["status"] != "ACTIVE":
        err("ERR_INSTALLER_NOT_ACTIVE", 409, "Installer must be ACTIVE to allocate")
    # Credit gate
    prospective = qty_allocated * lot["unit_cost_cents_provisional"]
    if inst["credit_hold"] \
            or (inst["credit_exposure_cents"] + prospective) >= inst["credit_limit_cents"]:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402,
            "Allocation would push credit exposure to/over credit limit")
    # Availability
    if lot_avail(lot) < qty_allocated:
        err("ERR_INSUFFICIENT_QTY", 409, "Lot does not have enough qty_available")
    # OCC last
    if expected_lot_version is not None and expected_lot_version != lot["version"]:
        err("ERR_STALE_LOT_VERSION", 412,
            "expected_lot_version does not match current InventoryLot.version")
    # Commit
    snapshot = lot["unit_cost_cents_final"] if lot["unit_cost_cents_final"] is not None \
        else lot["unit_cost_cents_provisional"]
    a = new_entity()
    a.update({
        "project_id": p["id"],
        "inventory_lot_id": lot["id"],
        "qty_allocated": qty_allocated,
        "unit_cost_cents_at_allocation": snapshot,
        "expected_lot_version": expected_lot_version,
        "allocated_at": iso(now()),
        "released_at": None,
        "shipped_at": None,
        "status": "OPEN",
    })
    DB["allocations"][a["id"]] = a
    lot["qty_allocated"] += qty_allocated
    touch(lot)
    recompute_project(p)
    if p["design_locked_at"] is not None and p["fulfillment_status"] == "DESIGN":
        if any(x["project_id"] == p["id"] and x["status"] == "OPEN"
               for x in DB["allocations"].values()):
            p["fulfillment_status"] = "ALLOCATED"
            touch(p)
    recompute_installer(inst)
    return ok_obj(pub(a), 201)


@app.route("/solar-dist/projects/<projectId>/allocations", methods=["GET"])
def list_project_allocations(projectId):
    auth()
    find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    items = [a for a in DB["allocations"].values() if a["project_id"] == projectId]
    if "status" in request.args:
        items = [a for a in items if a["status"] == request.args["status"]]
    return paginate(items)


@app.route("/solar-dist/allocations/<allocationId>", methods=["GET"])
def get_allocation(allocationId):
    auth()
    a = find("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")
    return ok_obj(pub(a))


@app.route("/solar-dist/allocations", methods=["GET"])
def list_allocations():
    auth()
    items = list(DB["allocations"].values())
    args = request.args
    for f in ("project_id", "inventory_lot_id", "status"):
        if f in args:
            items = [a for a in items if a[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/allocations/<allocationId>/ship", methods=["POST"])
def ship_allocation(allocationId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    a = find("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")
    if a["status"] != "OPEN":
        err("ERR_ALLOCATION_NOT_OPEN", 409, "Allocation must be OPEN to ship")
    lot = find("lots", a["inventory_lot_id"], "ERR_LOT_NOT_FOUND")
    if lot["status"] != "ON_HAND":
        err("ERR_LOT_NOT_ON_HAND", 409, "InventoryLot must be ON_HAND for allocation ship")
    # Ship-time availability: the units reserved by THIS allocation are the
    # units that leave the building ("the reservation is released at once"),
    # so the check measures availability including this allocation's own
    # reservation. It fires when intervening events (e.g. damage settlement)
    # drove qty_available below zero — i.e. the lot can no longer back the
    # outstanding reservations.
    if lot_avail(lot) + a["qty_allocated"] < a["qty_allocated"]:
        err("ERR_INSUFFICIENT_QTY", 409, "Lot does not have enough qty_available")
    a["status"] = "SHIPPED"
    a["shipped_at"] = iso(now())
    touch(a)
    lot["qty_on_hand"] -= a["qty_allocated"]
    lot["qty_allocated"] -= a["qty_allocated"]
    touch(lot)
    maybe_depleted(lot)
    p = DB["projects"].get(a["project_id"])
    if p:
        recompute_project(p)
        eval_fulfillment(p)
    return ok_obj(pub(a))


@app.route("/solar-dist/allocations/<allocationId>/release", methods=["POST"])
def release_allocation(allocationId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "ChannelManager"})
    a = find("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")
    p = DB["projects"].get(a["project_id"])
    if p is not None:
        own_installer(uid, role, p["installer_id"])
    if a["status"] != "OPEN":
        err("ERR_ALLOCATION_NOT_OPEN", 409, "Allocation must be OPEN to release")
    a["status"] = "RELEASED"
    a["released_at"] = iso(now())
    touch(a)
    lot = DB["lots"].get(a["inventory_lot_id"])
    if lot is not None:
        lot["qty_allocated"] -= a["qty_allocated"]
        touch(lot)
    if p is not None:
        recompute_project(p)
    return ok_obj(pub(a))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@app.route("/solar-dist/projects/<projectId>/invoices", methods=["GET"])
def list_project_invoices(projectId):
    auth()
    find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    items = [i for i in DB["invoices"].values() if i["project_id"] == projectId]
    args = request.args
    for f in ("status", "invoice_kind"):
        if f in args:
            items = [i for i in items if i[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/installers/<installerId>/invoices", methods=["GET"])
def list_installer_invoices(installerId):
    auth()
    find("installers", installerId, "ERR_INSTALLER_NOT_FOUND")
    items = [i for i in DB["invoices"].values() if i["installer_id"] == installerId]
    args = request.args
    for f in ("status", "invoice_kind"):
        if f in args:
            items = [i for i in items if i[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/invoices/<invoiceId>", methods=["GET"])
def get_invoice(invoiceId):
    auth()
    inv = find("invoices", invoiceId, "ERR_INVOICE_NOT_FOUND")
    return ok_obj(pub(inv))


@app.route("/solar-dist/invoices", methods=["GET"])
def list_invoices():
    auth()
    items = list(DB["invoices"].values())
    args = request.args
    for f in ("project_id", "installer_id", "status", "invoice_kind"):
        if f in args:
            items = [i for i in items if i[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/invoices/<invoiceId>/void", methods=["POST"])
def void_invoice(invoiceId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    inv = find("invoices", invoiceId, "ERR_INVOICE_NOT_FOUND")
    if inv["status"] != "OPEN" or inv["balance_due_cents"] != inv["amount_cents"]:
        err("ERR_INVOICE_NOT_OPEN", 409,
            "Only an OPEN invoice with no payments posted can be voided")
    inv["status"] = "VOID"
    touch(inv)
    inst = DB["installers"].get(inv["installer_id"])
    if inst:
        recompute_installer(inst)
    p = DB["projects"].get(inv["project_id"])
    if p:
        recompute_project(p)
        eval_payment_status(p)
    return ok_obj(pub(inv))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@app.route("/solar-dist/invoices/<invoiceId>/payments", methods=["POST"])
def post_payment(invoiceId):
    uid, role = auth()
    require_role(role, {"InstallerRep", "CreditOfficer"})
    b = body()
    amount = req_int(b, "amount_cents")
    inv = find("invoices", invoiceId, "ERR_INVOICE_NOT_FOUND")
    own_installer(uid, role, inv["installer_id"])
    if inv["status"] == "VOID":
        err("ERR_INVOICE_VOID", 409, "Cannot post a payment to a VOID invoice")
    if amount <= 0 or amount > inv["balance_due_cents"]:
        err("ERR_INVALID_PAYMENT_AMOUNT", 422,
            "Payment amount must be > 0 and <= invoice balance_due_cents")
    pay = new_entity()
    pay.update({
        "invoice_id": inv["id"],
        "amount_cents": amount,
        "posted_at": iso(now()),
        "reversed_at": None,
        "status": "POSTED",
    })
    DB["payments"][pay["id"]] = pay
    inv["balance_due_cents"] -= amount
    if inv["balance_due_cents"] == 0:
        inv["status"] = "PAID"
    elif inv["status"] == "OPEN":
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)
    inst = DB["installers"].get(inv["installer_id"])
    if inst:
        recompute_installer(inst)
    p = DB["projects"].get(inv["project_id"])
    if p:
        recompute_project(p)
        eval_payment_status(p)
    return ok_obj(pub(pay), 201)


@app.route("/solar-dist/invoices/<invoiceId>/payments", methods=["GET"])
def list_invoice_payments(invoiceId):
    auth()
    find("invoices", invoiceId, "ERR_INVOICE_NOT_FOUND")
    items = [p for p in DB["payments"].values() if p["invoice_id"] == invoiceId]
    return paginate(items)


@app.route("/solar-dist/payments/<paymentId>", methods=["GET"])
def get_payment(paymentId):
    auth()
    pay = find("payments", paymentId, "ERR_PAYMENT_NOT_FOUND")
    return ok_obj(pub(pay))


@app.route("/solar-dist/payments", methods=["GET"])
def list_payments():
    auth()
    items = list(DB["payments"].values())
    args = request.args
    for f in ("invoice_id", "status"):
        if f in args:
            items = [p for p in items if p[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/payments/<paymentId>/reverse", methods=["POST"])
def reverse_payment(paymentId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    pay = find("payments", paymentId, "ERR_PAYMENT_NOT_FOUND")
    if pay["status"] != "POSTED":
        err("ERR_PAYMENT_NOT_POSTED", 409, "Payment must be POSTED to reverse")
    inv = DB["invoices"].get(pay["invoice_id"])
    others = [p2 for p2 in DB["payments"].values()
              if p2["invoice_id"] == pay["invoice_id"] and p2["id"] != pay["id"]]
    if inv is not None and inv["status"] == "PAID" \
            and all(p2["status"] == "REVERSED" for p2 in others):
        err("ERR_PAYMENT_NOT_REVERSIBLE", 409,
            "Reversal would create negative paid_value_cents")
    pay["status"] = "REVERSED"
    pay["reversed_at"] = iso(now())
    touch(pay)
    if inv is not None:
        inv["balance_due_cents"] += pay["amount_cents"]
        remaining_posted = sum(p2["amount_cents"] for p2 in others
                               if p2["status"] == "POSTED")
        if inv["balance_due_cents"] > 0:
            inv["status"] = "PARTIALLY_PAID" if remaining_posted > 0 else "OPEN"
            if parse_dt(inv["due_date"]) < now():
                inv["status"] = "PAST_DUE"
        touch(inv)
        inst = DB["installers"].get(inv["installer_id"])
        if inst:
            recompute_installer(inst)
        p = DB["projects"].get(inv["project_id"])
        if p:
            recompute_project(p)
            eval_payment_status(p)
    return ok_obj(pub(pay))


# ---------------------------------------------------------------------------
# RMA claims
# ---------------------------------------------------------------------------
@app.route("/solar-dist/rma-claims", methods=["POST"])
def create_rma():
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    b = body()
    installer_id = req_str(b, "installer_id")
    product_id = req_str(b, "product_id")
    allocation_id = req_str(b, "allocation_id")
    qty_claimed = req_int(b, "qty_claimed")
    find("installers", installer_id, "ERR_INSTALLER_NOT_FOUND")
    own_installer(uid, role, installer_id)
    find("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    find("allocations", allocation_id, "ERR_ALLOCATION_NOT_FOUND")
    r = new_entity()
    r.update({
        "installer_id": installer_id,
        "product_id": product_id,
        "allocation_id": allocation_id,
        "qty_claimed": qty_claimed,
        "qty_approved": None,
        "credit_amount_cents": None,
        "manufacturer_rma_number": None,
        "status": "DRAFT",
    })
    DB["rmas"][r["id"]] = r
    return ok_obj(pub(r), 201)


@app.route("/solar-dist/rma-claims", methods=["GET"])
def list_rmas():
    auth()
    items = list(DB["rmas"].values())
    args = request.args
    for f in ("installer_id", "product_id", "allocation_id", "status"):
        if f in args:
            items = [r for r in items if r[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/rma-claims/<rmaId>", methods=["GET"])
def get_rma(rmaId):
    auth()
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    return ok_obj(pub(r))


@app.route("/solar-dist/rma-claims/<rmaId>/submit", methods=["POST"])
def submit_rma(rmaId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    own_installer(uid, role, r["installer_id"])
    if r["status"] != "DRAFT":
        err("ERR_INVALID_REQUEST", 400, "RMA claim must be DRAFT to submit")
    b = body()
    mrma = opt_str(b, "manufacturer_rma_number")
    alloc = find("allocations", r["allocation_id"], "ERR_ALLOCATION_NOT_FOUND")
    if alloc["status"] != "SHIPPED":
        err("ERR_ALLOCATION_NOT_SHIPPED", 409, "Allocation must be SHIPPED for RMA")
    if r["qty_claimed"] <= 0 or r["qty_claimed"] > alloc["qty_allocated"]:
        err("ERR_INVALID_QTY_CLAIMED", 422,
            "qty_claimed must be > 0 and <= source allocation qty")
    r["status"] = "SUBMITTED"
    if mrma is not None:
        r["manufacturer_rma_number"] = mrma
    touch(r)
    return ok_obj(pub(r))


@app.route("/solar-dist/rma-claims/<rmaId>/approve", methods=["POST"])
def approve_rma(rmaId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    if r["status"] != "SUBMITTED":
        err("ERR_RMA_NOT_SUBMITTED", 409, "RMA must be SUBMITTED to approve")
    b = body()
    qty_approved = req_int(b, "qty_approved")
    mrma = opt_str(b, "manufacturer_rma_number")
    if qty_approved <= 0 or qty_approved > r["qty_claimed"]:
        err("ERR_INVALID_QTY_CLAIMED", 422,
            "qty_approved must be > 0 and <= qty_claimed")
    alloc = DB["allocations"].get(r["allocation_id"])
    r["qty_approved"] = qty_approved
    r["credit_amount_cents"] = qty_approved * alloc["unit_cost_cents_at_allocation"]
    if mrma is not None:
        r["manufacturer_rma_number"] = mrma
    r["status"] = "APPROVED"
    touch(r)
    return ok_obj(pub(r))


@app.route("/solar-dist/rma-claims/<rmaId>/reject", methods=["POST"])
def reject_rma(rmaId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    if r["status"] != "SUBMITTED":
        err("ERR_RMA_NOT_SUBMITTED", 409, "RMA must be SUBMITTED to reject")
    r["status"] = "REJECTED"
    touch(r)
    return ok_obj(pub(r))


@app.route("/solar-dist/rma-claims/<rmaId>/issue-credit", methods=["POST"])
def issue_credit_rma(rmaId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    if r["status"] != "APPROVED":
        err("ERR_RMA_NOT_APPROVED", 409, "RMA must be APPROVED to issue credit")
    inst = DB["installers"][r["installer_id"]]
    alloc = DB["allocations"].get(r["allocation_id"])
    project = DB["projects"].get(alloc["project_id"]) if alloc else None
    memo = create_invoice(project, inst, "CREDIT_MEMO", -r["credit_amount_cents"])
    # Apply credit against installer's open invoices, oldest first
    remaining = r["credit_amount_cents"]
    targets = [i for i in DB["invoices"].values()
               if i["installer_id"] == inst["id"]
               and i["id"] != memo["id"]
               and i["status"] in ("OPEN", "PARTIALLY_PAID", "PAST_DUE")
               and i["invoice_kind"] != "WRITE_OFF"
               and i["balance_due_cents"] > 0]
    targets.sort(key=lambda i: (i["invoice_date"], i["created_at"], i["_seq"]))
    for inv in targets:
        if remaining <= 0:
            break
        reduction = min(inv["balance_due_cents"], remaining)
        inv["balance_due_cents"] -= reduction
        memo["balance_due_cents"] += reduction
        remaining -= reduction
        if inv["balance_due_cents"] == 0:
            inv["status"] = "PAID"
        touch(inv)
    if memo["balance_due_cents"] == 0:
        memo["status"] = "PAID"
    touch(memo)
    r["status"] = "CREDIT_ISSUED"
    touch(r)
    recompute_installer(inst)
    if project is not None:
        recompute_project(project)
        eval_payment_status(project)
    return ok_obj(pub(memo))


@app.route("/solar-dist/rma-claims/<rmaId>/close", methods=["POST"])
def close_rma(rmaId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    r = find("rmas", rmaId, "ERR_RMA_NOT_FOUND")
    if r["status"] != "CREDIT_ISSUED":
        err("ERR_INVALID_REQUEST", 400, "RMA must be CREDIT_ISSUED to close")
    r["status"] = "CLOSED"
    touch(r)
    return ok_obj(pub(r))


# ---------------------------------------------------------------------------
# Permit packages
# ---------------------------------------------------------------------------
def package_project(pkg):
    return DB["projects"].get(pkg["project_id"])


@app.route("/solar-dist/projects/<projectId>/permit-packages", methods=["GET"])
def list_project_packages(projectId):
    auth()
    find("projects", projectId, "ERR_PROJECT_NOT_FOUND")
    items = [p for p in DB["packages"].values() if p["project_id"] == projectId]
    return paginate(items)


@app.route("/solar-dist/permit-packages/<packageId>", methods=["GET"])
def get_package(packageId):
    auth()
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages", methods=["GET"])
def list_packages():
    auth()
    items = list(DB["packages"].values())
    args = request.args
    for f in ("project_id", "status"):
        if f in args:
            items = [p for p in items if p[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/permit-packages/<packageId>/documents", methods=["POST"])
def upload_document(packageId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    proj = package_project(pkg)
    if proj is not None:
        own_installer(uid, role, proj["installer_id"])
    b = body()
    slug = req_str(b, "document_slug")
    if pkg["status"] != "ASSEMBLING":
        err("ERR_INVALID_REQUEST", 400,
            "Documents may only be uploaded while the package is ASSEMBLING")
    if slug not in pkg["submitted_documents"]:
        pkg["submitted_documents"].append(slug)
        touch(pkg)
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages/<packageId>/submit", methods=["POST"])
def submit_package(packageId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    proj = package_project(pkg)
    if proj is not None:
        own_installer(uid, role, proj["installer_id"])
    if pkg["status"] != "ASSEMBLING":
        err("ERR_INVALID_REQUEST", 400, "Package must be ASSEMBLING to submit")
    if proj is None or proj["design_locked_at"] is None:
        err("ERR_DESIGN_NOT_LOCKED", 409,
            "Design must be locked before permit submission")
    if not all(d in pkg["submitted_documents"] for d in pkg["required_documents"]):
        err("ERR_MISSING_REQUIRED_DOCS", 422,
            "Permit submission requires every document in required_documents")
    pkg["status"] = "SUBMITTED"
    pkg["submitted_at"] = iso(now())
    touch(pkg)
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages/<packageId>/approve", methods=["POST"])
def approve_package(packageId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    if pkg["status"] != "SUBMITTED":
        err("ERR_PACKAGE_NOT_SUBMITTED", 409, "PermitPackage must be SUBMITTED")
    pkg["status"] = "APPROVED"
    pkg["approved_at"] = iso(now())
    touch(pkg)
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages/<packageId>/reject", methods=["POST"])
def reject_package(packageId):
    _, role = auth()
    require_role(role, {"ChannelManager"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    if pkg["status"] != "SUBMITTED":
        err("ERR_PACKAGE_NOT_SUBMITTED", 409, "PermitPackage must be SUBMITTED")
    pkg["status"] = "REJECTED"
    touch(pkg)
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages/<packageId>/reassemble", methods=["POST"])
def reassemble_package(packageId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    proj = package_project(pkg)
    if proj is not None:
        own_installer(uid, role, proj["installer_id"])
    if pkg["status"] != "REJECTED":
        err("ERR_INVALID_REQUEST", 400, "Package must be REJECTED to reassemble")
    pkg["status"] = "ASSEMBLING"
    pkg["submitted_at"] = None
    touch(pkg)
    return ok_obj(pub(pkg))


@app.route("/solar-dist/permit-packages/<packageId>/withdraw", methods=["POST"])
def withdraw_package(packageId):
    uid, role = auth()
    require_role(role, {"InstallerRep"})
    pkg = find("packages", packageId, "ERR_PACKAGE_NOT_FOUND")
    proj = package_project(pkg)
    if proj is not None:
        own_installer(uid, role, proj["installer_id"])
    if pkg["status"] not in ("ASSEMBLING", "REJECTED"):
        err("ERR_INVALID_REQUEST", 400,
            "Package must be ASSEMBLING or REJECTED to withdraw")
    pkg["status"] = "WITHDRAWN"
    touch(pkg)
    return ok_obj(pub(pkg))


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------
@app.route("/solar-dist/containers/<containerId>/damage-claims", methods=["POST"])
def create_damage_claim(containerId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    c = find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    b = body()
    container_line_id = req_str(b, "container_line_id")
    qty_damaged = req_int(b, "qty_damaged")
    if qty_damaged <= 0:
        err("ERR_INVALID_REQUEST", 400, "qty_damaged must be > 0")
    line = DB["lines"].get(container_line_id)
    if line is None or line["container_id"] != c["id"]:
        err("ERR_LINE_NOT_FOUND", 404, f"ContainerLine {container_line_id} not found")
    cl = new_entity()
    cl.update({
        "container_id": c["id"],
        "container_line_id": container_line_id,
        "qty_damaged": qty_damaged,
        "claimed_amount_cents": None,
        "filed_at": None,
        "settled_at": None,
        "status": "DRAFT",
    })
    DB["claims"][cl["id"]] = cl
    return ok_obj(pub(cl), 201)


@app.route("/solar-dist/containers/<containerId>/damage-claims", methods=["GET"])
def list_container_claims(containerId):
    auth()
    find("containers", containerId, "ERR_CONTAINER_NOT_FOUND")
    items = [c for c in DB["claims"].values() if c["container_id"] == containerId]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    return paginate(items)


@app.route("/solar-dist/damage-claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    auth()
    cl = find("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    return ok_obj(pub(cl))


@app.route("/solar-dist/damage-claims", methods=["GET"])
def list_claims():
    auth()
    items = list(DB["claims"].values())
    args = request.args
    for f in ("container_id", "container_line_id", "status"):
        if f in args:
            items = [c for c in items if c[f] == args[f]]
    return paginate(items)


@app.route("/solar-dist/damage-claims/<claimId>/file", methods=["POST"])
def file_claim(claimId):
    _, role = auth()
    require_role(role, {"DistributionAdmin"})
    cl = find("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    if cl["status"] != "DRAFT":
        err("ERR_INVALID_REQUEST", 400, "DamageClaim must be DRAFT to file")
    c = DB["containers"].get(cl["container_id"])
    if c is None or c["status"] != "RECEIVED":
        err("ERR_CONTAINER_NOT_RECEIVED", 409,
            "Container must be RECEIVED to file a damage claim")
    line = DB["lines"].get(cl["container_line_id"])
    if line is None or cl["qty_damaged"] != line["qty_damaged"]:
        err("ERR_CLAIM_QTY_MISMATCH", 409,
            "DamageClaim.qty_damaged must equal container line qty_damaged")
    total_booked = sum(l["qty_booked"] for l in container_lines(c["id"]))
    freight_per_unit = rhu(c["freight_cost_cents"], total_booked) if total_booked else 0
    cl["claimed_amount_cents"] = cl["qty_damaged"] * (
        line["declared_unit_value_cents"] + freight_per_unit)
    cl["filed_at"] = iso(now())
    cl["status"] = "FILED"
    touch(cl)
    return ok_obj(pub(cl))


def _resolve_claim(cl, settled):
    line = DB["lines"].get(cl["container_line_id"])
    if line is not None:
        lot = DB["lots"].get(line["inventory_lot_id"])
        if lot is not None:
            lot["qty_quarantined"] -= cl["qty_damaged"]
            lot["qty_on_hand"] -= cl["qty_damaged"]
            touch(lot)
            maybe_depleted(lot)
    if settled:
        cl["status"] = "SETTLED"
        cl["settled_at"] = iso(now())
    else:
        cl["status"] = "DENIED"
    touch(cl)


@app.route("/solar-dist/damage-claims/<claimId>/settle", methods=["POST"])
def settle_claim(claimId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    cl = find("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    if cl["status"] != "FILED":
        err("ERR_CLAIM_NOT_FILED", 409, "DamageClaim must be FILED to settle")
    _resolve_claim(cl, True)
    return ok_obj(pub(cl))


@app.route("/solar-dist/damage-claims/<claimId>/deny", methods=["POST"])
def deny_claim(claimId):
    _, role = auth()
    require_role(role, {"CreditOfficer"})
    cl = find("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    if cl["status"] != "FILED":
        err("ERR_CLAIM_NOT_FILED", 409, "DamageClaim must be FILED to deny")
    _resolve_claim(cl, False)
    return ok_obj(pub(cl))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
