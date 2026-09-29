"""Fertigation batches: blending with a recirculation cap, delivery and drainage."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import const
import fields
from authz import ALL_ROLES, IRRIGATION_TECH, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, terminal, to_status_enum, transition
from money import D, q2
from store import base_record, db, midnight, new_id, next_seq, now, ordered, touch

bp = Blueprint("fertigation", __name__)

ALLOWED = {
    "MIXED": ("DELIVERED", "DISCARDED"),
    "DELIVERED": ("RECONCILED",),
}


@bp.post("/fertigation-batches")
@guard([IRRIGATION_TECH])
def create_batch():
    payload = body()
    # priority 4
    zone_id = fields.string(payload, "zone_id")
    crop_cycle_id = fields.string(payload, "crop_cycle_id")
    batch_date = fields.day(payload, "batch_date")
    planned_volume = fields.integer(
        payload, "planned_volume_liters", lo=100, hi=200000
    )
    requested_recirc = fields.integer(
        payload, "requested_recirculated_liters", lo=0, hi=planned_volume
    )
    reservoir_ec = fields.number(payload, "reservoir_ec_ms", lo=0, hi=12)
    target_ec = fields.number(payload, "target_ec_ms", lo=0, hi=6, exclusive_lo=True)
    target_ph = fields.number(payload, "target_ph", lo="4.5", hi="7.0")
    n_ppm = fields.integer(payload, "n_ppm", lo=0, hi=400)
    k_ppm = fields.integer(payload, "k_ppm", lo=0, hi=600)
    ca_ppm = fields.integer(payload, "ca_ppm", lo=0, hi=400)
    drain_target = fields.number(payload, "drain_target_pct", lo=10, hi=45)
    # priority 7 - body FKs in declared input order
    zone = fetch("zones", zone_id)
    cycle = fetch("crop_cycles", crop_cycle_id)
    # cycle must be operationally active, ahead of the safety gates
    if cycle["status"] not in const.CYCLE_ACTIVE_FOR_FERTIGATION:
        raise ApiError("ERR_CROP_CYCLE_NOT_ACTIVE")
    # priority 15
    if zone["irrigation_posture"] == "LOCKED":
        raise ApiError("ERR_IRRIGATION_LOCKED")
    # priority 36 - recipe tolerance is anchored to the cultivar of this cycle
    variety = db["varieties"].get(cycle["variety_id"])
    if variety is not None:
        deviation = abs(D(target_ec) - D(variety["ec_target_ms"]))
        if deviation > const.RECIPE_EC_TOLERANCE_MS:
            raise ApiError("ERR_TARGET_EC_OFF_RECIPE")
    # priority 38
    if cycle["zone_id"] != zone_id:
        raise ApiError("ERR_CROP_CYCLE_ZONE_MISMATCH")

    record = base_record()
    record.update({
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "batch_date": batch_date,
        "planned_volume_liters": planned_volume,
        "requested_recirculated_liters": requested_recirc,
        "reservoir_ec_ms": reservoir_ec,
        "target_ec_ms": target_ec,
        "target_ph": target_ph,
        "n_ppm": n_ppm,
        "k_ppm": k_ppm,
        "ca_ppm": ca_ppm,
        "drain_target_pct": drain_target,
        "provisional_blend_ec_ms": None,
        "recirc_cap_pct": None,
        "recirculated_liters_applied": None,
        "fresh_liters_applied": None,
        "blended_ec_ms": None,
        "injector_ml": None,
        "status": "MIXED",
        "delivered_volume_liters": None,
        "drain_reading_count": 0,
        "cumulative_drain_volume_liters": q2(0),
        "last_drain_ec_ms": None,
        "drain_fraction_pct": None,
        "drain_alarm": False,
    })
    calc.blend_batch(record)
    db["fertigation_batches"][record["id"]] = record
    return created(public(record))


@bp.get("/fertigation-batches")
@guard(ALL_ROLES)
def list_batches():
    rows = ordered("fertigation_batches")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "crop_cycle_id", request.args.get("crop_cycle_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/fertigation-batches/<batch_id>")
@guard(ALL_ROLES)
def get_batch(batch_id):
    return ok(public(fetch("fertigation_batches", batch_id)))


@bp.post("/fertigation-batches/<batch_id>/transitions")
@guard([IRRIGATION_TECH])
def transition_batch(batch_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    delivered_volume = None
    if target == "DELIVERED":
        delivered_volume = fields.integer(payload, "delivered_volume_liters", lo=0)
    to_status_enum(target, const.BATCH_STATUSES)
    batch = fetch("fertigation_batches", batch_id)
    zone = db["zones"][batch["zone_id"]]
    terminal(batch["status"], const.BATCH_TERMINAL)
    transition(ALLOWED, batch["status"], target)

    if target == "DELIVERED":
        # priority 15 - the posture may have locked since the batch was mixed
        if zone["irrigation_posture"] == "LOCKED":
            raise ApiError("ERR_IRRIGATION_LOCKED")
        planned = D(batch["planned_volume_liters"])
        tolerance = planned * const.DELIVERY_TOLERANCE_PCT / D(100)
        if abs(D(delivered_volume) - planned) > tolerance:
            raise ApiError("ERR_DELIVERY_VOLUME_VARIANCE")
        batch["delivered_volume_liters"] = delivered_volume
        batch["status"] = "DELIVERED"

    elif target == "DISCARDED":
        batch["status"] = "DISCARDED"

    else:  # RECONCILED
        if batch["drain_reading_count"] < 1:
            raise ApiError("ERR_NO_DRAIN_READINGS")
        batch["status"] = "RECONCILED"

    touch(batch)
    return ok(public(batch))


@bp.post("/fertigation-batches/<batch_id>/drainage-readings")
@guard([IRRIGATION_TECH])
def log_drainage(batch_id):
    payload = body()
    drain_volume = fields.number(payload, "drain_volume_liters")
    drain_ec = fields.number(payload, "drain_ec_ms")
    reading_at = fields.timestamp(payload, "reading_at")
    batch = fetch("fertigation_batches", batch_id)
    # A reading against MIXED, RECONCILED or DISCARDED is uniformly rejected with
    # ERR_BATCH_NOT_DELIVERED (PRD 3.5 names this error for the frozen states too).
    if batch["status"] != "DELIVERED":
        raise ApiError("ERR_BATCH_NOT_DELIVERED")
    window_open = midnight(batch["batch_date"])
    window_close = window_open + timedelta(hours=const.DRAIN_READING_WINDOW_HOURS)
    if reading_at < window_open or reading_at > window_close:
        raise ApiError("ERR_READING_OUT_OF_WINDOW")

    zone = db["zones"][batch["zone_id"]]
    reading = {
        "id": new_id(),
        "_seq": next_seq(),
        "fertigation_batch_id": batch["id"],
        "drain_volume_liters": q2(drain_volume),
        "drain_ec_ms": D(drain_ec),
        "reading_at": reading_at,
        "created_at": now(),
    }
    db["drainage_readings"][reading["id"]] = reading

    calc.evaluate_drainage(batch, zone, drain_volume, drain_ec)
    # last_drain_ec_ms follows reading_at then created_at, not the filing order.
    siblings = [
        r for r in db["drainage_readings"].values()
        if r["fertigation_batch_id"] == batch["id"]
    ]
    siblings.sort(key=lambda r: (r["reading_at"], r["created_at"], r["_seq"]))
    batch["last_drain_ec_ms"] = siblings[-1]["drain_ec_ms"]
    touch(batch)

    # hop 2 - re-derive the irrigation posture; the zone version always moves
    calc.refresh_zone(zone, force=True)
    # hop 3 - a LOCKED posture stresses every active cycle in the compartment
    if zone["irrigation_posture"] == "LOCKED":
        for cycle in ordered("crop_cycles"):
            if cycle["zone_id"] != zone["id"]:
                continue
            if cycle["status"] not in const.CYCLE_ACTIVE_FOR_FERTIGATION:
                continue
            if not cycle["nutrient_stress_flag"]:
                cycle["nutrient_stress_flag"] = True
                touch(cycle)
    return ok(public(batch))
