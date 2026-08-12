"""Batch endpoints: plan, mill/dispersion/adjust/QC/rework/resume/fill/close/cancel/dispose."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from .domain import (
    ADJUSTMENT_KINDS,
    MILL_BUSY_STATES,
    SIZE_CODES,
    SIZES,
    WASHDOWN_BUFFER_MIN,
    base_of_batch,
    base_of_formula,
    compute_voc_actual_gpl,
    containers_of_batch,
    final_cost_cents,
    formula_of,
    reconcile_filled_net,
    ser_batch,
    ser_batch_adjustment,
    ser_container,
    theoretical_cost_cents,
    weigh_passes,
)
from .errors import ApiError, bad_request, conflict, invalid_state, not_found, unprocessable
from .store import next_batch_code, now, store
from .util import (
    D,
    add_months,
    auth,
    body,
    list_response,
    new_light_record,
    new_record,
    parse_datetime_value,
    round2,
    success,
    touch,
    v_enum,
    v_num,
    v_str,
)

bp = Blueprint("batches", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")

# Phases in which each adjustment kind is accepted
ADJUSTMENT_PHASES = {
    "THINNER": ("MILLING",),
    "THICKENER": ("MILLING",),
    "EXEMPT_SOLVENT": ("MILLING",),
    "TINT_SHOT": ("TINTING",),
}

NO_RESERVATION_STATES = ("CLOSED", "DISPOSED", "CANCELLED")


def _window_minutes(start_dt, end_dt):
    secs = (end_dt - start_dt).total_seconds()
    minutes = secs / 60
    return int(minutes) if float(minutes).is_integer() else minutes


def _check_window_conflict(mill_id, base_family, start_dt, end_dt):
    gap_same = timedelta(minutes=0)
    gap_diff = timedelta(minutes=WASHDOWN_BUFFER_MIN)
    for x in store.batches.values():
        if x["mill_id"] != mill_id or x["status"] in NO_RESERVATION_STATES:
            continue
        gap = gap_same if x["base_family"] == base_family else gap_diff
        x_start, x_end = x["_start_dt"], x["_end_dt"]
        if not (start_dt >= x_end + gap or x_start >= end_dt + gap):
            raise conflict("ERR_MILL_WINDOW_CONFLICT", "Mill reservation window conflicts with an existing reservation")


@bp.post("/coatings/batches")
def create_batch():
    auth(("ProductionOperator",))
    b = body()
    formula_id = v_str(b, "formula_id")
    mill_id = v_str(b, "mill_id")
    planned_gallons = v_num(b, "planned_gallons", gt=0)
    start_raw = b.get("mill_window_start")
    start_dt = parse_datetime_value(start_raw, "mill_window_start")
    end_raw = b.get("mill_window_end")
    end_dt = parse_datetime_value(end_raw, "mill_window_end")
    if end_dt <= start_dt:
        raise bad_request("mill_window_end must be strictly after mill_window_start")
    order_id = v_str(b, "order_id", required=False)
    # gate 4: existence, left to right
    formula = store.formulas.get(formula_id)
    if formula is None:
        raise not_found()
    mill = store.mills.get(mill_id)
    if mill is None:
        raise not_found()
    if order_id is not None and order_id not in store.orders:
        raise not_found()
    # gate 8: formula must be ACTIVE
    if formula["status"] != "ACTIVE":
        raise unprocessable("ERR_FORMULA_NOT_ACTIVE", "Referenced formula is not ACTIVE")
    base = base_of_formula(formula)
    # gate 10: capacity then window conflict
    if planned_gallons > mill["capacity_gallons"]:
        raise unprocessable("ERR_MILL_CAPACITY_EXCEEDED", "planned_gallons exceeds mill capacity")
    _check_window_conflict(mill_id, base["base_family"], start_dt, end_dt)
    # gate 11: custom minimum
    if planned_gallons < formula["min_batch_gallons"]:
        raise unprocessable("ERR_CUSTOM_MINIMUM_NOT_MET", "planned_gallons below the formula minimum")
    rec = new_record()
    rec.update({
        "batch_code": next_batch_code(),
        "formula_id": formula_id,
        "pinned_formula_version_no": formula["formula_version_no"],
        "product_category": base["product_category"],
        "base_family": base["base_family"],
        "mill_id": mill_id,
        "order_id": order_id,
        "planned_gallons": planned_gallons,
        "actual_gallons": None,
        "mill_window_start": start_raw,
        "mill_window_end": end_raw,
        "status": "PLANNED",
        "rework_count": 0,
        "dispersion_cycles": 0,
        "voc_actual_gpl": None,
        "theoretical_cost_cents": theoretical_cost_cents(base, formula, planned_gallons),
        "actual_cost_cents": None,
        "filled_net_kg": Decimal("0"),
        "waste_gallons": None,
        "closed_at": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_window_minutes": _window_minutes(start_dt, end_dt),
    })
    store.batches[rec["id"]] = rec
    touch(mill)  # reservation placed
    return success(ser_batch(rec), 201)


@bp.get("/coatings/batches/<bid>")
def get_batch(bid):
    auth(ALL)
    rec = store.batches.get(bid)
    if rec is None:
        raise not_found()
    return success(ser_batch(rec), 200)


@bp.get("/coatings/batches")
def list_batches():
    auth(ALL)
    recs = list(store.batches.values())
    for param in ("formula_id", "mill_id", "order_id", "status"):
        v = request.args.get(param)
        if v is not None:
            recs = [b for b in recs if b.get(param) == v]
    return list_response(recs, ser_batch)


@bp.post("/coatings/batches/<bid>/start-mill")
def start_mill(bid):
    auth(("ProductionOperator",))
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "PLANNED":
        raise invalid_state("Batch is not PLANNED")
    order = store.orders.get(batch["order_id"]) if batch.get("order_id") else None
    if order is not None and order["status"] != "SCHEDULED":
        raise invalid_state("Linked order is not SCHEDULED")
    formula = formula_of(batch)
    if formula is None or formula["status"] != "ACTIVE":
        raise unprocessable("ERR_FORMULA_NOT_ACTIVE", "Batch formula is not ACTIVE")
    mill = store.mills.get(batch["mill_id"])
    if mill is None or mill["status"] != "ACTIVE":
        raise conflict("ERR_MILL_NOT_AVAILABLE", "Mill is not ACTIVE")
    batch["status"] = "MILLING"
    touch(batch)
    if order is not None:
        order["status"] = "IN_PRODUCTION"
        touch(order)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/dispersion-check")
def dispersion_check(bid):
    auth(("ProductionOperator",))
    b = body()
    grind_reading = v_num(b, "grind_reading", minv=0)
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "MILLING":
        raise invalid_state("Batch is not MILLING")
    base = base_of_batch(batch)
    if grind_reading > base["grind_spec_um"]:
        batch["dispersion_cycles"] += 1
        touch(batch)
    else:
        batch["status"] = "TINTING"
        touch(batch)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/adjustments")
def create_adjustment(bid):
    auth(("ProductionOperator",))
    b = body()
    kind = v_enum(b, "kind", ADJUSTMENT_KINDS)
    quantity = v_num(b, "quantity", gt=0)
    colorant_id = b.get("colorant_id")
    if kind == "TINT_SHOT":
        if not isinstance(colorant_id, str):
            raise bad_request("colorant_id is required for TINT_SHOT")
    else:
        if colorant_id is not None:
            raise bad_request("colorant_id is forbidden unless kind is TINT_SHOT")
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    # gate 4: existence
    if kind == "TINT_SHOT" and colorant_id not in store.colorants:
        raise not_found()
    # gate 6: phase gating by kind
    if batch["status"] not in ADJUSTMENT_PHASES[kind]:
        raise invalid_state("Adjustment kind %s not allowed while batch is %s" % (kind, batch["status"]))
    if kind == "THINNER":
        voc = D(quantity) * Decimal("0.9")
    elif kind == "TINT_SHOT":
        voc = D(quantity) * D(store.colorants[colorant_id]["voc_g_per_unit"])
    else:
        voc = Decimal("0")
    rec = new_light_record()
    rec.update({
        "batch_id": bid,
        "kind": kind,
        "quantity": quantity,
        "colorant_id": colorant_id if kind == "TINT_SHOT" else None,
        "voc_contribution_g": voc,
        "cycle_index": batch["rework_count"],
    })
    store.batch_adjustments[rec["id"]] = rec
    return success(ser_batch_adjustment(rec), 201)


@bp.get("/coatings/batches/<bid>/adjustments")
def list_adjustments(bid):
    auth(ALL)
    if bid not in store.batches:
        raise not_found()
    recs = [a for a in store.batch_adjustments.values() if a["batch_id"] == bid]
    return list_response(recs, ser_batch_adjustment)


@bp.post("/coatings/batches/<bid>/submit-qc")
def submit_qc(bid):
    auth(("ProductionOperator",))
    b = body()
    actual_gallons = v_num(b, "actual_gallons", gt=0)
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "TINTING":
        raise invalid_state("Batch is not TINTING")
    batch["actual_gallons"] = actual_gallons
    batch["voc_actual_gpl"] = compute_voc_actual_gpl(batch)
    batch["status"] = "QC_PENDING"
    touch(batch)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/rework")
def rework_batch(bid):
    auth(("ProductionOperator",))
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "REWORK":
        raise invalid_state("Batch is not REWORK")
    mill = store.mills.get(batch["mill_id"])
    if mill is None or mill["status"] != "ACTIVE":
        raise conflict("ERR_MILL_NOT_AVAILABLE", "Mill is not ACTIVE")
    batch["status"] = "MILLING"
    touch(batch)
    order = store.orders.get(batch["order_id"]) if batch.get("order_id") else None
    if order is not None and order["status"] == "BLOCKED":
        order["status"] = "IN_PRODUCTION"
        touch(order)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/resume")
def resume_batch(bid):
    auth(("ProductionOperator",))
    b = body()
    new_formula_id = v_str(b, "new_formula_id")
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    formula = store.formulas.get(new_formula_id)
    if formula is None:
        raise not_found()
    if batch["status"] != "ON_HOLD":
        raise invalid_state("Batch is not ON_HOLD")
    if formula["status"] != "ACTIVE":
        raise unprocessable("ERR_FORMULA_NOT_ACTIVE", "new_formula_id does not reference an ACTIVE formula")
    batch["formula_id"] = new_formula_id
    batch["pinned_formula_version_no"] = formula["formula_version_no"]
    batch["status"] = "PLANNED"
    touch(batch)
    order = store.orders.get(batch["order_id"]) if batch.get("order_id") else None
    if order is not None and order["status"] == "BLOCKED":
        order["status"] = "SCHEDULED"
        touch(order)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/fills")
def create_fill(bid):
    auth(("ProductionOperator",))
    b = body()
    size_code = v_enum(b, "size_code", SIZE_CODES)
    actual_fill_g = b.get("actual_fill_g")
    if isinstance(actual_fill_g, bool) or not isinstance(actual_fill_g, int):
        if isinstance(actual_fill_g, float) and actual_fill_g.is_integer():
            actual_fill_g = int(actual_fill_g)
        else:
            raise bad_request("actual_fill_g must be an integer")
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] not in ("QC_APPROVED", "FILLING"):
        raise invalid_state("Batch is not ready for filling")
    if batch["status"] == "QC_APPROVED":
        batch["status"] = "FILLING"
    spec = SIZES[size_code]
    nominal = spec["nominal"]
    passed = weigh_passes(nominal, actual_fill_g)
    base = base_of_batch(batch)
    manufactured = now()
    rec = new_record()
    rec.update({
        "batch_id": bid,
        "size_code": size_code,
        "nominal_fill_g": nominal,
        "actual_fill_g": actual_fill_g,
        "fill_variance_g": actual_fill_g - nominal,
        "net_weight_kg": round2(D(actual_fill_g) / Decimal("1000")),
        "volume_gal": spec["volume"],
        "size_liters": spec["liters"],
        "status": "IN_STOCK" if passed else "QUARANTINED",
        "order_id": None,
        "destination_state_code": None,
        "manufactured_at": manufactured,
        "expiry_date": add_months(manufactured, base["shelf_life_months"]),
        "freeze_exposure_count": 0,
        "shipped_at": None,
        "disposal_request_id": None,
        "pre_disposal_status": None,
    })
    store.containers[rec["id"]] = rec
    reconcile_filled_net(batch)
    touch(batch)
    return success(ser_container(rec), 201)


@bp.post("/coatings/batches/<bid>/complete-filling")
def complete_filling(bid):
    auth(("ProductionOperator",))
    b = body()
    waste_gallons = v_num(b, "waste_gallons", minv=0)
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "FILLING":
        raise invalid_state("Batch is not FILLING")
    # pinned rounding order: per-container net weights (already 2dp) summed
    filled_kg = Decimal("0")
    for c in containers_of_batch(bid):
        if c["status"] != "REJECTED":
            filled_kg += c["net_weight_kg"]
    base = base_of_batch(batch)
    drawdown_kg = (D(batch["actual_gallons"]) - D(waste_gallons)) * D(base["density_kg_per_gal"])
    if drawdown_kg <= 0:
        ok = filled_kg == 0 and drawdown_kg == 0
    else:
        deviation = abs(filled_kg - drawdown_kg) / drawdown_kg * Decimal("100")
        ok = deviation <= Decimal("0.5")
    if not ok:
        raise unprocessable("ERR_FILL_RECONCILIATION_FAILED", "Filled mass deviates from drawdown by more than 0.5%")
    batch["waste_gallons"] = waste_gallons
    batch["filled_net_kg"] = filled_kg
    batch["actual_cost_cents"] = final_cost_cents(batch)
    batch["status"] = "FILLED"
    touch(batch)
    mill = store.mills.get(batch["mill_id"])
    if mill is not None:
        touch(mill)  # FILLED leaves the reserved-minutes state set
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/close")
def close_batch(bid):
    auth(("ProductionOperator",))
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] != "FILLED":
        raise invalid_state("Batch is not FILLED")
    for c in containers_of_batch(bid):
        if c["status"] == "QUARANTINED":
            raise invalid_state("Batch still has QUARANTINED containers")
    live_retain = False
    for m in store.color_matches.values():
        if (
            m["batch_id"] == bid
            and m["status"] == "APPROVED"
            and m["cycle_index"] == batch["rework_count"]
            and m["retain_purged_at"] is None
        ):
            live_retain = True
            break
    if not live_retain:
        raise unprocessable("ERR_RETAIN_SAMPLE_MISSING", "No live retain sample from an approved match of the final cycle")
    batch["status"] = "CLOSED"
    batch["closed_at"] = now()
    touch(batch)
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/cancel")
def cancel_batch(bid):
    auth(("ProductionOperator",))
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    if batch["status"] not in ("PLANNED", "ON_HOLD"):
        raise invalid_state("Only PLANNED or ON_HOLD batches can be cancelled")
    batch["status"] = "CANCELLED"
    touch(batch)
    mill = store.mills.get(batch["mill_id"])
    if mill is not None:
        touch(mill)  # reservation released
    return success(ser_batch(batch), 200)


@bp.post("/coatings/batches/<bid>/dispose")
def dispose_batch(bid):
    auth(("ProductionOperator",))
    batch = store.batches.get(bid)
    if batch is None:
        raise not_found()
    src = batch["status"]
    if src not in ("MILLING", "TINTING", "QC_PENDING", "REWORK", "QC_APPROVED"):
        raise invalid_state("Batch cannot be disposed from %s" % src)
    batch["status"] = "DISPOSAL_PENDING"
    touch(batch)
    if src in ("MILLING", "TINTING", "QC_PENDING"):
        order = store.orders.get(batch["order_id"]) if batch.get("order_id") else None
        if order is not None and order["status"] == "IN_PRODUCTION":
            order["status"] = "BLOCKED"
            touch(order)
    return success(ser_batch(batch), 200)
