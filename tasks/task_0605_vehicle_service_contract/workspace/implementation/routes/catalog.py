"""Coverage plans, reinsurance pools, repair facilities."""
from flask import Blueprint, request, g

from db import db
from errors import err
from middleware import require_roles
from response import ok, created, listing
import common as c

bp = Blueprint("catalog", __name__)


# ===========================================================================
# Coverage Plans
# ===========================================================================
@bp.route("/coverage-plans", methods=["POST"])
@require_roles("AdminUnderwriter")
def create_plan():
    body = c.require_body(request.get_json(silent=True))
    name = c.req_field(body, "name", "str")
    tier = c.req_field(body, "tier", "str")
    term_months = c.req_field(body, "term_months", "int")
    term_miles = c.req_field(body, "term_miles", "int")
    max_age = c.req_field(body, "max_vehicle_age_years", "int")
    max_odo = c.req_field(body, "max_odometer_at_sale", "int")
    base_premium = c.req_field(body, "base_premium_cents", "int")
    deductible = c.req_field(body, "deductible_cents", "int")
    labor_cap = c.req_field(body, "labor_rate_cap_cents_per_hour", "int")
    cession = c.req_field(body, "reinsurance_cession_pct", "number")
    rental_per_day = c.opt_field(body, "rental_benefit_cents_per_day", 0, "int")
    rental_max_days = c.opt_field(body, "rental_max_days", 0, "int")
    towing = c.opt_field(body, "towing_benefit_cents", 0, "int")

    # Range constraints (PRD §2.6)
    c.at_least(term_months, 1, "term_months")
    c.at_least(term_miles, 1, "term_miles")
    for nm, v in [("max_vehicle_age_years", max_age), ("max_odometer_at_sale", max_odo),
                  ("base_premium_cents", base_premium), ("deductible_cents", deductible),
                  ("labor_rate_cap_cents_per_hour", labor_cap),
                  ("rental_benefit_cents_per_day", rental_per_day),
                  ("rental_max_days", rental_max_days), ("towing_benefit_cents", towing)]:
        c.non_negative(v, nm)
    if cession < 0.0 or cession > 1.0:
        raise err("ERR_INVALID_CESSION_PCT", "reinsurance_cession_pct out of [0,1]")

    rec = c.make_common()
    rec.update({
        "name": name, "tier": tier, "term_months": term_months, "term_miles": term_miles,
        "max_vehicle_age_years": max_age, "max_odometer_at_sale": max_odo,
        "base_premium_cents": base_premium, "deductible_cents": deductible,
        "labor_rate_cap_cents_per_hour": labor_cap,
        "rental_benefit_cents_per_day": rental_per_day, "rental_max_days": rental_max_days,
        "towing_benefit_cents": towing, "reinsurance_cession_pct": cession,
        "status": "DRAFT",
    })
    db.coverage_plans[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/coverage-plans", methods=["GET"])
@require_roles("AdminUnderwriter", "ContractAdmin", "ClaimsAdjuster", "Auditor")
def list_plans():
    items = list(db.coverage_plans.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/coverage-plans/<id>", methods=["GET"])
@require_roles("AdminUnderwriter", "ContractAdmin", "ClaimsAdjuster", "Auditor")
def get_plan(id):
    rec = c.get_or_404(db.coverage_plans, id)
    return ok(c.public(rec))


@bp.route("/coverage-plans/<id>/activate", methods=["POST"])
@require_roles("AdminUnderwriter")
def activate_plan(id):
    rec = c.get_or_404(db.coverage_plans, id)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Plan not in DRAFT")
    if rec["reinsurance_cession_pct"] < 0.0 or rec["reinsurance_cession_pct"] > 1.0:
        raise err("ERR_INVALID_CESSION_PCT", "reinsurance_cession_pct out of [0,1]")
    if rec["term_months"] < 1 or rec["term_miles"] < 1:
        raise err("ERR_VALIDATION_RANGE", "term_months/term_miles must be >= 1")
    rec["status"] = "ACTIVE"
    c.touch(rec)
    c.audit(g.user_role, "CoveragePlan", rec["id"], "PLAN_ACTIVATED")
    return ok(c.public(rec))


@bp.route("/coverage-plans/<id>/retire", methods=["POST"])
@require_roles("AdminUnderwriter")
def retire_plan(id):
    rec = c.get_or_404(db.coverage_plans, id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan not in ACTIVE")
    for ct in db.contracts.values():
        if ct["coverage_plan_id"] == rec["id"] and ct["status"] in ("PENDING", "ACTIVE"):
            raise err("ERR_PLAN_IN_USE", "Plan still referenced by PENDING/ACTIVE contract")
    rec["status"] = "RETIRED"
    c.touch(rec)
    c.audit(g.user_role, "CoveragePlan", rec["id"], "PLAN_RETIRED")
    return ok(c.public(rec))


# ===========================================================================
# Reinsurance Pools
# ===========================================================================
@bp.route("/reinsurance-pools", methods=["POST"])
@require_roles("AdminUnderwriter")
def create_pool():
    body = c.require_body(request.get_json(silent=True))
    name = c.req_field(body, "name", "str")
    rec = c.make_common()
    rec.update({
        "name": name, "ceded_premium_cents": 0, "paid_loss_cents": 0,
        "reserve_held_cents": 0, "surplus_cents": 0, "status": "OPEN",
    })
    db.reinsurance_pools[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/reinsurance-pools", methods=["GET"])
@require_roles("AdminUnderwriter", "Auditor")
def list_pools():
    items = list(db.reinsurance_pools.values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    out = []
    for r in page:
        c.recompute_pool(r["id"])
        out.append(c.public(r))
    return listing(out, limit, offset, total)


@bp.route("/reinsurance-pools/<id>", methods=["GET"])
@require_roles("AdminUnderwriter", "Auditor")
def get_pool(id):
    rec = c.get_or_404(db.reinsurance_pools, id)
    c.recompute_pool(rec["id"])
    return ok(c.public(rec))


@bp.route("/reinsurance-pools/<id>/ledger-entries", methods=["GET"])
@require_roles("AdminUnderwriter", "Auditor")
def pool_ledger(id):
    c.get_or_404(db.reinsurance_pools, id)
    items = [e for e in db.ledger_entries.values() if e["reinsurance_pool_id"] == id]
    contract_id = request.args.get("contract_id")
    entry_type = request.args.get("entry_type")
    if contract_id is not None:
        items = [e for e in items if e.get("contract_id") == contract_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/reinsurance-pools/<id>/claims", methods=["GET"])
@require_roles("AdminUnderwriter", "Auditor")
def pool_claims(id):
    c.get_or_404(db.reinsurance_pools, id)
    items = [cl for cl in db.claims.values() if cl.get("reinsurance_pool_id") == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


# ===========================================================================
# Repair Facilities
# ===========================================================================
@bp.route("/repair-facilities", methods=["POST"])
@require_roles("AdminUnderwriter")
def create_facility():
    body = c.require_body(request.get_json(silent=True))
    name = c.req_field(body, "name", "str")
    posted_rate = c.req_field(body, "posted_labor_rate_cents_per_hour", "int")
    c.non_negative(posted_rate, "posted_labor_rate_cents_per_hour")
    network = c.opt_field(body, "network_status", "IN_NETWORK", "str")
    direct_pay = c.opt_field(body, "direct_pay_enrolled", False, "bool")
    rec = c.make_common()
    rec.update({
        "name": name, "posted_labor_rate_cents_per_hour": posted_rate,
        "network_status": network, "direct_pay_enrolled": direct_pay, "status": "ACTIVE",
    })
    db.repair_facilities[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/repair-facilities/<id>", methods=["GET"])
@require_roles("AdminUnderwriter", "ClaimsAdjuster", "RepairFacility", "Auditor")
def get_facility(id):
    rec = c.get_or_404(db.repair_facilities, id)
    return ok(c.public(rec))


@bp.route("/repair-facilities/<id>/claims", methods=["GET"])
@require_roles("AdminUnderwriter", "ClaimsAdjuster", "RepairFacility", "Auditor")
def facility_claims(id):
    c.get_or_404(db.repair_facilities, id)
    items = [cl for cl in db.claims.values() if cl["repair_facility_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/repair-facilities/<id>/repair-authorizations", methods=["GET"])
@require_roles("AdminUnderwriter", "ClaimsAdjuster", "RepairFacility", "Auditor")
def facility_auths(id):
    c.get_or_404(db.repair_facilities, id)
    items = [a for a in db.repair_authorizations.values() if a["repair_facility_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)
