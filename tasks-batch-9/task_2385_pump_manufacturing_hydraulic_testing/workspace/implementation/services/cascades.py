"""The three multi-hop cascades of PRD section 2.8 plus the shared ledgers."""

from db import db
from helpers import (
    allocations_of_build,
    build_orders_of_lot,
    defects_of,
    packages_of_build,
    patterns_of_model,
    touch,
)

NON_TERMINAL_BUILD_STATES = ("PLANNED", "ASSEMBLED", "TESTED", "REWORK_REQUIRED")
COMMITTED_BUILD_STATES_EXCLUDED = ("CLOSED", "CASTING_SHORT")


# ------------------------------------------------------- casting yield ledger


def recompute_committed_build_count(lot):
    count = 0
    for order in build_orders_of_lot(lot["id"]):
        if order["status"] not in COMMITTED_BUILD_STATES_EXCLUDED:
            count += 1
    lot["committed_build_count"] = count
    return count


def recompute_lot_ledger(lot):
    """Full recompute from the defect ledger -- never an incremental delta."""
    scrapped = 0
    rework = 0
    for defect in defects_of(lot["id"]):
        if defect["status"] == "DISPOSITIONED_SCRAP":
            scrapped += defect["affected_qty"]
        elif defect["status"] == "DISPOSITIONED_REPAIR":
            rework += defect["affected_qty"]
    lot["qty_scrapped"] = scrapped
    lot["qty_rework_pending"] = rework
    lot["qty_accepted"] = lot["qty_poured"] - scrapped - rework
    recompute_committed_build_count(lot)
    touch(lot)
    return lot


def shortfall(lot):
    return lot["qty_accepted"] < max(1, lot["committed_build_count"])


# -------------------------------------------------- cascade A: casting short


def release_allocation(allocation):
    kit = db.repair_kits.get(allocation["repair_kit_id"])
    if kit is not None:
        kit["qty_reserved"] -= allocation["requested_qty"]
        kit["qty_on_hand"] += allocation["requested_qty"]
        touch(kit)
    allocation["status"] = "RELEASED"
    touch(allocation)


def cascade_casting_short(lot):
    """Hops 2-4 of cascade A, each hop guarded by its own precondition."""
    candidates = [
        order
        for order in build_orders_of_lot(lot["id"])
        if order["status"] in NON_TERMINAL_BUILD_STATES
    ]
    if not candidates:
        return
    # Newest first (created_at descending).
    order = candidates[-1]
    order["status"] = "CASTING_SHORT"
    touch(order)
    recompute_committed_build_count(lot)
    touch(lot)

    for package in packages_of_build(order["id"]):
        if package["status"] not in ("CONFIGURED", "RELEASED"):
            continue
        package["status"] = "HELD"
        package["promised_ship_date"] = None
        touch(package)
        for allocation in allocations_of_build(order["id"]):
            if allocation["status"] == "RESERVED":
                release_allocation(allocation)


def maybe_quarantine_lot(lot):
    """Hop 1 of cascade A."""
    if lot["status"] in ("INSPECTED", "ACCEPTED") and shortfall(lot):
        lot["status"] = "QUARANTINED"
        touch(lot)
        cascade_casting_short(lot)


def maybe_restore_lot(lot):
    """QUARANTINED -> ACCEPTED once every defect is closed and supply is enough."""
    if lot["status"] != "QUARANTINED":
        return
    for defect in defects_of(lot["id"]):
        if defect["status"] in ("REPORTED", "DISPOSITIONED_REPAIR", "DISPOSITIONED_SCRAP"):
            return
    if shortfall(lot):
        return
    lot["status"] = "ACCEPTED"
    touch(lot)


# ------------------------------------------------- cascade B: failed hydraulic


def cascade_rework_required(build_order):
    if build_order is None or build_order["status"] not in ("ASSEMBLED", "TESTED"):
        return
    build_order["status"] = "REWORK_REQUIRED"
    touch(build_order)
    selection = db.selections.get(build_order["selection_id"])
    if selection is None or selection["status"] != "APPROVED":
        return
    selection["status"] = "UNDER_REVIEW"
    touch(selection)
    duty = db.duty_applications.get(selection["duty_application_id"])
    if duty is None or duty["status"] != "CONTRACTED":
        return
    duty["status"] = "OPEN"
    touch(duty)


# ---------------------------------------------------- cascade C: pattern wear


def constrain_model_if_needed(model_id):
    model = db.pump_models.get(model_id)
    if model is None or model["status"] != "ORDERABLE":
        return
    for pattern in patterns_of_model(model_id):
        if pattern["status"] == "QUALIFIED":
            return
    model["status"] = "PATTERN_CONSTRAINED"
    touch(model)


def unconstrain_model_if_possible(model_id):
    model = db.pump_models.get(model_id)
    if model is None or model["status"] != "PATTERN_CONSTRAINED":
        return
    for pattern in patterns_of_model(model_id):
        if pattern["status"] == "QUALIFIED":
            model["status"] = "ORDERABLE"
            touch(model)
            return


def recompute_pattern_wear(pattern):
    pattern["wear_index"] = pattern["pours_since_refurb"] + 2 * pattern["defect_pours_since_refurb"]
    touch(pattern)
    if pattern["status"] == "QUALIFIED" and pattern["wear_index"] >= pattern["wear_threshold"]:
        pattern["status"] = "WORN"
        constrain_model_if_needed(pattern["pump_model_id"])
