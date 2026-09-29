"""priority_composite_score — the weighted prioritization score (PRD 3.5)."""

from datetime import timedelta
from decimal import Decimal

from db import db, new_child_row, ordered, touch
from numeric import clamp2, dec, r2

WEIGHT_SAFETY = Decimal("0.35")
WEIGHT_GROWTH = Decimal("0.20")
WEIGHT_REGULATORY = Decimal("0.25")
WEIGHT_EOS = Decimal("0.20")
SAFETY_RULS_COEFFICIENT = Decimal("0.75")
SAFETY_CORRECTIVE_POINTS = Decimal("4.00")
REGULATORY_NEAR_DEADLINE_DAYS = 365
EOS_HORIZON_DAYS = 730
EXPEDITE_THRESHOLD = Decimal("85.00")

HUNDRED = Decimal("100.00")


def compute(request):
    asset = db.assets[request["asset_id"]]
    cycle = db.cycles[request["cycle_id"]]
    department = db.departments[request["department_id"]]
    plan_year_start = cycle["_plan_year_start"]

    # Step 1 — safety driver.
    safety = r2((HUNDRED - dec(asset["adjusted_ruls_score"])) * SAFETY_RULS_COEFFICIENT
                + SAFETY_CORRECTIVE_POINTS * Decimal(asset["corrective_count_24m"]))
    if safety > HUNDRED:
        safety = HUNDRED

    # Step 2 — growth driver: round the percentage first, then look up the tier.
    current = Decimal(request["current_annual_volume"])
    projected = Decimal(request["projected_annual_volume"])
    denominator = current if current > 1 else Decimal(1)
    growth_pct = r2((projected - current) / denominator * Decimal(100))
    if growth_pct < Decimal("0.00"):
        growth = Decimal("0.00")
    elif growth_pct < Decimal("10.00"):
        growth = Decimal("25.00")
    elif growth_pct < Decimal("25.00"):
        growth = Decimal("50.00")
    elif growth_pct < Decimal("50.00"):
        growth = Decimal("75.00")
    else:
        growth = Decimal("100.00")

    # Step 3 — regulatory driver.
    if not request["regulatory_mandate_flag"]:
        regulatory = Decimal("0.00")
    else:
        deadline = request.get("_mandate_deadline")
        if deadline is not None and deadline <= plan_year_start + timedelta(
                days=REGULATORY_NEAR_DEADLINE_DAYS):
            regulatory = Decimal("100.00")
        else:
            regulatory = Decimal("70.00")

    # Step 4 — end-of-support driver, measured against the plan year start.
    oem = asset["_oem_support_end_date"]
    if oem <= plan_year_start:
        eos = Decimal("100.00")
    elif oem <= plan_year_start + timedelta(days=EOS_HORIZON_DAYS):
        eos = Decimal("60.00")
    else:
        eos = Decimal("0.00")

    # Step 5 — a single rounding of the weighted sum.
    weighted_sum = r2(WEIGHT_SAFETY * safety + WEIGHT_GROWTH * growth
                      + WEIGHT_REGULATORY * regulatory + WEIGHT_EOS * eos)

    # Step 6 — subtract the department's utilization penalty, then clamp.
    penalty = Decimal(department["utilization_penalty_points"])
    composite = clamp2(r2(weighted_sum - penalty))

    return {
        "safety_driver": safety,
        "growth_driver": growth,
        "regulatory_driver": regulatory,
        "eos_driver": eos,
        "composite_score": composite,
        "expedited": composite >= EXPEDITE_THRESHOLD,
        "department_penalty_points": department["utilization_penalty_points"],
        "asset_adjusted_ruls_snapshot": dec(asset["adjusted_ruls_score"]),
        "corrective_count_snapshot": asset["corrective_count_24m"],
    }


def request_scores(request_id):
    return [s for s in ordered(db.scores.values())
            if s["request_id"] == request_id]


def score_request(request, reason):
    """Step 8 — append a PriorityScore and mirror it onto the request.

    Returns True when the request's expedited flag flipped.
    """
    result = compute(request)
    existing = request_scores(request["id"])
    sequence = max([s["sequence"] for s in existing], default=0) + 1
    row = new_child_row({
        "request_id": request["id"],
        "sequence": sequence,
        "reason": reason,
        "asset_adjusted_ruls_snapshot": result["asset_adjusted_ruls_snapshot"],
        "corrective_count_snapshot": result["corrective_count_snapshot"],
        "safety_driver": result["safety_driver"],
        "growth_driver": result["growth_driver"],
        "regulatory_driver": result["regulatory_driver"],
        "eos_driver": result["eos_driver"],
        "department_penalty_points": result["department_penalty_points"],
        "composite_score": result["composite_score"],
        "expedited": result["expedited"],
    })
    db.scores[row["id"]] = row

    was_expedited = request["expedited"]
    request["safety_driver"] = result["safety_driver"]
    request["growth_driver"] = result["growth_driver"]
    request["regulatory_driver"] = result["regulatory_driver"]
    request["eos_driver"] = result["eos_driver"]
    request["composite_score"] = result["composite_score"]
    request["expedited"] = result["expedited"]
    return bool(was_expedited) != bool(result["expedited"])


def refresh_cycle_counts(cycle, bump=False):
    """Recompute scored_count/expedited_count; bump the version when changed.

    PRD 3.3: scored_count counts the cycle's requests standing in SCORED;
    expedited_count counts the cycle's requests whose expedited flag is
    currently true, with no status restriction.
    """
    scored = 0
    expedited = 0
    for req in db.requests.values():
        if req["cycle_id"] != cycle["id"]:
            continue
        if req["status"] == "SCORED":
            scored += 1
        if req["expedited"]:
            expedited += 1
    changed = (cycle["scored_count"] != scored
               or cycle["expedited_count"] != expedited)
    cycle["scored_count"] = scored
    cycle["expedited_count"] = expedited
    if bump or changed:
        touch(cycle)
    return changed
