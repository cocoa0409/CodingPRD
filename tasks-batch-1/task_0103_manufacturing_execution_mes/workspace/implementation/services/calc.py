"""Calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3.3, §3.4, §3.9, §3.10).

All money is integer cents using Decimal with ROUND_HALF_UP; OEE ratios are
4-decimal Decimals clamped to [0, 1]. Never float for money.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

QUALITY_FLOOR = Decimal("0.95")
LABOR_RATE_CENTS_PER_SEC = Decimal(2)


def _D(x):
    """Coerce a stored number (int/float/str) to Decimal safely."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    if isinstance(x, int):
        return Decimal(x)
    # floats go through str() to avoid binary-float artifacts
    return Decimal(str(x))


def round_cents(value):
    """Round a Decimal to whole cents, round-half-up, return int."""
    return int(_D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """Round to 4 decimal places, round-half-up. Return a float for JSON."""
    q = _D(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def clamp01(value):
    v = _D(value)
    if v < 0:
        return Decimal(0)
    if v > 1:
        return Decimal(1)
    return v


# ---------------------------------------------------------------------------
# OEE recompute (PRD §3.3)
# ---------------------------------------------------------------------------
def primary_op_cycle_time(machine_id):
    """Primary operation for a machine: the Operation that runs on it with the
    LOWEST sequence_no across all routings; tie-break by earliest created_at.
    Returns the ideal_cycle_time_secs (Decimal) or None when no op references
    this machine.
    """
    ops = [o for o in db.operations.values() if o["machine_id"] == machine_id]
    if not ops:
        return None
    ops.sort(key=lambda o: (o["sequence_no"], o.get("created_at", ""), o.get("_seq", 0)))
    return _D(ops[0]["ideal_cycle_time_secs"])


def recompute_oee(machine):
    """Recompute A/P/Q and overall OEE from the machine's run logs; set
    quality_flagged. Mutates the machine record in place (caller bumps version).
    """
    logs = [l for l in db.machine_run_logs.values() if l["machine_id"] == machine["id"]]

    run_sum = sum((_D(l["run_time_secs"]) for l in logs), Decimal(0))
    total = sum((_D(l["total_units"]) for l in logs), Decimal(0))
    good = sum((_D(l["good_units"]) for l in logs), Decimal(0))

    planned = _D(machine["planned_production_secs"])
    a_avail = clamp01(run_sum / planned) if planned != 0 else Decimal(0)

    cycle = primary_op_cycle_time(machine["id"])
    if cycle is None or run_sum == 0:
        p_perf = Decimal(0)
    else:
        p_perf = clamp01((cycle * total) / run_sum)

    if total == 0:
        q_qual = Decimal(0)
    else:
        q_qual = clamp01(good / total)

    machine["oee_availability"] = round4(a_avail)
    machine["oee_performance"] = round4(p_perf)
    machine["oee_quality"] = round4(q_qual)
    # overall = round ONCE from full-precision (clamped, NOT pre-rounded) ratios
    machine["oee_overall"] = round4(a_avail * p_perf * q_qual)

    # machine_quality_flag: oee_quality <= QUALITY_FLOOR (<=, boundary flags).
    # Comparison is on the 4-decimal stored oee_quality value.
    machine["quality_flagged"] = _D(machine["oee_quality"]) <= QUALITY_FLOOR


# ---------------------------------------------------------------------------
# Multi-level BOM explosion (PRD §3.4)
# ---------------------------------------------------------------------------
def explode_bom(product_id, order_qty):
    """Walk the BomLine DAG top-down from product_id. Returns an ordered list of
    (component_product_id, required_qty: Decimal) — one entry per DISTINCT
    component product reached (subassemblies AND raw materials), quantities
    accumulated across every path.

    For each edge: effective_qty_per = quantity_per / (1 - scrap_factor_pct/100).
    required_qty[component] += order_qty * product(effective_qty_per along path).
    """
    required = {}            # component_product_id -> Decimal
    first_seen = {}          # component_product_id -> ordering key

    # Build adjacency: parent -> list of bom lines (ordered by creation).
    children = {}
    for bl in db.bom_lines.values():
        children.setdefault(bl["parent_product_id"], []).append(bl)
    for plist in children.values():
        plist.sort(key=lambda b: (b.get("created_at", ""), b.get("_seq", 0)))

    order = [0]

    def walk(prod_id, accumulated):
        for bl in children.get(prod_id, []):
            comp = bl["component_product_id"]
            scrap = _D(bl.get("scrap_factor_pct", 0))
            denom = Decimal(1) - (scrap / Decimal(100))
            eff = _D(bl["quantity_per"]) / denom
            path_qty = accumulated * eff
            required[comp] = required.get(comp, Decimal(0)) + path_qty
            if comp not in first_seen:
                first_seen[comp] = order[0]
                order[0] += 1
            # descend into the component (it may itself be a parent assembly)
            walk(comp, path_qty)

    walk(product_id, _D(order_qty))

    result = sorted(required.keys(), key=lambda c: first_seen[c])
    return [(c, required[c]) for c in result]


def standard_cost_for(required_qty, unit_cost_cents):
    """Per-component standard cost: round(required_qty * unit_cost_cents)."""
    return round_cents(_D(required_qty) * _D(unit_cost_cents))


# ---------------------------------------------------------------------------
# Material variance / actual cost (PRD §3.9, §3.10)
# ---------------------------------------------------------------------------
def actual_material_cost(work_order_id):
    """Sum over every non-reversed LotIssue for this order of
    round(issued_qty * source-lot product unit_cost_cents), per-issue rounded
    THEN summed. Returns int cents.
    """
    total = 0
    for issue in db.lot_issues.values():
        if issue.get("reversed"):
            continue
        demand = db.component_demands.get(issue["component_demand_id"])
        if demand is None or demand["work_order_id"] != work_order_id:
            continue
        lot = db.lots.get(issue["lot_id"])
        if lot is None:
            continue
        product = db.products.get(lot["product_id"])
        unit_cost = _D(product["unit_cost_cents"]) if product else Decimal(0)
        total += round_cents(_D(issue["issued_qty"]) * unit_cost)
    return total


def standard_total_cost(work_order_id):
    """Sum of standard_cost_cents across the order's component demands."""
    total = 0
    for d in db.component_demands.values():
        if d["work_order_id"] == work_order_id:
            total += int(d.get("standard_cost_cents", 0))
    return total


def material_variance(work_order_id):
    """actual_cost - standard_cost (integer cents)."""
    return actual_material_cost(work_order_id) - standard_total_cost(work_order_id)


def labor_total_cost(work_order_id):
    """Sum of per-completed-operation labor, each rounded BEFORE summing.

    op_secs = Operation.ideal_cycle_time_secs * wop.good_qty
    op_labor_cents = round(op_secs * LABOR_RATE_CENTS_PER_SEC)
    """
    total = 0
    for wop in db.work_order_operations.values():
        if wop["work_order_id"] != work_order_id:
            continue
        if wop["status"] != "COMPLETED":
            continue
        op = db.operations.get(wop["operation_id"])
        if op is None:
            continue
        op_secs = _D(op["ideal_cycle_time_secs"]) * _D(wop.get("good_qty", 0))
        total += round_cents(op_secs * LABOR_RATE_CENTS_PER_SEC)
    return total
