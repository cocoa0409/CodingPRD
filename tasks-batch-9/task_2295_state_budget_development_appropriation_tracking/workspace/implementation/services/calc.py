"""The named calculations of SCAFFOLD section 1.3.

Every rounding here is round half up, and the three places where the ORDER of
rounding is part of the contract are commented inline.
"""

import db
import util
from services import constants as C
from services import core

# --------------------------------------------------------------------------
# executive_recommendation_amount
# --------------------------------------------------------------------------


def recommendation_amount(base_cents, packages):
    additive = 0
    subtractive = 0
    for package in packages:
        if package["package_type"] == "REDUCTION":
            subtractive += package["amount_cents"]
        else:
            additive += package["amount_cents"]
    return base_cents + additive - subtractive


# --------------------------------------------------------------------------
# cycle_balance_certification
# --------------------------------------------------------------------------


def balance_certification(cycle):
    adopted = core.adopted_general_revenue(cycle)
    # the reserve is rounded to the cent BEFORE the subtraction, never after
    required_reserve = util.pct_of_cents(cycle["constitutional_reserve_pct"], adopted)
    appropriable = adopted - required_reserve
    recommended = core.total_recommended(cycle)
    return {
        "adopted_general_fund_revenue_cents": adopted,
        "required_reserve_cents": required_reserve,
        "appropriable_cents": appropriable,
        "total_recommended_cents": recommended,
        "balanced": recommended <= appropriable,
    }


# --------------------------------------------------------------------------
# committee_running_balance -- a full replay in sequence_number order
# --------------------------------------------------------------------------


def committee_replay(appropriation, actions):
    """Return (pairs, final_balance) or (None, None) when the balance goes negative."""
    introduced = appropriation["introduced_amount_cents"]
    balance = introduced
    pairs = []
    for action in actions:
        kind = action["action_type"]
        if kind == "SET":
            balance = action["amount_cents"]
        elif kind == "INCREASE":
            balance = balance + action["amount_cents"]
        elif kind == "DECREASE":
            balance = balance - action["amount_cents"]
        elif kind == "RESTORE":
            balance = introduced
        elif kind == "STRIKE":
            balance = 0
        if balance < 0:
            return None, None
        pairs.append((action, balance))
    return pairs, balance


# --------------------------------------------------------------------------
# allotment_release_ceiling
# --------------------------------------------------------------------------


def release_ceiling(allotment, appropriation, cycle):
    quarter = allotment["quarter"]
    authority = core.authority_of(appropriation)
    # each of the quarter cap and the projected cash figure is rounded to the
    # cent BEFORE entering the minimum, never after
    quarter_cap = util.pct_of_cents(
        C.QUARTER_CAP_PCT[appropriation["fund_type"]][min(4, max(1, quarter))], authority
    )
    unreleased = authority - appropriation["released_cents"]
    projected_cash = util.pct_of_cents(
        C.CASH_FLOW_FACTOR[min(4, max(1, quarter))],
        cycle["adopted_general_fund_revenue_cents"],
    )
    cash_available = max(0, projected_cash - cycle["total_released_cents"])

    terms = [
        ("REQUEST", allotment["requested_cents"]),
        ("QUARTER_CAP", quarter_cap),
        ("UNRELEASED_AUTHORITY", unreleased),
        ("CASH_FLOW", cash_available),
    ]
    ceiling = min(value for _, value in terms)
    binding = None
    for label, value in terms:
        if value == ceiling:
            binding = label
            break
    return ceiling, binding


# --------------------------------------------------------------------------
# reduction_scenario_waterfall
# --------------------------------------------------------------------------


def reduction_candidates(cycle):
    accepted_requests = {}
    for request in db.agency_requests.values():
        if (
            request["budget_cycle_id"] == cycle["id"]
            and request["status"] == "ACCEPTED"
        ):
            accepted_requests[request["id"]] = request
    candidates = [
        package
        for package in db.decision_packages.values()
        if package["package_type"] == "REDUCTION"
        and package["status"] == "PROPOSED"
        and package["agency_request_id"] in accepted_requests
    ]
    accepted_base = sum(r["base_budget_cents"] for r in accepted_requests.values())
    return accepted_base, candidates


def reduction_waterfall(cycle, target_pct):
    accepted_base, candidates = reduction_candidates(cycle)
    # the target is rounded round_half_up exactly once, before the walk begins
    target = util.pct_of_cents(target_pct, accepted_base)
    ordered = sorted(
        candidates,
        key=lambda p: (p["priority_rank"], -p["amount_cents"], p["created_at"], p["_seq"]),
    )
    achieved = 0
    selected = []
    for package in ordered:
        if achieved >= target:  # inclusive stop test
            break
        selected.append(package["id"])
        achieved += package["amount_cents"]  # packages are never split
    return {
        "target_reduction_cents": target,
        "selected_package_ids": selected,
        "achieved_reduction_cents": achieved,
        "overshoot_cents": max(0, achieved - target),
        "feasibility": "FEASIBLE" if achieved >= target else "INFEASIBLE",
    }


# --------------------------------------------------------------------------
# reversion_carryforward_split
# --------------------------------------------------------------------------


def carryforward_split(appropriation):
    """Per-appropriation split; the cap is rounded per row, before any rollup."""
    if appropriation["authority_status"] == "LAPSED":
        return 0, 0
    authority = core.authority_of(appropriation)
    unexpended = max(0, authority - appropriation["expended_cents"])
    cap = util.pct_of_cents(
        C.CARRYFORWARD_CAP_PCT[appropriation["fund_type"]], authority
    )
    carryforward = min(unexpended, cap)
    return carryforward, unexpended - carryforward


# --------------------------------------------------------------------------
# federal_moe_compliance
# --------------------------------------------------------------------------


def moe_assessment(grant, basis, current_spend):
    if basis == "SINGLE_YEAR":
        assessed = current_spend
    else:
        # rounded to the cent BEFORE the comparison
        assessed = util.round_half_up(
            util.dec(
                current_spend
                + grant["moe_prior_year1_spend_cents"]
                + grant["moe_prior_year2_spend_cents"]
            )
            / util.dec(3)
        )
    baseline = grant["moe_baseline_cents"]
    status = "COMPLIANT" if assessed >= baseline else "DEFICIENT"
    return {
        "moe_current_spend_cents": current_spend,
        "moe_compliance_ratio": float(util.ratio(assessed, baseline, 6)),
        "moe_assessed_basis": basis,
        "moe_compliance_status": status,
    }


# --------------------------------------------------------------------------
# emergency_appropriation_capacity -- pinned four-step order
# --------------------------------------------------------------------------


def emergency_capacity(cycle):
    # step 1: the row being requested is deliberately excluded from this total
    total = 0
    for appropriation in core.appropriations_of(cycle):
        if (
            appropriation["fund_type"] == "GENERAL"
            and appropriation["authority_status"] == "ENACTED"
        ):
            total += core.authority_of(appropriation)
    # step 2: the reserve floor is rounded before the step 3 subtraction
    required_minimum = util.pct_of_cents(cycle["constitutional_reserve_pct"], total)
    # step 3
    capacity = max(
        0,
        cycle["reserve_balance_cents"]
        - cycle["emergency_granted_cents"]
        - required_minimum,
    )
    return capacity


# --------------------------------------------------------------------------
# transfer statutory cap
# --------------------------------------------------------------------------


def transfer_cap(source):
    return util.pct_of_cents(C.TRANSFER_AUTHORITY_PCT, source["enacted_amount_cents"])
