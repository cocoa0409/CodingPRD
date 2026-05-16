"""Insurer / Plan / PlanVariant routes."""

from flask import Blueprint, request, g

from db import db, stamp_created, bump_version
from errors import raise_error
from middleware import auth_required
from response import success_object, success_array
from services.constants import VALID_STATES, VALID_TIERS, VALID_CSR_LEVELS
from services.pagination import parse_pagination, paginate
from services.serializers import (
    serialize_insurer,
    serialize_plan,
    serialize_plan_variant,
)


bp = Blueprint("catalog", __name__)


# ---- POST /insurers ----

@bp.post("/insurers")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def create_insurer():
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    filing_states = body.get("filing_states")
    contact_phone = body.get("contact_phone")
    if not name or not isinstance(filing_states, list) or not contact_phone:
        raise_error("ERR_INVALID_STATE", "name, filing_states, contact_phone required")
    for s in filing_states:
        if s not in VALID_STATES:
            raise_error("ERR_INVALID_STATE", f"Invalid state code: {s}")

    insurer = {
        "name": name,
        "filing_states": list(filing_states),
        "contact_phone": contact_phone,
    }
    stamp_created(insurer, versioned=False)
    db.insurers[insurer["id"]] = insurer
    return success_object(serialize_insurer(insurer), status=201)


# ---- GET /insurers ----

@bp.get("/insurers")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService", "Insurer"})
def list_insurers():
    items = list(db.insurers.values())
    filing_state = request.args.get("filing_state")
    if filing_state:
        items = [i for i in items if filing_state in i["filing_states"]]
    items.sort(key=lambda x: x["created_at"])
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_array([serialize_insurer(i) for i in page], meta)


# ---- POST /plans ----

@bp.post("/plans")
@auth_required(allowed_roles={"Insurer", "MarketplaceAdmin"})
def create_plan():
    body = request.get_json(silent=True) or {}
    insurer_id = body.get("insurer_id")
    coverage_year = body.get("coverage_year")
    filing_state = body.get("filing_state")
    tier = body.get("tier")
    base_premium = body.get("base_monthly_premium_cents")
    is_benchmark_silver = bool(body.get("is_benchmark_silver", False))

    insurer = db.insurers.get(insurer_id)
    if insurer is None:
        raise_error("ERR_NOT_FOUND")
    if g.user_role == "Insurer" and insurer_id != g.user_id:
        raise_error("ERR_FORBIDDEN")
    if tier not in VALID_TIERS or filing_state not in VALID_STATES:
        raise_error("ERR_INVALID_STATE", "Invalid tier or filing_state")
    if not isinstance(coverage_year, int) or not isinstance(base_premium, int):
        raise_error("ERR_INVALID_STATE", "coverage_year and base_monthly_premium_cents must be ints")
    if filing_state not in insurer["filing_states"]:
        raise_error("ERR_INVALID_STATE", "filing_state not in insurer's filing_states")

    if is_benchmark_silver:
        if tier != "SILVER":
            raise_error("ERR_INVALID_STATE", "Only SILVER plans can be benchmark")
        for p in db.plans.values():
            if (
                p["filing_state"] == filing_state
                and p["coverage_year"] == coverage_year
                and p["is_benchmark_silver"]
                and p["status"] == "ACTIVE"
            ):
                raise_error("ERR_BENCHMARK_CONFLICT")

    plan = {
        "insurer_id": insurer_id,
        "coverage_year": coverage_year,
        "filing_state": filing_state,
        "tier": tier,
        "base_monthly_premium_cents": base_premium,
        "is_benchmark_silver": is_benchmark_silver,
        "status": "ACTIVE",
        "catalog_version": 1,
    }
    stamp_created(plan, versioned=True)
    db.plans[plan["id"]] = plan
    return success_object(serialize_plan(plan), status=201)


# ---- PATCH /plans/{id} ----

@bp.patch("/plans/<plan_id>")
@auth_required(allowed_roles={"Insurer", "MarketplaceAdmin"})
def patch_plan(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        raise_error("ERR_NOT_FOUND")
    if g.user_role == "Insurer" and plan["insurer_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN")

    body = request.get_json(silent=True) or {}

    # Validate benchmark conflict BEFORE OCC (priority 16 < 18)
    if "is_benchmark_silver" in body:
        new_flag = bool(body["is_benchmark_silver"])
        if new_flag and not plan["is_benchmark_silver"]:
            if plan["tier"] != "SILVER":
                raise_error("ERR_INVALID_STATE", "Only SILVER plans can be benchmark")
            for p in db.plans.values():
                if p["id"] == plan["id"]:
                    continue
                if (
                    p["filing_state"] == plan["filing_state"]
                    and p["coverage_year"] == plan["coverage_year"]
                    and p["is_benchmark_silver"]
                    and p["status"] == "ACTIVE"
                ):
                    raise_error("ERR_BENCHMARK_CONFLICT")

    # OCC check (priority 18)
    if "version" in body and body["version"] is not None:
        if body["version"] != plan["version"]:
            raise_error("ERR_STALE_VERSION")

    catalog_bump = False
    if "base_monthly_premium_cents" in body:
        if not isinstance(body["base_monthly_premium_cents"], int):
            raise_error("ERR_INVALID_STATE", "base_monthly_premium_cents must be int")
        plan["base_monthly_premium_cents"] = body["base_monthly_premium_cents"]
        catalog_bump = True

    if "status" in body:
        new_status = body["status"]
        if new_status not in ("ACTIVE", "WITHDRAWN"):
            raise_error("ERR_INVALID_STATE", "status must be ACTIVE or WITHDRAWN")
        if new_status != plan["status"]:
            plan["status"] = new_status
            catalog_bump = True

    if "is_benchmark_silver" in body:
        new_flag = bool(body["is_benchmark_silver"])
        if new_flag != plan["is_benchmark_silver"]:
            plan["is_benchmark_silver"] = new_flag

    if catalog_bump:
        plan["catalog_version"] = plan.get("catalog_version", 1) + 1
    bump_version(plan)
    return success_object(serialize_plan(plan))


# ---- GET /plans ----

@bp.get("/plans")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService", "Insurer"})
def list_plans():
    items = list(db.plans.values())
    filing_state = request.args.get("filing_state")
    coverage_year = request.args.get("coverage_year")
    tier = request.args.get("tier")
    status_f = request.args.get("status")
    if filing_state:
        items = [p for p in items if p["filing_state"] == filing_state]
    if coverage_year:
        try:
            cy = int(coverage_year)
            items = [p for p in items if p["coverage_year"] == cy]
        except ValueError:
            pass
    if tier:
        items = [p for p in items if p["tier"] == tier]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    items.sort(key=lambda p: p["created_at"])
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_array([serialize_plan(p) for p in page], meta)


# ---- POST /plans/{id}/variants ----

@bp.post("/plans/<plan_id>/variants")
@auth_required(allowed_roles={"Insurer", "MarketplaceAdmin"})
def add_plan_variant(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        raise_error("ERR_NOT_FOUND")
    if g.user_role == "Insurer" and plan["insurer_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN")
    if plan["tier"] != "SILVER":
        raise_error("ERR_INVALID_STATE", "Only SILVER plans can carry CSR variants")

    body = request.get_json(silent=True) or {}
    csr_level = body.get("csr_level")
    actuarial_value = body.get("actuarial_value")
    out_of_pocket_max_cents = body.get("out_of_pocket_max_cents")
    if csr_level not in VALID_CSR_LEVELS:
        raise_error("ERR_INVALID_STATE", "Invalid csr_level")
    if not isinstance(out_of_pocket_max_cents, int):
        raise_error("ERR_INVALID_STATE", "out_of_pocket_max_cents must be int")

    variant = {
        "plan_id": plan_id,
        "csr_level": csr_level,
        "actuarial_value": actuarial_value,
        "out_of_pocket_max_cents": out_of_pocket_max_cents,
    }
    stamp_created(variant, versioned=False)
    db.plan_variants[variant["id"]] = variant
    return success_object(serialize_plan_variant(variant), status=201)
