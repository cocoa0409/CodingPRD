"""facility_allocation_waterfall and the conserved capital identity (PRD 3.6)."""

from decimal import Decimal

from db import db, new_row, ordered, touch
from errors import ApiError
from numeric import dec, r0, r2


def refresh_available(allocation):
    """PRD 2.10 — available_cents is always recomputed from the identity."""
    allocation["available_cents"] = (
        allocation["allocated_cents"] + allocation["released_contingency_cents"]
        - allocation["committed_cents"])
    return allocation["available_cents"]


def refresh_posture(allocation, cycle):
    """Refresh posture, keeping cycle.exhausted_allocation_count in step.

    Returns True when the cycle row was mutated.
    """
    if allocation["posture"] == "SUPERSEDED":
        return False
    target = "ACTIVE" if allocation["available_cents"] > 0 else "EXHAUSTED"
    if target == allocation["posture"]:
        return False
    allocation["posture"] = target
    if target == "EXHAUSTED":
        cycle["exhausted_allocation_count"] += 1
    else:
        cycle["exhausted_allocation_count"] -= 1
    return True


def eligible_requests(cycle):
    return [r for r in ordered(db.requests.values())
            if r["cycle_id"] == cycle["id"] and r["status"] == "SCORED"]


def project_cost(request):
    return (request["estimated_capital_cents"]
            + request["facility_modification_cents"])


def plan(cycle, method):
    """Compute the whole waterfall without writing anything."""
    requests = eligible_requests(cycle)

    groups = {}
    for req in requests:
        department = db.departments.get(req["department_id"])
        if department is None:
            continue
        groups.setdefault(department["facility_id"], []).append(req)

    system_contingency = r0(Decimal(cycle["total_capital_cents"])
                            * dec(cycle["contingency_pct"]))
    distributable = cycle["total_capital_cents"] - system_contingency

    facilities = []
    for facility_id, members in groups.items():
        demand = sum(project_cost(r) for r in members)
        weighted_numerator = sum(dec(r["composite_score"]) * Decimal(project_cost(r))
                                 for r in members)
        weighted_score = (r2(weighted_numerator / Decimal(demand)) if demand > 0
                          else Decimal("0.00"))
        facilities.append({
            "facility_id": facility_id,
            "demand_cents": demand,
            "weighted_score": weighted_score,
            "_seq": db.facilities[facility_id]["_seq"],
        })

    # Step 4 — rank order: weighted_score DESC, demand DESC, facility created_at ASC.
    facilities.sort(key=lambda f: (-f["weighted_score"], -f["demand_cents"],
                                   f["_seq"]))

    if method == "PRO_RATA":
        total_demand = sum(f["demand_cents"] for f in facilities)
        for f in facilities:
            if total_demand > 0:
                provisional = (distributable * f["demand_cents"]) // total_demand
            else:
                provisional = 0
            f["allocated_cents"] = min(f["demand_cents"], provisional)
        leftover = distributable - sum(f["allocated_cents"] for f in facilities)
        # Remainder sweep: walk rank order repeatedly, one cent at a time.
        while leftover > 0:
            progressed = False
            for f in facilities:
                if leftover == 0:
                    break
                if f["allocated_cents"] < f["demand_cents"]:
                    f["allocated_cents"] += 1
                    leftover -= 1
                    progressed = True
            if not progressed:
                break
    else:
        remaining = distributable
        for f in facilities:
            grant = min(f["demand_cents"], remaining)
            f["allocated_cents"] = grant
            remaining -= grant

    facility_pct = dec(cycle["facility_contingency_pct"])
    for f in facilities:
        f["contingency_reserve_cents"] = r0(Decimal(f["allocated_cents"])
                                            * facility_pct)

    contingency_drawn = sum(f["contingency_reserve_cents"] for f in facilities)

    return {
        "facilities": facilities,
        "requests": requests,
        "system_contingency_cents": system_contingency,
        "distributable_cents": distributable,
        "unallocated_cents": distributable - sum(f["allocated_cents"]
                                                 for f in facilities),
        "contingency_drawn_cents": contingency_drawn,
    }


def commit_plan(cycle, method, result, actor_id):
    """Write the plan: supersede prior rows, insert new ones, update the cycle."""
    for row in ordered(db.allocations.values()):
        if row["cycle_id"] == cycle["id"] and row["posture"] != "SUPERSEDED":
            row["posture"] = "SUPERSEDED"
            touch(row)

    for f in result["facilities"]:
        row = new_row({
            "cycle_id": cycle["id"],
            "facility_id": f["facility_id"],
            "demand_cents": f["demand_cents"],
            "weighted_score": f["weighted_score"],
            "allocated_cents": f["allocated_cents"],
            "contingency_reserve_cents": f["contingency_reserve_cents"],
            "contingency_status": "HELD",
            "released_contingency_cents": 0,
            "committed_cents": 0,
            "available_cents": f["allocated_cents"],
            "posture": "ACTIVE" if f["allocated_cents"] > 0 else "EXHAUSTED",
        })
        db.allocations[row["id"]] = row

    cycle["allocation_method"] = method
    cycle["system_contingency_cents"] = result["system_contingency_cents"]
    cycle["distributable_cents"] = result["distributable_cents"]
    cycle["unallocated_cents"] = result["unallocated_cents"]
    cycle["contingency_drawn_cents"] = result["contingency_drawn_cents"]
    cycle["allocation_count"] = len(result["facilities"])
    cycle["exhausted_allocation_count"] = 0
    cycle["allocated_by_user_id"] = actor_id
    cycle["status"] = "ALLOCATED"
    touch(cycle)
    return cycle
