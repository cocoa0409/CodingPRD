"""Cross-cutting work-order / unit / rework service logic.

These functions encapsulate the FIFO reservation and consumption, the
compliance gates, the yield recompute, and the cost rollups that several
endpoints share.
"""

import calculations as calc
import db
import errors
import inventory as inv
from errors import ApiError


# ---------------------------------------------------------------------------
# Compliance gates
# ---------------------------------------------------------------------------
def check_rohs(part, lot):
    """Raise ERR_ROHS_VIOLATION if part is RoHS-required but lot is non-compliant."""
    if part["is_rohs_required"] and not lot["is_rohs_compliant"]:
        raise ApiError(errors.ERR_ROHS_VIOLATION, 422,
                       "RoHS-required part cannot draw from a non-RoHS-compliant lot.")


def check_cmrt(part, lot):
    """Raise ERR_CMRT_MISSING if part needs CMRT but lot lacks it."""
    if part["contains_conflict_minerals"] and not lot["has_cmrt"]:
        raise ApiError(errors.ERR_CMRT_MISSING, 422,
                       "Conflict-minerals part cannot consume a lot lacking a CMRT.")


# ---------------------------------------------------------------------------
# Kit required-qty (calculations.kit_required_qty)
# ---------------------------------------------------------------------------
def compute_required_qty_by_part(bom_id, planned_qty):
    """Return {part_id: required_qty} over non-DNP BomLines, summing per-assembly.

    Preserves first-appearance order of parts via an ordered dict.
    """
    per_assembly = {}
    for ln in sorted(db.bom_lines.values(), key=lambda l: l.get("_seq", 0)):
        if ln["bom_id"] != bom_id or ln["is_dnp"]:
            continue
        per_assembly[ln["part_id"]] = per_assembly.get(ln["part_id"], 0) + ln["qty_per_assembly"]
    return {pid: pa * planned_qty for pid, pa in per_assembly.items()}


# ---------------------------------------------------------------------------
# Kitting: build requirements + FIFO reservation
# ---------------------------------------------------------------------------
def kit_work_order(wo, bom):
    """Create kit requirements, reserve FIFO, set statuses. Returns shortage count.

    RoHS gate applies to any AVAILABLE lot that would be reserved. The gate is
    evaluated before committing reservations; on violation nothing is created.
    """
    required_by_part = compute_required_qty_by_part(bom["id"], wo["planned_qty"])

    # RoHS pre-check: for each required part, the AVAILABLE lots that would be
    # drawn FIFO toward its requirement must be RoHS compliant when the part is
    # RoHS-required. We check the lots that would actually be reserved.
    planned_reservations = {}  # part_id -> reserved amount
    for part_id, required in required_by_part.items():
        part = db.parts[part_id]
        lots = inv.fifo_available_lots(part_id)
        # account for already-reserved-elsewhere stock (free pool)
        free = inv.free_available_qty(part_id)
        to_reserve = min(required, max(free, 0))
        # RoHS gate: validate the lots from which we'd draw `to_reserve`
        if part["is_rohs_required"]:
            remaining = to_reserve
            for lot in lots:
                if remaining <= 0:
                    break
                draw = min(remaining, lot["remaining_qty"])
                if draw <= 0:
                    continue
                if not lot["is_rohs_compliant"]:
                    raise ApiError(errors.ERR_ROHS_VIOLATION, 422,
                                   "RoHS-required part would reserve a non-compliant lot.")
                remaining -= draw
        planned_reservations[part_id] = to_reserve

    # Commit: create requirements with reserved_qty and status.
    shortage = 0
    for part_id, required in required_by_part.items():
        reserved = planned_reservations[part_id]
        status = "RESERVED" if reserved >= required else "SHORT"
        if status == "SHORT":
            shortage += 1
        kr = db.new_record({
            "work_order_id": wo["id"],
            "part_id": part_id,
            "required_qty": required,
            "reserved_qty": reserved,
            "consumed_qty": 0,
            "status": status,
        })
        db.kit_requirements[kr["id"]] = kr
        inv.recompute_part_rollups(part_id)
    return shortage


def kit_requirements_for_wo(wo_id):
    return [kr for kr in db.kit_requirements.values() if kr["work_order_id"] == wo_id]


def release_reservations(wo_id):
    """Compensate reservations of a KITTED work order on cancel."""
    affected_parts = set()
    for kr in kit_requirements_for_wo(wo_id):
        if kr["status"] == "RESERVED":
            kr["status"] = "RELEASED"
            kr["reserved_qty"] = 0
            db.touch(kr)
            affected_parts.add(kr["part_id"])
    for pid in affected_parts:
        inv.recompute_part_rollups(pid)


# ---------------------------------------------------------------------------
# Consumption: FIFO draw, deplete lots, recompute rollups, return cost
# ---------------------------------------------------------------------------
def consume_fifo(part, qty, check_cmrt_gate):
    """Draw `qty` from a part's AVAILABLE lots FIFO. Returns total cents drawn.

    Applies the RoHS gate always, and the CMRT gate when check_cmrt_gate is True.
    Mutates lot.remaining_qty, depletes lots, recomputes the part rollups.
    """
    lots = inv.fifo_available_lots(part["id"])
    remaining = qty
    cost = 0
    # Validate gates over the lots that will be drawn before mutating.
    plan = []  # (lot, draw)
    rem = qty
    for lot in lots:
        if rem <= 0:
            break
        draw = min(rem, lot["remaining_qty"])
        if draw <= 0:
            continue
        check_rohs(part, lot)
        if check_cmrt_gate:
            check_cmrt(part, lot)
        plan.append((lot, draw))
        rem -= draw
    # If insufficient stock, this is a generic validation failure.
    if rem > 0:
        raise errors.validation("Insufficient available stock to consume.")
    # Commit the planned draws.
    for lot, draw in plan:
        lot["remaining_qty"] -= draw
        cost += draw * lot["unit_cost_cents"]
        if lot["remaining_qty"] <= 0:
            lot["remaining_qty"] = 0
            lot["status"] = "DEPLETED"
        db.touch(lot)
    inv.recompute_part_rollups(part["id"])
    return cost


def start_consume(wo):
    """Consume each kit requirement's required_qty FIFO; set CONSUMED; return cost.

    RoHS + CMRT gates apply. Validates all draws across all requirements before
    committing (atomic): if any gate fails nothing is consumed.
    """
    krs = [kr for kr in kit_requirements_for_wo(wo["id"]) if kr["status"] == "RESERVED"]

    # Phase 1 — plan & validate gates for every requirement without mutating.
    plans = []  # (kr, part, [(lot, draw)])
    for kr in sorted(krs, key=lambda k: k.get("_seq", 0)):
        part = db.parts[kr["part_id"]]
        lots = inv.fifo_available_lots(part["id"])
        rem = kr["required_qty"]
        draws = []
        for lot in lots:
            if rem <= 0:
                break
            draw = min(rem, lot["remaining_qty"])
            if draw <= 0:
                continue
            check_rohs(part, lot)
            check_cmrt(part, lot)
            draws.append((lot, draw))
            rem -= draw
        if rem > 0:
            raise errors.validation("Insufficient stock to consume requirement.")
        plans.append((kr, part, draws))

    # Phase 2 — commit.
    total_cost = 0
    affected_parts = set()
    for kr, part, draws in plans:
        consumed = 0
        for lot, draw in draws:
            lot["remaining_qty"] -= draw
            total_cost += draw * lot["unit_cost_cents"]
            consumed += draw
            if lot["remaining_qty"] <= 0:
                lot["remaining_qty"] = 0
                lot["status"] = "DEPLETED"
            db.touch(lot)
        kr["consumed_qty"] = consumed
        kr["reserved_qty"] = 0
        kr["status"] = "CONSUMED"
        db.touch(kr)
        affected_parts.add(part["id"])
    for pid in affected_parts:
        inv.recompute_part_rollups(pid)
    return total_cost


# ---------------------------------------------------------------------------
# Yield recompute (calculations.first_pass_yield)
# ---------------------------------------------------------------------------
def units_for_wo(wo_id):
    return [u for u in db.units.values() if u["work_order_id"] == wo_id]


def recompute_wo_yield(wo):
    """Recompute passed_qty, first_pass_yield_pct for the work order."""
    units = units_for_wo(wo["id"])
    total_tested = sum(1 for u in units if u["quality_status"] != "BUILT")
    first_pass = sum(1 for u in units
                     if u["quality_status"] == "PASS" and u["rework_count"] == 0)
    passed_qty = sum(1 for u in units if u["quality_status"] == "PASS")
    wo["passed_qty"] = passed_qty
    wo["first_pass_yield_pct"] = calc.first_pass_yield_pct(total_tested, first_pass)


def recompute_built_qty(wo):
    wo["built_qty"] = len(units_for_wo(wo["id"]))
