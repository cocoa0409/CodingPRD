"""RatePlan: the ingestion channel for one supplier into one market (PRD 3.4)."""
from flask import Blueprint

import auth
import cascade
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("rate_plans", __name__)

POLICIES = ("FLEX", "MODERATE", "STRICT", "NON_REF")
STATUSES = ("ACTIVE", "PARITY_HOLD", "ARCHIVED")
PARITY_TERMINAL = ("RESOLVED_COMPLIANT", "WAIVED")


@bp.post("/suppliers/<supplier_id>/rate-plans")
def create_rate_plan(supplier_id):
    actor = auth.authenticate(("SupplierUser", "CommercialManager"))
    auth.require_supplier_scope(actor, supplier_id)
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    raw_market = data.get("market_id")
    if isinstance(raw_market, str) and raw_market:
        common.find("markets", raw_market)
    market_id = validate.str_req(data, "market_id")
    name = validate.str_req(data, "name")
    currency = validate.str_req(data, "currency")
    policy = validate.enum_req(data, "cancellation_policy_code", POLICIES)
    cutoff = validate.int_req(data, "free_cancel_cutoff_hours", 0, 720)
    tax_fee_pct = validate.num_req(data, "tax_fee_pct", 0, 0.5)
    monitored = validate.bool_opt(data, "parity_monitored", True)
    common.guard_offboarded(supplier)
    plan = store.new_row("rate_plans", {
        "supplier_id": supplier["id"],
        "market_id": market_id,
        "name": name,
        "currency": currency,
        "cancellation_policy_code": policy,
        "free_cancel_cutoff_hours": cutoff,
        "tax_fee_pct": tax_fee_pct,
        "parity_monitored": monitored,
        "status": "ACTIVE",
        "parity_hold_case_id": None,
    })
    return response.obj(plan, 201)


@bp.get("/rate-plans/<plan_id>")
def read_rate_plan(plan_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("rate_plans", plan_id), 200)


@bp.get("/rate-plans")
def list_rate_plans():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    market_id = validate.filter_str("market_id")
    status = validate.filter_enum("status", STATUSES)
    rows = []
    for row in db["rate_plans"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if market_id is not None and row["market_id"] != market_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/rate-plans/<plan_id>/release-parity-hold")
def release_hold(plan_id):
    auth.authenticate(("ParityAnalyst", "ComplianceOfficer"))
    plan = common.find("rate_plans", plan_id)
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(plan))
    case = db["parity_cases"].get(plan.get("parity_hold_case_id"))
    if plan["status"] != "PARITY_HOLD" or case is None or case["status"] not in PARITY_TERMINAL:
        raise ApiError("ERR_RATE_PLAN_NOT_ON_HOLD")
    plan["status"] = "ACTIVE"
    plan["parity_hold_case_id"] = None
    touch(plan)
    return response.obj(plan, 200)


@bp.post("/rate-plans/<plan_id>/archive")
def archive(plan_id):
    auth.authenticate(("CommercialManager",))
    plan = common.find("rate_plans", plan_id)
    data = validate.body()
    validate.str_opt(data, "note")
    common.guard_offboarded(common.plan_supplier(plan))
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_RATE_PLAN_NOT_ON_HOLD",
                       "Only an ACTIVE rate plan can be archived.")
    if cascade.offers_of_plan(plan["id"], ("LIVE",)):
        raise ApiError("ERR_OFFER_NOT_LIVE",
                       "A plan with LIVE offers cannot be archived.")
    plan["status"] = "ARCHIVED"
    touch(plan)
    for offer in cascade.offers_of_plan(plan["id"], ("PENDING",)):
        offer["status"] = "CLOSED"
        touch(offer)
    return response.obj(plan, 200)
