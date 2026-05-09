"""IndirectCostAllocation — multi-project waterfall allocation."""

from decimal import Decimal, ROUND_HALF_UP

from common import money_to_json, rate_to_json, round_money, round_rate, stamp_immutable, to_decimal
from db import db
from errors import (
    ERR_ALLOCATION_RUN_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_PROJECT_NOT_FOUND,
    raise_error,
)


RATE_TABLE = {
    "NATIONAL":   {"DIRECT_COST": Decimal("0.20"), "PERSONNEL_COST": Decimal("0.25"), "FLOOR_AREA": Decimal("0.15")},
    "PROVINCIAL": {"DIRECT_COST": Decimal("0.15"), "PERSONNEL_COST": Decimal("0.18"), "FLOOR_AREA": Decimal("0.12")},
    "ENTERPRISE": {"DIRECT_COST": Decimal("0.10"), "PERSONNEL_COST": Decimal("0.12"), "FLOOR_AREA": Decimal("0.08")},
    "INTERNAL":   {"DIRECT_COST": Decimal("0.05"), "PERSONNEL_COST": Decimal("0.06"), "FLOOR_AREA": Decimal("0.04")},
}
LARGE_PROJECT_THRESHOLD = Decimal("1000000")
RATE_REDUCTION = Decimal("0.02")
GLOBAL_INDIRECT_POOL = Decimal("5000000")
VALID_BASES = {"DIRECT_COST", "PERSONNEL_COST", "FLOOR_AREA"}


def serialize_allocation(a):
    return {
        "id": a["id"],
        "allocation_run_id": a["allocation_run_id"],
        "project_id": a["project_id"],
        "allocation_base": a["allocation_base"],
        "allocation_rate": rate_to_json(a["allocation_rate"]),
        "base_value": money_to_json(a["base_value"]),
        "shared_share": rate_to_json(a["shared_share"]) if a.get("shared_share") is not None else None,
        "allocated_amount": money_to_json(a["allocated_amount"]),
        "created_at": a["created_at"],
    }


def _resolve_rate(funding_source, allocation_base, total_budget):
    base_rate = RATE_TABLE[funding_source][allocation_base]
    if total_budget > LARGE_PROJECT_THRESHOLD:
        rate = base_rate - RATE_REDUCTION
        if rate < 0:
            rate = Decimal("0")
    else:
        rate = base_rate
    return round_rate(rate)


def _compute_base_value(project, allocation_base):
    if allocation_base == "FLOOR_AREA":
        floor = project.get("floor_area_sqm")
        if floor is None:
            floor = Decimal("100")
        else:
            floor = to_decimal(floor)
        return floor

    # DIRECT_COST or PERSONNEL_COST: sum of paid reimbursements
    total = Decimal("0.00")
    for r in db.reimbursements.values():
        if r["project_id"] != project["id"]:
            continue
        if r["status"] != "PAID":
            continue
        bi = db.budget_items.get(r["budget_item_id"])
        if bi is None:
            continue
        if allocation_base == "DIRECT_COST":
            if bi["category"] != "OUTSOURCING":
                total += r["amount"]
        elif allocation_base == "PERSONNEL_COST":
            if bi["category"] == "PERSONNEL":
                total += r["amount"]
    return round_money(total)


def run_allocation(allocation_base, project_id=None):
    if allocation_base not in VALID_BASES:
        raise_error(ERR_INVALID_INPUT, "invalid allocation_base")

    # Resolve in-scope projects
    if project_id is not None:
        if project_id not in db.projects:
            raise_error(ERR_PROJECT_NOT_FOUND, f"project {project_id} not found")
        scope_projects = [db.projects[project_id]]
    else:
        scope_projects = [p for p in db.projects.values() if p["status"] in ("ACTIVE", "CLOSING")]

    run_id = db.new_id()

    # Step 1+2: compute raw amounts
    raws = []
    for p in scope_projects:
        base_value = _compute_base_value(p, allocation_base)
        rate = _resolve_rate(p["funding_source"], allocation_base, p.get("total_budget") or Decimal("0"))
        raw = round_money(to_decimal(base_value) * rate)
        raws.append({"project": p, "base_value": base_value, "rate": rate, "raw": raw})

    # Step 3: waterfall sharing
    total_raw = sum((r["raw"] for r in raws), Decimal("0.00"))
    if total_raw <= GLOBAL_INDIRECT_POOL:
        # everyone gets their raw in full
        for r in raws:
            r["allocated"] = round_money(r["raw"])
            r["shared_share"] = None
    else:
        # Sort descending by raw, tie-break by project_id ascending
        ordered = sorted(raws, key=lambda r: (-r["raw"], r["project"]["id"]))
        remaining = GLOBAL_INDIRECT_POOL
        for entry in ordered:
            give = min(entry["raw"], remaining)
            entry["allocated"] = round_money(give)
            entry["shared_share"] = (give / total_raw) if total_raw > 0 else Decimal("0")
            remaining -= give
        # rounding remainder accrues to the first (largest) project
        actual_sum = sum((e["allocated"] for e in ordered), Decimal("0.00"))
        diff = round_money(GLOBAL_INDIRECT_POOL - actual_sum)
        if diff != Decimal("0.00") and ordered:
            ordered[0]["allocated"] = round_money(ordered[0]["allocated"] + diff)
        # Assign back to raws (preserving original order)

    allocations = []
    for entry in raws:
        a = {
            "id": db.new_id(),
            "allocation_run_id": run_id,
            "project_id": entry["project"]["id"],
            "allocation_base": allocation_base,
            "allocation_rate": entry["rate"],
            "base_value": round_money(entry["base_value"]),
            "shared_share": entry.get("shared_share"),
            "allocated_amount": round_money(entry["allocated"]),
        }
        stamp_immutable(a)
        db.indirect_allocations[a["id"]] = a
        allocations.append(a)
        # Update project.indirect_cost_amount
        entry["project"]["indirect_cost_amount"] = a["allocated_amount"]

    db.allocation_runs[run_id] = [a["id"] for a in allocations]
    return run_id, allocations


def get_run_or_404(run_id):
    ids = db.allocation_runs.get(run_id)
    if ids is None:
        raise_error(ERR_ALLOCATION_RUN_NOT_FOUND, f"run {run_id} not found")
    return [db.indirect_allocations[i] for i in ids]
