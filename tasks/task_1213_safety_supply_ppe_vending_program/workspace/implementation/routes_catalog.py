"""Catalog routes: cost centers, job roles, items, contract prices, policies."""
from flask import Blueprint

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (body, get_or_404, opt_int, opt_str, paged,
                     pagination_params, qparam, req_date, req_int, req_str)
from util import new_record, parse_date, touch

bp = Blueprint("catalog", __name__)

ITEM_CATEGORIES = {"GENERAL", "RESPIRATOR", "FALL_PROTECTION"}


# --- CostCenter ------------------------------------------------------------

@bp.post("/cost-centers")
def create_cost_center():
    require_roles("FinanceAnalyst")
    b = body()
    code = req_str(b, "cost_center_code")
    name = req_str(b, "name")
    rec = new_record({
        "cost_center_code": code,
        "name": name,
        "ytd_charged_cents": 0,
    })
    db.cost_centers[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/cost-centers/<costCenterId>")
def get_cost_center(costCenterId):
    require_roles("Any")
    return ok(get_or_404(db.cost_centers, costCenterId, "ERR_COST_CENTER_NOT_FOUND"))


# --- JobRole ---------------------------------------------------------------

@bp.post("/job-roles")
def create_job_role():
    require_roles("EHSAdministrator")
    b = body()
    role_name = req_str(b, "role_name")
    description = opt_str(b, "description")
    rec = new_record({
        "role_name": role_name,
        "description": description if description is not None else "",
    })
    db.job_roles[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/job-roles/<jobRoleId>")
def get_job_role(jobRoleId):
    require_roles("Any")
    return ok(get_or_404(db.job_roles, jobRoleId, "ERR_JOB_ROLE_NOT_FOUND"))


# --- Item ------------------------------------------------------------------

@bp.post("/items")
def create_item():
    require_roles("EHSAdministrator")
    b = body()
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    category = req_str(b, "category")
    if category not in ITEM_CATEGORIES:
        err("ERR_VALIDATION_FAILED", "invalid category")
    base_price = req_int(b, "base_list_price_cents", minimum=0)
    interval = opt_int(b, "inspection_interval_days")
    if category == "FALL_PROTECTION":
        if interval is None or interval <= 0:
            err("ERR_VALIDATION_FAILED",
                "inspection_interval_days required (> 0) for FALL_PROTECTION")
    else:
        interval = None  # stays null for non-fall-protection categories
    if any(i["sku"] == sku for i in db.items.values()):
        err("ERR_DUPLICATE_SKU", "sku already exists")
    rec = new_record({
        "sku": sku,
        "name": name,
        "category": category,
        "requires_fit_test": category == "RESPIRATOR",
        "serialized_tracking": category == "FALL_PROTECTION",
        "inspection_interval_days": interval,
        "base_list_price_cents": base_price,
        "status": "ACTIVE",
    })
    db.items[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/items/<itemId>")
def get_item(itemId):
    require_roles("Any")
    return ok(get_or_404(db.items, itemId, "ERR_ITEM_NOT_FOUND"))


@bp.post("/items/<itemId>/discontinue")
def discontinue_item(itemId):
    require_roles("EHSAdministrator")
    body()
    item = get_or_404(db.items, itemId, "ERR_ITEM_NOT_FOUND")
    if item["status"] != "ACTIVE":
        err("ERR_ITEM_DISCONTINUED", "item is not ACTIVE")
    item["status"] = "DISCONTINUED"
    touch(item)
    return ok(item)


# --- ContractPrice ---------------------------------------------------------

@bp.post("/contract-prices")
def create_contract_price():
    require_roles("EHSAdministrator")
    b = body()
    item_id = req_str(b, "item_id")
    min_qty = req_int(b, "min_period_qty", minimum=0)
    price = req_int(b, "unit_price_cents", minimum=0)
    eff_from = req_date(b, "effective_from")
    eff_to = req_date(b, "effective_to")
    if parse_date(eff_to) < parse_date(eff_from):
        err("ERR_VALIDATION_FAILED", "effective_to must be >= effective_from")
    get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    nf, nt = parse_date(eff_from), parse_date(eff_to)
    for p in db.contract_prices.values():
        # overlap is policed per tier breakpoint: rows with a different
        # min_period_qty may share a window (tiered pricing requires it).
        if p["item_id"] != item_id or p["min_period_qty"] != min_qty:
            continue
        # closed-interval intersection
        if nf <= parse_date(p["effective_to"]) and nt >= parse_date(p["effective_from"]):
            err("ERR_CONTRACT_PRICE_WINDOW_CONFLICT",
                "window overlaps an existing contract price for this item")
    rec = new_record({
        "item_id": item_id,
        "min_period_qty": min_qty,
        "unit_price_cents": price,
        "effective_from": eff_from,
        "effective_to": eff_to,
    })
    db.contract_prices[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/contract-prices")
def list_contract_prices():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.contract_prices.values())
    item_id = qparam("item_id")
    if item_id is not None:
        rows = [p for p in rows if p["item_id"] == item_id]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/contract-prices/<priceId>")
def get_contract_price(priceId):
    require_roles("Any")
    return ok(get_or_404(db.contract_prices, priceId, "ERR_CONTRACT_PRICE_NOT_FOUND"))


# --- IssuancePolicy --------------------------------------------------------

@bp.post("/issuance-policies")
def create_policy():
    require_roles("EHSAdministrator")
    b = body()
    job_role_id = req_str(b, "job_role_id")
    item_id = req_str(b, "item_id")
    limit_qty = req_int(b, "period_limit_qty", minimum=0)
    window_days = req_int(b, "period_window_days", minimum=0)
    get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    get_or_404(db.job_roles, job_role_id, "ERR_JOB_ROLE_NOT_FOUND")
    if any(p["job_role_id"] == job_role_id and p["item_id"] == item_id
           for p in db.issuance_policies.values()):
        err("ERR_DUPLICATE_POLICY", "policy already exists for (job_role_id, item_id)")
    rec = new_record({
        "job_role_id": job_role_id,
        "item_id": item_id,
        "period_limit_qty": limit_qty,
        "period_window_days": window_days,
    })
    db.issuance_policies[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/issuance-policies")
def list_policies():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.issuance_policies.values())
    jr = qparam("job_role_id")
    it = qparam("item_id")
    if jr is not None:
        rows = [p for p in rows if p["job_role_id"] == jr]
    if it is not None:
        rows = [p for p in rows if p["item_id"] == it]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/issuance-policies/<policyId>")
def get_policy(policyId):
    require_roles("Any")
    return ok(get_or_404(db.issuance_policies, policyId, "ERR_NOT_FOUND"))
