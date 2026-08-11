"""Yeast programs, press batches, blend lines, tanks, fermentation batches."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INSUFFICIENT_FRUIT,
    ERR_INSUFFICIENT_VOLUME,
    ERR_NO_TANK_AVAILABLE,
    ERR_PRESS_WINDOW_CONFLICT,
    invalid_state,
    not_found,
    validation,
)
from middleware import require_roles
from response import paginate, parse_ts, success_object
from services import (
    TANK_MATERIALS,
    YEAST_KINDS,
    _d,
    compute_abv,
    emit_event,
    fnum,
    lot_status_from_pressed,
    q2,
    q3,
    recompute_contract_received,
    ser_blend_line,
    ser_fermentation_batch,
    ser_press_batch,
    ser_tank,
    ser_yeast,
)

bp = Blueprint("cellar", __name__, url_prefix="/cidery")

CELLAR_READ = ("CellarLead", "ComplianceOfficer", "PackagingOperator", "PlatformAdmin")


def body():
    return request.get_json(silent=True) or {}


# --- YeastProgram ------------------------------------------------------------------
@bp.post("/yeast-programs")
@require_roles("CellarLead")
def create_yeast_program():
    b = body()
    kind = b.get("kind")
    if kind is not None and kind not in YEAST_KINDS:
        raise validation(f"kind must be one of {sorted(YEAST_KINDS)}")
    rec = {
        "code": b.get("code"),
        "kind": kind,
        "attenuation_pct": b.get("attenuation_pct"),
        "temp_min_f": b.get("temp_min_f"),
        "temp_max_f": b.get("temp_max_f"),
        "nutrient_required": bool(b.get("nutrient_required", False)),
    }
    db.stamp_new(rec, common=False)
    db.store["yeast_programs"][rec["id"]] = rec
    return success_object(ser_yeast(rec), 201)


@bp.get("/yeast-programs/<id>")
@require_roles(*CELLAR_READ)
def get_yeast_program(id):
    rec = db.store["yeast_programs"].get(id)
    if rec is None:
        raise not_found("yeast program")
    return success_object(ser_yeast(rec))


@bp.get("/yeast-programs")
@require_roles(*CELLAR_READ)
def list_yeast_programs():
    return paginate(list(db.store["yeast_programs"].values()), ser_yeast)


# --- PressBatch / BlendLine ----------------------------------------------------------
def _get_batch(batchId):
    rec = db.store["press_batches"].get(batchId)
    if rec is None:
        raise not_found("press batch")
    return rec


def _batch_lines(batch_id):
    return sorted(
        (l for l in db.store["blend_lines"].values()
         if l["press_batch_id"] == batch_id),
        key=lambda l: (l["created_at"], l["_seq"]),
    )


def _recompute_target(batch):
    total = sum(l["weight_lbs"] for l in _batch_lines(batch["id"]))
    target = int(_d(total) * Decimal("0.5"))
    if batch["target_juice_liters"] != target:
        batch["target_juice_liters"] = target
        db.bump(batch)


def _validate_line(lot, weight, running):
    if lot["status"] not in ("RECEIVED", "PARTIALLY_PRESSED"):
        raise invalid_state("harvest lot is not in RECEIVED or PARTIALLY_PRESSED")
    unpressed = lot["weight_lbs"] - lot["pressed_weight_lbs"]
    if running.get(lot["id"], 0) + weight > unpressed:
        raise ApiError(
            ERR_INSUFFICIENT_FRUIT,
            "blend line weight exceeds lot unpressed_weight_lbs",
            409,
        )
    running[lot["id"]] = running.get(lot["id"], 0) + weight


@bp.post("/press-batches")
@require_roles("CellarLead")
def create_press_batch():
    b = body()
    try:
        scheduled = parse_ts(b.get("scheduled_press_date"))
    except (TypeError, ValueError):
        raise validation("scheduled_press_date must be an ISO8601 timestamp")
    window = b.get("press_window_minutes")
    if not isinstance(window, int) or window < 30 or window > 480:
        raise validation("press_window_minutes must be between 30 and 480")
    lines_in = b.get("blend_lines") or []
    # resolve and validate every line before creating anything (atomicity)
    running = {}
    resolved = []
    for line in lines_in:
        lot = db.store["harvest_lots"].get(line.get("harvest_lot_id"))
        if lot is None:
            raise not_found("harvest lot")
        weight = line.get("weight_lbs")
        if not isinstance(weight, int) or weight <= 0:
            raise validation("blend line weight_lbs must be a positive integer")
        _validate_line(lot, weight, running)
        resolved.append((lot, weight, line.get("position")))
    rec = {
        "scheduled_press_date": scheduled,
        "press_window_minutes": window,
        "target_juice_liters": 0,
        "actual_juice_liters": None,
        "press_yield_ratio": None,
        "blend_brix": None,
        "blend_tannin": None,
        "status": "PLANNED",
    }
    db.stamp_new(rec)
    db.store["press_batches"][rec["id"]] = rec
    for lot, weight, position in resolved:
        _create_line(rec["id"], lot["id"], weight, position)
    _recompute_target(rec)
    return success_object(ser_press_batch(rec), 201)


def _create_line(batch_id, lot_id, weight, position):
    rec = {
        "press_batch_id": batch_id,
        "harvest_lot_id": lot_id,
        "weight_lbs": weight,
        "position": position,
    }
    db.stamp_new(rec, common=False)
    db.store["blend_lines"][rec["id"]] = rec
    return rec


@bp.get("/press-batches/<batchId>")
@require_roles(*CELLAR_READ)
def get_press_batch(batchId):
    return success_object(ser_press_batch(_get_batch(batchId)))


@bp.get("/press-batches")
@require_roles(*CELLAR_READ)
def list_press_batches():
    items = list(db.store["press_batches"].values())
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate(items, ser_press_batch)


@bp.get("/press-batches/<batchId>/blend-lines")
@require_roles("CellarLead", "ComplianceOfficer", "PlatformAdmin")
def list_batch_blend_lines(batchId):
    batch = _get_batch(batchId)
    return paginate(_batch_lines(batch["id"]), ser_blend_line)


@bp.post("/press-batches/<batchId>/blend-lines")
@require_roles("CellarLead")
def add_blend_line(batchId):
    batch = _get_batch(batchId)
    b = body()
    lot = db.store["harvest_lots"].get(b.get("harvest_lot_id"))
    if lot is None:
        raise not_found("harvest lot")
    if batch["status"] != "PLANNED":
        raise invalid_state("blend lines can only be added to a PLANNED batch")
    weight = b.get("weight_lbs")
    if not isinstance(weight, int) or weight <= 0:
        raise validation("weight_lbs must be a positive integer")
    _validate_line(lot, weight, {})
    rec = _create_line(batch["id"], lot["id"], weight, b.get("position"))
    _recompute_target(batch)
    return success_object(ser_blend_line(rec), 201)


@bp.get("/blend-lines")
@require_roles("CellarLead", "ComplianceOfficer", "PlatformAdmin")
def list_blend_lines():
    items = list(db.store["blend_lines"].values())
    pb = request.args.get("press_batch_id")
    if pb is not None:
        items = [l for l in items if l["press_batch_id"] == pb]
    hl = request.args.get("harvest_lot_id")
    if hl is not None:
        items = [l for l in items if l["harvest_lot_id"] == hl]
    return paginate(items, ser_blend_line)


@bp.get("/blend-lines/<id>")
@require_roles("CellarLead", "ComplianceOfficer", "PlatformAdmin")
def get_blend_line(id):
    rec = db.store["blend_lines"].get(id)
    if rec is None:
        raise not_found("blend line")
    return success_object(ser_blend_line(rec))


def _apply_consumption(batch, sign):
    """sign=+1 applies consumption at start; sign=-1 reverses it at pause."""
    for line in _batch_lines(batch["id"]):
        lot = db.store["harvest_lots"].get(line["harvest_lot_id"])
        if lot is None:
            continue
        lot["pressed_weight_lbs"] += sign * line["weight_lbs"]
        lot["status"] = lot_status_from_pressed(lot)
        db.bump(lot)
        contract = db.store["contracts"].get(lot["contract_id"])
        if contract is not None:
            recompute_contract_received(contract)


@bp.post("/press-batches/<batchId>/start")
@require_roles("CellarLead")
def start_press_batch(batchId):
    batch = _get_batch(batchId)
    if batch["status"] != "PLANNED":
        raise invalid_state("press batch is not PLANNED")
    lines = _batch_lines(batch["id"])
    if not lines:
        raise invalid_state("press batch has no blend lines")
    lots = []
    for line in lines:
        lot = db.store["harvest_lots"].get(line["harvest_lot_id"])
        if lot is None or lot["status"] not in ("RECEIVED", "PARTIALLY_PRESSED"):
            raise invalid_state(
                "all blend line harvest lots must be RECEIVED or PARTIALLY_PRESSED"
            )
        lots.append(lot)
    if sum(l["weight_lbs"] for l in lines) <= 0:
        raise invalid_state("sum of blend line weights must be greater than zero")
    # press window overlap: half-open [start, start + window)
    this_start = batch["scheduled_press_date"]
    this_end = this_start + timedelta(minutes=batch["press_window_minutes"])
    for other in db.store["press_batches"].values():
        if other["id"] == batch["id"] or other["status"] != "PRESSING":
            continue
        o_start = other["scheduled_press_date"]
        o_end = o_start + timedelta(minutes=other["press_window_minutes"])
        if o_start < this_end and o_end > this_start:
            raise ApiError(
                ERR_PRESS_WINDOW_CONFLICT,
                "press window overlaps another PRESSING batch",
                409,
            )
    _apply_consumption(batch, +1)
    batch["status"] = "PRESSING"
    db.bump(batch)
    return success_object(ser_press_batch(batch))


@bp.post("/press-batches/<batchId>/pause")
@require_roles("CellarLead")
def pause_press_batch(batchId):
    batch = _get_batch(batchId)
    if batch["status"] != "PRESSING":
        raise invalid_state("press batch is not PRESSING")
    b = body()
    batch["_last_pause_reason"] = b.get("reason")
    _apply_consumption(batch, -1)
    batch["status"] = "PLANNED"
    db.bump(batch)
    return success_object(ser_press_batch(batch))


@bp.post("/press-batches/<batchId>/complete")
@require_roles("CellarLead")
def complete_press_batch(batchId):
    batch = _get_batch(batchId)
    if batch["status"] != "PRESSING":
        raise invalid_state("press batch is not PRESSING")
    b = body()
    actual = b.get("actual_juice_liters")
    if not isinstance(actual, int) or actual <= 0:
        raise validation("actual_juice_liters must be provided and greater than zero")
    lines = [
        l for l in _batch_lines(batch["id"])
        if db.store["harvest_lots"].get(l["harvest_lot_id"]) is not None
        and db.store["harvest_lots"][l["harvest_lot_id"]]["status"]
        in ("PARTIALLY_PRESSED", "PRESSED")
    ]
    total_w = sum(l["weight_lbs"] for l in lines)
    if total_w > 0:
        brix_sum = sum(
            _d(l["weight_lbs"])
            * _d(db.store["harvest_lots"][l["harvest_lot_id"]]["measured_brix"])
            for l in lines
        )
        tannin_sum = sum(
            _d(l["weight_lbs"])
            * _d(db.store["harvest_lots"][l["harvest_lot_id"]]["measured_tannin_g_per_l"])
            for l in lines
        )
        batch["blend_brix"] = fnum(q2(brix_sum / _d(total_w)))
        batch["blend_tannin"] = fnum(q2(tannin_sum / _d(total_w)))
    else:
        batch["blend_brix"] = None
        batch["blend_tannin"] = None
    batch["actual_juice_liters"] = actual
    ratio = None
    if total_w > 0:
        ratio = q3(_d(actual) / (_d(total_w) * Decimal("0.5")))
        batch["press_yield_ratio"] = fnum(ratio)
    batch["status"] = "COMPLETE"
    db.bump(batch)
    if ratio is not None and (ratio < Decimal("0.55") or ratio > Decimal("0.85")):
        emit_event(
            "PressBatch", batch["id"], "YIELD_ANOMALY",
            {"status": "PRESSING"},
            {
                "status": "COMPLETE",
                "press_yield_ratio": batch["press_yield_ratio"],
                "actual_juice_liters": actual,
            },
        )
    return success_object(ser_press_batch(batch))


@bp.post("/press-batches/<batchId>/cancel")
@require_roles("CellarLead")
def cancel_press_batch(batchId):
    batch = _get_batch(batchId)
    if batch["status"] != "PLANNED":
        raise invalid_state("only a PLANNED press batch can be cancelled")
    for line in _batch_lines(batch["id"]):
        db.store["blend_lines"].pop(line["id"], None)
    batch["target_juice_liters"] = 0
    batch["status"] = "CANCELLED"
    db.bump(batch)
    return success_object(ser_press_batch(batch))


# --- Tank ----------------------------------------------------------------------------
@bp.post("/tanks")
@require_roles("CellarLead")
def create_tank():
    b = body()
    material = b.get("material")
    if material is not None and material not in TANK_MATERIALS:
        raise validation(f"material must be one of {sorted(TANK_MATERIALS)}")
    rec = {
        "code": b.get("code"),
        "capacity_liters": b.get("capacity_liters"),
        "material": material,
        "temperature_controlled": bool(b.get("temperature_controlled", False)),
        "status": "EMPTY",
        "current_batch_id": None,
    }
    db.stamp_new(rec)
    db.store["tanks"][rec["id"]] = rec
    return success_object(ser_tank(rec), 201)


def _get_tank(tankId):
    rec = db.store["tanks"].get(tankId)
    if rec is None:
        raise not_found("tank")
    return rec


@bp.get("/tanks/<tankId>")
@require_roles(*CELLAR_READ)
def get_tank(tankId):
    return success_object(ser_tank(_get_tank(tankId)))


@bp.get("/tanks")
@require_roles(*CELLAR_READ)
def list_tanks():
    items = list(db.store["tanks"].values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paginate(items, ser_tank)


@bp.post("/tanks/<tankId>/reserve")
@require_roles("CellarLead")
def reserve_tank(tankId):
    tank = _get_tank(tankId)
    if tank["status"] != "EMPTY":
        raise invalid_state("only an EMPTY tank can be reserved")
    tank["status"] = "RESERVED"
    db.bump(tank)
    return success_object(ser_tank(tank))


@bp.post("/tanks/<tankId>/release")
@require_roles("CellarLead")
def release_tank(tankId):
    tank = _get_tank(tankId)
    if tank["status"] != "RESERVED":
        raise invalid_state("only a RESERVED tank can be released")
    tank["status"] = "EMPTY"
    db.bump(tank)
    return success_object(ser_tank(tank))


# --- FermentationBatch ----------------------------------------------------------------
def _get_fbatch(batchId):
    rec = db.store["fermentation_batches"].get(batchId)
    if rec is None:
        raise not_found("fermentation batch")
    return rec


@bp.post("/fermentation-batches")
@require_roles("CellarLead")
def create_fermentation_batch():
    b = body()
    press = db.store["press_batches"].get(b.get("press_batch_id"))
    if press is None:
        raise not_found("press batch")
    tank = db.store["tanks"].get(b.get("tank_id"))
    if tank is None:
        raise not_found("tank")
    yeast = db.store["yeast_programs"].get(b.get("yeast_program_id"))
    if yeast is None:
        raise not_found("yeast program")
    if press["status"] != "COMPLETE":
        raise invalid_state("referenced press batch is not COMPLETE")
    volume = press["actual_juice_liters"]
    temp_critical = (yeast["temp_min_f"] or 0) < 55 or (yeast["temp_max_f"] or 0) > 75
    eligible = (
        tank["status"] in ("EMPTY", "RESERVED")
        and (tank["capacity_liters"] or 0) >= (volume or 0)
        and (not temp_critical or tank["temperature_controlled"])
    )
    if not eligible:
        raise ApiError(
            ERR_NO_TANK_AVAILABLE,
            "no tank satisfies capacity/temperature eligibility",
            409,
        )
    og = press["blend_brix"]
    rec = {
        "press_batch_id": press["id"],
        "tank_id": tank["id"],
        "yeast_program_id": yeast["id"],
        "started_at": db.now(),
        "original_gravity_brix": og,
        "current_gravity_brix": og,
        "volume_liters": volume,
        "abv_pct": compute_abv(og, og),
        "back_blend_source_batch_id": None,
        "back_blend_pct": 0,
        "status": "PITCHED",
        "_aging_started_at": None,
    }
    db.stamp_new(rec)
    db.store["fermentation_batches"][rec["id"]] = rec
    tank["status"] = "FERMENTING"
    tank["current_batch_id"] = rec["id"]
    db.bump(tank)
    return success_object(ser_fermentation_batch(rec), 201)


@bp.get("/fermentation-batches/<batchId>")
@require_roles(*CELLAR_READ)
def get_fermentation_batch(batchId):
    return success_object(ser_fermentation_batch(_get_fbatch(batchId)))


@bp.get("/fermentation-batches")
@require_roles(*CELLAR_READ)
def list_fermentation_batches():
    items = list(db.store["fermentation_batches"].values())
    for param in (
        "status", "tank_id", "press_batch_id", "yeast_program_id",
        "back_blend_source_batch_id",
    ):
        val = request.args.get(param)
        if val is not None:
            items = [x for x in items if x.get(param) == val]
    return paginate(items, ser_fermentation_batch)


@bp.post("/fermentation-batches/<batchId>/readings")
@require_roles("CellarLead")
def record_reading(batchId):
    batch = _get_fbatch(batchId)
    if batch["status"] in ("PACKAGED", "DUMPED"):
        raise invalid_state("cannot record readings on a terminal batch")
    b = body()
    gravity = b.get("gravity_brix")
    if gravity is None:
        raise validation("gravity_brix is required")
    batch["current_gravity_brix"] = gravity
    if (
        batch["status"] == "PITCHED"
        and _d(gravity) < _d(batch["original_gravity_brix"])
    ):
        batch["status"] = "FERMENTING"
    batch["abv_pct"] = compute_abv(
        batch["original_gravity_brix"], batch["current_gravity_brix"]
    )
    db.bump(batch)
    return success_object(ser_fermentation_batch(batch))


@bp.post("/fermentation-batches/<batchId>/age")
@require_roles("CellarLead")
def age_batch(batchId):
    batch = _get_fbatch(batchId)
    if batch["status"] != "FERMENTING":
        raise invalid_state("fermentation batch is not FERMENTING")
    yeast = db.store["yeast_programs"].get(batch["yeast_program_id"])
    attenuation = _d((yeast or {}).get("attenuation_pct") or 0) / Decimal("100")
    threshold = _d(batch["original_gravity_brix"]) * (Decimal("1") - attenuation) + Decimal("0.5")
    if _d(batch["current_gravity_brix"]) > threshold:
        raise invalid_state("gravity has not fallen to terminal")
    batch["status"] = "AGING"
    batch["_aging_started_at"] = db.now()
    db.bump(batch)
    tank = db.store["tanks"].get(batch["tank_id"])
    if tank is not None:
        tank["status"] = "AGING"
        db.bump(tank)
    return success_object(ser_fermentation_batch(batch))


@bp.post("/fermentation-batches/<batchId>/ready")
@require_roles("CellarLead")
def ready_batch(batchId):
    batch = _get_fbatch(batchId)
    if batch["status"] != "AGING":
        raise invalid_state("fermentation batch is not AGING")
    started = batch.get("_aging_started_at")
    if started is None or db.now() - started < timedelta(days=14):
        raise invalid_state("aging duration is less than 14 days")
    batch["status"] = "READY"
    db.bump(batch)
    return success_object(ser_fermentation_batch(batch))


@bp.post("/fermentation-batches/<batchId>/dump")
@require_roles("CellarLead")
def dump_batch(batchId):
    batch = _get_fbatch(batchId)
    if batch["status"] not in ("PITCHED", "FERMENTING", "AGING"):
        raise invalid_state("batch cannot be dumped from its current state")
    b = body()
    batch["_dump_reason"] = b.get("reason")
    batch["status"] = "DUMPED"
    batch["volume_liters"] = 0
    db.bump(batch)
    tank = db.store["tanks"].get(batch["tank_id"])
    if tank is not None:
        tank["status"] = "EMPTY"
        tank["current_batch_id"] = None
        db.bump(tank)
    return success_object(ser_fermentation_batch(batch))


@bp.post("/fermentation-batches/<batchId>/back-blend")
@require_roles("CellarLead")
def back_blend(batchId):
    batch = _get_fbatch(batchId)
    b = body()
    source = db.store["fermentation_batches"].get(b.get("source_batch_id"))
    if source is None:
        raise not_found("source fermentation batch")
    if source["id"] == batch["id"]:
        raise invalid_state("a batch cannot back-blend into itself")
    if batch["status"] in ("PACKAGED", "DUMPED"):
        raise invalid_state("target batch is terminal")
    if source["status"] in ("PACKAGED", "DUMPED"):
        raise invalid_state("source batch is terminal")
    v = b.get("source_volume_liters")
    if not isinstance(v, int) or v <= 0:
        raise validation("source_volume_liters must be a positive integer")
    if v > source["volume_liters"]:
        raise ApiError(
            ERR_INSUFFICIENT_VOLUME,
            "source batch has insufficient volume_liters",
            409,
        )
    old_volume = batch["volume_liters"]
    new_volume = old_volume + v
    if new_volume > 0:
        blended = (
            _d(old_volume) * _d(batch["current_gravity_brix"])
            + _d(v) * _d(source["current_gravity_brix"])
        ) / _d(new_volume)
        # PRD 3.3 recomputes current_gravity_brix as the plain volume-weighted
        # average; 2.6 lists no rounding contract for gravity, so store exact.
        batch["current_gravity_brix"] = fnum(blended)
    source["volume_liters"] -= v
    db.bump(source)
    batch["volume_liters"] = new_volume
    batch["back_blend_source_batch_id"] = source["id"]
    batch["back_blend_pct"] = fnum(q2(_d(v) / _d(new_volume) * Decimal("100")))
    batch["abv_pct"] = compute_abv(
        batch["original_gravity_brix"], batch["current_gravity_brix"]
    )
    db.bump(batch)
    return success_object(ser_fermentation_batch(batch))
