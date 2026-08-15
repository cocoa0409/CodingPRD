"""Wash batches: schedule (window + purge rules), assign, start, complete, cancel."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_resource, touch, by_creation, logical_date
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    MAX_WASH_CYCLES,
    WASHER_PURGE,
    as_datetime,
    as_number,
    batch_json,
    create_lab_test,
    get_body,
    get_or_404,
    raise_shape,
    wash_verdict,
)

bp = Blueprint("wash", __name__)

SL = ["SanitationLead"]


@bp.post("/api/plants/<plant_id>/wash-batches")
@auth(SL)
def create_batch(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()
    washer = body.get("washer_unit")
    start, ok_s = as_datetime(body.get("scheduled_start"))
    end, ok_e = as_datetime(body.get("scheduled_end"))

    # Rung 7 — non-overlap, then the 30-minute purge buffer, against other
    # non-CANCELLED batches on the same washer of this plant.
    if washer in ("WASHER_A", "WASHER_B") and ok_s and ok_e:
        others = [
            w
            for w in store.wash_batches.values()
            if w["plant_id"] == plant["id"]
            and w["washer_unit"] == washer
            and w["status"] != "CANCELLED"
        ]
        for o in others:
            if start < o["_end"] and o["_start"] < end:
                raise ApiError(
                    "ERR_WASHER_WINDOW_CONFLICT",
                    "the batch window overlaps another batch on this washer",
                    409,
                )
        for o in others:
            if o["_end"] <= start and start - o["_end"] < WASHER_PURGE:
                raise ApiError(
                    "ERR_WASHER_PURGE_BUFFER",
                    "a 30-minute purge is required after the previous batch on this washer",
                    409,
                )
            if end <= o["_start"] and o["_start"] - end < WASHER_PURGE:
                raise ApiError(
                    "ERR_WASHER_PURGE_BUFFER",
                    "a 30-minute purge is required before the next batch on this washer",
                    409,
                )

    # Rung 11 — input shape.
    errs = []
    if washer not in ("WASHER_A", "WASHER_B"):
        errs.append("washer_unit must be WASHER_A or WASHER_B")
    if not ok_s:
        errs.append("scheduled_start must be a valid ISO 8601 datetime")
    if not ok_e:
        errs.append("scheduled_end must be a valid ISO 8601 datetime")
    if ok_s and ok_e and end <= start:
        errs.append("scheduled_end must fall after scheduled_start")
    raise_shape(errs)

    batch = new_resource(
        {
            "plant_id": plant["id"],
            "washer_unit": washer,
            "scheduled_start": body.get("scheduled_start"),
            "scheduled_end": body.get("scheduled_end"),
            "rinse_temp_c": None,
            "sanitizer_ppm": None,
            "status": "SCHEDULED",
        }
    )
    batch["_start"] = start
    batch["_end"] = end
    store.wash_batches[batch["id"]] = batch
    return ok_object(batch_json(batch), 201)


@bp.get("/api/wash-batches")
@auth(ALL_ROLES)
def list_batches():
    items = list(store.wash_batches.values())
    plant_id = request.args.get("plant_id")
    washer = request.args.get("washer_unit")
    status = request.args.get("status")
    if plant_id is not None:
        items = [w for w in items if w["plant_id"] == plant_id]
    if washer is not None:
        items = [w for w in items if w["washer_unit"] == washer]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return ok_list([batch_json(w) for w in by_creation(items)])


@bp.get("/api/plants/<plant_id>/wash-batches")
@auth(ALL_ROLES)
def list_plant_batches(plant_id):
    get_or_404(store.plants, plant_id, "plant")
    items = [w for w in store.wash_batches.values() if w["plant_id"] == plant_id]
    return ok_list([batch_json(w) for w in by_creation(items)])


@bp.get("/api/wash-batches/<batch_id>")
@auth(ALL_ROLES)
def get_batch(batch_id):
    batch = get_or_404(store.wash_batches, batch_id, "wash batch")
    return ok_object(batch_json(batch))


@bp.post("/api/wash-batches/<batch_id>/assign-bottles")
@auth(SL)
def assign_bottles(batch_id):
    batch = get_or_404(store.wash_batches, batch_id, "wash batch")
    body = get_body()

    # Rung 3 — existence of every listed bottle.
    bottle_ids = body.get("bottle_ids")
    bottles = []
    if isinstance(bottle_ids, list):
        for bid in bottle_ids:
            b = store.bottles.get(bid) if isinstance(bid, str) else None
            if b is None:
                raise ApiError("ERR_NOT_FOUND", "a bottle in bottle_ids does not exist", 404)
            bottles.append(b)

    # Rung 5 — batch state, then each bottle's state.
    if batch["status"] != "SCHEDULED":
        raise err_invalid_state("bottles can only be assigned to a SCHEDULED batch")
    for b in bottles:
        if b["status"] != "RETURNED_DIRTY":
            raise err_invalid_state("only RETURNED_DIRTY bottles can be assigned to a wash batch")

    # Rung 8 — cross-plant.
    for b in bottles:
        if b["plant_id"] != batch["plant_id"]:
            raise ApiError(
                "ERR_CROSS_PLANT_REFERENCE",
                "a bottle belongs to a different plant than the batch",
                409,
            )

    # Rung 9 — lifecycle ceiling.
    for b in bottles:
        if b["wash_cycle_count"] >= MAX_WASH_CYCLES:
            raise ApiError(
                "ERR_BOTTLE_CYCLE_LIMIT",
                "the bottle has reached the 150-wash lifecycle ceiling and must be retired",
                409,
            )

    # Rung 11 — input shape.
    if not isinstance(bottle_ids, list):
        raise_shape(["bottle_ids must be an array"])

    for b in bottles:
        b["status"] = "IN_WASH"
        b["current_wash_batch_id"] = batch["id"]
        touch(b)
    return ok_object(batch_json(batch))


@bp.post("/api/wash-batches/<batch_id>/start")
@auth(SL)
def start_batch(batch_id):
    batch = get_or_404(store.wash_batches, batch_id, "wash batch")
    if batch["status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED batch can be started")
    running = any(
        w["id"] != batch["id"]
        and w["plant_id"] == batch["plant_id"]
        and w["washer_unit"] == batch["washer_unit"]
        and w["status"] == "RUNNING"
        for w in store.wash_batches.values()
    )
    if running:
        raise err_invalid_state("another batch is already RUNNING on this washer")
    batch["status"] = "RUNNING"
    touch(batch)
    return ok_object(batch_json(batch))


@bp.post("/api/wash-batches/<batch_id>/complete")
@auth(SL)
def complete_batch(batch_id):
    batch = get_or_404(store.wash_batches, batch_id, "wash batch")
    if batch["status"] != "RUNNING":
        raise err_invalid_state("only a RUNNING batch can be completed")
    body = get_body()
    rinse, ok_r = as_number(body.get("rinse_temp_c"))
    ppm, ok_p = as_number(body.get("sanitizer_ppm"))
    errs = []
    if not ok_r:
        errs.append("rinse_temp_c must be a number")
    if not ok_p:
        errs.append("sanitizer_ppm must be a number")
    raise_shape(errs)

    verdict = wash_verdict(rinse, ppm)
    batch["rinse_temp_c"] = rinse
    batch["sanitizer_ppm"] = ppm
    batch["status"] = "PASSED" if verdict == "PASS" else "FAILED"
    touch(batch)

    assigned = [
        b for b in store.bottles.values() if b.get("current_wash_batch_id") == batch["id"]
    ]
    if verdict == "PASS":
        for b in assigned:
            b["status"] = "SANITIZED"
            b["wash_cycle_count"] += 1
            b["last_wash_batch_id"] = batch["id"]
            b["current_wash_batch_id"] = None
            touch(b)
        create_lab_test(
            batch["plant_id"],
            "BOTTLE_SANITATION",
            "subject_wash_batch_id",
            batch["id"],
            logical_date() + timedelta(days=1),
            "AUTO",
        )
    else:
        for b in assigned:
            b["status"] = "RETURNED_DIRTY"
            b["current_wash_batch_id"] = None
            touch(b)
    return ok_object(batch_json(batch))


@bp.post("/api/wash-batches/<batch_id>/cancel")
@auth(SL)
def cancel_batch(batch_id):
    batch = get_or_404(store.wash_batches, batch_id, "wash batch")
    if batch["status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED batch can be cancelled")
    batch["status"] = "CANCELLED"
    touch(batch)
    for b in store.bottles.values():
        if b.get("current_wash_batch_id") == batch["id"]:
            b["status"] = "RETURNED_DIRTY"
            b["current_wash_batch_id"] = None
            touch(b)
    return ok_object(batch_json(batch))
