"""Packaging lines, line runs, and film supply lots (PRD §3.5)."""

from datetime import timedelta

from flask import request

import services as svc
from db import STORE, bump, new_record
from errors import ApiError
from middleware import PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import film_lot_out, line_out, run_out
from util import (
    FILM_TYPES,
    LINE_TYPES,
    REQUIRED_LINE_TYPE,
    as_enum,
    as_positive_int,
    as_string,
    body_dict,
    parse_dt,
    req_present,
)


# ---------------------------------------------------------------------------
# Packaging lines
# ---------------------------------------------------------------------------

@bp.route("/plant/packaging-lines", methods=["POST"])
@endpoint({"PlantManager"})
def create_line(user_id, role):
    body = body_dict(request.get_json(silent=True))
    line_code = as_string(req_present(body, "line_code"), "line_code")
    line_type = as_enum(req_present(body, "line_type"), "line_type", LINE_TYPES)
    rate = as_positive_int(req_present(body, "rate_units_per_minute"), "rate_units_per_minute")
    film_type = as_enum(
        req_present(body, "supported_film_type"), "supported_film_type", FILM_TYPES
    )
    for existing in STORE["lines"].values():
        if existing["line_code"] == line_code:
            raise ApiError("ERR_INVALID_REQUEST", "line_code must be unique")

    rec = new_record()
    rec.update(
        line_code=line_code,
        line_type=line_type,
        rate_units_per_minute=rate,
        supported_film_type=film_type,
    )
    STORE["lines"][rec["id"]] = rec
    return ok_object(line_out(rec), 201)


@bp.route("/plant/packaging-lines", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_lines(user_id, role):
    return list_response(list(STORE["lines"].values()), line_out)


@bp.route("/plant/packaging-lines/<lineId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_line(user_id, role, lineId):
    return ok_object(line_out(svc.require_record("lines", lineId, "PackagingLine")))


# ---------------------------------------------------------------------------
# Line runs
# ---------------------------------------------------------------------------

@bp.route("/plant/packaging-lines/<lineId>/runs", methods=["POST"])
@endpoint({"ProductionPlanner"})
def create_run(user_id, role, lineId):
    body = body_dict(request.get_json(silent=True))
    batch_id = as_string(req_present(body, "batch_id"), "batch_id")
    film_lot_id = as_string(req_present(body, "film_lot_id"), "film_lot_id")
    planned_start = parse_dt(req_present(body, "planned_start"), "planned_start")
    units_planned = as_positive_int(req_present(body, "units_planned"), "units_planned")

    # existence: path id first, then body FKs in input order (stage 6)
    line = svc.require_record("lines", lineId, "PackagingLine")
    batch = svc.require_record("batches", batch_id, "ProductionBatch")
    film_lot = svc.require_record("film_lots", film_lot_id, "FilmSupplyLot")
    order = svc.order_of_batch(batch)

    # state (stage 8)
    if batch["status"] not in ("KITTED", "COOKED", "FROZEN"):
        raise ApiError(
            "ERR_BATCH_STATE", "Runs may be booked only for KITTED, COOKED or FROZEN batches"
        )
    # critical-control safety (stage 9)
    if film_lot["status"] != "AVAILABLE":
        raise ApiError("ERR_FILM_LOT_QUARANTINED", "Film lot is QUARANTINED")

    duration = svc.run_duration_minutes(line, units_planned)
    planned_end = planned_start + timedelta(minutes=duration)
    reserved_film = svc.film_reservation_m(units_planned, order["pack_format"])

    # temporal windows incl. changeover buffers (stage 10)
    if svc.line_window_conflict(
        line, order["copack_customer_id"], order["recipe_id"], planned_start, planned_end
    ):
        raise ApiError(
            "ERR_LINE_WINDOW_CONFLICT",
            "Run window collides with another SCHEDULED/IN_PROGRESS run on the line",
        )
    # capacity / structural constraints (stage 11), in declared order
    if line["line_type"] != REQUIRED_LINE_TYPE[order["pack_format"]]:
        raise ApiError(
            "ERR_LINE_FORMAT_MISMATCH",
            "%s orders require a %s line" % (order["pack_format"], REQUIRED_LINE_TYPE[order["pack_format"]]),
        )
    if film_lot["film_type"] != line["supported_film_type"]:
        raise ApiError(
            "ERR_FILM_TYPE_MISMATCH", "Film lot film_type differs from the line's supported_film_type"
        )
    _, _, _, available = svc.film_meters(film_lot)
    if available < reserved_film:
        raise ApiError("ERR_FILM_INSUFFICIENT", "meters_available is below the run's reservation")

    rec = new_record()
    rec.update(
        line_id=line["id"],
        batch_id=batch["id"],
        film_lot_id=film_lot["id"],
        planned_start=planned_start,
        units_planned=units_planned,
        duration_minutes=duration,
        planned_end=planned_end,
        reserved_film_m=reserved_film,
        units_packed=None,
        film_meters_consumed=None,
        status="SCHEDULED",
    )
    STORE["runs"][rec["id"]] = rec
    return ok_object(run_out(rec), 201)


@bp.route("/plant/line-runs", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_runs(user_id, role):
    line_id = request.args.get("line_id")
    batch_id = request.args.get("batch_id")
    film_lot_id = request.args.get("film_lot_id")
    status = request.args.get("status")
    recs = list(STORE["runs"].values())
    if line_id is not None:
        recs = [r for r in recs if r["line_id"] == line_id]
    if batch_id is not None:
        recs = [r for r in recs if r["batch_id"] == batch_id]
    if film_lot_id is not None:
        recs = [r for r in recs if r["film_lot_id"] == film_lot_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, run_out)


@bp.route("/plant/line-runs/<runId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_run(user_id, role, runId):
    return ok_object(run_out(svc.require_record("runs", runId, "LineRun")))


@bp.route("/plant/line-runs/<runId>/start", methods=["POST"])
@endpoint({"LineOperator"})
def start_run(user_id, role, runId):
    run = svc.require_record("runs", runId, "LineRun")
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE", "Run cannot be started from %s" % run["status"])
    batch = svc.get_batch(run["batch_id"])
    if batch is None or batch["status"] != "FROZEN":
        raise ApiError("ERR_BATCH_STATE", "Batch must be FROZEN to start a run")
    film_lot = STORE["film_lots"].get(run["film_lot_id"])
    if film_lot is None or film_lot["status"] != "AVAILABLE":
        raise ApiError("ERR_FILM_LOT_QUARANTINED", "Film lot is not AVAILABLE")
    run["status"] = "IN_PROGRESS"
    bump(run)
    return ok_object(run_out(run))


@bp.route("/plant/line-runs/<runId>/complete", methods=["POST"])
@endpoint({"LineOperator"})
def complete_run(user_id, role, runId):
    body = body_dict(request.get_json(silent=True))
    units_packed = as_positive_int(req_present(body, "units_packed"), "units_packed")
    film_consumed = as_positive_int(
        req_present(body, "film_meters_consumed"), "film_meters_consumed"
    )
    run = svc.require_record("runs", runId, "LineRun")
    if run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_RUN_STATE", "Run cannot be completed from %s" % run["status"])

    batch = svc.get_batch(run["batch_id"])
    order = svc.order_of_batch(batch) if batch else None
    recipe = svc.recipe_of_order(order) if order else None

    run["units_packed"] = units_packed
    run["film_meters_consumed"] = film_consumed
    run["status"] = "COMPLETED"
    bump(run)
    # Film reservation release / consumption are derived from run status.

    # Finished-goods lot is born QA_PENDING with pack_format denormalized (PRD §3.5/§3.7)
    lot = new_record()
    lot.update(
        batch_id=batch["id"],
        slot_id=None,
        pack_format=order["pack_format"],
        cases_produced=svc.pack_out_cases(units_packed, order["pack_format"]),
        net_weight_kg=svc.pack_out_net_weight_kg(units_packed, recipe["portion_weight_g"]),
        stored_cases=0,
        withdrawn_total=0,
        cases_shipped=0,
        release_status="QA_PENDING",
        _ship_events=[],
    )
    STORE["lots"][lot["id"]] = lot

    # batch FROZEN -> PACKED (auto); units_packed_total / yield_pct are derived
    if batch["status"] == "FROZEN":
        batch["status"] = "PACKED"
        bump(batch)
    return ok_object(run_out(run))


@bp.route("/plant/line-runs/<runId>/cancel", methods=["POST"])
@endpoint({"ProductionPlanner"})
def cancel_run(user_id, role, runId):
    run = svc.require_record("runs", runId, "LineRun")
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE", "Only a SCHEDULED run can be cancelled")
    svc.cancel_scheduled_run(run)
    return ok_object(run_out(run))


# ---------------------------------------------------------------------------
# Film supply lots
# ---------------------------------------------------------------------------

@bp.route("/plant/film-lots", methods=["POST"])
@endpoint({"PlantManager"})
def create_film_lot(user_id, role):
    body = body_dict(request.get_json(silent=True))
    film_type = as_enum(req_present(body, "film_type"), "film_type", FILM_TYPES)
    rolls = as_positive_int(req_present(body, "rolls_received"), "rolls_received")
    meters_per_roll = as_positive_int(req_present(body, "meters_per_roll"), "meters_per_roll")

    rec = new_record()
    rec.update(
        film_type=film_type,
        rolls_received=rolls,
        meters_per_roll=meters_per_roll,
        status="AVAILABLE",
    )
    STORE["film_lots"][rec["id"]] = rec
    return ok_object(film_lot_out(rec), 201)


@bp.route("/plant/film-lots", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_film_lots(user_id, role):
    film_type = request.args.get("film_type")
    status = request.args.get("status")
    recs = list(STORE["film_lots"].values())
    if film_type is not None:
        recs = [l for l in recs if l["film_type"] == film_type]
    if status is not None:
        recs = [l for l in recs if l["status"] == status]
    return list_response(recs, film_lot_out)


@bp.route("/plant/film-lots/<lotId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_film_lot(user_id, role, lotId):
    return ok_object(film_lot_out(svc.require_record("film_lots", lotId, "FilmSupplyLot")))


@bp.route("/plant/film-lots/<lotId>/quarantine", methods=["POST"])
@endpoint({"QATechnician"})
def quarantine_film_lot(user_id, role, lotId):
    lot = svc.require_record("film_lots", lotId, "FilmSupplyLot")
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_REQUEST", "Only an AVAILABLE film lot can be quarantined")
    lot["status"] = "QUARANTINED"
    bump(lot)
    return ok_object(film_lot_out(lot))


@bp.route("/plant/film-lots/<lotId>/release-quarantine", methods=["POST"])
@endpoint({"QAManager"})
def release_film_quarantine(user_id, role, lotId):
    lot = svc.require_record("film_lots", lotId, "FilmSupplyLot")
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_REQUEST", "Only a QUARANTINED film lot can be released")
    lot["status"] = "AVAILABLE"
    bump(lot)
    return ok_object(film_lot_out(lot))
