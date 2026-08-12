"""Business logic: certificate queries, cost calculations, state-machine cascades."""

from decimal import Decimal

from db import STORE, bump, logical_now, new_record
from errors import ApiError
from util import (
    BLEND_CAP,
    GRADE_RANK,
    REGRIND_VALUE_PCT,
    SETUP_FEE,
    TRIM_ALLOWANCE_FACTOR,
    q2,
    q3,
    q4,
    timedelta_seconds,
)


# ---- Lookups ----

def get_lot(lot_id):
    lot = STORE["material_lots"].get(lot_id)
    if lot is None:
        raise ApiError("ERR_MATERIAL_LOT_NOT_FOUND", "MaterialLot %s does not exist" % lot_id)
    return lot


def get_batch(batch_id):
    batch = STORE["regrind_batches"].get(batch_id)
    if batch is None:
        raise ApiError("ERR_REGRIND_BATCH_NOT_FOUND", "RegrindBatch %s does not exist" % batch_id)
    return batch


def get_tool(tool_id):
    tool = STORE["tools"].get(tool_id)
    if tool is None:
        raise ApiError("ERR_TOOL_NOT_FOUND", "Tool %s does not exist" % tool_id)
    return tool


def get_spec(spec_id):
    spec = STORE["packaging_specs"].get(spec_id)
    if spec is None:
        raise ApiError("ERR_PACKAGING_SPEC_NOT_FOUND", "PackagingSpec %s does not exist" % spec_id)
    return spec


def get_order(order_id):
    order = STORE["production_orders"].get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "ProductionOrder %s does not exist" % order_id)
    return order


def get_allocation(allocation_id):
    alloc = STORE["material_allocations"].get(allocation_id)
    if alloc is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND", "MaterialAllocation %s does not exist" % allocation_id)
    return alloc


def get_resource(resource_id):
    res = STORE["machine_resources"].get(resource_id)
    if res is None:
        raise ApiError("ERR_MACHINE_RESOURCE_NOT_FOUND", "MachineResource %s does not exist" % resource_id)
    return res


def get_run(run_id):
    run = STORE["forming_runs"].get(run_id)
    if run is None:
        raise ApiError("ERR_FORMING_RUN_NOT_FOUND", "FormingRun %s does not exist" % run_id)
    return run


def get_scrap(scrap_id):
    scrap = STORE["scrap_records"].get(scrap_id)
    if scrap is None:
        raise ApiError("ERR_SCRAP_RECORD_NOT_FOUND", "ScrapRecord %s does not exist" % scrap_id)
    return scrap


def get_inspection(inspection_id):
    insp = STORE["quality_inspections"].get(inspection_id)
    if insp is None:
        raise ApiError("ERR_QUALITY_INSPECTION_NOT_FOUND", "QualityInspection %s does not exist" % inspection_id)
    return insp


def get_task(task_id):
    task = STORE["assembly_tasks"].get(task_id)
    if task is None:
        raise ApiError("ERR_ASSEMBLY_TASK_NOT_FOUND", "AssemblyTask %s does not exist" % task_id)
    return task


def get_cert(cert_id):
    cert = STORE["cleanliness_certificates"].get(cert_id)
    if cert is None:
        raise ApiError("ERR_CERTIFICATE_NOT_FOUND", "CleanlinessCertificate %s does not exist" % cert_id)
    return cert


def allocations_of(order_id):
    return [a for a in STORE["material_allocations"].values() if a["production_order_id"] == order_id]


def runs_of(order_id):
    return [r for r in STORE["forming_runs"].values() if r["production_order_id"] == order_id]


# ---- Mass invariants (SCAFFOLD calculations: lot_mass_conservation) ----

def lot_recompute(lot):
    lot["available_kg"] = lot["quantity_kg"] - lot["allocated_kg"] - lot["consumed_kg"]


def batch_recompute(batch):
    batch["available_kg"] = batch["accumulated_kg"] - batch["reserved_kg"] - batch["consumed_kg"]


# ---- Certificates (SCAFFOLD calculation: certificate_validity) ----

def certs_for(subject_type, subject_id):
    return [
        c for c in STORE["cleanliness_certificates"].values()
        if c["subject_type"] == subject_type and c["subject_id"] == subject_id
    ]


def cert_is_valid(cert, at=None):
    """Half-open [issued_at, expires_at) against the server logical clock."""
    t = at if at is not None else logical_now()
    return cert["issued_at"] <= t < cert["expires_at"]


def cert_exists_at_grade(subject_type, subject_id, min_grade):
    """Any certificate for the subject at grade rank >= min_grade, regardless of expiry."""
    need = GRADE_RANK[min_grade]
    return any(GRADE_RANK[c["grade"]] >= need for c in certs_for(subject_type, subject_id))


def valid_cert_at_grade(subject_type, subject_id, min_grade):
    """Any certificate for the subject at grade rank >= min_grade AND currently valid."""
    need = GRADE_RANK[min_grade]
    return any(
        GRADE_RANK[c["grade"]] >= need and cert_is_valid(c)
        for c in certs_for(subject_type, subject_id)
    )


# ---- Cost calculations (SCAFFOLD calculations: order_cost, tool_amortization_charge) ----

def tooling_charge_for(order):
    tool = get_tool(order["tool_id"])
    if tool["status"] == "PROTOTYPE":
        # prototype_flat variant: full prototype build cost on the order
        return q2(tool["prototype_cost"])
    if tool["production_cost"] is not None:
        # production_per_shot variant
        per_shot = q4(tool["production_cost"] / Decimal(tool["rated_lifetime_shots"]))
        return q2(per_shot * Decimal(order["ordered_qty"]))
    return q2(tool["prototype_cost"])


def reference_virgin_cost(order, alloc_status):
    """unit_cost_per_kg of the order's virgin allocation with the greatest qty_kg;
    tie-break: earliest created_at (insertion order)."""
    cands = [
        a for a in allocations_of(order["id"])
        if a["source_type"] == "VIRGIN_LOT" and a["status"] == alloc_status
    ]
    if not cands:
        return Decimal("0")
    best = max(cands, key=lambda a: (a["qty_kg"], -a["_seq"]))
    return get_lot(best["lot_id"])["unit_cost_per_kg"]


def compute_provisional_cost(order):
    """Prices the plan: standard cycle/rate over ordered_qty; RESERVED allocations."""
    machine = q2(
        Decimal(order["ordered_qty"]) * Decimal(order["std_cycle_time_s"])
        / Decimal(3600) * order["std_machine_rate_per_hour"]
    )
    ref = reference_virgin_cost(order, "RESERVED")
    regrind_unit = REGRIND_VALUE_PCT * ref
    mat = Decimal("0")
    for a in allocations_of(order["id"]):
        if a["status"] != "RESERVED":
            continue
        if a["source_type"] == "VIRGIN_LOT":
            mat += a["qty_kg"] * get_lot(a["lot_id"])["unit_cost_per_kg"]
        else:
            mat += a["qty_kg"] * regrind_unit
    material = q2(mat)
    tooling = tooling_charge_for(order)
    total = q2(SETUP_FEE + machine + material + tooling)
    return total, tooling


def compute_final_cost(order):
    """Prices actuality: measured run windows and station rates; CONSUMED allocations."""
    machine_sum = Decimal("0")
    for run in runs_of(order["id"]):
        if run["status"] != "COMPLETED":
            continue
        station = get_resource(run["station_id"])
        hours = timedelta_seconds(run["actual_end"] - run["planned_start"]) / Decimal(3600)
        machine_sum += q4(station["machine_rate_per_hour"] * hours)
    machine = q2(machine_sum)
    ref = reference_virgin_cost(order, "CONSUMED")
    regrind_unit = REGRIND_VALUE_PCT * ref
    mat = Decimal("0")
    for a in allocations_of(order["id"]):
        if a["status"] != "CONSUMED":
            continue
        if a["source_type"] == "VIRGIN_LOT":
            mat += a["qty_kg"] * get_lot(a["lot_id"])["unit_cost_per_kg"]
        else:
            mat += a["qty_kg"] * regrind_unit
    material = q2(mat)
    tooling = tooling_charge_for(order)
    return q2(SETUP_FEE + machine + material + tooling)


# ---- Allocation balance mutation ----

def allocation_source(alloc):
    if alloc["source_type"] == "VIRGIN_LOT":
        return get_lot(alloc["lot_id"])
    return get_batch(alloc["regrind_batch_id"])


def reserve_balance(alloc):
    if alloc["source_type"] == "VIRGIN_LOT":
        lot = get_lot(alloc["lot_id"])
        lot["allocated_kg"] += alloc["qty_kg"]
        lot_recompute(lot)
        bump(lot)
    else:
        batch = get_batch(alloc["regrind_batch_id"])
        batch["reserved_kg"] += alloc["qty_kg"]
        batch_recompute(batch)
        bump(batch)


def release_balance(alloc):
    if alloc["source_type"] == "VIRGIN_LOT":
        lot = get_lot(alloc["lot_id"])
        lot["allocated_kg"] -= alloc["qty_kg"]
        lot_recompute(lot)
        bump(lot)
    else:
        batch = get_batch(alloc["regrind_batch_id"])
        batch["reserved_kg"] -= alloc["qty_kg"]
        batch_recompute(batch)
        bump(batch)


def release_allocation(alloc):
    """RESERVED|REVIEW -> RELEASED with source balance restoration."""
    alloc["status"] = "RELEASED"
    bump(alloc)
    release_balance(alloc)


# ---- Order completion cascade (SCAFFOLD: ProductionOrder schedule RUNNING -> COMPLETED) ----

def complete_order(order):
    # Hop 1: every allocation still RESERVED -> CONSUMED
    for alloc in allocations_of(order["id"]):
        if alloc["status"] != "RESERVED":
            continue
        alloc["status"] = "CONSUMED"
        bump(alloc)
        # Hop 2: shift balances on the source pool
        if alloc["source_type"] == "VIRGIN_LOT":
            lot = get_lot(alloc["lot_id"])
            lot["allocated_kg"] -= alloc["qty_kg"]
            lot["consumed_kg"] += alloc["qty_kg"]
            lot_recompute(lot)
            bump(lot)
            # Hop 3: lot depleted at exactly zero available
            if lot["status"] == "CERTIFIED" and lot["available_kg"] == 0:
                lot["status"] = "DEPLETED"
                bump(lot)
        else:
            batch = get_batch(alloc["regrind_batch_id"])
            batch["reserved_kg"] -= alloc["qty_kg"]
            batch["consumed_kg"] += alloc["qty_kg"]
            batch_recompute(batch)
            bump(batch)
    order["final_cost"] = compute_final_cost(order)
    order["schedule_status"] = "COMPLETED"
    bump(order)


def check_order_completion(order):
    """Automatic completion: shots target met AND quality RELEASED.
    Evaluated at run complete and at PASS disposition."""
    if (
        order["schedule_status"] == "RUNNING"
        and order["shots_completed"] >= order["ordered_qty"]
        and order["quality_status"] == "RELEASED"
    ):
        complete_order(order)
