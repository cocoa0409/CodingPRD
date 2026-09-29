"""Cross-entity behaviour: cascades, reversals and the guarded transitions.

Every helper in here assumes the caller already ran the earlier rungs of the
validation ladder; nothing writes until the last guard has passed (PRD §2.8).
"""

import calc
from calc import (COMMITTED_SLOT_STATUSES, LIVE_CALL_STATUSES, LIVE_CHANGE_STATUSES,
                  LIVE_SLOT_STATUSES, d)
from db import db, new_record, touch
from errors import ApiError


# --------------------------------------------------------------------------- #
# shift plan recomputation
# --------------------------------------------------------------------------- #
def recompute_plan(plan):
    if plan is None:
        return
    unit, changeover, committed = calc.plan_figures(plan)
    if (plan["unit_labor_minutes"] != unit
            or plan["changeover_minutes"] != changeover
            or plan["committed_labor_minutes"] != committed):
        plan["unit_labor_minutes"] = unit
        plan["changeover_minutes"] = changeover
        plan["committed_labor_minutes"] = committed
        touch(plan)


def touch_line(line):
    """Line derived fields are recomputed on read; only updated_at moves."""
    touch(line, bump=False)


# --------------------------------------------------------------------------- #
# build-slot reversal (PRD §2.11 presentation-slot conservation)
# --------------------------------------------------------------------------- #
def desequence_slot(slot):
    """SEQUENCED -> PLANNED with the exact reversal of every charge."""
    plan = db.shift_plans.get(slot["shift_plan_id"])
    for alloc in slot["presentation_allocations"]:
        station = db.stations.get(alloc["station_id"])
        if station is None:
            continue
        station["presentation_slots_used"] -= alloc["slot_units"]
        if station["presentation_slots_used"] < 0:
            station["presentation_slots_used"] = 0
        touch(station)
    slot["status"] = "PLANNED"
    slot["shift_plan_id"] = None
    slot["sync_delivery_call_id"] = None
    slot["option_points_snapshot"] = None
    slot["labor_minutes_snapshot"] = None
    slot["presentation_allocations"] = []
    slot["allocated_slot_units"] = 0
    touch(slot)
    recompute_plan(plan)
    line = db.lines.get(slot["line_id"])
    touch_line(line)


def release_allocations(slot):
    """Give line-side capacity back when the finished appliance ships."""
    for alloc in slot["presentation_allocations"]:
        station = db.stations.get(alloc["station_id"])
        if station is None:
            continue
        station["presentation_slots_used"] -= alloc["slot_units"]
        if station["presentation_slots_used"] < 0:
            station["presentation_slots_used"] = 0
        touch(station)
    touch_line(db.lines.get(slot["line_id"]))


# --------------------------------------------------------------------------- #
# delivery-call cancellation
# --------------------------------------------------------------------------- #
def cancel_call(call, reason):
    """Cancel a SCHEDULED call and de-sequence the slots pinned to it."""
    call["status"] = "CANCELLED"
    call["cancel_reason"] = reason
    touch(call)
    desequenced = []
    slots = [s for s in db.build_slots.values()
             if s["sync_delivery_call_id"] == call["id"] and s["status"] == "SEQUENCED"]
    slots.sort(key=lambda s: (s["sequence_index"], s["created_at"], s["id"]))
    for slot in slots:
        desequence_slot(slot)
        desequenced.append(slot["id"])
    return desequenced


# --------------------------------------------------------------------------- #
# supplier scoring + demotion cascade
# --------------------------------------------------------------------------- #
def rescore_supplier(supplier, skip_call_ids=None):
    """Replay the score from the counters and run the demotion cascade.

    Returns (demoted, cancelled_call_ids, de_sequenced_slot_ids).
    """
    previous_status = supplier["status"]
    supplier["on_time_score"] = calc.supplier_score(supplier)
    supplier["status"] = calc.supplier_status_for(supplier["on_time_score"])
    touch(supplier)

    cancelled, desequenced = [], []
    demoted = previous_status == "APPROVED" and supplier["status"] != "APPROVED"
    if not demoted:
        return False, cancelled, desequenced

    skip = set(skip_call_ids or ())
    calls = [c for c in db.delivery_calls.values()
             if c["supplier_id"] == supplier["id"]
             and c["status"] == "SCHEDULED"
             and c["id"] not in skip]
    calls.sort(key=lambda c: (c["window_start"], c["created_at"], c["id"]))
    for call in calls:
        desequenced.extend(cancel_call(call, "SUPPLIER_PROBATION"))
        cancelled.append(call["id"])
    return True, cancelled, desequenced


# --------------------------------------------------------------------------- #
# part lifecycle helpers
# --------------------------------------------------------------------------- #
def live_change_exists(part_id, exclude_change_id=None):
    for change in db.engineering_changes.values():
        if change["affected_part_id"] != part_id:
            continue
        if exclude_change_id is not None and change["id"] == exclude_change_id:
            continue
        if change["status"] in LIVE_CHANGE_STATUSES:
            return True
    return False


def maybe_release_part(part_id, exclude_change_id=None):
    """CHANGE_PENDING -> ACTIVE once no live change names the part."""
    part = db.parts.get(part_id)
    if part is None or part["lifecycle_status"] != "CHANGE_PENDING":
        return
    if live_change_exists(part_id, exclude_change_id=exclude_change_id):
        return
    part["lifecycle_status"] = "ACTIVE"
    touch(part)


def mark_part_change_pending(part_id):
    part = db.parts.get(part_id)
    if part is not None and part["lifecycle_status"] == "ACTIVE":
        part["lifecycle_status"] = "CHANGE_PENDING"
        touch(part)


def recompute_part_cohort_rate(part):
    metrics = calc.warranty_metrics(part["id"])
    part["cohort_failure_rate_per_1000"] = metrics["cohort_failure_rate_per_1000"]
    return metrics


# --------------------------------------------------------------------------- #
# shift-plan coverage
# --------------------------------------------------------------------------- #
def covering_plans(line_id, instant):
    plans = []
    for plan in db.shift_plans.values():
        if plan["line_id"] != line_id or plan["status"] != "ACTIVE":
            continue
        if plan["shift_start"] <= instant < plan["shift_end"]:
            plans.append(plan)
    plans.sort(key=lambda p: (p["shift_start"], p["created_at"], p["id"]))
    return plans


def covering_call(part_id, station_id, instant):
    calls = [c for c in db.delivery_calls.values()
             if c["part_id"] == part_id
             and c["station_id"] == station_id
             and c["status"] in LIVE_CALL_STATUSES
             and c["window_start"] <= instant < c["window_end"]]
    calls.sort(key=lambda c: (c["window_start"], c["created_at"], c["id"]))
    return calls[0] if calls else None


# --------------------------------------------------------------------------- #
# sequencing (validation ladder rules 9, 14-16, 24-31)
# --------------------------------------------------------------------------- #
def sequence_slot(slot):
    line = db.lines.get(slot["line_id"])
    variant = db.model_variants.get(slot["model_variant_id"])

    # 9 — state
    if slot["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    # 14 — governing variant released
    if variant is None or variant["status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    # 15 — production-effective BOM non-empty
    bom = calc.resolve_bom(variant["id"], slot["sequence_index"])
    if not bom:
        raise ApiError("ERR_BOM_NOT_EFFECTIVE")
    ordered = calc.bom_allocation_order(list(bom.values()))
    # 16 — no CHANGE_PENDING / OBSOLETE part
    for bom_line in ordered:
        part = db.parts.get(bom_line["part_id"])
        if part is None or part["lifecycle_status"] in ("CHANGE_PENDING", "OBSOLETE"):
            raise ApiError("ERR_PART_CHANGE_PENDING")
    # 24 — exactly one covering ACTIVE plan
    plans = covering_plans(line["id"], slot["planned_start"])
    if len(plans) != 1:
        raise ApiError("ERR_NO_SHIFT_COVERAGE")
    plan = plans[0]
    # 25 — sequence index still free
    for other in calc.line_slots(line["id"]):
        if other["id"] == slot["id"]:
            continue
        if other["sequence_index"] == slot["sequence_index"] and other["status"] in LIVE_SLOT_STATUSES:
            raise ApiError("ERR_SEQUENCE_INDEX_TAKEN")
    # 26 — posture
    if calc.line_posture(line) == "STOPPED":
        raise ApiError("ERR_LINE_POSTURE_BLOCKED")
    # 27 — sequenced-module suppliers approved
    sequenced_lines = []
    for bom_line in ordered:
        part = db.parts[bom_line["part_id"]]
        if part["is_sequenced_module"]:
            sequenced_lines.append((bom_line, part))
    for _bom_line, part in sequenced_lines:
        supplier = db.suppliers.get(part["supplier_id"])
        if supplier is None or supplier["status"] != "APPROVED":
            raise ApiError("ERR_SUPPLIER_NOT_APPROVED")
    # 28 — covering synchronous delivery
    covered = {}
    pinned_call = None
    for bom_line, part in sequenced_lines:
        call = covering_call(part["id"], bom_line["station_id"], slot["planned_start"])
        if call is None:
            raise ApiError("ERR_SYNC_DELIVERY_MISSING")
        covered[bom_line["id"]] = call
        if pinned_call is None:
            pinned_call = call
    # 29 — rolling option-load windows
    if not calc.option_load_windows_ok(line, plan, slot["sequence_index"],
                                      variant["option_content_points"]):
        raise ApiError("ERR_OPTION_LOAD_WINDOW_EXCEEDED")
    # 30 — presentation allocation waterfall
    pending = {}
    for bom_line in ordered:
        part = db.parts[bom_line["part_id"]]
        units = calc.slot_units_for(bom_line, part, bom_line["id"] in covered)
        if units == 0:
            continue
        station = db.stations.get(bom_line["station_id"])
        if station is None:
            raise ApiError("ERR_PRESENTATION_SLOTS_EXHAUSTED")
        proposed = pending.get(station["id"], 0) + units
        if station["presentation_slots_used"] + proposed > station["presentation_slot_capacity"]:
            raise ApiError("ERR_PRESENTATION_SLOTS_EXHAUSTED")
        pending[station["id"]] = proposed
    # 31 — labour capacity
    _unit, _changeover, committed = calc.plan_figures(
        plan, extra=(slot["sequence_index"], variant["family_code"], variant["labor_minutes"]))
    if d(committed) > calc.available_labor_minutes(plan):
        raise ApiError("ERR_LABOR_CAPACITY_EXCEEDED")

    # ---- commit -----------------------------------------------------------
    allocations = []
    for station in calc.line_stations(line["id"]):
        if station["id"] in pending:
            charge = pending[station["id"]]
            station["presentation_slots_used"] += charge
            touch(station)
            allocations.append({"station_id": station["id"], "slot_units": charge})

    slot["status"] = "SEQUENCED"
    slot["shift_plan_id"] = plan["id"]
    slot["sync_delivery_call_id"] = pinned_call["id"] if pinned_call else None
    slot["option_points_snapshot"] = variant["option_content_points"]
    slot["labor_minutes_snapshot"] = variant["labor_minutes"]
    slot["presentation_allocations"] = allocations
    slot["allocated_slot_units"] = sum(a["slot_units"] for a in allocations)
    touch(slot)

    recompute_plan(plan)
    touch_line(line)
    return slot


# --------------------------------------------------------------------------- #
# engineering-change cut-in (depth-4 cascade, PRD §3.8)
# --------------------------------------------------------------------------- #
def cut_in_change(change, replacement_part_id, new_qty_per_unit):
    variant = db.model_variants.get(change["model_variant_id"])
    line = db.lines.get(change["target_line_id"])

    # 9 — state
    if change["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    # 14 — variant released
    if variant is None or variant["status"] != "RELEASED":
        raise ApiError("ERR_MODEL_NOT_RELEASED")
    # 15 — an ACTIVE line at the position carrying the affected part
    target = None
    for bom_line in db.bom_lines.values():
        if (bom_line["model_variant_id"] == change["model_variant_id"]
                and bom_line["bom_position_code"] == change["bom_position_code"]
                and bom_line["part_id"] == change["affected_part_id"]
                and bom_line["status"] == "ACTIVE"):
            if target is None or (bom_line["effective_from_sequence"], bom_line["created_at"], bom_line["id"]) > \
                    (target["effective_from_sequence"], target["created_at"], target["id"]):
                target = bom_line
    if target is None:
        raise ApiError("ERR_BOM_NOT_EFFECTIVE")
    # 17 — target line stopped
    if line is None or calc.line_posture(line) != "STOPPED":
        raise ApiError("ERR_LINE_NOT_STOPPED")
    # 18 — cut-in ahead of released production
    if change["cut_in_sequence_index"] <= calc.max_released_sequence_index(line["id"]):
        raise ApiError("ERR_CUT_IN_INDEX_TOO_LOW")
    # 19 — replacement part present and different
    if replacement_part_id is None or replacement_part_id == change["affected_part_id"]:
        raise ApiError("ERR_REPLACEMENT_PART_REQUIRED")

    # ---- commit -----------------------------------------------------------
    cut_in_at = db.clock
    change["status"] = "CUT_IN"
    change["cut_in_at"] = cut_in_at
    change["replacement_part_id"] = replacement_part_id
    if new_qty_per_unit is not None:
        change["new_qty_per_unit"] = new_qty_per_unit
    touch(change)

    # link 1 — mint the replacement BOM line, supersede the old one
    qty = new_qty_per_unit if new_qty_per_unit is not None else target["qty_per_unit"]
    minted = new_record()
    minted.update({
        "model_variant_id": change["model_variant_id"],
        "part_id": replacement_part_id,
        "station_id": target["station_id"],
        "bom_position_code": change["bom_position_code"],
        "qty_per_unit": qty,
        "effective_from_sequence": change["cut_in_sequence_index"],
        "superseded_by_bom_line_id": None,
        "created_by_change_id": change["id"],
        "status": "ACTIVE",
    })
    db.bom_lines[minted["id"]] = minted
    target["status"] = "SUPERSEDED"
    target["superseded_by_bom_line_id"] = minted["id"]
    touch(target)

    # link 2 — the outgoing part becomes service-only
    outgoing = db.parts.get(change["affected_part_id"])
    if outgoing is not None and outgoing["lifecycle_status"] in ("ACTIVE", "CHANGE_PENDING"):
        outgoing["lifecycle_status"] = "SERVICE_ONLY"
        outgoing["service_obligation_until"] = calc.plus_years(
            cut_in_at, calc.SERVICE_OBLIGATION_YEARS)
        touch(outgoing)

    # links 3 and 4 — future dock calls cancelled, dependent slots de-sequenced
    calls = [c for c in db.delivery_calls.values()
             if c["part_id"] == change["affected_part_id"]
             and c["status"] == "SCHEDULED"
             and c["window_start"] >= cut_in_at]
    calls.sort(key=lambda c: (c["window_start"], c["created_at"], c["id"]))
    for call in calls:
        cancel_call(call, "PART_SERVICE_ONLY")

    touch_line(line)
    return change


# --------------------------------------------------------------------------- #
# quality gate progression (PRD §3.7)
# --------------------------------------------------------------------------- #
def _has_recorded_pass(unit_id, test_type):
    for test in db.quality_tests.values():
        if (test["production_unit_id"] == unit_id
                and test["test_type"] == test_type
                and test["status"] == "RECORDED"
                and test["result"] == "PASS"):
            return True
    return False


def advance_quality(unit, variant, test):
    """Walk the quality dimension after a freshly recorded test."""
    if test["result"] == "FAIL":
        unit["quality_status"] = "QUARANTINED"
        if unit["assembly_status"] in ("IN_STATION", "ASSEMBLED"):
            unit["assembly_status"] = "REWORK"
        unit["rework_count"] += 1
        return
    if test["test_type"] == "ELECTRICAL_SAFETY" and test["result"] == "PASS":
        if unit["quality_status"] == "PENDING":
            unit["quality_status"] = "SAFETY_PASSED"
    if unit["quality_status"] == "SAFETY_PASSED":
        gated = _has_recorded_pass(unit["id"], "FUNCTIONAL_CYCLE")
        if gated and variant["requires_leak_test"]:
            gated = _has_recorded_pass(unit["id"], "LEAK")
        if gated:
            unit["quality_status"] = "GATED"


# --------------------------------------------------------------------------- #
# checkpoint sweep (PRD §3.9, five ordered steps)
# --------------------------------------------------------------------------- #
def run_checkpoint(line):
    now = db.clock
    station_ids = {s["id"] for s in calc.line_stations(line["id"])}

    missed_ids, cancelled_call_ids = [], []
    desequenced_ids, cancelled_slot_ids = [], []
    demoted_ids, closed_change_ids = [], []

    # step 1
    line["checkpoint_index"] += 1

    # step 2 — overdue dock calls
    due = [c for c in db.delivery_calls.values()
           if c["status"] == "SCHEDULED"
           and c["station_id"] in station_ids
           and c["window_end"] + calc.minutes(calc.MISS_GRACE_MINUTES) <= now]
    due.sort(key=lambda c: (c["window_end"], c["created_at"], c["id"]))
    sweep_ids = {c["id"] for c in due}
    for call in due:
        if call["status"] != "SCHEDULED":
            continue
        call["status"] = "MISSED"
        touch(call)
        missed_ids.append(call["id"])
        supplier = db.suppliers.get(call["supplier_id"])
        if supplier is None:
            continue
        supplier["missed_count"] += 1
        demoted, cancelled, desequenced = rescore_supplier(supplier, skip_call_ids=sweep_ids)
        if demoted and supplier["id"] not in demoted_ids:
            demoted_ids.append(supplier["id"])
        cancelled_call_ids.extend(cancelled)
        desequenced_ids.extend(desequenced)

    # step 3 — expired planned slots
    stale = [s for s in calc.line_slots(line["id"])
             if s["status"] == "PLANNED" and s["planned_start"] < now]
    stale.sort(key=lambda s: (s["sequence_index"], s["created_at"], s["id"]))
    for slot in stale:
        slot["status"] = "CANCELLED"
        touch(slot)
        cancelled_slot_ids.append(slot["id"])

    # step 4 — cut-in changes whose pre-change units have all left the floor
    changes = [c for c in db.engineering_changes.values()
               if c["status"] == "CUT_IN" and c["target_line_id"] == line["id"]]
    changes.sort(key=lambda c: (c["created_at"], c["id"]))
    for change in changes:
        blocking = False
        for unit in db.production_units.values():
            slot = db.build_slots.get(unit["build_slot_id"])
            if slot is None or slot["line_id"] != line["id"]:
                continue
            if unit["built_at_sequence_index"] >= change["cut_in_sequence_index"]:
                continue
            if unit["assembly_status"] in ("IN_STATION", "REWORK"):
                blocking = True
                break
        if not blocking:
            change["status"] = "CLOSED"
            touch(change)
            closed_change_ids.append(change["id"])

    # step 5 — derived line state
    touch_line(line)

    return {
        "checkpoint_index": line["checkpoint_index"],
        "missed_call_ids": missed_ids,
        "cancelled_call_ids": cancelled_call_ids,
        "de_sequenced_build_slot_ids": desequenced_ids,
        "cancelled_build_slot_ids": cancelled_slot_ids,
        "demoted_supplier_ids": demoted_ids,
        "closed_change_ids": closed_change_ids,
    }


# --------------------------------------------------------------------------- #
# warranty design-feedback cascade (PRD §3.9)
# --------------------------------------------------------------------------- #
def mint_warranty_change(ret, unit, part):
    slot = db.build_slots.get(unit["build_slot_id"])
    line = db.lines.get(slot["line_id"]) if slot else None
    bom = calc.resolve_bom(slot["model_variant_id"], unit["built_at_sequence_index"],
                           include_superseded=True) if slot else {}
    position_code = None
    for code in sorted(bom.keys()):
        if bom[code]["part_id"] == part["id"]:
            position_code = code
            break

    change = new_record()
    change.update({
        "origin": "WARRANTY",
        "model_variant_id": slot["model_variant_id"] if slot else None,
        "bom_position_code": position_code,
        "affected_part_id": part["id"],
        "replacement_part_id": None,
        "target_line_id": line["id"] if line else None,
        "source_warranty_return_id": ret["id"],
        "cut_in_sequence_index": (calc.max_released_sequence_index(line["id"]) + 1) if line else 1,
        "new_qty_per_unit": None,
        "submitted_by_user_id": "system",
        "decided_by_user_id": None,
        "revision_round": 0,
        "cut_in_at": None,
        "status": "SUBMITTED",
    })
    db.engineering_changes[change["id"]] = change
    mark_part_change_pending(part["id"])
    return change
