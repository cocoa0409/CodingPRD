"""Blend batches: charging, blending, disposition, QC results and retain jars."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import core
import enums
import store
import views
from core import (D, authenticate, body, caller_id, fail, now, pagination, q_enum,
                  q_str, req_dt, req_enum, req_num, req_int, req_str, rhu, sec)

bp = Blueprint("batches", __name__)


# ==========================================================================
# Helpers
# ==========================================================================
def _batch_spec(batch):
    recipe = store.get("BlendRecipe", batch["blend_recipe_id"])
    if recipe is None:
        return None, None
    return recipe, store.get("ProductSpec", recipe["product_spec_id"])


def _segregation_check(batch):
    who = caller_id()
    for result in store.where("QCResult", blend_batch_id=batch["id"]):
        if result["technician_user_id"] == who:
            fail("ERR_SEGREGATION_OF_DUTIES")


def _batch_draws(batch_id):
    rows = store.where("ComponentDraw", blend_batch_id=batch_id)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ==========================================================================
# BlendBatch CRUD
# ==========================================================================
@bp.post("/blend-batches")
def create_batch():
    authenticate(["BlendOperator"])
    b = body()
    recipe_id = req_str(b, "blend_recipe_id")
    batch_code = req_str(b, "batch_code")
    planned_volume_l = req_num(b, "planned_volume_l", gt=0)

    recipe = store.must_get("BlendRecipe", recipe_id)
    for existing in store.all_rows("BlendBatch"):
        if existing["batch_code"] == batch_code:
            fail("ERR_DUPLICATE_CODE")

    record = {
        "blend_recipe_id": recipe["id"],
        "batch_code": batch_code,
        "planned_volume_l": planned_volume_l,
        "blend_tank_id": None,
        "charge_volume_l": None,
        "charge_mass_kg": None,
        "window_start": None,
        "window_end": None,
        "production_status": "PLANNED",
        "qc_status": "PENDING",
        "predicted_kv100_cst": recipe["predicted_kv100_cst"],
        "measured_kv100_cst": None,
        "heel_ratio_actual": None,
        "claim_eligible": False,
        "estimated_component_cost_cents": 0,
        "component_cost_cents": 0,
        "retain_count": 0,
    }
    return views.one(store.insert("BlendBatch", record), 201)


@bp.get("/blend-batches/<bid>")
def read_batch(bid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("BlendBatch", bid))


@bp.get("/blend-batches")
def list_batches():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    recipe_id = q_str("blend_recipe_id")
    tank_id = q_str("blend_tank_id")
    production_status = q_enum("production_status", enums.PRODUCTION_STATUSES)
    qc_status = q_enum("qc_status", enums.QC_STATUSES)
    rows = store.where("BlendBatch", blend_recipe_id=recipe_id, blend_tank_id=tank_id,
                       production_status=production_status, qc_status=qc_status)
    return views.listing(views.by_created_asc(rows), limit, offset)


# ==========================================================================
# Charging
# ==========================================================================
@bp.post("/blend-batches/<bid>/charge")
def charge_batch(bid):
    authenticate(["BlendOperator"])
    b = body()
    tank_id = req_str(b, "blend_tank_id")
    charge_volume_l = req_num(b, "charge_volume_l", gt=0)
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")

    batch = store.must_get("BlendBatch", bid)                        # rung 4
    tank = store.must_get("BlendTank", tank_id)                      # rung 5

    if batch["production_status"] != "PLANNED":                      # rung 10
        fail("ERR_INVALID_STATE")
    if tank["status"] != "AVAILABLE":                                # rung 11
        fail("ERR_TANK_NOT_AVAILABLE")
    recipe, spec = _batch_spec(batch)
    if recipe is None or recipe["status"] != "ACTIVE":               # rung 12
        fail("ERR_RECIPE_NOT_ACTIVE")
    if spec is None or spec["status"] != "ACTIVE":                   # rung 13
        fail("ERR_SPEC_NOT_ACTIVE")

    for lot in store.all_rows("ComponentLot"):
        calc.refresh_lot(lot)

    heel_family = tank["heel_additive_family"]
    spec_family = spec["additive_family"]
    cross, same = calc.heel_families(tank, spec)

    # rung 17 - absolute food-grade barrier
    if spec_family == "FOOD_GRADE_H1" and heel_family not in ("NONE", "FOOD_GRADE_H1"):
        fail("ERR_FLUSH_REQUIRED")
    if heel_family == "FOOD_GRADE_H1" and spec_family != "FOOD_GRADE_H1":
        fail("ERR_FLUSH_REQUIRED")

    # rung 18 - heel ratio ceiling
    ratio = calc.heel_ratio(tank, charge_volume_l)
    if ratio > calc.heel_limit(cross, same):
        fail("ERR_HEEL_CONTAMINATION_EXCEEDED")

    components = calc.recipe_components(recipe["id"])
    mass_kg = calc.charge_mass_kg(charge_volume_l)
    required = calc.component_requirements(components, mass_kg)

    # rung 19 - blocked stock
    for code, required_kg in required.items():
        available = sum((D(l["available_kg"]) for l in calc.candidate_lots(code)),
                        Decimal(0))
        if available < D(required_kg):
            blocked = sum((D(l["available_kg"]) for l in calc.quarantined_lots(code)),
                          Decimal(0))
            if available + blocked >= D(required_kg):
                fail("ERR_LOT_QUARANTINED")

    # rung 24 - tank occupancy collision (half-open, changeover-buffered)
    effective_start = window_start
    if cross:
        effective_start = window_start - timedelta(
            minutes=calc.CHANGEOVER_BUFFER_MINUTES)
    for other in store.all_rows("BlendBatch"):
        if other["id"] == batch["id"]:
            continue
        if other["blend_tank_id"] != tank["id"]:
            continue
        if other["production_status"] not in ("PLANNED", "CHARGING", "BLENDED",
                                              "RELEASED"):
            continue
        if other["window_start"] is None or other["window_end"] is None:
            continue
        if (sec(effective_start) < sec(other["window_end"])
                and sec(other["window_start"]) < sec(window_end)):
            fail("ERR_TANK_WINDOW_CONFLICT")

    # rung 26 - window sanity
    if not sec(window_end) > sec(window_start):
        fail("ERR_INVALID_WINDOW")

    # rung 29 - pinned revision currency
    if recipe["spec_revision_pinned"] != spec["revision"]:
        fail("ERR_SPEC_REVISION_STALE")

    # rung 35 - material shortage
    for code, required_kg in required.items():
        available = sum((D(l["available_kg"]) for l in calc.candidate_lots(code)),
                        Decimal(0))
        if available < D(required_kg):
            fail("ERR_COMPONENT_SHORTAGE")

    # rung 38 - tank capacity
    if D(tank["heel_volume_l"]) + D(charge_volume_l) > D(tank["capacity_l"]):
        fail("ERR_TANK_CAPACITY_EXCEEDED")

    # ---- side effects ----------------------------------------------------
    estimated = calc.moving_average_cost(required)

    touched_lots = []
    for code, required_kg in required.items():
        remaining = D(required_kg)
        for lot in calc.candidate_lots(code):
            if remaining <= 0:
                break
            available = D(lot["available_kg"])
            if available <= 0:
                continue
            take = rhu(min(available, remaining), 3)
            if take <= 0:
                continue
            store.insert("ComponentDraw", {
                "blend_batch_id": batch["id"],
                "component_lot_id": lot["id"],
                "component_code": lot["component_code"],
                "drawn_kg": take,
                "unit_cost_cents_per_kg": lot["unit_cost_cents_per_kg"],
                "status": "RESERVED",
            })
            remaining -= take
            calc.refresh_lot(lot)
            touched_lots.append(lot)
            if D(lot["available_kg"]) == 0 and lot["status"] == "AVAILABLE":
                lot["status"] = "DEPLETED"
                store.touch(lot)

    batch["blend_tank_id"] = tank["id"]
    batch["charge_volume_l"] = charge_volume_l
    batch["charge_mass_kg"] = mass_kg
    batch["window_start"] = window_start
    batch["window_end"] = window_end
    batch["production_status"] = "CHARGING"
    batch["heel_ratio_actual"] = ratio
    batch["estimated_component_cost_cents"] = estimated

    claim_limit = calc.claim_heel_limit(cross, same)
    eligible = ratio <= claim_limit
    if eligible:
        for lot in touched_lots:
            if not lot["coa_viscosity_verified"]:
                eligible = False
                break
    if eligible and recipe["spec_revision_pinned"] != spec["revision"]:
        eligible = False
    batch["claim_eligible"] = eligible

    store.touch(batch)
    tank["status"] = "CHARGED"
    store.touch(tank)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/cancel-charge")
def cancel_charge(bid):
    authenticate(["BlendOperator"])
    b = body()
    req_str(b, "reason")
    batch = store.must_get("BlendBatch", bid)
    if batch["production_status"] != "CHARGING" or batch["qc_status"] != "PENDING":
        fail("ERR_INVALID_STATE")

    for draw in _batch_draws(batch["id"]):
        if draw["status"] != "RESERVED":
            continue
        draw["status"] = "RETURNED"
        store.touch(draw)
        lot = store.get("ComponentLot", draw["component_lot_id"])
        if lot is not None:
            calc.refresh_lot(lot)
            if lot["status"] == "DEPLETED" and D(lot["available_kg"]) > 0:
                lot["status"] = "AVAILABLE"
                store.touch(lot)

    tank = store.get("BlendTank", batch["blend_tank_id"])
    batch["blend_tank_id"] = None
    batch["charge_volume_l"] = None
    batch["charge_mass_kg"] = None
    batch["window_start"] = None
    batch["window_end"] = None
    batch["heel_ratio_actual"] = None
    batch["estimated_component_cost_cents"] = 0
    batch["claim_eligible"] = False
    batch["production_status"] = "PLANNED"
    store.touch(batch)

    if tank is not None and tank["status"] == "CHARGED":
        tank["status"] = "AVAILABLE"
        store.touch(tank)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/complete-blend")
def complete_blend(bid):
    authenticate(["BlendOperator"])
    batch = store.must_get("BlendBatch", bid)
    production = batch["production_status"]
    if production == "CHARGING":
        pass
    elif production == "REWORKED" and batch["qc_status"] == "PENDING":
        pass
    else:
        fail("ERR_INVALID_STATE")

    for draw in _batch_draws(batch["id"]):
        if draw["status"] == "RESERVED":
            draw["status"] = "CONSUMED"
            store.touch(draw)
            lot = store.get("ComponentLot", draw["component_lot_id"])
            if lot is not None:
                calc.refresh_lot(lot)

    batch["component_cost_cents"] = calc.consumption_layer_cost(batch["id"])
    batch["production_status"] = "BLENDED"
    store.touch(batch)
    return views.one(batch)


# ==========================================================================
# Disposition
# ==========================================================================
@bp.post("/blend-batches/<bid>/release")
def release_batch(bid):
    authenticate(["QualityManager"])
    batch = store.must_get("BlendBatch", bid)
    _segregation_check(batch)                                        # rung 7
    if batch["production_status"] != "BLENDED":                      # rung 10
        fail("ERR_INVALID_STATE")
    if batch["qc_status"] not in ("PASSED", "WAIVED"):
        fail("ERR_INVALID_STATE")
    if cascades.refresh_retain_count(batch) < calc.MIN_RETAIN_COUNT:  # rung 23
        fail("ERR_INSUFFICIENT_RETAINS")

    recipe, spec = _batch_spec(batch)
    batch["production_status"] = "RELEASED"
    store.touch(batch)

    tank = store.get("BlendTank", batch["blend_tank_id"])
    if tank is not None and tank["status"] == "CHARGED":
        tank["status"] = "AVAILABLE"
        tank["heel_volume_l"] = rhu(
            D(batch["charge_volume_l"]) * calc.HEEL_RETENTION_PCT / D(100), 3)
        if spec is not None:
            tank["heel_additive_family"] = spec["additive_family"]
            tank["heel_product_code"] = spec["product_code"]
        store.touch(tank)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/quarantine")
def quarantine_batch(bid):
    authenticate(["QualityManager"])
    b = body()
    req_str(b, "reason")
    batch = store.must_get("BlendBatch", bid)
    if batch["production_status"] not in ("BLENDED", "RELEASED"):
        fail("ERR_INVALID_STATE")
    from_blended = batch["production_status"] == "BLENDED"
    batch["production_status"] = "QUARANTINED"
    store.touch(batch)
    cascades.cascade_b(batch, quarantine_tank=from_blended)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/rework")
def rework_batch(bid):
    authenticate(["BlendOperator"])
    b = body()
    req_str(b, "reason")
    batch = store.must_get("BlendBatch", bid)
    if batch["production_status"] != "QUARANTINED" or batch["qc_status"] != "FAILED":
        fail("ERR_INVALID_STATE")
    batch["production_status"] = "REWORKED"
    batch["qc_status"] = "PENDING"
    batch["measured_kv100_cst"] = None
    store.touch(batch)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/dispose")
def dispose_batch(bid):
    authenticate(["QualityManager"])
    b = body()
    req_str(b, "reason")
    batch = store.must_get("BlendBatch", bid)
    if batch["production_status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE")
    batch["production_status"] = "DISPOSED"
    store.touch(batch)
    return views.one(batch)


@bp.post("/blend-batches/<bid>/waive-qc")
def waive_qc(bid):
    authenticate(["QualityManager"])
    b = body()
    req_str(b, "justification")
    batch = store.must_get("BlendBatch", bid)
    _segregation_check(batch)                                        # rung 7
    if batch["qc_status"] not in ("FAILED", "SAMPLED"):              # rung 10
        fail("ERR_INVALID_STATE")
    if batch["claim_eligible"]:                                      # rung 22
        fail("ERR_CLAIM_NOT_SUBSTANTIATED")
    batch["qc_status"] = "WAIVED"
    store.touch(batch)
    return views.one(batch)


# ==========================================================================
# Draws, QC results, retains
# ==========================================================================
@bp.get("/blend-batches/<bid>/component-draws")
def list_batch_draws(bid):
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    status = q_enum("status", enums.DRAW_STATUSES)
    store.must_get("BlendBatch", bid)
    rows = store.where("ComponentDraw", blend_batch_id=bid, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


def _required_tests_pass(batch_id):
    rows = sorted(store.where("QCResult", blend_batch_id=batch_id),
                  key=lambda r: (r["created_at"], r["_seq"]))
    for test_type in calc.REQUIRED_TESTS:
        latest = None
        for row in rows:
            if row["test_type"] == test_type:
                latest = row
        if latest is None or latest["result"] != "PASS":
            return False
    return True


@bp.post("/blend-batches/<bid>/qc-results")
def create_qc_result(bid):
    authenticate(["QCTechnician"])
    b = body()
    test_type = req_enum(b, "test_type", enums.TEST_TYPES)
    measured_value = req_num(b, "measured_value", gt=0)
    batch = store.must_get("BlendBatch", bid)

    recipe, spec = _batch_spec(batch)
    if test_type == "KV100" and spec is not None:
        lower, upper = calc.viscosity_band(spec["target_kv100_cst"],
                                           spec["kv100_tolerance_pct"])
        verdict = "PASS" if calc.in_band(measured_value, lower, upper) else "FAIL"
    else:
        verdict = "PASS" if D(measured_value) > 0 else "FAIL"

    qc = batch["qc_status"]
    if qc not in ("PENDING", "SAMPLED"):                             # rung 10
        fail("ERR_INVALID_STATE")
    if qc == "PENDING" and verdict == "PASS":
        if batch["production_status"] not in ("CHARGING", "BLENDED", "REWORKED"):
            fail("ERR_INVALID_STATE")

    result = store.insert("QCResult", {
        "blend_batch_id": batch["id"],
        "test_type": test_type,
        "measured_value": measured_value,
        "result": verdict,
        "tested_at": now(),
        "technician_user_id": caller_id(),
    }, versioned=False)

    if test_type == "KV100":
        batch["measured_kv100_cst"] = measured_value

    if verdict == "FAIL":
        batch["qc_status"] = "FAILED"
        if batch["production_status"] == "BLENDED":
            batch["production_status"] = "QUARANTINED"
            store.touch(batch)
            cascades.cascade_b(batch, quarantine_tank=True)
            return views.one(result, 201)
    elif qc == "PENDING":
        batch["qc_status"] = "SAMPLED"
    elif qc == "SAMPLED" and _required_tests_pass(batch["id"]):
        batch["qc_status"] = "PASSED"

    store.touch(batch)
    return views.one(result, 201)


@bp.get("/blend-batches/<bid>/qc-results")
def list_qc_results(bid):
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    test_type = q_enum("test_type", enums.TEST_TYPES)
    store.must_get("BlendBatch", bid)
    rows = store.where("QCResult", blend_batch_id=bid, test_type=test_type)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/blend-batches/<bid>/retain-samples")
def create_retain(bid):
    authenticate(["QCTechnician"])
    b = body()
    retain_code = req_str(b, "retain_code")
    volume_ml = req_num(b, "volume_ml", ge=100)
    batch = store.must_get("BlendBatch", bid)

    for existing in store.where("RetainSample", blend_batch_id=batch["id"]):
        if existing["retain_code"] == retain_code:
            fail("ERR_DUPLICATE_CODE")

    recipe, spec = _batch_spec(batch)
    retained_at = now()
    spec_id = spec["id"] if spec is not None else None
    retain = store.insert("RetainSample", {
        "blend_batch_id": batch["id"],
        "retain_code": retain_code,
        "volume_ml": volume_ml,
        "retained_at": retained_at,
        "retention_until": calc.retention_until(spec_id, retained_at),
        "status": "HELD",
    })
    cascades.refresh_retain_count(batch)
    store.touch(batch)
    return views.one(retain, 201)


@bp.get("/blend-batches/<bid>/retain-samples")
def list_retains(bid):
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    status = q_enum("status", enums.RETAIN_STATUSES)
    store.must_get("BlendBatch", bid)
    rows = store.where("RetainSample", blend_batch_id=bid, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/retain-samples/<rid>/dispose")
def dispose_retain(rid):
    authenticate(["QualityManager"])
    b = body()
    req_str(b, "reason")
    retain = store.must_get("RetainSample", rid)
    if retain["status"] != "HELD":                                   # rung 10
        fail("ERR_INVALID_STATE")
    if sec(now()) < sec(retain["retention_until"]):                  # rung 27
        fail("ERR_RETENTION_WINDOW_ACTIVE")
    retain["status"] = "DISPOSED"
    store.touch(retain)
    batch = store.get("BlendBatch", retain["blend_batch_id"])
    if batch is not None:
        cascades.refresh_retain_count(batch)
    return views.one(retain)
