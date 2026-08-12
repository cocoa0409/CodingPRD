"""Benefit plan + plan tier endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import (err, ERR_PLAN_NOT_FOUND, ERR_EMPLOYER_NOT_FOUND,
                    ERR_PLAN_NOT_DRAFT, ERR_PLAN_NOT_ACTIVE,
                    ERR_STALE_VERSION, ERR_DUPLICATE_TIER_CODE, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success, paginate
from services.core import new_entity, touch, serialize, sort_created, tiers_of_plan
from util import (body_json, req, opt, as_str, as_int, as_num, as_list,
                  check_enum, parse_dt)

bp = Blueprint("plans", __name__)

TIER_CODES = ("INDIVIDUAL", "COUPLE", "FAMILY")


def get_plan(pid):
    p = STORE.plans.get(pid)
    if p is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan id does not resolve")
    return p


def plan_json(p):
    return serialize(p)


@bp.post("/api/benefit-plans")
def create_plan():
    require_roles("BenefitsAdmin")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    name = as_str(req(body, "name"), "name")
    benefit_year = as_int(req(body, "benefit_year"), "benefit_year")
    period_start_raw = req(body, "period_start")
    period_end_raw = req(body, "period_end")
    if employer_id not in STORE.employers:
        raise err(ERR_EMPLOYER_NOT_FOUND, 404, "employer id does not resolve")
    ps = parse_dt(period_start_raw)
    pe = parse_dt(period_end_raw)
    if pe <= ps:
        from errors import ERR_INVALID_DATE_RANGE
        raise err(ERR_INVALID_DATE_RANGE, 400, "period_end must be strictly after period_start")
    p = new_entity()
    p.update({
        "employer_id": employer_id,
        "name": name,
        "benefit_year": benefit_year,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "status": "DRAFT",
        "_ps": ps, "_pe": pe,
    })
    STORE.plans[p["id"]] = p
    return success(plan_json(p), 201)


@bp.get("/api/benefit-plans/<pid>")
def read_plan(pid):
    require_roles("BenefitsAdmin", "Auditor")
    return success(plan_json(get_plan(pid)))


@bp.get("/api/benefit-plans")
def list_plans():
    require_roles("BenefitsAdmin", "Auditor")
    items = sort_created(STORE.plans.values())
    employer_id = request.args.get("employer_id")
    status = request.args.get("status")
    if employer_id is not None:
        items = [p for p in items if p["employer_id"] == employer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([plan_json(p) for p in items])


@bp.post("/api/benefit-plans/<pid>/activate")
def activate_plan(pid):
    require_roles("BenefitsAdmin")
    p = get_plan(pid)
    if p["status"] != "DRAFT":
        raise err(ERR_PLAN_NOT_DRAFT, 409, "activate requires plan DRAFT")
    if len(tiers_of_plan(pid)) < 1:
        raise err(ERR_INVALID_REQUEST, 409, "plan requires at least one tier to activate")
    p["status"] = "ACTIVE"
    touch(p)
    return success(plan_json(p))


@bp.post("/api/benefit-plans/<pid>/retire")
def retire_plan(pid):
    require_roles("BenefitsAdmin")
    p = get_plan(pid)
    if p["status"] != "ACTIVE":
        raise err(ERR_PLAN_NOT_ACTIVE, 409, "retire requires plan ACTIVE")
    p["status"] = "RETIRED"
    touch(p)
    return success(plan_json(p))


TIER_INT_FIELDS = ("annual_allowance_cents", "quarterly_cap_cents",
                   "per_claim_cap_cents", "visit_frequency_cap")
TIER_NUM_FIELDS = ("dependent_cap_pct", "in_network_pct", "preferred_pct",
                   "out_of_network_pct")


@bp.put("/api/benefit-plans/<pid>/tiers")
def replace_tiers(pid):
    require_roles("BenefitsAdmin")
    p = get_plan(pid)
    body = body_json()
    tiers = as_list(req(body, "tiers"), "tiers")
    expected = as_int(req(body, "expected_plan_version"), "expected_plan_version")
    # shape validation of each tier item
    parsed = []
    for item in tiers:
        if not isinstance(item, dict):
            raise err(ERR_INVALID_REQUEST, 400, "each tier must be an object")
        t = {"tier_code": check_enum(req(item, "tier_code"), TIER_CODES, "tier_code")}
        for f in TIER_INT_FIELDS:
            t[f] = as_int(req(item, f), f)
        for f in TIER_NUM_FIELDS:
            t[f] = as_num(req(item, f), f)
        parsed.append(t)
    # state: replacement permitted while DRAFT or ACTIVE
    if p["status"] not in ("DRAFT", "ACTIVE"):
        raise err(ERR_PLAN_NOT_ACTIVE, 409, "tier replacement requires plan DRAFT or ACTIVE")
    # OCC staleness
    if expected != p["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_plan_version does not match current version")
    # business: duplicate tier codes rejected
    seen = set()
    for t in parsed:
        if t["tier_code"] in seen:
            raise err(ERR_DUPLICATE_TIER_CODE, 400, "tiers payload repeats a tier_code")
        seen.add(t["tier_code"])
    # superseding amendment: delete existing tier rows, insert new ones
    for tid in [t["id"] for t in STORE.tiers.values() if t["plan_id"] == pid]:
        del STORE.tiers[tid]
    for t in parsed:
        row = new_entity(with_version=False)
        row.update({"plan_id": pid})
        row.update(t)
        STORE.tiers[row["id"]] = row
    touch(p)
    return success(plan_json(p))


@bp.get("/api/benefit-plans/<pid>/tiers")
def list_tiers(pid):
    require_roles("BenefitsAdmin", "Auditor", "Member")
    get_plan(pid)
    return paginate([serialize(t) for t in tiers_of_plan(pid)])
