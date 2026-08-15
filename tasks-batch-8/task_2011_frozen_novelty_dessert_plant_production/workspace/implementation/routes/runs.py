"""Production runs (PRD §3.5, §3.6): scheduling, mix assignment, the start
prerequisite fan-in, dual-variant completion costing, and cancellation."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_ALLERGEN_CLEAN_NOT_VERIFIED,
    ERR_COPACK_CONTRACT_REQUIRED,
    ERR_INSUFFICIENT_MIX,
    ERR_INVALID_STATE,
    ERR_LINE_FORMAT_MISMATCH,
    ERR_MIX_EXPIRED,
    ERR_MIX_NOT_RELEASED,
    ERR_MIX_PRODUCT_MISMATCH,
    ERR_PRODUCT_DISCONTINUED,
    ERR_TUNNEL_BOOKING_REQUIRED,
    ERR_ZONE_CAPACITY_EXCEEDED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import (
    D,
    litres_remaining,
    overrun_mix_usage,
    serialize,
    zone_capacity_ok_for_new_lot,
)
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = Blueprint("runs", __name__)

RUN_SPEC = {
    "run_code": {"type": "string", "required": True},
    "product_id": {"type": "string", "required": True},
    "line_id": {"type": "string", "required": True},
    "planned_units": {"type": "integer", "min": 1, "required": True},
    "scheduled_start": {"type": "datetime", "required": True},
}

ASSIGN_MIX_SPEC = {
    "mix_batch_id": {"type": "string", "required": True},
}

COMPLETE_SPEC = {
    "actual_units": {"type": "integer", "min": 1, "required": True},
    "mix_metered_litres": {"type": "number", "min": 0, "min_exclusive": True,
                           "required": True},
    "zone_id": {"type": "string", "required": True},
}


@bp.route("/production-runs", methods=["POST"])
def create_run():
    authenticate({"ProductionPlanner"})
    body = body_json()
    exist_body_fks(body, {
        "product_id": ("products", "product"),
        "line_id": ("lines", "line"),
    })
    check_shape(body, RUN_SPEC)
    product = db.get("products", body["product_id"])
    line = db.get("lines", body["line_id"])
    # Priority 13: line.format must equal product.format.
    if line["format"] != product["format"]:
        raise ApiError(
            ERR_LINE_FORMAT_MISMATCH, 422, "line format differs from product format"
        )
    # Priority 35: co_pack_only products require an ACTIVE covering contract.
    if product.get("co_pack_only"):
        covered = any(
            c["product_id"] == product["id"] and c["status"] == "ACTIVE"
            for c in db.all_of("contracts")
        )
        if not covered:
            raise ApiError(
                ERR_COPACK_CONTRACT_REQUIRED,
                422,
                "co_pack_only product requires an ACTIVE co-pack contract",
            )
    # Priority 39: DISCONTINUED products cannot be referenced by new runs.
    if product["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCT_DISCONTINUED, 422, "product is not ACTIVE")
    run = db.new_entity("runs", {
        "run_code": body["run_code"],
        "product_id": product["id"],
        "line_id": line["id"],
        "planned_units": body["planned_units"],
        "scheduled_start": body["scheduled_start"],
        "mix_batch_id": None,
        "status": "SCHEDULED",
        "actual_units": None,
        "mix_metered_litres": None,
        "mix_litres_theoretical": None,
        "overrun_actual_pct": None,
        "mix_cost_variance_cents": None,
        "completed_at": None,
    })
    return success_obj(serialize("runs", run), 201)


@bp.route("/production-runs", methods=["GET"])
def list_runs():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("runs"), ["product_id", "line_id", "mix_batch_id", "status"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("runs", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/production-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    authenticate(ALL_ROLES)
    run = path_entity("runs", run_id, "production run")
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/assign-mix", methods=["POST"])
def assign_mix(run_id):
    authenticate({"ProductionPlanner"})
    run = path_entity("runs", run_id, "production run")
    body = body_json()
    exist_body_fks(body, {"mix_batch_id": ("mix_batches", "mix batch")})
    check_shape(body, ASSIGN_MIX_SPEC)
    if run["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "run is not SCHEDULED")
    batch = db.get("mix_batches", body["mix_batch_id"])
    # Priority 10: batch must be RELEASED.
    if batch["status"] != "RELEASED":
        raise ApiError(ERR_MIX_NOT_RELEASED, 422, "mix batch is not RELEASED")
    # Priority 11: batch product must equal run product.
    if batch["product_id"] != run["product_id"]:
        raise ApiError(
            ERR_MIX_PRODUCT_MISMATCH, 422, "mix batch product differs from run product"
        )
    # Priority 12: expires_at must be strictly after the scheduled start.
    if parse_dt(batch["expires_at"]) <= parse_dt(run["scheduled_start"]):
        raise ApiError(
            ERR_MIX_EXPIRED, 422, "mix expires at or before the scheduled start"
        )
    run["mix_batch_id"] = batch["id"]
    run["status"] = "MIX_ASSIGNED"
    db.touch(run)
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/start", methods=["POST"])
def start_run(run_id):
    authenticate({"LineOperator"})
    run = path_entity("runs", run_id, "production run")
    if run["status"] != "MIX_ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409, "run is not MIX_ASSIGNED")
    line = db.get("lines", run["line_id"])
    if line is None or line["status"] != "IDLE":
        raise ApiError(ERR_INVALID_STATE, 409, "line is not IDLE")
    # Priority 9: a VERIFIED changeover to the run's product must exist on the line.
    verified = [
        c for c in db.all_of("changeovers")
        if c["line_id"] == run["line_id"]
        and c["to_product_id"] == run["product_id"]
        and c["status"] == "VERIFIED"
    ]
    if not verified:
        raise ApiError(
            ERR_ALLERGEN_CLEAN_NOT_VERIFIED,
            422,
            "no VERIFIED changeover to the run's product on the line",
        )
    batch = db.get("mix_batches", run["mix_batch_id"])
    # Priority 10: assigned mix must still be RELEASED.
    if batch is None or batch["status"] != "RELEASED":
        raise ApiError(ERR_MIX_NOT_RELEASED, 422, "mix batch is not RELEASED")
    # Priority 12: mix must not be expired at start.
    if db.now() >= parse_dt(batch["expires_at"]):
        raise ApiError(ERR_MIX_EXPIRED, 422, "mix batch has expired")
    # Priority 22: a BOOKED tunnel booking for the run must exist.
    booked = [
        b for b in db.all_of("bookings")
        if b["run_id"] == run["id"] and b["status"] == "BOOKED"
    ]
    if not booked:
        raise ApiError(
            ERR_TUNNEL_BOOKING_REQUIRED, 422, "run has no BOOKED tunnel booking"
        )
    changeover = verified[0]
    changeover["status"] = "CONSUMED"
    db.touch(changeover)
    line["status"] = "RUNNING"
    db.touch(line)
    run["status"] = "IN_PRODUCTION"
    db.touch(run)
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/hold", methods=["POST"])
def hold_run(run_id):
    authenticate({"QAManager"})
    run = path_entity("runs", run_id, "production run")
    if run["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, 409, "run is not IN_PRODUCTION")
    run["status"] = "ON_HOLD"
    db.touch(run)
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/resume", methods=["POST"])
def resume_run(run_id):
    authenticate({"QAManager"})
    run = path_entity("runs", run_id, "production run")
    if run["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_STATE, 409, "run is not ON_HOLD")
    run["status"] = "IN_PRODUCTION"
    db.touch(run)
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/complete", methods=["POST"])
def complete_run(run_id):
    authenticate({"LineOperator"})
    run = path_entity("runs", run_id, "production run")
    body = body_json()
    exist_body_fks(body, {"zone_id": ("zones", "freezer zone")})
    check_shape(body, COMPLETE_SPEC)
    if run["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, 409, "run is not IN_PRODUCTION")
    product = db.get("products", run["product_id"])
    zone = db.get("zones", body["zone_id"])
    now = db.now()
    # Priority 19: freezer zone day-aggregate pallet capacity for the new lot.
    if not zone_capacity_ok_for_new_lot(
        zone, product, body["actual_units"], now
    ):
        raise ApiError(
            ERR_ZONE_CAPACITY_EXCEEDED,
            422,
            "freezer zone day-aggregate pallet capacity would be exceeded",
        )
    batch = db.get("mix_batches", run["mix_batch_id"])
    metered = D(body["mix_metered_litres"])
    # Priority 37: metered litres must fit in the batch's remaining litres.
    if metered > litres_remaining(batch):
        raise ApiError(
            ERR_INSUFFICIENT_MIX, 422, "metered litres exceed the batch's remaining litres"
        )
    # --- All preconditions pass; side effects fire atomically from here. ---
    theoretical, overrun_actual, variance = overrun_mix_usage(
        product, body["actual_units"], body["mix_metered_litres"]
    )
    completed_at = db.fmt_ts(now)
    best_before = db.fmt_ts(now + timedelta(days=int(product["shelf_life_days"])))
    run["actual_units"] = body["actual_units"]
    run["mix_metered_litres"] = body["mix_metered_litres"]
    run["mix_litres_theoretical"] = theoretical
    run["overrun_actual_pct"] = overrun_actual
    run["mix_cost_variance_cents"] = variance
    run["completed_at"] = completed_at
    run["status"] = "COMPLETED"
    db.touch(run)
    # The lot is born at completion.
    db.new_entity("lots", {
        "lot_code": "LOT-" + run["run_code"],
        "run_id": run["id"],
        "product_id": run["product_id"],
        "zone_id": zone["id"],
        "units_produced": body["actual_units"],
        "units_available": body["actual_units"],
        "units_reserved": 0,
        "units_shipped": 0,
        "units_destroyed": 0,
        "produced_at": completed_at,
        "best_before": best_before,
        "status": "AVAILABLE",
        "quarantined_by": None,
    })
    # Mix consumption; CONSUMED when litres_remaining reaches exactly 0 (2dp).
    batch["litres_consumed"] = batch["litres_consumed"] + metered
    db.touch(batch)
    if litres_remaining(batch).quantize(Decimal("0.01")) == 0:
        batch["status"] = "CONSUMED"
        db.touch(batch)
    # This run's BOOKED tunnel bookings complete.
    for booking in db.all_of("bookings"):
        if booking["run_id"] == run["id"] and booking["status"] == "BOOKED":
            booking["status"] = "COMPLETED"
            db.touch(booking)
    # The line frees up and snapshots the product it just ran.
    line = db.get("lines", run["line_id"])
    line["status"] = "IDLE"
    line["last_product_id"] = run["product_id"]
    line["last_allergens"] = list(product["allergens"])
    db.touch(line)
    return success_obj(serialize("runs", run))


@bp.route("/production-runs/<run_id>/cancel", methods=["POST"])
def cancel_run(run_id):
    authenticate({"ProductionPlanner"})
    run = path_entity("runs", run_id, "production run")
    if run["status"] not in ("SCHEDULED", "MIX_ASSIGNED", "ON_HOLD"):
        raise ApiError(ERR_INVALID_STATE, 409, "run cannot be canceled")
    prior_status = run["status"]
    for booking in db.all_of("bookings"):
        if booking["run_id"] == run["id"] and booking["status"] == "BOOKED":
            booking["status"] = "CANCELED"
            db.touch(booking)
    if prior_status == "ON_HOLD":
        # Line returns to IDLE without last_product update; no lot is created.
        line = db.get("lines", run["line_id"])
        if line is not None and line["status"] == "RUNNING":
            line["status"] = "IDLE"
            db.touch(line)
    if prior_status == "MIX_ASSIGNED":
        run["mix_batch_id"] = None
    run["status"] = "CANCELED"
    db.touch(run)
    return success_obj(serialize("runs", run))
