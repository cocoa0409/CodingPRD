from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Blueprint, request

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_SOD_VIOLATION,
                    ERR_SCENARIO_WEIGHTS, ERR_OVER_RECOGNITION)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from clock import CLOCK
from validate import require_roles, body, req_enum

bp = Blueprint("estimates", __name__)

METHODS = {"EXPECTED_VALUE", "MOST_LIKELY"}
CAPS = {"STANDARD": Decimal("0.85"), "ELEVATED": Decimal("0.70"), "HIGH": Decimal("0.50")}
ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")
CREATABLE_STATES = ("DRAFT", "CHANGES_REQUESTED", "APPROVED", "ACTIVE")


def get_contract_or_404(contract_id):
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    return c


def compute_amounts(method, scenarios, risk_tier):
    if method == "EXPECTED_VALUE":
        total = sum(s["probability_bps"] * s["amount_cents"] for s in scenarios)
        unconstrained = int((Decimal(total) / Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # MOST_LIKELY: greatest probability, ties broken by earliest index
        best = max(range(len(scenarios)), key=lambda i: scenarios[i]["probability_bps"])
        # max() over indices keeps the earliest index among ties
        unconstrained = scenarios[best]["amount_cents"]
    cap_term = int((Decimal(unconstrained) * CAPS[risk_tier]).to_integral_value(rounding=ROUND_FLOOR))
    constrained = min(unconstrained, cap_term)
    return unconstrained, constrained


@bp.post("/revrec/contracts/<contract_id>/vc-estimates")
def create_estimate(contract_id):
    uid = require_roles("RevenueAccountant")
    c = get_contract_or_404(contract_id)
    data = body()
    method = req_enum(data, "method", METHODS)
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "scenarios must be an array")
    for s in scenarios:
        if not isinstance(s, dict) \
                or isinstance(s.get("probability_bps"), bool) or not isinstance(s.get("probability_bps"), int) \
                or isinstance(s.get("amount_cents"), bool) or not isinstance(s.get("amount_cents"), int):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each scenario must pair integer probability_bps with integer amount_cents")
    if c["status"] not in CREATABLE_STATES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "estimates may be proposed only while DRAFT, CHANGES_REQUESTED, APPROVED, or ACTIVE")
    if sum(s["probability_bps"] for s in scenarios) != 10000:
        raise ApiError(ERR_SCENARIO_WEIGHTS, 422, "scenario probability_bps values must sum to exactly 10000")
    unconstrained, constrained = compute_amounts(method, scenarios, c["risk_tier"])
    rec = make_rec(STORE.estimates, {
        "contract_id": contract_id,
        "method": method,
        "scenarios": [{"probability_bps": s["probability_bps"], "amount_cents": s["amount_cents"]}
                      for s in scenarios],
        "unconstrained_amount_cents": unconstrained,
        "constrained_amount_cents": constrained,
        "status": "PROPOSED",
        "proposed_by_user_id": uid,
        "approved_by_user_id": None,
    })
    return ok_object(ser.estimate(rec), 201)


@bp.get("/revrec/contracts/<contract_id>/vc-estimates")
def list_estimates(contract_id):
    require_roles(*ALL_READ)
    get_contract_or_404(contract_id)
    items = [e for e in STORE.estimates.values() if e["contract_id"] == contract_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_created(items)
    return ok_list([ser.estimate(e) for e in items], len(items) or 1, 0, len(items))


@bp.post("/revrec/vc-estimates/<estimate_id>/approve")
def approve_estimate(estimate_id):
    uid = require_roles("RevenueManager")
    e = STORE.estimates.get(estimate_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "estimate_id does not identify an existing estimate")
    if e["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "approve requires the estimate to be PROPOSED")
    if uid == e["proposed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 409, "the approver must differ from the proposer")
    c = get_contract_or_404(e["contract_id"])
    new_vc = e["constrained_amount_cents"]

    # Prospectively compute the cascade so guards reject without mutating.
    alloc = catch_ups = None
    if c["status"] in ("APPROVED", "ACTIVE"):
        alloc, catch_ups = svc.plan_catch_ups(c, c["fixed_consideration_cents"], new_vc)
    if c["status"] == "ACTIVE" and catch_ups:
        svc.require_open_period(CLOCK.today())
    if alloc is not None and svc.check_over_recognition(c, alloc):
        raise ApiError(ERR_OVER_RECOGNITION, 422,
                       "reallocation would leave an obligation below its recognized amount")

    for prior in STORE.estimates.values():
        if prior["contract_id"] == c["id"] and prior["status"] == "APPROVED" and prior["id"] != estimate_id:
            prior["status"] = "SUPERSEDED"
            mark(prior)
    e["status"] = "APPROVED"
    e["approved_by_user_id"] = uid
    mark(e)
    c["active_vc_estimate_id"] = estimate_id
    c["vc_estimate_cents"] = new_vc
    mark(c)
    if alloc is not None:
        for p in svc.live_pobs(c["id"]):
            if p["allocated_amount_cents"] != alloc[p["id"]]:
                p["allocated_amount_cents"] = alloc[p["id"]]
                mark(p)
    if c["status"] == "ACTIVE" and catch_ups:
        for p, amount in catch_ups:
            svc.post_entry(c, p, "CATCH_UP_ADJUSTMENT", "ESTIMATE", amount, CLOCK.today())
    return ok_object(ser.estimate(e))


@bp.post("/revrec/vc-estimates/<estimate_id>/reject")
def reject_estimate(estimate_id):
    require_roles("RevenueManager")
    e = STORE.estimates.get(estimate_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "estimate_id does not identify an existing estimate")
    if e["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "reject requires the estimate to be PROPOSED")
    e["status"] = "REJECTED"
    mark(e)
    return ok_object(ser.estimate(e))
