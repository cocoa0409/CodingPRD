"""Registry routes: logical clock, customers, fields, products, compatibility rules."""

from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_nonempty_str, req_int, req_pos_int,
                  req_num, req_nonneg_num, req_pos_num, req_dt, req_enum, opt_str,
                  ok, paginate, iso, validation_error, not_found, forbidden, conflict)
from domain import (new_mutable, new_evidence, serialize, CATEGORIES, VERDICTS)

bp = Blueprint("registry", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Logical clock (test-driving; CoopAdmin only)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("CoopAdmin")
    body = get_body()
    store.clock = req_dt(body, "to_iso8601")
    return ok({"current_utc": iso(store.clock)})


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    require_roles("CoopAdmin")
    body = get_body()
    name = req_nonempty_str(body, "name")
    billing_email = req_nonempty_str(body, "billing_email")
    rate = req_int(body, "rate_per_acre_cents", minimum=0)
    credit = req_int(body, "credit_limit_cents", minimum=0)
    c = new_mutable({
        "name": name,
        "billing_email": billing_email,
        "rate_per_acre_cents": rate,
        "credit_limit_cents": credit,
        "outstanding_cents": 0,
    })
    store.customers[c["id"]] = c
    return ok(serialize("customer", c), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    uid, role = require_roles("CoopAdmin", "Dispatcher", "ComplianceOfficer", "Grower")
    if role == "Grower" and cid != uid:
        raise forbidden("a Grower may read only their own customer record")
    c = store.customers.get(cid)
    if c is None:
        raise not_found("customer not found")
    return ok(serialize("customer", c))


@bp.get("/customers")
def list_customers():
    require_roles("CoopAdmin", "Dispatcher", "ComplianceOfficer")
    items = sorted(store.customers.values(), key=lambda c: (c["created_at"], c["_seq"]))
    return paginate([serialize("customer", c) for c in items])


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

@bp.post("/fields")
def create_field():
    uid, role = require_roles("Grower", "CoopAdmin")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    label = req_nonempty_str(body, "label")
    crop = req_nonempty_str(body, "crop")
    acres = req_pos_num(body, "acres")
    clearance = req_int(body, "buffer_clearance_ft", minimum=0)
    if role == "Grower" and customer_id != uid:
        raise forbidden("a Grower may create fields only for their own customer_id")
    if customer_id not in store.customers:
        raise not_found("customer not found")
    f = new_mutable({
        "customer_id": customer_id,
        "label": label,
        "crop": crop,
        "acres": acres,
        "buffer_clearance_ft": clearance,
        "rei_until": None,
    })
    store.fields[f["id"]] = f
    return ok(serialize("field", f), 201)


@bp.get("/fields/<fid>")
def get_field(fid):
    require_roles("Grower", "Agronomist", "Dispatcher", "Applicator",
                  "ComplianceOfficer", "CoopAdmin")
    f = store.fields.get(fid)
    if f is None:
        raise not_found("field not found")
    return ok(serialize("field", f))


@bp.get("/fields")
def list_fields():
    require_roles("Grower", "Agronomist", "Dispatcher", "Applicator",
                  "ComplianceOfficer", "CoopAdmin")
    items = sorted(store.fields.values(), key=lambda f: (f["created_at"], f["_seq"]))
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [f for f in items if f["customer_id"] == cid]
    return paginate([serialize("field", f) for f in items])


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@bp.post("/products")
def create_product():
    require_roles("CoopAdmin")
    body = get_body()
    p = new_mutable({
        "name": req_nonempty_str(body, "name"),
        "epa_registration_no": req_nonempty_str(body, "epa_registration_no"),
        "category": req_enum(body, "category", CATEGORIES),
        "rei_hours": req_int(body, "rei_hours", minimum=0),
        "max_wind_mph": req_nonneg_num(body, "max_wind_mph"),
        "min_temp_f": req_num(body, "min_temp_f"),
        "max_temp_f": req_num(body, "max_temp_f"),
        "required_buffer_ft": req_int(body, "required_buffer_ft", minimum=0),
        "unit_cost_cents": req_int(body, "unit_cost_cents", minimum=0),
        "markup_pct": req_nonneg_num(body, "markup_pct"),
    })
    store.products[p["id"]] = p
    return ok(serialize("product", p), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    require_roles("Grower", "Agronomist", "Dispatcher", "Applicator",
                  "ComplianceOfficer", "CoopAdmin")
    p = store.products.get(pid)
    if p is None:
        raise not_found("product not found")
    return ok(serialize("product", p))


# ---------------------------------------------------------------------------
# Compatibility rules (unordered pair; at most one rule per pair)
# ---------------------------------------------------------------------------

@bp.post("/compatibility-rules")
def create_compatibility_rule():
    require_roles("CoopAdmin")
    body = get_body()
    a = req_str(body, "product_a_id")
    b = req_str(body, "product_b_id")
    verdict = req_enum(body, "verdict", VERDICTS)
    note = opt_str(body, "note")
    if a == b:
        raise validation_error("product_a_id and product_b_id must differ")
    if a not in store.products:
        raise not_found("product_a_id does not exist")
    if b not in store.products:
        raise not_found("product_b_id does not exist")
    for r in store.compatibility_rules.values():
        if {r["product_a_id"], r["product_b_id"]} == {a, b}:
            raise validation_error("a compatibility rule already exists for this product pair")
    rule = new_evidence({
        "product_a_id": a,
        "product_b_id": b,
        "verdict": verdict,
        "note": note,
    })
    store.compatibility_rules[rule["id"]] = rule
    return ok(serialize("compatibility_rule", rule), 201)


@bp.get("/compatibility-rules/<rid>")
def get_compatibility_rule(rid):
    require_roles("Agronomist", "Dispatcher", "CoopAdmin")
    r = store.compatibility_rules.get(rid)
    if r is None:
        raise not_found("compatibility rule not found")
    return ok(serialize("compatibility_rule", r))


@bp.get("/compatibility-rules")
def list_compatibility_rules():
    require_roles("Agronomist", "Dispatcher", "CoopAdmin")
    items = sorted(store.compatibility_rules.values(),
                   key=lambda r: (r["created_at"], r["_seq"]))
    pa = request.args.get("product_a_id")
    pb = request.args.get("product_b_id")
    if pa is not None:
        items = [r for r in items if r["product_a_id"] == pa]
    if pb is not None:
        items = [r for r in items if r["product_b_id"] == pb]
    return paginate([serialize("compatibility_rule", r) for r in items])
