"""Catalog + service-date routes: clock, operators, fare classes, routes,
service dates and their lifecycle/sales transitions (PRD 3.1, 3.2, 2.9)."""
from flask import Blueprint

import db
from errors import err
from response import success
from middleware import auth
from helpers import parse_pagination, paginate, get_json_body
import clock
from timeutil import parse_iso, parse_date
from constants import (
    OPERATOR_MODES, FARE_CODES, SEATING_MODES,
    DEFAULT_CONNECTION_BUFFER_MIN, DEFAULT_EXCHANGE_FEE_CENTS,
)
import serializers as ser
from services import inventory
from services.bookings import cascade_cancel_service_date

bp = Blueprint("catalog", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Clock (PRD 2.9)
# ---------------------------------------------------------------------------
@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"SupportAgent"})
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    clock.set_now(dt)
    return success({}, 200)


# ---------------------------------------------------------------------------
# Operator (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/v1/operators", methods=["POST"])
def create_operator():
    auth({"ScheduleManager"})
    body = get_json_body()
    name = body.get("name")
    mode = body.get("mode")
    if not isinstance(name, str) or not name:
        raise err("ERR_INVALID_REQUEST", "name is required")
    if mode not in OPERATOR_MODES:
        raise err("ERR_INVALID_REQUEST", "mode must be RAIL or BUS")

    buffer_min = body.get("default_connection_buffer_min", DEFAULT_CONNECTION_BUFFER_MIN)
    if not _is_int(buffer_min) or buffer_min < 0:
        raise err("ERR_INVALID_REQUEST", "default_connection_buffer_min must be a non-negative integer")
    exchange_fee = body.get("exchange_fee_cents", DEFAULT_EXCHANGE_FEE_CENTS)
    if not _is_int(exchange_fee) or exchange_fee < 0:
        raise err("ERR_INVALID_REQUEST", "exchange_fee_cents must be a non-negative integer")

    oid = db.new_id()
    rec = {
        "id": oid, "name": name, "mode": mode,
        "default_connection_buffer_min": buffer_min,
        "exchange_fee_cents": exchange_fee,
    }
    db.stamp_create(rec)
    db.operators[oid] = rec
    return success(ser.operator_out(rec), 201)


@bp.route("/v1/operators/<operator_id>", methods=["GET"])
def get_operator(operator_id):
    auth({"ScheduleManager", "FareAnalyst", "Passenger", "GateAgent", "SupportAgent"})
    rec = db.operators.get(operator_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "operator not found")
    return success(ser.operator_out(rec), 200)


# ---------------------------------------------------------------------------
# FareClass (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/v1/fare-classes", methods=["POST"])
def create_fare_class():
    auth({"FareAnalyst"})
    body = get_json_body()
    operator_id = body.get("operator_id")
    code = body.get("code")
    seating_mode = body.get("seating_mode")

    if not isinstance(operator_id, str) or not operator_id:
        raise err("ERR_INVALID_REQUEST", "operator_id is required")
    if db.operators.get(operator_id) is None:
        raise err("ERR_NOT_FOUND", "operator not found")
    if code not in FARE_CODES:
        raise err("ERR_INVALID_REQUEST", "code must be ECONOMY or BUSINESS")
    if seating_mode not in SEATING_MODES:
        raise err("ERR_INVALID_REQUEST", "seating_mode must be RESERVED or OPEN")

    surcharge = body.get("surcharge_cents", 0)
    if not _is_int(surcharge) or surcharge < 0:
        raise err("ERR_INVALID_REQUEST", "surcharge_cents must be a non-negative integer")
    refundable = body.get("refundable", True)
    if not isinstance(refundable, bool):
        raise err("ERR_INVALID_REQUEST", "refundable must be a boolean")

    fid = db.new_id()
    rec = {
        "id": fid, "operator_id": operator_id, "code": code,
        "seating_mode": seating_mode, "surcharge_cents": surcharge,
        "refundable": refundable, "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.fare_classes[fid] = rec
    return success(ser.fare_class_out(rec), 201)


@bp.route("/v1/fare-classes", methods=["GET"])
def list_fare_classes():
    auth({"FareAnalyst", "ScheduleManager", "Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    from flask import request
    op = request.args.get("operator_id")
    recs = [r for r in db.fare_classes.values() if op is None or r["operator_id"] == op]
    page, meta = paginate(recs, limit, offset)
    return success([ser.fare_class_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/fare-classes/<fare_class_id>", methods=["GET"])
def get_fare_class(fare_class_id):
    auth({"FareAnalyst", "ScheduleManager", "Passenger", "SupportAgent"})
    rec = db.fare_classes.get(fare_class_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "fare class not found")
    return success(ser.fare_class_out(rec), 200)


@bp.route("/v1/fare-classes/<fare_class_id>/retire", methods=["POST"])
def retire_fare_class(fare_class_id):
    auth({"FareAnalyst"})
    rec = db.fare_classes.get(fare_class_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "fare class not found")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "fare class not ACTIVE")
    rec["status"] = "RETIRED"
    db.touch(rec)
    return success(ser.fare_class_out(rec), 200)


# ---------------------------------------------------------------------------
# Route (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/v1/routes", methods=["POST"])
def create_route():
    auth({"ScheduleManager"})
    body = get_json_body()
    operator_id = body.get("operator_id")
    if not isinstance(operator_id, str) or not operator_id:
        raise err("ERR_INVALID_REQUEST", "operator_id is required")
    if db.operators.get(operator_id) is None:
        raise err("ERR_NOT_FOUND", "operator not found")

    origin = body.get("origin_code")
    dest = body.get("destination_code")
    depart = body.get("depart_minute_of_day")
    arrive = body.get("arrive_minute_of_day")
    if not isinstance(origin, str) or not origin:
        raise err("ERR_INVALID_REQUEST", "origin_code is required")
    if not isinstance(dest, str) or not dest:
        raise err("ERR_INVALID_REQUEST", "destination_code is required")
    if not _is_int(depart) or depart < 0 or depart > 1439:
        raise err("ERR_INVALID_REQUEST", "depart_minute_of_day must be 0..1439")
    if not _is_int(arrive) or arrive < 0 or arrive > 1439:
        raise err("ERR_INVALID_REQUEST", "arrive_minute_of_day must be 0..1439")

    rid = db.new_id()
    rec = {
        "id": rid, "operator_id": operator_id, "origin_code": origin,
        "destination_code": dest, "depart_minute_of_day": depart,
        "arrive_minute_of_day": arrive, "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.routes[rid] = rec
    return success(ser.route_out(rec), 201)


@bp.route("/v1/routes", methods=["GET"])
def list_routes():
    auth({"ScheduleManager", "FareAnalyst", "Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    from flask import request
    op = request.args.get("operator_id")
    recs = [r for r in db.routes.values() if op is None or r["operator_id"] == op]
    page, meta = paginate(recs, limit, offset)
    return success([ser.route_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    auth({"ScheduleManager", "FareAnalyst", "Passenger", "SupportAgent"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "route not found")
    return success(ser.route_out(rec), 200)


@bp.route("/v1/routes/<route_id>/publish", methods=["POST"])
def publish_route(route_id):
    auth({"ScheduleManager"})
    rec = db.routes.get(route_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "route not found")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "route not DRAFT")
    rec["status"] = "PUBLISHED"
    db.touch(rec)
    return success(ser.route_out(rec), 200)


# ---------------------------------------------------------------------------
# ServiceDate (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/v1/service-dates", methods=["POST"])
def create_service_date():
    auth({"ScheduleManager"})
    body = get_json_body()
    route_id = body.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        raise err("ERR_INVALID_REQUEST", "route_id is required")
    route = db.routes.get(route_id)
    if route is None:
        raise err("ERR_NOT_FOUND", "route not found")

    departure_date = body.get("departure_date")
    seats_total = body.get("seats_total")
    base_fare = body.get("base_fare_cents")
    if not isinstance(departure_date, str):
        raise err("ERR_INVALID_REQUEST", "departure_date is required")
    try:
        parse_date(departure_date)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "departure_date must be YYYY-MM-DD")
    if not _is_int(seats_total) or seats_total < 1:
        raise err("ERR_INVALID_REQUEST", "seats_total must be >= 1")
    if not _is_int(base_fare) or base_fare < 0:
        raise err("ERR_INVALID_REQUEST", "base_fare_cents must be >= 0")

    # Cross-entity precondition: route must be PUBLISHED (PRD 3.1).
    if route["status"] != "PUBLISHED":
        raise err("ERR_ROUTE_NOT_PUBLISHED", "route is not PUBLISHED")

    sid = db.new_id()
    rec = {
        "id": sid, "route_id": route_id, "departure_date": departure_date,
        "seats_total": seats_total, "base_fare_cents": base_fare,
        "seats_held": 0, "seats_sold": 0, "seats_available": seats_total,
        "load_factor": 0.0, "lifecycle": "SCHEDULED", "sales": "OPEN",
    }
    db.stamp_create(rec)
    db.service_dates[sid] = rec
    return success(ser.service_date_out(rec), 201)


@bp.route("/v1/service-dates", methods=["GET"])
def list_service_dates():
    auth({"ScheduleManager", "FareAnalyst", "Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    from flask import request
    route_id = request.args.get("route_id")
    recs = [r for r in db.service_dates.values() if route_id is None or r["route_id"] == route_id]
    page, meta = paginate(recs, limit, offset)
    return success([ser.service_date_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/service-dates/<service_date_id>", methods=["GET"])
def get_service_date(service_date_id):
    auth({"ScheduleManager", "FareAnalyst", "Passenger", "GateAgent", "SupportAgent"})
    rec = db.service_dates.get(service_date_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "service date not found")
    return success(ser.service_date_out(rec), 200)


def _load_sd(service_date_id):
    rec = db.service_dates.get(service_date_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "service date not found")
    return rec


@bp.route("/v1/service-dates/<service_date_id>/delay", methods=["POST"])
def delay_service_date(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["lifecycle"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "lifecycle not SCHEDULED")
    rec["lifecycle"] = "DELAYED"
    db.touch(rec)
    return success(ser.service_date_out(rec), 200)


@bp.route("/v1/service-dates/<service_date_id>/restore", methods=["POST"])
def restore_service_date(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["lifecycle"] != "DELAYED":
        raise err("ERR_INVALID_STATE", "lifecycle not DELAYED")
    rec["lifecycle"] = "SCHEDULED"
    db.touch(rec)
    return success(ser.service_date_out(rec), 200)


@bp.route("/v1/service-dates/<service_date_id>/depart", methods=["POST"])
def depart_service_date(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["lifecycle"] not in ("SCHEDULED", "DELAYED"):
        raise err("ERR_INVALID_STATE", "lifecycle not SCHEDULED or DELAYED")
    rec["lifecycle"] = "DEPARTED"
    rec["sales"] = "SUSPENDED"
    db.touch(rec)
    return success(ser.service_date_out(rec), 200)


@bp.route("/v1/service-dates/<service_date_id>/cancel", methods=["POST"])
def cancel_service_date(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["lifecycle"] not in ("SCHEDULED", "DELAYED"):
        raise err("ERR_INVALID_STATE", "lifecycle not SCHEDULED or DELAYED")
    rec["lifecycle"] = "CANCELLED"
    rec["sales"] = "SUSPENDED"
    db.touch(rec)
    cascade_cancel_service_date(rec)
    return success(ser.service_date_out(rec), 200)


@bp.route("/v1/service-dates/<service_date_id>/suspend-sales", methods=["POST"])
def suspend_sales(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["sales"] != "OPEN":
        raise err("ERR_INVALID_STATE", "sales not OPEN")
    if rec["lifecycle"] in ("DEPARTED", "CANCELLED"):
        raise err("ERR_PRECONDITION_NOT_MET", "lifecycle is terminal")
    rec["sales"] = "SUSPENDED"
    db.touch(rec)
    return success(ser.service_date_out(rec), 200)


@bp.route("/v1/service-dates/<service_date_id>/resume-sales", methods=["POST"])
def resume_sales(service_date_id):
    auth({"ScheduleManager"})
    rec = _load_sd(service_date_id)
    if rec["sales"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "sales not SUSPENDED")
    if rec["lifecycle"] in ("DEPARTED", "CANCELLED"):
        raise err("ERR_PRECONDITION_NOT_MET", "lifecycle is terminal")
    rec["sales"] = "OPEN"
    db.touch(rec)
    return success(ser.service_date_out(rec), 200)
