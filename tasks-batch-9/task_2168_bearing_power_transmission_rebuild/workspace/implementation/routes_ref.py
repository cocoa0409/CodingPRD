"""Customers, assets, clearance standards, benches, credit notes, logical clock."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
import store
import validate as v
import views
from auth import ALL_ROLES, authenticate, require_roles
from errors import fail
from response import created, listing, ok

bp = Blueprint("ref", __name__)

CRITICALITY = {"CRITICAL", "STANDARD"}
DUTY_CLASS = {"CONTINUOUS", "INTERMITTENT", "STANDBY"}


def _path_customer(cid):
    rec = store.get("customers", cid)
    if rec is None:
        fail("ERR_CUSTOMER_NOT_FOUND", "Customer %s not found" % cid)
    return rec


def _path_asset(aid):
    rec = store.get("assets", aid)
    if rec is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s not found" % aid)
    return rec


def _path_bench(bid):
    rec = store.get("benches", bid)
    if rec is None:
        fail("ERR_BENCH_NOT_FOUND", "Bench %s not found" % bid)
    return rec


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.post("/shop/customers")
def create_customer():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    name = v.req_str(body, "name")
    account_code = v.req_str(body, "account_code")
    if not (1 <= len(account_code) <= 32):
        fail("ERR_INVALID_REQUEST", "account_code must be 1-32 characters")
    contact_email = v.opt_str(body, "contact_email", None)

    for row in store.all_rows("customers"):
        if row["account_code"] == account_code:
            fail("ERR_DUPLICATE_KEY", "account_code already in use")

    rec = store.base_record()
    rec.update({
        "name": name,
        "account_code": account_code,
        "contact_email": contact_email,
        "core_credit_balance_cents": 0,
        "warranty_credit_balance_cents": 0,
        "manual_credit_balance_cents": 0,
        "total_credit_balance_cents": 0,
    })
    store.insert("customers", rec)
    return created(views.render("customers", rec))


@bp.get("/shop/customers/<cid>")
def read_customer(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = _path_customer(cid)
    views.require_owner(role, uid, "customers", rec)
    return ok(views.render("customers", rec))


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
@bp.post("/shop/customers/<cid>/assets")
def create_asset(cid):
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    customer = _path_customer(cid)
    body = v.body()
    asset_tag = v.req_str(body, "asset_tag")
    criticality = v.req_enum(body, "criticality", CRITICALITY)
    duty_class = v.req_enum(body, "duty_class", DUTY_CLASS)
    site_code = v.opt_str(body, "site_code", "MAIN")

    for row in store.all_rows("assets"):
        if row["customer_id"] == customer["id"] and row["asset_tag"] == asset_tag:
            fail("ERR_DUPLICATE_KEY", "asset_tag already registered for this account")

    rec = store.base_record()
    rec.update({
        "customer_id": customer["id"],
        "asset_tag": asset_tag,
        "criticality": criticality,
        "duty_class": duty_class,
        "site_code": site_code,
    })
    store.insert("assets", rec)
    return created(views.render("assets", rec))


@bp.get("/shop/customers/<cid>/assets")
def list_assets(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    customer = _path_customer(cid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "customers", customer)
    rows = [a for a in store.all_rows("assets") if a["customer_id"] == customer["id"]]
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("assets", page), limit, offset, total)


@bp.get("/shop/assets/<aid>")
def read_asset(aid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = _path_asset(aid)
    views.require_owner(role, uid, "assets", rec)
    return ok(views.render("assets", rec))


# ---------------------------------------------------------------------------
# Manual credit notes
# ---------------------------------------------------------------------------
@bp.post("/shop/customers/<cid>/credit-notes")
def create_credit_note(cid):
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    customer = _path_customer(cid)
    body = v.body()
    amount = v.req_int(body, "amount_cents", minimum=0)
    memo = v.req_str(body, "memo")
    expected = v.req_int(body, "expected_customer_version")

    if expected != customer["version"]:
        fail("ERR_STALE_VERSION", "expected_customer_version does not match")

    projected = int(customer["total_credit_balance_cents"]) + amount
    if projected > calc.CUSTOMER_CREDIT_CEILING_CENTS:
        fail("ERR_CREDIT_CAP_EXCEEDED", "manual adjustment exceeds the account credit ceiling")

    note = ledger.post_note(customer["id"], "MANUAL_ADJUSTMENT", amount, memo=memo)
    ledger.settle(customer, reprice=False)
    return created(views.render("credit_notes", note))


# ---------------------------------------------------------------------------
# Clearance standards
# ---------------------------------------------------------------------------
def _parse_bands(body):
    bands = body.get("feature_bands")
    if not isinstance(bands, list) or not bands:
        fail("ERR_INVALID_REQUEST", "feature_bands must be a non-empty array")
    parsed = []
    seen = set()
    for raw in bands:
        if not isinstance(raw, dict):
            fail("ERR_INVALID_REQUEST", "each feature band must be an object")
        code = v.req_str(raw, "feature_code")
        if code in seen:
            fail("ERR_INVALID_REQUEST", "feature_code repeated in feature_bands")
        seen.add(code)
        min_um = v.req_int(raw, "min_um")
        max_um = v.req_int(raw, "max_um")
        if max_um <= min_um:
            fail("ERR_INVALID_REQUEST", "max_um must be strictly greater than min_um")
        ext = v.opt_int(raw, "rework_extension_um", 0, minimum=0)
        pct = v.opt_num(raw, "deduction_pct", Decimal(0), minimum=0)
        if pct > Decimal(1):
            fail("ERR_INVALID_REQUEST", "deduction_pct must be between 0 and 1")
        weight = v.opt_num(raw, "weight", Decimal(1), exclusive_min=0)
        parsed.append({
            "feature_code": code,
            "min_um": min_um,
            "max_um": max_um,
            "rework_extension_um": ext,
            "deduction_pct": pct,
            "weight": weight,
        })
    return parsed


@bp.post("/shop/clearance-standards")
def create_standard():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    model_code = v.req_str(body, "model_code")
    base_value = v.req_int(body, "base_core_value_cents", minimum=0)
    max_rebuild = v.req_int(body, "max_rebuild_count", minimum=0)
    warranty_hours = v.req_int(body, "warranty_hours", minimum=1)
    warranty_months = v.req_int(body, "warranty_months", minimum=1)
    cleanroom_required = v.opt_bool(body, "cleanroom_required", False)

    required_codes = body.get("required_feature_codes")
    if not isinstance(required_codes, list) or not required_codes:
        fail("ERR_INVALID_REQUEST", "required_feature_codes must be a non-empty array")
    for code in required_codes:
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST", "required_feature_codes entries must be strings")

    bands = _parse_bands(body)
    band_codes = {b["feature_code"] for b in bands}
    for code in required_codes:
        if code not in band_codes:
            fail("ERR_INVALID_REQUEST",
                 "required_feature_code %s absent from feature_bands" % code)

    for row in store.all_rows("standards"):
        if row["model_code"] == model_code:
            fail("ERR_DUPLICATE_KEY", "model_code already published")

    rec = store.base_record()
    rec.update({
        "model_code": model_code,
        "base_core_value_cents": base_value,
        "max_rebuild_count": max_rebuild,
        "warranty_hours": warranty_hours,
        "warranty_months": warranty_months,
        "cleanroom_required": cleanroom_required,
        "required_feature_codes": list(required_codes),
        "feature_bands": bands,
    })
    store.insert("standards", rec)
    return created(views.render("standards", rec))


@bp.get("/shop/clearance-standards/<sid>")
def read_standard(sid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = store.get("standards", sid)
    if rec is None:
        fail("ERR_STANDARD_NOT_FOUND", "Clearance standard %s not found" % sid)
    return ok(views.render("standards", rec))


# ---------------------------------------------------------------------------
# Benches
# ---------------------------------------------------------------------------
@bp.post("/shop/benches")
def create_bench():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    bench_code = v.req_str(body, "bench_code")
    parallel_slots = v.req_int(body, "parallel_slots", minimum=1)
    cleanroom = v.opt_bool(body, "cleanroom", False)

    for row in store.all_rows("benches"):
        if row["bench_code"] == bench_code:
            fail("ERR_DUPLICATE_KEY", "bench_code already registered")

    rec = store.base_record()
    rec.update({
        "bench_code": bench_code,
        "parallel_slots": parallel_slots,
        "cleanroom": cleanroom,
        "committed_minutes": 0,
    })
    store.insert("benches", rec)
    return created(views.render("benches", rec))


@bp.get("/shop/benches/<bid>")
def read_bench(bid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = _path_bench(bid)
    return ok(views.render("benches", rec))


@bp.get("/shop/benches/<bid>/reservations")
def list_bench_reservations(bid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    bench = _path_bench(bid)
    limit, offset = v.pagination()
    rows = [r for r in store.all_rows("reservations") if r["bench_id"] == bench["id"]]
    status = v.qparam("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = views.scope_rows(role, uid, "reservations", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("reservations", page), limit, offset, total)


# ---------------------------------------------------------------------------
# Credit notes
# ---------------------------------------------------------------------------
@bp.get("/shop/credit-notes/<nid>")
def read_note(nid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = store.get("credit_notes", nid)
    if rec is None:
        fail("ERR_CREDIT_NOTE_NOT_FOUND", "Credit note %s not found" % nid)
    views.require_owner(role, uid, "credit_notes", rec)
    return ok(views.render("credit_notes", rec))


@bp.get("/shop/credit-notes")
def list_notes():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = v.pagination()
    rows = store.all_rows("credit_notes")
    for key in ("customer_id", "core_unit_id", "warranty_claim_id", "kind", "status"):
        value = v.qparam(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows = views.scope_rows(role, uid, "credit_notes", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("credit_notes", page), limit, offset, total)


@bp.post("/shop/credit-notes/<nid>/void")
def void_note(nid):
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    rec = store.get("credit_notes", nid)
    if rec is None:
        fail("ERR_CREDIT_NOTE_NOT_FOUND", "Credit note %s not found" % nid)
    body = v.body()
    reason = v.req_str(body, "void_reason")
    if rec["status"] != "POSTED":
        fail("ERR_CREDIT_NOTE_INVALID_STATE", "note is not POSTED")
    ledger.void_note(rec, reason)
    ledger.settle(store.get("customers", rec["customer_id"]), reprice=True)
    return ok(views.render("credit_notes", rec))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    parsed = v.req_ts(body, "to_iso8601")
    store.set_logical(parsed)
    return ok({"current_utc": body["to_iso8601"]})
