"""Contracts and ancillary products."""
from flask import Blueprint, request, g

from db import db
from errors import err
from middleware import require_roles
from response import ok, created, listing
import common as c

bp = Blueprint("contracts", __name__)


# ---------------------------------------------------------------------------
# Earned premium recompute + auto-expire on read (PRD §3.2)
# ---------------------------------------------------------------------------
def months_elapsed(sale_dt, now_dt):
    return (now_dt.year - sale_dt.year) * 12 + (now_dt.month - sale_dt.month) - \
        (1 if (now_dt.day, now_dt.hour, now_dt.minute, now_dt.second) <
         (sale_dt.day, sale_dt.hour, sale_dt.minute, sale_dt.second) else 0)


def recompute_contract(contract):
    """Recompute earned_premium_cents and auto ACTIVE->EXPIRED when term elapsed."""
    plan = db.coverage_plans.get(contract["coverage_plan_id"])
    sale_dt = c.parse_iso(contract.get("sale_date"))
    if plan is None or sale_dt is None:
        return
    now_dt = db.clock_utc
    elapsed = months_elapsed(sale_dt, now_dt)
    term = plan["term_months"]
    if contract["status"] == "ACTIVE" and elapsed >= term:
        _expire(contract)
    # earned_premium recomputation (pro-rata time basis on base premium)
    if contract["status"] in ("ACTIVE", "EXPIRED", "LAPSED", "CANCELLED"):
        frac = min(1.0, max(0.0, elapsed / term)) if term > 0 else 0.0
        contract["earned_premium_cents"] = c.round_half_up(plan["base_premium_cents"] * frac)


def _expire(contract):
    # release remaining case reserves on open claims
    for cl in db.claims.values():
        if cl["contract_id"] != contract["id"]:
            continue
        if cl.get("reserve_cents", 0) > 0 and cl["payment_status"] != "PAID":
            amt = cl["reserve_cents"]
            c.post_ledger(cl["reinsurance_pool_id"], "RESERVE_RELEASE", -amt,
                          "Reserve release on contract expiry", contract_id=contract["id"])
            cl["reserve_cents"] = 0
            c.touch(cl)
    contract["status"] = "EXPIRED"
    c.touch(contract)
    c.audit("system", "Contract", contract["id"], "CONTRACT_EXPIRED")


# ===========================================================================
# Contracts
# ===========================================================================
@bp.route("/contracts", methods=["POST"])
@require_roles("ContractAdmin")
def create_contract():
    body = c.require_body(request.get_json(silent=True))
    plan_id = c.req_field(body, "coverage_plan_id", "str")
    pool_id = c.req_field(body, "reinsurance_pool_id", "str")
    vin = c.req_field(body, "vin", "str")
    model_year = c.req_field(body, "vehicle_model_year", "int")
    odo = c.req_field(body, "odometer_at_sale", "int")
    sale_date = c.req_field(body, "sale_date", "str")
    sale_price = c.req_field(body, "sale_price_cents", "int")
    financed = c.opt_field(body, "financed", False, "bool")
    finance_term = c.opt_field(body, "finance_term_months", 0, "int")

    c.non_negative(odo, "odometer_at_sale")
    c.non_negative(sale_price, "sale_price_cents")
    c.non_negative(finance_term, "finance_term_months")

    # FK resolution
    c.fk_or_404(db.coverage_plans, plan_id)
    c.fk_or_404(db.reinsurance_pools, pool_id)

    rec = c.make_common()
    rec.update({
        "coverage_plan_id": plan_id, "reinsurance_pool_id": pool_id, "vin": vin,
        "vehicle_model_year": model_year, "odometer_at_sale": odo, "sale_date": sale_date,
        "sale_price_cents": sale_price, "financed": financed,
        "finance_term_months": finance_term, "earned_premium_cents": 0,
        "paid_claim_total_cents": 0, "cancellation_id": None, "status": "PENDING",
    })
    db.contracts[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/contracts", methods=["GET"])
@require_roles("ContractAdmin", "ClaimsAdjuster", "AdminUnderwriter", "Auditor")
def list_contracts():
    items = list(db.contracts.values())
    for key in ("coverage_plan_id", "reinsurance_pool_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    out = []
    for r in page:
        recompute_contract(r)
        out.append(c.public(r))
    return listing(out, limit, offset, total)


@bp.route("/contracts/<id>", methods=["GET"])
@require_roles("ContractAdmin", "ClaimsAdjuster", "AdminUnderwriter", "Auditor")
def get_contract(id):
    rec = c.get_or_404(db.contracts, id)
    recompute_contract(rec)
    return ok(c.public(rec))


@bp.route("/contracts/<id>/activate", methods=["POST"])
@require_roles("ContractAdmin")
def activate_contract(id):
    rec = c.get_or_404(db.contracts, id)
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Contract not in PENDING")
    plan = db.coverage_plans.get(rec["coverage_plan_id"])
    # priority order per §3.7: plan-active, then vehicle-eligibility, then finance-term
    if plan is None or plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Coverage plan is not ACTIVE")
    age = db.clock_utc.year - rec["vehicle_model_year"]
    if age > plan["max_vehicle_age_years"] or rec["odometer_at_sale"] > plan["max_odometer_at_sale"]:
        raise err("ERR_VEHICLE_INELIGIBLE", "Vehicle ineligible by tier")
    if rec["financed"] and rec["finance_term_months"] < 1:
        raise err("ERR_FINANCE_TERM_REQUIRED", "finance_term_months required when financed")
    rec["status"] = "ACTIVE"
    rec["earned_premium_cents"] = 0
    c.post_ledger(rec["reinsurance_pool_id"], "PREMIUM_CEDED", 0,
                  "Premium ceded placeholder on contract activation", contract_id=rec["id"])
    c.touch(rec)
    c.audit(g.user_role, "Contract", rec["id"], "CONTRACT_ACTIVATED")
    return ok(c.public(rec))


@bp.route("/contracts/<id>/lapse", methods=["POST"])
@require_roles("ContractAdmin")
def lapse_contract(id):
    rec = c.get_or_404(db.contracts, id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract not in ACTIVE")
    for cl in db.claims.values():
        if cl["contract_id"] != rec["id"]:
            continue
        if cl["adjudication_status"] == "UNDER_REVIEW":
            raise err("ERR_OPEN_CLAIM_BLOCKS", "Open claim under review")
        if cl["adjudication_status"] == "APPROVED" and cl["payment_status"] != "PAID":
            raise err("ERR_OPEN_CLAIM_BLOCKS", "Open approved unpaid claim")
    rec["status"] = "LAPSED"
    c.touch(rec)
    c.audit(g.user_role, "Contract", rec["id"], "CONTRACT_LAPSED")
    return ok(c.public(rec))


@bp.route("/contracts/<id>/reinstate", methods=["POST"])
@require_roles("ContractAdmin")
def reinstate_contract(id):
    rec = c.get_or_404(db.contracts, id)
    if rec["status"] != "LAPSED":
        raise err("ERR_INVALID_STATE", "Contract not in LAPSED")
    plan = db.coverage_plans.get(rec["coverage_plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Coverage plan is not ACTIVE")
    rec["status"] = "ACTIVE"
    c.touch(rec)
    c.audit(g.user_role, "Contract", rec["id"], "CONTRACT_REINSTATED")
    return ok(c.public(rec))


@bp.route("/contracts/<id>/ancillary-products", methods=["GET"])
@require_roles("ContractAdmin", "AdminUnderwriter", "Auditor")
def contract_ancillaries(id):
    c.get_or_404(db.contracts, id)
    items = [a for a in db.ancillary_products.values() if a["contract_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/contracts/<id>/claims", methods=["GET"])
@require_roles("ContractAdmin", "ClaimsAdjuster", "Auditor")
def contract_claims(id):
    c.get_or_404(db.contracts, id)
    items = [cl for cl in db.claims.values() if cl["contract_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/contracts/<id>/cancellation", methods=["GET"])
@require_roles("ContractAdmin", "Auditor")
def contract_cancellation(id):
    c.get_or_404(db.contracts, id)
    items = [x for x in db.cancellations.values() if x["contract_id"] == id]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


@bp.route("/contracts/<id>/ledger-entries", methods=["GET"])
@require_roles("ContractAdmin", "AdminUnderwriter", "Auditor")
def contract_ledger(id):
    c.get_or_404(db.contracts, id)
    items = [e for e in db.ledger_entries.values() if e.get("contract_id") == id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = c.sort_created(items)
    page, limit, offset, total = c.paginate(request.args, items)
    return listing([c.public(r) for r in page], limit, offset, total)


# ===========================================================================
# Ancillary Products
# ===========================================================================
@bp.route("/ancillary-products", methods=["POST"])
@require_roles("ContractAdmin")
def create_ancillary():
    body = c.require_body(request.get_json(silent=True))
    contract_id = c.req_field(body, "contract_id", "str")
    product_type = c.req_field(body, "product_type", "str")
    premium = c.req_field(body, "premium_cents", "int")
    gap_cap = c.opt_field(body, "gap_cap_cents", 0, "int")
    refundable = c.opt_field(body, "refundable", True, "bool")
    c.non_negative(premium, "premium_cents")
    c.non_negative(gap_cap, "gap_cap_cents")

    contract = c.fk_or_404(db.contracts, contract_id)
    if contract["status"] != "PENDING":
        raise err("ERR_BUNDLE_TOO_LATE", "Cannot bundle onto a non-PENDING contract")

    rec = c.make_common()
    rec.update({
        "contract_id": contract_id, "product_type": product_type, "premium_cents": premium,
        "gap_cap_cents": gap_cap, "refundable": refundable, "status": "BUNDLED",
    })
    db.ancillary_products[rec["id"]] = rec
    return created(c.public(rec))


@bp.route("/ancillary-products/<id>", methods=["GET"])
@require_roles("ContractAdmin", "AdminUnderwriter", "Auditor")
def get_ancillary(id):
    rec = c.get_or_404(db.ancillary_products, id)
    return ok(c.public(rec))
