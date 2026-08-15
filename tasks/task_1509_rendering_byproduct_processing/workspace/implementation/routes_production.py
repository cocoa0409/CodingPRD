"""InboundBatch, CookRun, and ProductLot endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_datetime, v_list, ok, view, stamp_new, touch,
                    paginate, sorted_items, get_or_404, fail, parse_dt, rhu)
from logic import (posture_gate, batch_view, lot_view, remaining_lbs,
                   theoretical_yields, compute_grade, current_settlement,
                   windows_overlap, RECIPE_SPECIES, RECIPE_LOT_TYPES,
                   YIELD_TOLERANCE_PCT, TIER1_LIMIT, TIER1_RATE, TIER2_RATE)

bp = Blueprint("production", __name__)

SPECIES_ALL = {"BOVINE", "PORCINE", "POULTRY", "OVINE", "MIXED"}
RECIPES = {"RUMINANT_RENDER", "PORCINE_RENDER", "POULTRY_RENDER", "MIXED_RENDER"}
SCREEN_RESULTS = {"PASS", "FAIL_TEMPERATURE", "FAIL_PROHIBITED"}
ACTIVE_COOK_STAGES = ("STAGED", "COOKING", "SETTLING", "PRESSING")


# ---------------- inbound batches ----------------

@bp.post("/rendering/inbound-batches")
def create_batch():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    supplier_id = v_str(b, "supplier_id")
    agreement_id = v_str(b, "agreement_id")
    species = v_enum(b, "species", SPECIES_ALL)
    weight = v_int(b, "weight_lbs", minv=1)
    temp = v_num(b, "temperature_f")
    received_at = v_datetime(b, "received_at")
    require_role(role, "ScalehouseOperator")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    supplier = get_or_404("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    agreement = get_or_404("agreements", agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    posture_gate(plant, "op")
    batch = {
        "plant_id": plant_id,
        "supplier_id": supplier_id,
        "agreement_id": agreement_id,
        "route_stop_id": None,
        "species": species,
        "weight_lbs": weight,
        "temperature_f": temp,
        "received_at": received_at,
        "screening_result": "PENDING",
        "screened_by": None,
        "reserved_lbs": 0,
        "consumed_lbs": 0,
        "status": "RECEIVED",
    }
    stamp_new(batch)
    db.STORES["batches"][batch["id"]] = batch
    return ok(batch_view(batch), 201)


@bp.get("/rendering/inbound-batches")
def list_batches():
    caller()
    items = sorted_items("batches", {
        "plant_id": request.args.get("plant_id"),
        "supplier_id": request.args.get("supplier_id"),
        "agreement_id": request.args.get("agreement_id"),
        "route_stop_id": request.args.get("route_stop_id"),
        "status": request.args.get("status"),
        "species": request.args.get("species"),
    })
    return paginate(items, viewfn=batch_view)


@bp.get("/rendering/inbound-batches/<bid>")
def get_batch(bid):
    caller()
    return ok(batch_view(get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")), 200)


@bp.post("/rendering/inbound-batches/<bid>/screen")
def screen_batch(bid):
    uid, role = caller()
    b = body_json()
    result = v_enum(b, "screening_result", SCREEN_RESULTS)
    require_role(role, "ScalehouseOperator")
    batch = get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")
    plant = get_or_404("plants", batch["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    if batch["status"] != "RECEIVED":
        fail("ERR_BATCH_INVALID_STATE", 409, "Batch must be RECEIVED to screen")
    batch["screening_result"] = result
    batch["screened_by"] = uid
    if result == "PASS":
        batch["status"] = "ACCEPTED"
    elif result == "FAIL_TEMPERATURE":
        batch["status"] = "QUARANTINED"
    else:  # FAIL_PROHIBITED
        agreement = db.STORES["agreements"].get(batch["agreement_id"])
        policy = agreement["prohibited_material_policy"] if agreement else "ZERO_TOLERANCE"
        batch["status"] = "REJECTED" if policy == "ZERO_TOLERANCE" else "QUARANTINED"
    touch(batch)
    return ok(batch_view(batch), 200)


@bp.post("/rendering/inbound-batches/<bid>/quarantine")
def quarantine_batch(bid):
    uid, role = caller()
    require_role(role, "ComplianceOfficer")
    batch = get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")
    plant = get_or_404("plants", batch["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    if batch["status"] != "RECEIVED":
        fail("ERR_BATCH_INVALID_STATE", 409, "Only a RECEIVED batch may be placed on hold")
    batch["status"] = "QUARANTINED"
    touch(batch)
    return ok(batch_view(batch), 200)


@bp.post("/rendering/inbound-batches/<bid>/adjudicate")
def adjudicate_batch(bid):
    uid, role = caller()
    b = body_json()
    decision = v_enum(b, "decision", {"ACCEPT", "REJECT"})
    require_role(role, "ComplianceOfficer")
    batch = get_or_404("batches", bid, "ERR_BATCH_NOT_FOUND")
    plant = get_or_404("plants", batch["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    if batch["status"] != "QUARANTINED":
        fail("ERR_BATCH_INVALID_STATE", 409, "Batch must be QUARANTINED to adjudicate")
    if batch["screened_by"] is not None and batch["screened_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Adjudicator must differ from the screener")
    batch["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(batch)
    return ok(batch_view(batch), 200)


# ---------------- cook runs ----------------

@bp.post("/rendering/cook-runs")
def create_cook_run():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    cooker_line = v_int(b, "cooker_line", minv=1)
    recipe = v_enum(b, "recipe", RECIPES)
    planned_inputs = v_list(b, "planned_inputs")
    for item in planned_inputs:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", 400, "planned_inputs entries must be objects")
        if not isinstance(item.get("batch_id"), str):
            fail("ERR_INVALID_REQUEST", 400, "planned_inputs.batch_id is required")
        w = item.get("weight_lbs")
        if isinstance(w, bool) or not isinstance(w, int) or w < 1:
            fail("ERR_INVALID_REQUEST", 400, "planned_inputs.weight_lbs must be an integer >= 1")
    cook_start = v_datetime(b, "cook_start", whole_hour=True)
    cook_end = v_datetime(b, "cook_end", whole_hour=True)
    cs_dt = parse_dt(cook_start)
    ce_dt = parse_dt(cook_end)
    if ce_dt <= cs_dt:
        fail("ERR_INVALID_REQUEST", 400, "cook_end must be strictly after cook_start")
    if (ce_dt - cs_dt).total_seconds() % 3600 != 0:
        fail("ERR_INVALID_REQUEST", 400, "cook window duration must be whole hours")
    require_role(role, "ProductionSupervisor")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    batches = []
    for item in planned_inputs:
        batches.append(get_or_404("batches", item["batch_id"], "ERR_BATCH_NOT_FOUND"))
    posture_gate(plant, "op")
    # species segregation (priority 9)
    allowed = RECIPE_SPECIES[recipe]
    for batch in batches:
        if batch["species"] not in allowed:
            fail("ERR_SPECIES_MIXING_VIOLATION", 422,
                 f"Species {batch['species']} is not allowed in {recipe}")
    # cross-entity state (priority 11)
    for batch in batches:
        if batch["status"] != "ACCEPTED":
            fail("ERR_BATCH_NOT_ACCEPTED", 409, "Input batch is not ACCEPTED")
    # cooker aggregate capacity (priority 12)
    overlapping = 0
    for r in db.STORES["cook_runs"].values():
        if (r["plant_id"] == plant_id and r["status"] in ACTIVE_COOK_STAGES
                and windows_overlap(cs_dt, ce_dt, r["_cs"], r["_ce"])):
            overlapping += 1
    if overlapping >= plant["cooker_capacity"]:
        fail("ERR_COOKER_CAPACITY_EXCEEDED", 409, "Cooker capacity exceeded for this window")
    # capacity sums (priority 13)
    if len(planned_inputs) == 0:
        fail("ERR_EMPTY_INPUT", 422, "planned_inputs must be non-empty")
    pending = {}
    for item, batch in zip(planned_inputs, batches):
        used = pending.get(batch["id"], 0)
        if item["weight_lbs"] > remaining_lbs(batch) - used:
            fail("ERR_WEIGHT_EXCEEDS_REMAINING", 422,
                 "Planned weight exceeds the batch's remaining_lbs")
        pending[batch["id"]] = used + item["weight_lbs"]
    fat, meal = theoretical_yields([(batch["species"], item["weight_lbs"])
                                    for item, batch in zip(planned_inputs, batches)])
    run = {
        "plant_id": plant_id,
        "cooker_line": cooker_line,
        "recipe": recipe,
        "planned_inputs": [{"batch_id": i["batch_id"], "weight_lbs": i["weight_lbs"]}
                           for i in planned_inputs],
        "total_input_lbs": sum(i["weight_lbs"] for i in planned_inputs),
        "theoretical_fat_lbs": fat,
        "theoretical_meal_lbs": meal,
        "actual_fat_output_lbs": None,
        "actual_meal_output_lbs": None,
        "yield_variance_pct": None,
        "energy_cost_cents": None,
        "cook_start": cook_start,
        "cook_end": cook_end,
        "_cs": cs_dt,
        "_ce": ce_dt,
        "recook_count": 0,
        "failure_reason": None,
        "status": "STAGED",
        "_completed_period": None,
    }
    stamp_new(run)
    db.STORES["cook_runs"][run["id"]] = run
    for item, batch in zip(planned_inputs, batches):
        batch["reserved_lbs"] += item["weight_lbs"]
        touch(batch)
    return ok(view(run), 201)


@bp.get("/rendering/cook-runs")
def list_cook_runs():
    caller()
    items = sorted_items("cook_runs", {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
        "recipe": request.args.get("recipe"),
    })
    return paginate(items)


@bp.get("/rendering/cook-runs/<cid>")
def get_cook_run(cid):
    caller()
    return ok(view(get_or_404("cook_runs", cid, "ERR_COOK_RUN_NOT_FOUND")), 200)


def _run_ctx(cid):
    run = get_or_404("cook_runs", cid, "ERR_COOK_RUN_NOT_FOUND")
    plant = get_or_404("plants", run["plant_id"], "ERR_PLANT_NOT_FOUND")
    return run, plant


@bp.post("/rendering/cook-runs/<cid>/start")
def start_cook_run(cid):
    uid, role = caller()
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "cook_start")
    if run["status"] != "STAGED":
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be STAGED to start")
    for item in run["planned_inputs"]:
        batch = db.STORES["batches"].get(item["batch_id"])
        # the run's own reservation is still held inside batch.reserved_lbs, so
        # the pounds available to this run are remaining + this line's share
        if batch is None or item["weight_lbs"] > remaining_lbs(batch) + item["weight_lbs"]:
            fail("ERR_WEIGHT_EXCEEDS_REMAINING", 422,
                 "An input batch no longer has sufficient remaining_lbs")
    run["status"] = "COOKING"
    touch(run)
    return ok(view(run), 200)


@bp.post("/rendering/cook-runs/<cid>/advance")
def advance_cook_run(cid):
    uid, role = caller()
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "op")
    if run["status"] == "COOKING":
        run["status"] = "SETTLING"
    elif run["status"] == "SETTLING":
        run["status"] = "PRESSING"
    else:
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be COOKING or SETTLING to advance")
    touch(run)
    return ok(view(run), 200)


@bp.post("/rendering/cook-runs/<cid>/fail")
def fail_cook_run(cid):
    uid, role = caller()
    b = body_json()
    reason = v_str(b, "failure_reason")
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "op")
    if run["status"] not in ("COOKING", "SETTLING"):
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be COOKING or SETTLING to fail")
    run["status"] = "FAILED"
    run["failure_reason"] = reason
    touch(run)
    return ok(view(run), 200)


@bp.post("/rendering/cook-runs/<cid>/restage")
def restage_cook_run(cid):
    uid, role = caller()
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "op")
    if run["status"] != "FAILED":
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be FAILED to restage")
    run["status"] = "STAGED"
    run["recook_count"] += 1
    run["failure_reason"] = None
    touch(run)
    return ok(view(run), 200)


@bp.post("/rendering/cook-runs/<cid>/complete")
def complete_cook_run(cid):
    uid, role = caller()
    b = body_json()
    actual_fat = v_int(b, "actual_fat_output_lbs", minv=0)
    actual_meal = v_int(b, "actual_meal_output_lbs", minv=0)
    override_note = b.get("override_note")
    if override_note is not None and not isinstance(override_note, str):
        fail("ERR_INVALID_REQUEST", 400, "override_note must be a string")
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "op")
    if run["status"] != "PRESSING":
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be PRESSING to complete")
    theo_total = run["theoretical_fat_lbs"] + run["theoretical_meal_lbs"]
    actual_total = actual_fat + actual_meal
    if theo_total > 0:
        variance = float(rhu(Decimal(actual_total - theo_total) / Decimal(theo_total) * 100, 2))
    else:
        variance = 0.0
    if abs(variance) > YIELD_TOLERANCE_PCT and not override_note:
        fail("ERR_YIELD_OUT_OF_TOLERANCE", 422,
             "Absolute yield variance exceeds 25% and no override_note was supplied")
    duration_hours = int((run["_ce"] - run["_cs"]).total_seconds() // 3600)
    prior_hours = 0
    for other in db.STORES["cook_runs"].values():
        if (other["id"] != run["id"] and other["plant_id"] == run["plant_id"]
                and other["status"] == "COMPLETED"
                and other.get("_completed_period") == plant["current_period_index"]):
            prior_hours += int((other["_ce"] - other["_cs"]).total_seconds() // 3600)
    t1 = max(0, min(duration_hours, TIER1_LIMIT - prior_hours))
    t2 = duration_hours - t1
    energy_cost = t1 * TIER1_RATE + t2 * TIER2_RATE
    run["actual_fat_output_lbs"] = actual_fat
    run["actual_meal_output_lbs"] = actual_meal
    run["yield_variance_pct"] = variance
    run["energy_cost_cents"] = energy_cost
    run["status"] = "COMPLETED"
    run["_completed_period"] = plant["current_period_index"]
    touch(run)
    for item in run["planned_inputs"]:
        batch = db.STORES["batches"].get(item["batch_id"])
        if batch is None:
            continue
        batch["reserved_lbs"] -= item["weight_lbs"]
        batch["consumed_lbs"] += item["weight_lbs"]
        if remaining_lbs(batch) == 0 and batch["consumed_lbs"] > 0:
            batch["status"] = "DEPLETED"
        touch(batch)
    fat_type, meal_type = RECIPE_LOT_TYPES[run["recipe"]]
    for ptype, qty in ((fat_type, actual_fat), (meal_type, actual_meal)):
        lot = {
            "plant_id": run["plant_id"],
            "cook_run_id": run["id"],
            "product_type": ptype,
            "quantity_lbs": qty,
            "allocated_lbs": 0,
            "lab_moisture_pct": None,
            "lab_ffa_pct": None,
            "lab_protein_pct": None,
            "grade": "UNGRADED",
            "graded_by": None,
            "status": "LAB_PENDING",
        }
        stamp_new(lot)
        db.STORES["lots"][lot["id"]] = lot
    settlement = current_settlement(plant)
    if settlement is not None:
        settlement["energy_costs_cents"] += energy_cost
        touch(settlement)
    return ok(view(run), 200)


@bp.post("/rendering/cook-runs/<cid>/cancel")
def cancel_cook_run(cid):
    uid, role = caller()
    require_role(role, "ProductionSupervisor")
    run, plant = _run_ctx(cid)
    posture_gate(plant, "op")
    if run["status"] not in ("STAGED", "FAILED"):
        fail("ERR_COOK_RUN_INVALID_STATE", 409, "Cook run must be STAGED or FAILED to cancel")
    for item in run["planned_inputs"]:
        batch = db.STORES["batches"].get(item["batch_id"])
        if batch is not None:
            batch["reserved_lbs"] -= item["weight_lbs"]
            touch(batch)
    run["status"] = "CANCELLED"
    touch(run)
    return ok(view(run), 200)


# ---------------- product lots ----------------

@bp.get("/rendering/product-lots")
def list_lots():
    caller()
    items = sorted_items("lots", {
        "plant_id": request.args.get("plant_id"),
        "cook_run_id": request.args.get("cook_run_id"),
        "status": request.args.get("status"),
        "product_type": request.args.get("product_type"),
        "grade": request.args.get("grade"),
    })
    return paginate(items, viewfn=lot_view)


@bp.get("/rendering/product-lots/<lid>")
def get_lot(lid):
    caller()
    return ok(lot_view(get_or_404("lots", lid, "ERR_LOT_NOT_FOUND")), 200)


def _lot_ctx(lid):
    lot = get_or_404("lots", lid, "ERR_LOT_NOT_FOUND")
    plant = get_or_404("plants", lot["plant_id"], "ERR_PLANT_NOT_FOUND")
    return lot, plant


def _apply_lab_values(lot, b):
    moisture = v_num(b, "lab_moisture_pct")
    is_fat = lot["product_type"] in ("TALLOW", "YELLOW_GREASE")
    ffa = v_num(b, "lab_ffa_pct", required=is_fat)
    protein = v_num(b, "lab_protein_pct", required=not is_fat)
    lot["lab_moisture_pct"] = moisture
    lot["lab_ffa_pct"] = ffa
    lot["lab_protein_pct"] = protein
    return compute_grade(lot["product_type"], moisture, ffa, protein)


@bp.post("/rendering/product-lots/<lid>/grade")
def grade_lot(lid):
    uid, role = caller()
    b = body_json()
    v_num(b, "lab_moisture_pct")  # always required (schema precedes role)
    require_role(role, "QualityLabTech")
    lot, plant = _lot_ctx(lid)
    posture_gate(plant, "op")
    if lot["status"] != "LAB_PENDING":
        fail("ERR_LOT_INVALID_STATE", 409, "Lot must be LAB_PENDING to grade")
    grade = _apply_lab_values(lot, b)
    lot["grade"] = grade
    lot["graded_by"] = uid
    lot["status"] = "REJECTED" if grade == "OFF_SPEC" else "GRADED"
    touch(lot)
    return ok(lot_view(lot), 200)


@bp.post("/rendering/product-lots/<lid>/release")
def release_lot(lid):
    uid, role = caller()
    require_role(role, "ProductionSupervisor")
    lot, plant = _lot_ctx(lid)
    posture_gate(plant, "op")
    if lot["status"] != "GRADED" or lot["grade"] == "OFF_SPEC":
        fail("ERR_LOT_INVALID_STATE", 409, "Lot must be GRADED (and not OFF_SPEC) to release")
    if lot["graded_by"] is not None and lot["graded_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Releaser must differ from the grader")
    lot["status"] = "RELEASED"
    touch(lot)
    return ok(lot_view(lot), 200)


@bp.post("/rendering/product-lots/<lid>/downgrade")
def downgrade_lot(lid):
    uid, role = caller()
    require_role(role, "QualityLabTech")
    lot, plant = _lot_ctx(lid)
    posture_gate(plant, "op")
    if lot["status"] not in ("GRADED", "RELEASED"):
        fail("ERR_LOT_INVALID_STATE", 409, "Lot must be GRADED or RELEASED to downgrade")
    if lot["status"] == "RELEASED" and lot["allocated_lbs"] != 0:
        fail("ERR_LOT_INVALID_STATE", 409, "Cannot downgrade a lot with allocations")
    lot["status"] = "DOWNGRADED"
    touch(lot)
    return ok(lot_view(lot), 200)


@bp.post("/rendering/product-lots/<lid>/regrade")
def regrade_lot(lid):
    uid, role = caller()
    b = body_json()
    v_num(b, "lab_moisture_pct")  # always required (schema precedes role)
    require_role(role, "QualityLabTech")
    lot, plant = _lot_ctx(lid)
    posture_gate(plant, "op")
    if lot["status"] != "DOWNGRADED":
        fail("ERR_LOT_INVALID_STATE", 409, "Lot must be DOWNGRADED to regrade")
    grade = _apply_lab_values(lot, b)
    lot["grade"] = grade
    lot["graded_by"] = uid
    lot["status"] = "REJECTED" if grade == "OFF_SPEC" else "GRADED"
    touch(lot)
    return ok(lot_view(lot), 200)


@bp.post("/rendering/product-lots/<lid>/reject")
def reject_lot(lid):
    uid, role = caller()
    require_role(role, "QualityLabTech")
    lot, plant = _lot_ctx(lid)
    posture_gate(plant, "op")
    if lot["status"] not in ("GRADED", "DOWNGRADED"):
        fail("ERR_LOT_INVALID_STATE", 409, "Lot must be GRADED or DOWNGRADED to reject")
    lot["status"] = "REJECTED"
    touch(lot)
    return ok(lot_view(lot), 200)
