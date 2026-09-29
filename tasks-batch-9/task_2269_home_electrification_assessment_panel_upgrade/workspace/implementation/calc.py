"""Calculation rules (scaffold section 1.3 / PRD sections 2.6, 3.2, 3.4, 3.5, 3.9)."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import clock
import store

# ---------------------------------------------------------------- constants --
SIZE_ADJUSTMENT = {
    1: "0.70",
    2: "0.80",
    3: "0.90",
    4: "1.00",
    5: "1.08",
    6: "1.16",
    7: "1.24",
}
CONDITIONAL_REDUCTION_PCT = Decimal("0.10")
ROLLING_WINDOW = 10
WEIGHTED_WINDOW_DAYS = 365
TRAVEL_BUFFER_MINUTES = 45
GROUP_ORDER = ["HVAC_GROUP", "WATER_GROUP", "APPLIANCE_GROUP", "ELECTRICAL_GROUP"]
POINTS = {"PASSED": 100, "CONDITIONAL_PASS": 70, "FAILED": 0}


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def floor_cents(value):
    """Floor a Decimal (or int) to a whole number of cents."""
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up(value, places=0):
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


# ------------------------------------------------- income tier assignment ---
def tier_cap_cents(program, tier):
    return {
        "LOW": program["low_tier_cap_cents"],
        "MODERATE": program["moderate_tier_cap_cents"],
        "STANDARD": program["standard_tier_cap_cents"],
    }[tier]


def tier_cost_share(program, tier):
    """Cost-share fraction for a tier; zero while the household has no tier."""
    if tier is None:
        return Decimal("0")
    return dec({
        "LOW": program["low_tier_cost_share_pct"],
        "MODERATE": program["moderate_tier_cost_share_pct"],
        "STANDARD": program["standard_tier_cost_share_pct"],
    }[tier])


def income_tier_assignment(program, verification):
    size = verification["household_size_attested"]
    factor = Decimal(SIZE_ADJUSTMENT[min(size, 7)])
    adjusted_median = dec(verification["county_median_income_cents"]) * factor
    ami_raw = (dec(verification["annual_household_income_cents"]) / adjusted_median) * Decimal(100)
    ami_percent = round_half_up(ami_raw, 1)
    if ami_percent <= dec(program["ami_low_threshold_pct"]):
        tier = "LOW"
    elif ami_percent <= dec(program["ami_moderate_threshold_pct"]):
        tier = "MODERATE"
    else:
        tier = "STANDARD"
    return {
        "ami_percent": float(ami_percent),
        "income_tier": tier,
        "cap_cents": tier_cap_cents(program, tier),
        "cost_share_pct": tier_cost_share(program, tier),
    }


# ------------------------------------------------ measure line / allocation --
def allocate(lines, program, cost_share, ceiling, final=False, conditional=False):
    """The two-stage allocation waterfall (PRD section 3.5).

    `lines` must already be sorted in the pinned order
    (sort_order ASC, then created_at ASC). Each entry is a dict with keys:
    ref, measure_code, group, is_panel, unit, maxq, mcap, qty, cost, rejected.
    """
    details = []
    for line in lines:
        qty = line["qty"] or 0
        cost = line["cost"] or 0
        raw = line["unit"] * min(qty, line["maxq"])
        cost_share_cap = floor_cents(dec(cost) * cost_share)
        amount = min(raw, line["mcap"], cost_share_cap)
        if line["is_panel"]:
            amount = min(amount, program["panel_upgrade_cap_cents"])
        if final and conditional:
            amount = floor_cents(dec(amount) * (Decimal(1) - CONDITIONAL_REDUCTION_PCT))
        if line.get("rejected"):
            amount = 0
        details.append({
            "ref": line.get("ref"),
            "measure_code": line["measure_code"],
            "group": line["group"],
            "raw_incentive_cents": raw,
            "cost_share_cap_cents": cost_share_cap,
            "capped_line_cents": amount,
            "allocated_cents": amount,
        })

    # Stage 2 -- combined-measure cap, group by group in the fixed group order.
    group_cap = program["group_cap_cents"]
    group_cap_applied = False
    residual_detail = None
    for group in GROUP_ORDER:
        members = [d for d in details if d["group"] == group]
        if not members:
            continue
        total = sum(d["allocated_cents"] for d in members)
        if total > group_cap:
            group_cap_applied = True
            assigned = 0
            for member in members[:-1]:
                value = (member["allocated_cents"] * group_cap) // total
                member["allocated_cents"] = value
                assigned += value
            members[-1]["allocated_cents"] = group_cap - assigned
            residual_detail = members[-1]

    group_capped_total = sum(d["allocated_cents"] for d in details)

    # Stage 3 -- household lifetime cap, applied strictly after stage 2.
    household_cap_applied = False
    if details and group_capped_total > ceiling:
        household_cap_applied = True
        assigned = 0
        for member in details[:-1]:
            value = (member["allocated_cents"] * ceiling) // group_capped_total
            member["allocated_cents"] = value
            assigned += value
        details[-1]["allocated_cents"] = ceiling - assigned
        residual_detail = details[-1]

    total_incentive = sum(d["allocated_cents"] for d in details)
    return {
        "lines": details,
        "group_capped_total_cents": group_capped_total,
        "household_cap_limit_cents": ceiling,
        "total_incentive_cents": total_incentive,
        "group_cap_applied": group_cap_applied,
        "household_cap_applied": household_cap_applied,
        "residual_cents_assigned_to_measure_code": (
            residual_detail["measure_code"] if residual_detail is not None else None
        ),
    }


# ------------------------------------------------------- benefit stacking ----
def benefit_stacking_limit(program, project, utility_rebate_cents):
    cost = project["actual_project_cost_cents"]
    if cost is None:
        cost = project["estimated_project_cost_cents"]
    utility = utility_rebate_cents
    state_before = project["final_total_incentive_cents"]
    if state_before is None:
        state_before = project["provisional_total_incentive_cents"]
    federal_pct = dec(program["federal_credit_pct"])
    federal_cap = program["federal_credit_cap_cents"]

    first_federal = min(
        federal_cap,
        max(0, floor_cents(federal_pct * dec(cost - state_before - utility))),
    )
    total_benefit = state_before + utility + first_federal
    limit = floor_cents(dec(cost) * dec(program["max_combined_benefit_pct"]))
    if total_benefit > limit:
        allowed_state = max(0, state_before - (total_benefit - limit))
    else:
        allowed_state = state_before
    final_federal = min(
        federal_cap,
        max(0, floor_cents(federal_pct * dec(cost - allowed_state - utility))),
    )
    residual = max(0, allowed_state + utility + final_federal - limit)
    return {
        "computed_state_incentive_before_cents": state_before,
        "allowed_state_incentive_cents": allowed_state,
        "allowed_federal_credit_cents": final_federal,
        "combined_benefit_limit_cents": limit,
        "residual_overage_cents": residual,
    }


# ------------------------------------------------------- quality scoring -----
def quality_candidates(contractor_id):
    """Inspections of every project of this contractor carrying a result."""
    candidates = []
    for inspection in store.inspections.values():
        if inspection["status"] not in POINTS:
            continue
        project = store.projects.get(inspection["project_id"])
        if project is None or project["contractor_id"] != contractor_id:
            continue
        candidates.append(inspection)
    candidates.sort(key=lambda i: ((i["result_recorded_at"] or ""), i["_seq"]), reverse=True)
    return candidates


def rolling_window_score(candidates):
    window = candidates[:ROLLING_WINDOW]
    if not window:
        return 100, 0
    total = sum(POINTS[i["status"]] for i in window)
    score = int(round_half_up(dec(total) / dec(len(window))))
    return score, len(window)


def severity_weighted_score(candidates):
    horizon = clock.now() - timedelta(days=WEIGHTED_WINDOW_DAYS)
    window = []
    for inspection in candidates:
        recorded = clock.parse_datetime(inspection["result_recorded_at"])
        if recorded is not None and recorded >= horizon:
            window.append(inspection)
    if not window:
        return 100, 0
    numerator = Decimal(0)
    denominator = Decimal(0)
    for inspection in window:
        weight = dec(1 + (inspection["deficiency_count"] or 0))
        numerator += weight * dec(POINTS[inspection["status"]])
        denominator += weight
    score = int(round_half_up(numerator / denominator))
    return score, len(window)
