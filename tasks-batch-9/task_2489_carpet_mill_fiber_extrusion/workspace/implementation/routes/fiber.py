"""Fiber batches: queueing, spinning and disposition (PRD 3.2)."""

from flask import Blueprint

import calc
from calc import dec
from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from routes.polymer import POLYMER_TYPES, READ_ROLES, WRITE_ROLES
from services import ledgers
from validators import (
    bad,
    json_body,
    opt_id,
    opt_num,
    opt_str,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("fiber", __name__)

DYE_METHODS = ("SOLUTION_DYED", "PIECE_DYED_READY")
FIBER_STATUSES = ("QUEUED", "SPUN", "RELEASED", "ALLOCATED", "CONSUMED", "SCRAPPED")


def _sources(batch):
    """The (lot, kg) pairs whose mass this batch draws."""
    out = []
    primary = store.polymer_lots.get(batch["polymer_lot_id"])
    if primary is not None:
        out.append((primary, batch["input_kg"]))
    if batch.get("blend_polymer_lot_id"):
        blend = store.polymer_lots.get(batch["blend_polymer_lot_id"])
        if blend is not None:
            out.append((blend, batch.get("blend_input_kg") or 0.0))
    return out


@bp.post("/mill/fiber-batches")
def queue_fiber_batch():
    authenticate(WRITE_ROLES)
    body = json_body()
    batch_code = req_str(body, "batch_code")
    polymer_lot_id = req_str(body, "polymer_lot_id")
    input_kg = req_num(body, "input_kg", 3, gt=0)
    denier_target = req_num(body, "denier_target", 1, gt=0)
    filament_count = req_int(body, "filament_count", ge=1)
    dye_method = req_enum(body, "dye_method", DYE_METHODS)
    blend_polymer_lot_id = opt_id(body, "blend_polymer_lot_id")
    blend_input_kg = opt_num(body, "blend_input_kg", 3, default=0.0, ge=0)
    solution_color_code = opt_str(body, "solution_color_code")

    # Rung 4 — the blend pair must be supplied together.
    if blend_polymer_lot_id is not None and not blend_input_kg > 0:
        bad("blend_input_kg must be greater than zero when blend_polymer_lot_id is supplied")
    if blend_polymer_lot_id is None and blend_input_kg and blend_input_kg > 0:
        bad("blend_input_kg may only be supplied together with blend_polymer_lot_id")

    # Rung 6 — body reference existence.
    primary = fetch("polymer_lots", polymer_lot_id)
    blend = None
    if blend_polymer_lot_id is not None:
        blend = fetch("polymer_lots", blend_polymer_lot_id)

    # Rung 7 — natural-key uniqueness.
    unique("fiber_batches", "batch_code", batch_code)

    # Rung 16 — dyeing-route coherence.
    if dye_method == "SOLUTION_DYED":
        if not solution_color_code:
            raise ApiError(
                "ERR_DYE_METHOD_COLOR_MISMATCH",
                "A SOLUTION_DYED batch must carry a solution_color_code",
            )
    elif solution_color_code:
        raise ApiError(
            "ERR_DYE_METHOD_COLOR_MISMATCH",
            "solution_color_code is only valid on a SOLUTION_DYED batch",
        )

    # Rung 17 — feedstock compatibility and availability.
    if blend is not None and blend["polymer_type"] != primary["polymer_type"]:
        raise ApiError(
            "ERR_POLYMER_BLEND_INCOMPATIBLE",
            "The blend lot's polymer_type differs from the primary lot's",
        )
    if dec(input_kg) > dec(primary["available_kg"]):
        raise ApiError(
            "ERR_POLYMER_MASS_UNAVAILABLE",
            "input_kg exceeds the primary lot's available_kg",
        )
    if blend is not None and dec(blend_input_kg) > dec(blend["available_kg"]):
        raise ApiError(
            "ERR_POLYMER_MASS_UNAVAILABLE",
            "blend_input_kg exceeds the blend lot's available_kg",
        )

    batch = insert(
        store.fiber_batches,
        {
            "batch_code": batch_code,
            "polymer_lot_id": polymer_lot_id,
            "input_kg": input_kg,
            "blend_polymer_lot_id": blend_polymer_lot_id,
            "blend_input_kg": blend_input_kg if blend_polymer_lot_id else 0.0,
            "denier_target": denier_target,
            "filament_count": filament_count,
            "dye_method": dye_method,
            "solution_color_code": solution_color_code,
            "throughput_g_per_min": None,
            "spin_speed_m_per_min": None,
            "denier_actual": None,
            "extruded_kg": None,
            "status": "QUEUED",
        },
    )

    for lot, kg in _sources(batch):
        ledgers.move_polymer(lot, "available_kg", "reserved_kg", dec(kg))

    return created("fiber_batch", batch)


@bp.post("/mill/fiber-batches/<fiber_batch_id>/extrude")
def extrude(fiber_batch_id):
    authenticate(WRITE_ROLES)
    body = json_body()
    throughput = req_num(body, "throughput_g_per_min", 1, gt=0)
    spin_speed = req_num(body, "spin_speed_m_per_min", 1, gt=0)

    batch = fetch("fiber_batches", fiber_batch_id)

    if batch["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUEUED batch may be spun")

    primary = store.polymer_lots.get(batch["polymer_lot_id"])
    if primary is None or dec(primary["melt_flow_index"]) < calc.MIN_MELT_FLOW_INDEX:
        raise ApiError(
            "ERR_MELT_FLOW_OUT_OF_RANGE",
            "The primary lot's melt_flow_index is below the extrusion floor of 12.0",
        )

    batch["throughput_g_per_min"] = throughput
    batch["spin_speed_m_per_min"] = spin_speed
    batch["denier_actual"] = calc.denier_actual(
        throughput, spin_speed, batch["filament_count"]
    )
    batch["extruded_kg"] = calc.extruded_kg(
        batch["input_kg"], batch.get("blend_input_kg")
    )
    batch["status"] = "SPUN"
    touch(batch)

    for lot, kg in _sources(batch):
        ledgers.move_polymer(lot, "reserved_kg", "consumed_kg", dec(kg))

    return ok("fiber_batch", batch)


@bp.post("/mill/fiber-batches/<fiber_batch_id>/disposition")
def disposition(fiber_batch_id):
    authenticate(WRITE_ROLES)
    body = json_body()
    choice = req_enum(body, "disposition", ("RELEASE", "SCRAP"))

    batch = fetch("fiber_batches", fiber_batch_id)

    if choice == "RELEASE":
        if batch["status"] != "SPUN":
            raise ApiError("ERR_INVALID_STATE", "Only a SPUN batch may be released")
        if not calc.denier_within_tolerance(
            batch["denier_actual"], batch["denier_target"]
        ):
            raise ApiError(
                "ERR_DENIER_OUT_OF_TOLERANCE",
                "denier_actual is outside three percent of denier_target",
            )
        batch["status"] = "RELEASED"
        touch(batch)
        return ok("fiber_batch", batch)

    if batch["status"] not in ("QUEUED", "SPUN"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only a QUEUED or SPUN batch may be scrapped"
        )

    if batch["status"] == "QUEUED":
        for lot, kg in _sources(batch):
            ledgers.move_polymer(lot, "reserved_kg", "available_kg", dec(kg))
    else:
        for lot, kg in _sources(batch):
            ledgers.move_polymer(lot, "consumed_kg", "scrapped_kg", dec(kg))

    batch["status"] = "SCRAPPED"
    touch(batch)
    return ok("fiber_batch", batch)


@bp.get("/mill/fiber-batches/<fiber_batch_id>")
def read_fiber_batch(fiber_batch_id):
    authenticate(READ_ROLES)
    return ok("fiber_batch", fetch("fiber_batches", fiber_batch_id))


@bp.get("/mill/fiber-batches")
def list_fiber_batches():
    authenticate(READ_ROLES)
    return listing(
        "fiber_batch",
        "fiber_batches",
        enum_filters={"status": FIBER_STATUSES, "dye_method": DYE_METHODS},
        value_filters=("polymer_lot_id", "blend_polymer_lot_id"),
    )
