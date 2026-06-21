from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, now_iso
from middleware import require_roles
from response import success_object, success_array
from services import calc
from services.common import (
    get_json_body, parse_pagination, paginate,
    require_str, opt_bool, require_int_min, require_int_range, require_enum,
    get_stop_or_404, get_route_or_404, get_parcel_or_404,
)
from services.serialize import serialize_stop, serialize_attempt

bp = Blueprint("stops", __name__)

OUTCOMES = {"DELIVERED", "NO_ONE_HOME", "REFUSED", "ADDRESS_ISSUE"}


@bp.post("/delivery/stops")
@require_roles("DispatchManager")
def create_stop():
    body = get_json_body()
    route_id = require_str(body, "route_id")
    parcel_id = require_str(body, "parcel_id")
    sequence = require_int_min(body, "sequence", 1)
    window_start = require_int_range(body, "window_start_min", 0, 1440)
    # window_end must be > start and <= 1440
    we = body.get("window_end_min")
    if isinstance(we, bool) or not isinstance(we, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "window_end_min must be an integer.")
    if we <= window_start or we > 1440:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "window_end_min out of range.")
    window_end = we

    # FK existence
    route = get_route_or_404(route_id)
    parcel = get_parcel_or_404(parcel_id)

    # parcel must be SORTED
    if parcel["status"] != "SORTED":
        raise ApiError(errors.ERR_PARCEL_NOT_SORTED, 409, "Parcel not SORTED.")

    # stop limit / sequence uniqueness among non-CANCELLED stops
    active = [s for s in db.stops.values()
              if s["route_id"] == route_id and s["status"] != "CANCELLED"]
    if any(s["sequence"] == sequence for s in active):
        raise ApiError(errors.ERR_ROUTE_STOP_LIMIT, 409, "Duplicate sequence on route.")
    if len(active) + 1 > route["max_stops"]:
        raise ApiError(errors.ERR_ROUTE_STOP_LIMIT, 409, "Route stop limit exceeded.")

    origin_center = db.transit_centers.get(parcel.get("sorted_at_center_id"))

    ts = now_iso()
    sid = db.new_id()
    stop = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "route_id": route_id,
        "parcel_id": parcel_id,
        "sequence": sequence,
        "window_start_min": window_start,
        "window_end_min": window_end,
        "attempt_count": 0,
        "redelivery_fee_cents": 0,
        "status": "PENDING",
    }
    db.stops[sid] = stop

    # parcel SORTED -> ROUTED
    parcel["status"] = "ROUTED"
    parcel["updated_at"] = now_iso()
    parcel["version"] += 1

    # origin center sorted_count recompute (parcel left SORTED)
    if origin_center is not None:
        calc.recompute_center_sorted_count(origin_center)
        origin_center["updated_at"] = now_iso()
        origin_center["version"] += 1

    # route metrics + version bump
    calc.recompute_route_metrics(route)
    route["updated_at"] = now_iso()
    route["version"] += 1

    return success_object(serialize_stop(stop), 201)


@bp.get("/delivery/stops")
@require_roles("DispatchManager", "Driver")
def list_stops():
    limit, offset = parse_pagination()
    route_id = request.args.get("route_id")
    parcel_id = request.args.get("parcel_id")
    items = list(db.stops.values())
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    if parcel_id is not None:
        items = [s for s in items if s["parcel_id"] == parcel_id]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_stop(s) for s in page], limit, offset, total)


@bp.get("/delivery/stops/<stop_id>")
@require_roles("DispatchManager", "Driver", "CustomerServiceAgent")
def get_stop(stop_id):
    stop = get_stop_or_404(stop_id)
    return success_object(serialize_stop(stop), 200)


@bp.post("/delivery/stops/<stop_id>/attempts")
@require_roles("Driver")
def log_attempt(stop_id):
    stop = get_stop_or_404(stop_id)
    body = get_json_body()
    outcome = require_enum(body, "outcome", OUTCOMES)
    signature_name = body.get("signature_name")
    if signature_name is not None and not isinstance(signature_name, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "signature_name must be a string.")
    used_driver_release = opt_bool(body, "used_driver_release", False)

    # state precondition
    if stop["status"] not in ("OUT_FOR_DELIVERY", "REDELIVERY_SCHEDULED"):
        raise ApiError(errors.ERR_STOP_NOT_OUT_FOR_DELIVERY, 409, "Stop not out for delivery.")

    parcel = db.parcels.get(stop["parcel_id"])
    route = db.routes.get(stop["route_id"])
    driver = db.drivers.get(route["driver_id"]) if route else None

    from_state = stop["status"]
    delivered = outcome == "DELIVERED"

    if delivered:
        # business safety checks (driver release before signature per validation priority 9<10)
        if used_driver_release and not parcel["driver_release_authorized"]:
            raise ApiError(errors.ERR_DRIVER_RELEASE_NOT_AUTHORIZED, 409, "Driver release not authorized.")
        if parcel["signature_required"] and not used_driver_release:
            if not signature_name:
                raise ApiError(errors.ERR_SIGNATURE_REQUIRED, 409, "Signature required.")

    # append attempt
    calc.recompute_stop_attempt_count(stop)  # ensure current before increment via append
    aid = db.new_id()
    ts = now_iso()
    attempt = {
        "id": aid,
        "created_at": ts,
        "stop_id": stop["id"],
        "outcome": outcome,
        "signature_name": signature_name,
        "used_driver_release": used_driver_release,
        "attempt_index": 0,  # set after recompute
    }
    db.attempts[aid] = attempt
    calc.recompute_stop_attempt_count(stop)
    attempt["attempt_index"] = stop["attempt_count"]

    if delivered:
        stop["status"] = "DELIVERED"
        stop["updated_at"] = now_iso()
        stop["version"] += 1
        # parcel ROUTED -> DELIVERED
        if parcel is not None:
            parcel["status"] = "DELIVERED"
            parcel["updated_at"] = now_iso()
            parcel["version"] += 1
        # recovery credit if delivered out of REDELIVERY_SCHEDULED
        if from_state == "REDELIVERY_SCHEDULED" and driver is not None:
            calc.apply_recovery_credit(driver)
            driver["updated_at"] = now_iso()
            driver["version"] += 1
    else:
        stop["status"] = "ATTEMPTED"
        stop["updated_at"] = now_iso()
        stop["version"] += 1
        if driver is not None and parcel is not None:
            calc.apply_attempt_penalty(driver, attempt["attempt_index"], parcel)
            driver["updated_at"] = now_iso()
            driver["version"] += 1

    # recompute route metrics (stop status changed)
    if route is not None:
        calc.recompute_route_metrics(route)
        route["updated_at"] = now_iso()
        route["version"] += 1

    return success_object(serialize_attempt(attempt), 201)


@bp.get("/delivery/stops/<stop_id>/attempts")
@require_roles("DispatchManager", "Driver")
def list_attempts(stop_id):
    get_stop_or_404(stop_id)
    limit, offset = parse_pagination()
    items = [a for a in db.attempts.values() if a["stop_id"] == stop_id]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([serialize_attempt(a) for a in page], limit, offset, total)


@bp.post("/delivery/stops/<stop_id>/reschedule")
@require_roles("DispatchManager")
def reschedule_stop(stop_id):
    stop = get_stop_or_404(stop_id)
    if stop["status"] != "ATTEMPTED":
        raise ApiError(errors.ERR_STOP_NOT_ATTEMPTED, 409, "Stop not in ATTEMPTED.")

    parcel = db.parcels.get(stop["parcel_id"])
    route = db.routes.get(stop["route_id"])
    driver = db.drivers.get(route["driver_id"]) if route else None

    if stop["attempt_count"] < calc.MAX_ATTEMPTS:
        # redelivery branch
        calc.compute_redelivery_surcharge(stop, parcel)
        stop["status"] = "REDELIVERY_SCHEDULED"
        stop["updated_at"] = now_iso()
        stop["version"] += 1
    else:
        # failed branch
        stop["status"] = "FAILED"
        stop["updated_at"] = now_iso()
        stop["version"] += 1
        if parcel is not None:
            parcel["status"] = "RETURNED"
            parcel["updated_at"] = now_iso()
            parcel["version"] += 1
        if driver is not None:
            calc.apply_return_penalty(driver)
            driver["updated_at"] = now_iso()
            driver["version"] += 1

    if route is not None:
        calc.recompute_route_metrics(route)
        route["updated_at"] = now_iso()
        route["version"] += 1

    return success_object(serialize_stop(stop), 200)


@bp.post("/delivery/stops/<stop_id>/cancel")
@require_roles("DispatchManager")
def cancel_stop(stop_id):
    stop = get_stop_or_404(stop_id)
    if stop["status"] != "PENDING":
        raise ApiError(errors.ERR_STOP_NOT_CANCELLABLE, 409, "Stop not cancellable.")

    route = db.routes.get(stop["route_id"])
    parcel = db.parcels.get(stop["parcel_id"])
    origin_center = db.transit_centers.get(route["origin_center_id"]) if route else None

    stop["status"] = "CANCELLED"
    stop["updated_at"] = now_iso()
    stop["version"] += 1

    if parcel is not None and parcel["status"] == "ROUTED":
        parcel["status"] = "SORTED"
        parcel["sorted_at_center_id"] = route["origin_center_id"] if route else parcel.get("sorted_at_center_id")
        parcel["updated_at"] = now_iso()
        parcel["version"] += 1

    if origin_center is not None:
        calc.recompute_center_sorted_count(origin_center)
        origin_center["updated_at"] = now_iso()
        origin_center["version"] += 1

    if route is not None:
        calc.recompute_route_metrics(route)
        route["updated_at"] = now_iso()
        route["version"] += 1

    return success_object(serialize_stop(stop), 200)
