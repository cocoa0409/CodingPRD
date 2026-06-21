"""Policy endpoints: create / list / read / issue / rescind / anniversary /
waive-premium (PRD §3.1, §3.2, §3.10)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, core

bp = Blueprint("policies", __name__)

PRODUCT_MODES = {"REIMBURSEMENT", "INDEMNITY"}
INFLATION_RIDERS = {"NONE", "COMPOUND_3PCT", "COMPOUND_5PCT"}


@bp.route("/policies", methods=["POST"])
def create_policy():
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    body = common.get_json_body()

    policyholder_id = common.require_str(body, "policyholder_id")
    product_mode = common.require_enum(body, "product_mode", PRODUCT_MODES)
    daily = common.require_int(body, "daily_benefit_max_cents")
    monthly = common.require_int(body, "monthly_benefit_max_cents")
    initial_pool = common.require_int(body, "initial_pool_cents")
    inflation_rider = common.require_enum(body, "inflation_rider", INFLATION_RIDERS)
    elim = common.require_int(body, "elimination_period_days")
    is_partnership = common.optional_bool(body, "is_partnership_policy", False)

    # FK existence (after schema validation per §2.7 ordering)
    lookup.policyholder_or_404(policyholder_id)

    rid = new_id()
    rec = {
        "id": rid,
        "policyholder_id": policyholder_id,
        "product_mode": product_mode,
        "daily_benefit_max_cents": daily,
        "monthly_benefit_max_cents": monthly,
        "initial_pool_cents": initial_pool,
        "inflation_rider": inflation_rider,
        "elimination_period_days": elim,
        "is_partnership_policy": is_partnership,
        "inflation_years_elapsed": 0,
        "coverage_status": "APPLIED",
        "premium_status": "PENDING",
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.policies[rid] = rec

    if is_partnership:
        pdid = new_id()
        pd = {
            "id": pdid,
            "policy_id": rid,
            "protected_asset_cents": 0,
            "disregard_status": "ACCRUING",
        }
        pd.update(common_fields(STORE.next_seq()))
        STORE.partnership_disregards[pdid] = pd

    return object_response(serialize.policy(rec), 201)


@bp.route("/policies", methods=["GET"])
def list_policies():
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator"])
    records = list(STORE.policies.values())
    ph_filter = request.args.get("policyholder_id")
    if ph_filter is not None:
        records = [r for r in records if r["policyholder_id"] == ph_filter]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.policy(r) for r in page], limit, offset, total)


@bp.route("/policies/<rid>", methods=["GET"])
def get_policy(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator", "Policyholder"])
    rec = lookup.policy_or_404(rid)
    return object_response(serialize.policy(rec), 200)


@bp.route("/policies/<rid>/issue", methods=["POST"])
def issue_policy(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    pol = lookup.policy_or_404(rid)
    if pol["coverage_status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Policy not in APPLIED state")
    pol["coverage_status"] = "IN_FORCE"
    # Create the BenefitPool
    poolid = new_id()
    pool = {
        "id": poolid,
        "policy_id": rid,
        "lifetime_paid_cents": 0,
        "nonforfeiture_reduction_cents": 0,
    }
    pool.update(common_fields(STORE.next_seq()))
    STORE.benefit_pools[poolid] = pool
    touch(pol)
    return object_response(serialize.policy(pol), 200)


@bp.route("/policies/<rid>/rescind", methods=["POST"])
def rescind_policy(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    pol = lookup.policy_or_404(rid)
    if pol["coverage_status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Policy not in APPLIED state")
    pol["coverage_status"] = "RESCINDED"
    touch(pol)
    return object_response(serialize.policy(pol), 200)


@bp.route("/policies/<rid>/apply-anniversary", methods=["POST"])
def apply_anniversary(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    pol = lookup.policy_or_404(rid)
    if pol["coverage_status"] not in ("IN_FORCE", "CLAIM_OPEN"):
        raise errors.err(errors.ERR_ANNIVERSARY_NOT_IN_FORCE,
                         "Policy not in force for anniversary")
    # Pool growth delta for the ledger entry: change in inflated pool.
    pool = core.pool_for_policy(rid)
    before = serialize.benefit_pool(pool)["inflated_pool_cents"] if pool else 0
    pol["inflation_years_elapsed"] += 1
    after = serialize.benefit_pool(pool)["inflated_pool_cents"] if pool else 0
    core.append_ledger(rid, None, "INFLATION_GROWTH", after - before)
    touch(pol)
    return object_response(serialize.policy(pol), 200)


@bp.route("/policies/<rid>/waive-premium", methods=["POST"])
def waive_premium(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    pol = lookup.policy_or_404(rid)
    # State precedes business-safety checks per §3.13 ordering; but the §1.2
    # transition is from PAID_CURRENT, and the gating checks are benefits +
    # coverage. Apply benefits_triggered then coverage state.
    if not serialize.policy_benefits_triggered(rid):
        raise errors.err(errors.ERR_BENEFITS_NOT_TRIGGERED, "Benefits not triggered")
    if pol["coverage_status"] not in ("IN_FORCE", "CLAIM_OPEN"):
        raise errors.err(errors.ERR_INVALID_STATE, "Coverage not in force / on claim")
    pol["premium_status"] = "WAIVED"
    for inv in STORE.premium_invoices.values():
        if inv["policy_id"] == rid and inv["status"] == "OPEN":
            inv["status"] = "WAIVED"
            touch(inv)
    touch(pol)
    return object_response(serialize.policy(pol), 200)
