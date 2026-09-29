"""Plans, valuations, the settlement amendment, strategies, filings, ledger, clock."""

import re

from flask import Blueprint, request

from db import db, make_entity, now, ordered, public, set_clock, touch
from errors import api_error
from middleware import (
    ALL_ROLES,
    authenticate,
    body,
    filter_arg,
    get_datetime,
    get_enum,
    get_int,
    get_string,
    lookup,
    pagination,
    require_range,
    slice_page,
)
from response import list_response, object_response
from services import calculations as calc
from services import domain as dom

bp = Blueprint("plans", __name__)

EIN_RE = re.compile(r"^\d{9}$")

PLAN_READ_ROLES = ["PlanSponsor", "PlanFiduciary", "Actuary", "PlanAdministrator", "Regulator"]
FUNDED_STATUS_ROLES = ["PlanSponsor", "PlanFiduciary", "Actuary", "Regulator"]
STRATEGY_READ_ROLES = ["PlanSponsor", "PlanFiduciary", "Actuary", "Regulator"]
LEDGER_ROLES = ["PlanSponsor", "PlanFiduciary", "Actuary", "Regulator"]

STRATEGY_TYPES = ("LUMP_SUM_WINDOW", "ANNUITY_BUYOUT", "LDI_GLIDEPATH", "HYBRID_WINDOW_AND_BUYOUT")
AMENDMENT_SCOPES = ("LUMP_SUM_ONLY", "BUYOUT_ONLY", "BOTH")
SCOPE_BACKING = {
    "LUMP_SUM_ONLY": ("LUMP_SUM_WINDOW", "HYBRID_WINDOW_AND_BUYOUT"),
    "BUYOUT_ONLY": ("ANNUITY_BUYOUT", "HYBRID_WINDOW_AND_BUYOUT"),
    "BOTH": ("HYBRID_WINDOW_AND_BUYOUT",),
}
ENTRY_TYPES = (
    "BUYOUT_RECOGNITION",
    "LUMP_SUM_RECOGNITION",
    "REMEDIATION",
    "REMEDIATION_REVERSAL",
    "PLAN_TERMINATION",
)


def _bounded_string(payload, name, low, high, required=True):
    value = get_string(payload, name, required=required)
    if value is None:
        return None
    if len(value) < low or len(value) > high:
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' has an invalid length." % name)
    return value


def _valuation_inputs(payload):
    total_liability = get_int(payload, "total_liability_cents")
    plan_assets = get_int(payload, "plan_assets_cents")
    service_cost = get_int(payload, "service_cost_cents")
    interest_cost = get_int(payload, "interest_cost_cents")
    unrecognized = get_int(payload, "unrecognized_actuarial_loss_cents")
    discount_rate = get_int(payload, "discount_rate_bps")
    require_range(total_liability, "total_liability_cents", 0, None)
    require_range(plan_assets, "plan_assets_cents", 0, None)
    require_range(service_cost, "service_cost_cents", 0, None)
    require_range(interest_cost, "interest_cost_cents", 0, None)
    require_range(unrecognized, "unrecognized_actuarial_loss_cents", 0, None)
    require_range(discount_rate, "discount_rate_bps", 1, 2000)
    return {
        "total_liability_cents": total_liability,
        "plan_assets_cents": plan_assets,
        "service_cost_cents": service_cost,
        "interest_cost_cents": interest_cost,
        "unrecognized_actuarial_loss_cents": unrecognized,
        "discount_rate_bps": discount_rate,
    }


# --------------------------------------------------------------------------
# plans
# --------------------------------------------------------------------------


@bp.post("/prt/plans")
def create_plan():
    authenticate(["PlanSponsor"])
    payload = body()
    sponsor_name = _bounded_string(payload, "sponsor_name", 1, 200)
    plan_name = _bounded_string(payload, "plan_name", 1, 200)
    plan_ein = get_string(payload, "plan_ein")
    figures = _valuation_inputs(payload)
    if not EIN_RE.match(plan_ein.strip()):
        raise api_error("ERR_INVALID_AMOUNT", "plan_ein must be exactly nine digits.")
    plan_ein = plan_ein.strip()
    for existing in db.plans.values():
        if existing["plan_ein"] == plan_ein:
            raise api_error("ERR_INVALID_REQUEST", "plan_ein is already registered.")

    plan = make_entity()
    plan["sponsor_name"] = sponsor_name
    plan["plan_name"] = plan_name
    plan["plan_ein"] = plan_ein
    plan["plan_status"] = "ONGOING"
    plan.update(figures)
    plan["accounting_funded_status_bp"] = 0
    plan["participant_liability_total_cents"] = 0
    plan["amendment_scope"] = None
    plan["amendment_adopted_at"] = None
    plan["amendment_effective_date"] = None
    plan["cumulative_settlement_charge_cents"] = 0
    plan["deferred_settlement_charge_cents"] = 0
    plan["filing_reference"] = None
    plan["filing_submitted_at"] = None
    plan["filing_deficiency_reason"] = None
    plan["residual_effective_at"] = None
    plan["terminated_at"] = None
    dom.recompute_plan_accounting_funded_status(plan)
    db.plans[plan["id"]] = plan
    return object_response(public(plan), 201)


@bp.get("/prt/plans/<plan_id>")
def get_plan(plan_id):
    authenticate(PLAN_READ_ROLES)
    plan = lookup("plans", plan_id)
    return object_response(public(plan))


@bp.get("/prt/plans/<plan_id>/funded-status")
def get_funded_status(plan_id):
    authenticate(FUNDED_STATUS_ROLES)
    plan = lookup("plans", plan_id)
    figures = dom.plan_funded_status(plan)
    figures["cumulative_settlement_charge_cents"] = plan["cumulative_settlement_charge_cents"]
    figures["deferred_settlement_charge_cents"] = plan["deferred_settlement_charge_cents"]
    return object_response(figures)


@bp.post("/prt/plans/<plan_id>/valuation-updates")
def valuation_update(plan_id):
    authenticate(["PlanSponsor", "Actuary"])
    plan = lookup("plans", plan_id)
    payload = body()
    expected = get_int(payload, "expected_plan_version")
    figures = _valuation_inputs(payload)
    if expected != plan["version"]:
        raise api_error("ERR_STALE_PLAN_VERSION")
    plan.update(figures)
    dom.recompute_plan_participant_liability(plan)
    dom.recompute_plan_accounting_funded_status(plan)
    touch(plan)
    return object_response(public(plan))


@bp.post("/prt/plans/<plan_id>/settlement-amendment")
def settlement_amendment(plan_id):
    authenticate(["PlanSponsor"])
    plan = lookup("plans", plan_id)
    payload = body()
    action = get_enum(payload, "amendment_action", ("ADOPT", "RESCIND"))
    scope = None
    effective_date = None
    if action == "ADOPT":
        scope = get_enum(payload, "amendment_scope", AMENDMENT_SCOPES)
        effective_date = get_datetime(payload, "amendment_effective_date")
        if effective_date < now():
            raise api_error(
                "ERR_INVALID_INTERVAL",
                "amendment_effective_date must not precede the logical clock.",
            )
        if plan["plan_status"] != "ONGOING":
            raise api_error("ERR_PLAN_STATE_INVALID")
        backing = SCOPE_BACKING[scope]
        approved = [
            s
            for s in dom.plan_strategies(plan["id"])
            if s["strategy_status"] == "APPROVED" and s["strategy_type"] in backing
        ]
        if not approved:
            raise api_error("ERR_STRATEGY_NOT_APPROVED")
        plan["plan_status"] = "SETTLEMENT_AUTHORIZED"
        plan["amendment_scope"] = scope
        plan["amendment_effective_date"] = effective_date
        plan["amendment_adopted_at"] = now()
        touch(plan)
        return object_response(public(plan))

    # RESCIND
    if plan["plan_status"] != "SETTLEMENT_AUTHORIZED":
        raise api_error("ERR_PLAN_STATE_INVALID")
    windows = dom.plan_windows(plan["id"])
    tranches = dom.plan_tranches(plan["id"])
    for window in windows:
        if window["window_status"] in ("OPEN", "CLOSED"):
            raise api_error("ERR_WINDOW_STATE_INVALID")
    for tranche in tranches:
        if tranche["tranche_status"] in (
            "QUOTING",
            "INSURER_SELECTED",
            "PRICING_LOCKED",
            "ASSETS_TRANSFERRED",
        ):
            raise api_error("ERR_TRANCHE_STATE_INVALID")

    plan["plan_status"] = "ONGOING"
    plan["amendment_scope"] = None
    plan["amendment_adopted_at"] = None
    plan["amendment_effective_date"] = None
    for window in windows:
        if window["window_status"] == "PLANNED":
            window["window_status"] = "VOIDED"
            touch(window)
    for tranche in tranches:
        if tranche["tranche_status"] == "DRAFT":
            tranche["tranche_status"] = "ABANDONED"
            tranche["abandoned_at"] = now()
            for participant in dom.tranche_assigned_participants(tranche):
                participant["participant_status"] = "IN_PLAN"
                participant["tranche_id"] = None
                dom.refresh_participant_confidence(participant)
            touch(tranche)
    dom.recompute_plan_participant_liability(plan)
    touch(plan)
    return object_response(public(plan))


@bp.post("/prt/plans/<plan_id>/termination-filing")
def termination_filing(plan_id):
    authenticate(["PlanSponsor"])
    plan = lookup("plans", plan_id)
    payload = body()
    filing_reference = get_string(payload, "filing_reference")
    if plan["plan_status"] == "FILING_DEFICIENT":
        get_string(payload, "deficiency_response")
    if plan["plan_status"] not in ("RESIDUAL", "FILING_DEFICIENT"):
        raise api_error("ERR_PLAN_STATE_INVALID")
    outstanding = [
        c
        for c in dom.plan_complaints(plan["id"])
        if c["complaint_status"] in ("OPEN", "TRIAGED")
    ]
    if outstanding:
        raise api_error("ERR_COMPLAINT_STATE_INVALID")
    plan["plan_status"] = "TERMINATION_FILED"
    plan["filing_reference"] = filing_reference
    plan["filing_submitted_at"] = now()
    plan["filing_deficiency_reason"] = None
    touch(plan)
    return object_response(public(plan))


@bp.post("/prt/plans/<plan_id>/filing-review")
def filing_review(plan_id):
    authenticate(["Regulator"])
    plan = lookup("plans", plan_id)
    payload = body()
    decision = get_enum(payload, "review_decision", ("APPROVE", "RETURN_DEFICIENT"))
    reason = None
    if decision == "RETURN_DEFICIENT":
        reason = get_string(payload, "filing_deficiency_reason")
    if plan["plan_status"] != "TERMINATION_FILED":
        raise api_error("ERR_PLAN_STATE_INVALID")

    if decision == "RETURN_DEFICIENT":
        plan["plan_status"] = "FILING_DEFICIENT"
        plan["filing_deficiency_reason"] = reason
        touch(plan)
        return object_response(public(plan))

    if plan["accounting_funded_status_bp"] < 10000:
        raise api_error("ERR_PLAN_ASSETS_INSUFFICIENT")

    pbo_settled = plan["participant_liability_total_cents"]
    plan["plan_status"] = "TERMINATED"
    plan["terminated_at"] = now()
    for participant in dom.plan_participants(plan["id"]):
        if participant["participant_status"] == "IN_PLAN":
            participant["participant_status"] = "RESIDUAL_ANNUITY_PURCHASED"
            touch(participant)
    for complaint in dom.plan_complaints(plan["id"]):
        if complaint["complaint_status"] == "RESOLVED":
            complaint["complaint_status"] = "CLOSED_FINAL"
            touch(complaint)
    dom.append_settlement_entry(
        plan,
        "PLAN_TERMINATION",
        0,
        0,
        0,
        pbo_settled,
        "PensionPlan TERMINATION_FILED -> TERMINATED",
    )
    dom.recompute_plan_participant_liability(plan)
    dom.recompute_plan_accounting_funded_status(plan)
    touch(plan)
    return object_response(public(plan))


# --------------------------------------------------------------------------
# strategies
# --------------------------------------------------------------------------


@bp.post("/prt/plans/<plan_id>/strategies")
def create_strategy(plan_id):
    authenticate(["Actuary"])
    plan = lookup("plans", plan_id)
    payload = body()
    label = _bounded_string(payload, "strategy_name", 1, 120)
    strategy_type = get_enum(payload, "strategy_type", STRATEGY_TYPES)
    hedge_ratio = get_int(payload, "ldi_hedge_ratio_bp", required=False, default=0)

    strategy = make_entity()
    strategy["plan_id"] = plan["id"]
    strategy["strategy_type"] = strategy_type
    strategy["strategy_label"] = label
    strategy["ldi_hedge_ratio_bp"] = hedge_ratio
    strategy["strategy_status"] = "DRAFT"
    strategy["projected_accounting_cost_cents"] = None
    strategy["projected_settlement_cost_cents"] = None
    strategy["projected_basis_gap_cents"] = None
    strategy["in_scope_participant_count"] = 0
    strategy["submitted_by_user_id"] = None
    strategy["decided_by_user_id"] = None
    strategy["revision_count"] = 0
    strategy["decision_rationale"] = None
    db.strategies[strategy["id"]] = strategy
    return object_response(public(strategy), 201)


@bp.get("/prt/plans/<plan_id>/strategies")
def list_strategies(plan_id):
    authenticate(STRATEGY_READ_ROLES)
    plan = lookup("plans", plan_id)
    status = request.args.get("strategy_status")
    limit, offset = pagination()
    records = dom.plan_strategies(plan["id"])
    if status is not None:
        records = [s for s in records if s["strategy_status"] == status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(s) for s in page], limit, offset, total)


@bp.post("/prt/strategies/<strategy_id>/submission")
def submit_strategy(strategy_id):
    user_id, _role = authenticate(["Actuary"])
    strategy = lookup("strategies", strategy_id)
    body()
    if strategy["strategy_status"] != "DRAFT":
        raise api_error("ERR_STRATEGY_STATE_INVALID")
    plan = db.plans.get(strategy["plan_id"])
    if plan is None or plan["plan_status"] not in ("ONGOING", "SETTLEMENT_AUTHORIZED"):
        raise api_error("ERR_PLAN_STATE_INVALID")

    cohorts = calc.STRATEGY_COHORT_MAP[strategy["strategy_type"]]
    population = [
        p
        for p in dom.plan_participants(plan["id"])
        if p["participant_status"] in ("IN_PLAN", "ASSIGNED")
        and p["mortality_status"] != "DECEASED_CONFIRMED"
        and p["cohort"] in cohorts
    ]
    projection = calc.strategy_projection(strategy["strategy_type"], population)
    strategy["strategy_status"] = "UNDER_EVALUATION"
    strategy.update(projection)
    strategy["submitted_by_user_id"] = user_id
    touch(strategy)
    return object_response(public(strategy))


@bp.post("/prt/strategies/<strategy_id>/decision")
def decide_strategy(strategy_id):
    user_id, _role = authenticate(["PlanFiduciary"])
    strategy = lookup("strategies", strategy_id)
    payload = body()
    decision = get_enum(payload, "decision", ("APPROVE", "REJECT", "RETURN_FOR_REVISION"))
    rationale = get_string(payload, "decision_rationale")
    if strategy["strategy_status"] != "UNDER_EVALUATION":
        raise api_error("ERR_STRATEGY_STATE_INVALID")
    if decision == "RETURN_FOR_REVISION" and strategy["revision_count"] >= calc.MAX_REVISION_ROUNDS:
        raise api_error("ERR_STRATEGY_STATE_INVALID")
    if strategy["submitted_by_user_id"] is not None and user_id == strategy["submitted_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVE":
        strategy["strategy_status"] = "APPROVED"
        strategy["decided_by_user_id"] = user_id
        strategy["decision_rationale"] = rationale
    elif decision == "REJECT":
        strategy["strategy_status"] = "REJECTED"
        strategy["decided_by_user_id"] = user_id
        strategy["decision_rationale"] = rationale
    else:
        strategy["strategy_status"] = "DRAFT"
        strategy["decided_by_user_id"] = user_id
        strategy["decision_rationale"] = rationale
        strategy["revision_count"] = strategy["revision_count"] + 1
        strategy["projected_accounting_cost_cents"] = None
        strategy["projected_settlement_cost_cents"] = None
        strategy["projected_basis_gap_cents"] = None
        strategy["in_scope_participant_count"] = 0
        strategy["submitted_by_user_id"] = None
    touch(strategy)
    return object_response(public(strategy))


# --------------------------------------------------------------------------
# settlement entries (read-only ledger)
# --------------------------------------------------------------------------


@bp.get("/prt/settlement-entries")
def list_entries():
    authenticate(LEDGER_ROLES)
    plan_id = filter_arg("plans", "plan_id")
    tranche_id = filter_arg("tranches", "tranche_id")
    window_id = filter_arg("windows", "window_id")
    entry_type = request.args.get("entry_type")
    limit, offset = pagination()
    records = ordered(list(db.entries.values()))
    if plan_id is not None:
        records = [e for e in records if e["plan_id"] == plan_id]
    if tranche_id is not None:
        records = [e for e in records if e["tranche_id"] == tranche_id]
    if window_id is not None:
        records = [e for e in records if e["window_id"] == window_id]
    if entry_type is not None:
        records = [e for e in records if e["entry_type"] == entry_type]
    page, total = slice_page(records, limit, offset)
    return list_response([public(e) for e in page], limit, offset, total)


@bp.get("/prt/settlement-entries/<entry_id>")
def get_entry(entry_id):
    authenticate(LEDGER_ROLES)
    entry = lookup("entries", entry_id)
    return object_response(public(entry))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ALL_ROLES)
    payload = body()
    instant = get_datetime(payload, "current_utc")
    set_clock(instant)
    return object_response({})
