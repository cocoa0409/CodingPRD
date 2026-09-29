"""Service layer: ledgers, derived-value recomputation and cascades A-H.

Every derived value here is recomputed from its declared row set rather than
patched incrementally, and every row a cascade touches is restamped and has its
version incremented exactly as PRD 2.10 requires.
"""
from decimal import Decimal

import calc
import core
from core import S, ZERO, q2, q3, q4, touch

# --------------------------------------------------------------------------
# ResinLot three-bucket mass ledger.  available + reserved + consumed == received.
# --------------------------------------------------------------------------
def _assert_lot_ledger(lot):
    total = q3(lot["available_kg"] + lot["reserved_kg"] + lot["consumed_kg"])
    if total != q3(lot["received_kg"]):
        raise AssertionError("resin lot ledger broken on %s" % lot["id"])


def lot_reserve(lot, kg):
    lot["available_kg"] = q3(lot["available_kg"] - kg)
    lot["reserved_kg"] = q3(lot["reserved_kg"] + kg)
    if lot["status"] == "AVAILABLE" and lot["available_kg"] == q3(ZERO):
        lot["status"] = "DEPLETED"
    _assert_lot_ledger(lot)
    touch(lot)


def lot_consume(lot, kg):
    """Irreversible: reserved -> consumed, available untouched."""
    lot["reserved_kg"] = q3(lot["reserved_kg"] - kg)
    lot["consumed_kg"] = q3(lot["consumed_kg"] + kg)
    if lot["status"] == "AVAILABLE" and lot["available_kg"] == q3(ZERO):
        lot["status"] = "DEPLETED"
    _assert_lot_ledger(lot)
    touch(lot)


def lot_return(lot, kg):
    """Compensating move: reserved -> available.  Revives a DEPLETED lot."""
    lot["reserved_kg"] = q3(lot["reserved_kg"] - kg)
    lot["available_kg"] = q3(lot["available_kg"] + kg)
    revived = False
    if lot["status"] == "DEPLETED" and lot["available_kg"] > q3(ZERO):
        lot["status"] = "AVAILABLE"
        revived = True
    _assert_lot_ledger(lot)
    touch(lot)
    return revived


# --------------------------------------------------------------------------
# ProductModel two-bucket warranty ledger.
# --------------------------------------------------------------------------
def _assert_reserve_ledger(model):
    if (model["warranty_reserve_cents"] + model["warranty_paid_cents"]
            != model["initial_warranty_reserve_cents"]):
        raise AssertionError("warranty ledger broken on %s" % model["id"])


def reserve_draw(model, amount_cents):
    model["warranty_reserve_cents"] -= amount_cents
    model["warranty_paid_cents"] += amount_cents
    _assert_reserve_ledger(model)
    touch(model)


def reserve_restore(model, amount_cents):
    model["warranty_reserve_cents"] += amount_cents
    model["warranty_paid_cents"] -= amount_cents
    _assert_reserve_ledger(model)
    touch(model)


# --------------------------------------------------------------------------
# Cycle charge roll-ups.
# --------------------------------------------------------------------------
def recompute_cycle_rollups(cycle):
    charged, weighted, regrind = calc.cycle_rollups(cycle)
    cycle["charged_mass_kg"] = charged
    cycle["weighted_melt_index_g10min"] = weighted
    cycle["cycle_regrind_pct"] = regrind


# --------------------------------------------------------------------------
# ProductionOrder derived values and blocked-state sweeps.
# --------------------------------------------------------------------------
def apply_cost(order):
    figures = calc.order_cost(order)
    order["material_cost_cents"] = figures["material_cost_cents"]
    order["oven_energy_cost_cents"] = figures["oven_energy_cost_cents"]
    order["overhead_cents"] = figures["overhead_cents"]
    order["total_cost_cents"] = figures["total_cost_cents"]
    order["unit_cost_cents"] = figures["unit_cost_cents"]


def recompute_completion(order):
    """Recompute both counters, then apply the COMPLETE / IN_PRODUCTION edges."""
    completed, scrapped = calc.order_completion(order)
    order["completed_qty"] = completed
    order["scrapped_qty"] = scrapped
    if order["status"] == "IN_PRODUCTION" and completed >= order["ordered_qty"]:
        order["status"] = "COMPLETE"
    elif order["status"] == "COMPLETE" and completed < order["ordered_qty"]:
        order["status"] = "IN_PRODUCTION"
    apply_cost(order)


def sweep_unblock_resin():
    """Unblock sweep: a qualified lot has returned.  BLOCKED_RESIN orders move to
    READY_TO_SCHEDULE, or to BLOCKED_WAREHOUSE when their site is FROZEN."""
    count = 0
    for order in core.sorted_rows(core.rows("production_orders")):
        if order["status"] != "BLOCKED_RESIN":
            continue
        model = S.product_models.get(order["product_model_id"])
        if model is None or calc.qualified_lot_count(model) < 1:
            continue
        site = S.warehouses.get(order["target_warehouse_id"])
        if site is not None and site["posture"] == "FROZEN":
            order["status"] = "BLOCKED_WAREHOUSE"
            order["blocked_reason"] = "WAREHOUSE_FROZEN"
        else:
            order["status"] = "READY_TO_SCHEDULE"
            order["blocked_reason"] = None
        touch(order)
        count += 1
    return count


def sweep_block_resin():
    """Blocking sweep: a lot left AVAILABLE.  Orders with no qualified lot left
    and work still outstanding move to BLOCKED_RESIN."""
    count = 0
    for order in core.sorted_rows(core.rows("production_orders")):
        if order["status"] not in ("READY_TO_SCHEDULE", "IN_PRODUCTION"):
            continue
        if order["completed_qty"] >= order["ordered_qty"]:
            continue
        model = S.product_models.get(order["product_model_id"])
        if model is None or calc.qualified_lot_count(model) >= 1:
            continue
        order["status"] = "BLOCKED_RESIN"
        order["blocked_reason"] = "NO_QUALIFIED_RESIN_LOT"
        touch(order)
        count += 1
    return count


# --------------------------------------------------------------------------
# Warehouse footprint, posture and the posture cascade (CASCADE-H links 2-4).
# --------------------------------------------------------------------------
def recompute_warehouse(site, bump=True):
    committed = calc.warehouse_committed_cube(site)
    site["committed_cube_m3"] = committed
    site["utilization_pct"] = q2(
        committed / site["footprint_capacity_cube_m3"] * Decimal(100))
    site["posture"] = calc.derive_posture(site["utilization_pct"], site)
    if bump:
        touch(site)
    posture_cascade(site)


def posture_cascade(site):
    """A site that reached the frozen threshold blocks its orders; one that has
    left FROZEN releases them again, subject to a qualified lot existing."""
    for order in core.sorted_rows(core.rows("production_orders")):
        if order["target_warehouse_id"] != site["id"]:
            continue
        if site["posture"] == "FROZEN":
            if order["status"] in ("READY_TO_SCHEDULE", "IN_PRODUCTION"):
                order["status"] = "BLOCKED_WAREHOUSE"
                order["blocked_reason"] = "WAREHOUSE_FROZEN"
                touch(order)
        else:
            if order["status"] == "BLOCKED_WAREHOUSE":
                model = S.product_models.get(order["product_model_id"])
                if model is not None and calc.qualified_lot_count(model) >= 1:
                    order["status"] = "READY_TO_SCHEDULE"
                    order["blocked_reason"] = None
                    touch(order)


def recompute_bucket(bucket):
    bucket["build_ahead_cap_qty"] = calc.build_ahead_cap_qty(bucket)
    bucket["build_ahead_committed_qty"] = calc.build_ahead_committed_qty(bucket)
    touch(bucket)


def recompute_bucket_of(unit_bucket_id):
    if not unit_bucket_id:
        return
    bucket = S.demand_buckets.get(unit_bucket_id)
    if bucket is not None:
        recompute_bucket(bucket)


# --------------------------------------------------------------------------
# Nest-group vacate half of the footprint rule, with anchor promotion.
# --------------------------------------------------------------------------
def vacate_unit(unit):
    """Clear a hull's zone occupancy and promote the earliest surviving follower
    of its nest group.  Promotion RAISES the group's footprint."""
    site_id = unit.get("warehouse_id")
    zone = unit.get("storage_zone_code")
    model_id = unit["product_model_id"]
    was_anchor = bool(unit.get("is_zone_anchor"))
    unit["storage_zone_code"] = None
    unit["stored_at"] = None
    unit["demand_bucket_id"] = None
    unit["stored_footprint_cube_m3"] = q4(ZERO)
    unit["is_zone_anchor"] = False
    if not (was_anchor and site_id and zone):
        return
    followers = [u for u in calc.occupying_units(site_id)
                 if u["id"] != unit["id"]
                 and u.get("storage_zone_code") == zone
                 and u["product_model_id"] == model_id]
    if not followers:
        return
    followers.sort(key=lambda u: (u["stored_at"], u["hull_serial"]))
    promoted = followers[0]
    model = S.product_models.get(model_id)
    promoted["is_zone_anchor"] = True
    promoted["stored_footprint_cube_m3"] = q4(model["gross_cube_m3"])
    touch(promoted)


# --------------------------------------------------------------------------
# Charge release and cycle abort: the shared tail of cascades A, E, F, G,
# the mould service hold, CASCADE-B links 2-5 and order cancellation.
# --------------------------------------------------------------------------
def release_charge(charge, reason):
    """RESERVED -> RELEASED, returning charge_kg from reserved_kg to available_kg."""
    lot = S.resin_lots.get(charge["resin_lot_id"])
    charge["status"] = "RELEASED"
    charge["released_reason"] = reason
    touch(charge)
    revived = lot_return(lot, charge["charge_kg"])
    return revived


def abort_cycle(cycle, abort_reason, release_reason, free_mold=True):
    """Abort one cycle and release every charge it still holds.  A cycle past
    oven start keeps its CONSUMED charges - consumption is irreversible."""
    released = 0
    for charge in core.sorted_rows(calc.charges_of_cycle(cycle)):
        if charge["status"] != "RESERVED":
            continue
        release_charge(charge, release_reason)
        released += 1
    cycle["status"] = "ABORTED"
    cycle["abort_reason"] = abort_reason
    recompute_cycle_rollups(cycle)
    touch(cycle)
    if free_mold and cycle.get("mold_id"):
        mold = S.molds.get(cycle["mold_id"])
        if mold is not None and mold["status"] == "IN_CYCLE":
            mold["status"] = "AVAILABLE"
            touch(mold)
    return released


def abort_scheduled_cycles(predicate, abort_reason, release_reason):
    """Head of the shared compensating cascade used by the mould service hold,
    CASCADE-B, CASCADE-E, CASCADE-F and CASCADE-G."""
    aborted = 0
    released = 0
    for cycle in core.sorted_rows(core.rows("molding_cycles")):
        if cycle["status"] != "SCHEDULED":
            continue
        if not predicate(cycle):
            continue
        released += abort_cycle(cycle, abort_reason, release_reason)
        aborted += 1
    return aborted, released


# --------------------------------------------------------------------------
# Hull minting at demould (deterministic serials, no random value).
# --------------------------------------------------------------------------
def mint_units(cycle, mold, order):
    existing = len(calc.units_of_order(order))
    build_seq = existing + 1
    minted = []
    for cavity_index in range(1, mold["cavity_count"] + 1):
        serial = "%s-%02d-%04d" % (order["order_code"], cavity_index,
                                   build_seq + cavity_index - 1)
        unit = {
            "molding_cycle_id": cycle["id"],
            "product_model_id": mold["product_model_id"],
            "cavity_index": cavity_index,
            "hull_serial": serial,
            "warehouse_id": None,
            "outfitted_by_technician_id": None,
            "inspected_by_technician_id": None,
            "trim_waste_kg": q3(ZERO),
            "hardware_kit_serial": None,
            "wall_thickness_points": [],
            "mean_wall_thickness_mm": None,
            "wall_sd_mm": None,
            "wall_cv_pct": None,
            "min_wall_thickness_mm": None,
            "impact_test_joules": None,
            "cosmetic_defect_grade": None,
            "final_warpage_index": None,
            "inspection_verdict": "PENDING",
            "rework_count": 0,
            "build_status": "DEMOLDED",
            "logistics_status": "UNALLOCATED",
            "storage_zone_code": None,
            "stored_footprint_cube_m3": q4(ZERO),
            "is_zone_anchor": False,
            "stored_at": None,
            "demand_bucket_id": None,
            "delivered_at": None,
        }
        core.insert("finished_units", unit)
        minted.append(unit)
    return minted


# --------------------------------------------------------------------------
# CASCADE-C: footprint release with anchor promotion, site recompute, unblock.
# --------------------------------------------------------------------------
def release_footprint(unit, new_logistics_status, clear_warehouse):
    site_id = unit.get("warehouse_id")
    bucket_id = unit.get("demand_bucket_id")
    unit["logistics_status"] = new_logistics_status
    vacate_unit(unit)
    if clear_warehouse:
        unit["warehouse_id"] = None
    touch(unit)
    site = S.warehouses.get(site_id) if site_id else None
    if site is not None:
        recompute_warehouse(site)
    recompute_bucket_of(bucket_id)


# --------------------------------------------------------------------------
# Trailer roll-ups.  Recomputed from scratch on every line add and remove.
# --------------------------------------------------------------------------
def refresh_shipment(shipment):
    before = {}
    for line in calc.lines_of_shipment(shipment["id"], "LOADED"):
        before[line["id"]] = (line["nest_position"], line["line_gross_cube_m3"],
                              line["line_nested_cube_m3"], line["line_freight_cents"])
    lines = calc.shipment_rollup(shipment)
    for line in lines:
        after = (line["nest_position"], line["line_gross_cube_m3"],
                 line["line_nested_cube_m3"], line["line_freight_cents"])
        if before.get(line["id"]) != after:
            touch(line)
    return lines


# --------------------------------------------------------------------------
# Voiding a suspended customer's open claims (no money moves).
# --------------------------------------------------------------------------
def void_open_claims(customer):
    voided = 0
    for claim in core.sorted_rows(core.rows("warranty_claims")):
        if claim["customer_id"] != customer["id"]:
            continue
        if claim["claim_status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        claim["claim_status"] = "VOIDED"
        claim["denial_reason"] = "APPROVAL_VOIDED"
        touch(claim)
        voided += 1
    return voided
