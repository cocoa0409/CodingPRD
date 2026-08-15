"""Second half of the API surface: routes, stops, intakes, wash batches,
swaps, lost-item cases, invoices, and the logical-clock test driver.

Exposed as a Flask Blueprint so `python3 app.py` serves a single app object
(app.py registers this blueprint after defining its own routes).
"""

from datetime import datetime, timedelta

from flask import Blueprint, request

import errors
import helpers as H
from db import db, new_resource, touch, clock_now, clock_today, set_clock, fmt_ts, fmt_ts_seconds
from envelope import ok
from errors import ApiError

bp = Blueprint("routes_ext", __name__)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@bp.post("/api/routes")
def create_route():
    body = H.parse_body()
    service_zone_id = H.req_str(body, "service_zone_id")
    route_date = H.req_date(body, "route_date")
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    zone = H.ref_or_404("service_zones", service_zone_id)
    if H.WEEKDAYS[route_date.weekday()] not in zone["service_weekdays"]:
        raise errors.bad_request("route_date is not one of the zone's service_weekdays")
    route = new_resource({
        "service_zone_id": service_zone_id,
        "route_date": route_date.isoformat(),
        "status": "PLANNED",
        "planned_stop_count": 0,
        "completed_stop_count": 0,
        "total_clean_items_delivered": 0,
        "total_soiled_bags_collected": 0,
        "_route_date": route_date,
    })
    db["routes"][route["id"]] = route
    # Auto-create PLANNED stops for eligible subscriptions (PRD §3.3).
    subs = sorted(db["subscriptions"].values(), key=lambda s: (s["created_at"], s["_seq"]))
    for sub in subs:
        if sub["service_status"] != "ACTIVE":
            continue
        if sub["service_zone_id"] != service_zone_id:
            continue
        paused = any(
            p["subscription_id"] == sub["id"] and p["status"] in ("SCHEDULED", "ACTIVE")
            and p["_start_date"] <= route_date < p["_end_date"]
            for p in db["service_pauses"].values())
        if paused:
            continue
        exists = any(
            s["subscription_id"] == sub["id"]
            and (db["routes"].get(s["route_id"]) or {}).get("_route_date") == route_date
            for s in db["route_stops"].values())
        if exists:
            continue
        stop = new_resource({
            "route_id": route["id"],
            "subscription_id": sub["id"],
            "stop_seq": None,
            "window_start_minutes": sub["window_start_minutes"],
            "window_end_minutes": sub["window_end_minutes"],
            "status": "PLANNED",
            "clean_items_delivered": 0,
            "soiled_bags_collected": 0,
            "is_makeup": False,
            "rescheduled_to_stop_id": None,
        })
        db["route_stops"][stop["id"]] = stop
    H.recompute_route_manifest(route)
    return ok(H.serialize("routes", route), 201)


@bp.get("/api/routes")
def list_routes():
    return H.do_list("routes", [("service_zone_id", request.args.get("service_zone_id")),
                                ("route_date", request.args.get("route_date")),
                                ("status", request.args.get("status"))])


@bp.get("/api/routes/<route_id>")
def get_route(route_id):
    return H.do_get_one("routes", route_id)


@bp.post("/api/routes/<route_id>/sequence")
def sequence_route(route_id):
    H.parse_body()
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    route = H.get_or_404("routes", route_id)
    if route["status"] in H.ROUTE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Route is in a terminal state")
    if route["status"] not in ("PLANNED", "SEQUENCED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a PLANNED or SEQUENCED route can be sequenced")
    zone = db["service_zones"].get(route["service_zone_id"])
    if not clock_now() < H.cutoff_instant(route, zone):
        raise ApiError(errors.ERR_CUTOFF_PASSED, 422,
                       "The sequencing cutoff for this route has passed")
    planned = [s for s in db["route_stops"].values()
               if s["route_id"] == route_id and s["status"] == "PLANNED"]

    def sort_key(s):
        sub = db["subscriptions"].get(s["subscription_id"])
        sub_created = sub["created_at"] if sub else ""
        sub_seq = sub["_seq"] if sub else 0
        return (s["window_start_minutes"], sub_created, sub_seq)

    planned.sort(key=sort_key)
    for i, stop in enumerate(planned, start=1):
        stop["stop_seq"] = i
        touch(stop)
    route["status"] = "SEQUENCED"
    touch(route)
    return ok(H.serialize("routes", route))


@bp.post("/api/routes/<route_id>/events")
def route_event(route_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.ROUTE_EVENT_TYPES)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    route = H.get_or_404("routes", route_id)
    if route["status"] in H.ROUTE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Route is in a terminal state")
    zone = db["service_zones"].get(route["service_zone_id"])

    if event_type == "LOCK":
        if route["status"] != "SEQUENCED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a SEQUENCED route can be locked")
        if not clock_now() < H.cutoff_instant(route, zone):
            raise ApiError(errors.ERR_CUTOFF_PASSED, 422,
                           "The locking cutoff for this route has passed")
        route["status"] = "LOCKED"
        touch(route)
    elif event_type == "START":
        if route["status"] != "LOCKED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a LOCKED route can be started")
        if clock_today() != route["_route_date"]:
            raise ApiError(errors.ERR_CUTOFF_PASSED, 422,
                           "A route can only be started on its route_date")
        route["status"] = "IN_PROGRESS"
        touch(route)
    elif event_type == "COMPLETE":
        if route["status"] != "IN_PROGRESS":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only an IN_PROGRESS route can be completed")
        for stop in db["route_stops"].values():
            if stop["route_id"] == route_id and stop["status"] not in H.STOP_TERMINAL:
                raise ApiError(errors.ERR_INVALID_STATE, 409,
                               "Every stop must be in a terminal state before completing the route")
        route["status"] = "COMPLETED"
        touch(route)
    elif event_type == "CANCEL":
        if route["status"] not in ("PLANNED", "SEQUENCED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a PLANNED or SEQUENCED route can be cancelled")
        for stop in db["route_stops"].values():
            if stop["route_id"] == route_id and stop["status"] == "PLANNED":
                stop["status"] = "SKIPPED"
                touch(stop)
        route["status"] = "CANCELLED"
        H.touch_route(route)
    return ok(H.serialize("routes", route))


# ---------------------------------------------------------------------------
# RouteStop
# ---------------------------------------------------------------------------

@bp.post("/api/route-stops")
def create_stop():
    body = H.parse_body()
    route_id = H.req_str(body, "route_id")
    subscription_id = H.req_str(body, "subscription_id")
    window_start = H.req_int(body, "window_start_minutes", lo=0, hi=1439)
    window_end = H.req_int(body, "window_end_minutes", lo=1, hi=1440)
    if window_start >= window_end:
        raise errors.bad_request("window_start_minutes must be before window_end_minutes")
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    route = H.ref_or_404("routes", route_id)
    H.ref_or_404("subscriptions", subscription_id)
    if route["status"] not in ("PLANNED", "SEQUENCED"):
        raise ApiError(errors.ERR_ROUTE_LOCKED, 409,
                       "Stops can only be added to a PLANNED or SEQUENCED route")
    if H.window_conflicts(route_id, window_start, window_end):
        raise ApiError(errors.ERR_STOP_WINDOW_CONFLICT, 409,
                       "Stop window collides with a non-terminal stop on the route")
    stop = new_resource({
        "route_id": route_id,
        "subscription_id": subscription_id,
        "stop_seq": None,
        "window_start_minutes": window_start,
        "window_end_minutes": window_end,
        "status": "PLANNED",
        "clean_items_delivered": 0,
        "soiled_bags_collected": 0,
        "is_makeup": True,
        "rescheduled_to_stop_id": None,
    })
    db["route_stops"][stop["id"]] = stop
    H.touch_route(route)
    return ok(H.serialize("route_stops", stop), 201)


@bp.get("/api/route-stops")
def list_stops():
    return H.do_list("route_stops", [("route_id", request.args.get("route_id")),
                                     ("subscription_id", request.args.get("subscription_id")),
                                     ("status", request.args.get("status"))])


@bp.get("/api/route-stops/<stop_id>")
def get_stop(stop_id):
    return H.do_get_one("route_stops", stop_id)


@bp.post("/api/route-stops/<stop_id>/complete")
def complete_stop(stop_id):
    body = H.parse_body()
    soiled_bags_collected = H.req_int(body, "soiled_bags_collected", lo=0)
    clean_items_delivered = H.req_int(body, "clean_items_delivered", lo=0)
    expected_route_version = H.req_int(body, "expected_route_version")
    uid, role = H.actor()
    H.require_role(role, {"RouteDriver", "PlatformAdmin"})
    stop = H.get_or_404("route_stops", stop_id)
    if stop["status"] in H.STOP_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Stop is in a terminal state")
    if stop["status"] != "PLANNED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a PLANNED stop can be completed")
    route = db["routes"].get(stop["route_id"])
    if route is None or route["status"] != "IN_PROGRESS":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Route is not IN_PROGRESS")
    sub = db["subscriptions"].get(stop["subscription_id"])
    if sub is None or sub["service_status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE, 409,
                       "Subscription is not ACTIVE")
    if expected_route_version != route["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_route_version does not match the route version")
    if route["total_clean_items_delivered"] + clean_items_delivered > H.ROUTE_CAPACITY_ITEMS:
        raise ApiError(errors.ERR_ROUTE_CAPACITY_EXCEEDED, 422,
                       "Completion would exceed the route capacity of 4000 items")
    stop["clean_items_delivered"] = clean_items_delivered
    stop["soiled_bags_collected"] = soiled_bags_collected
    stop["status"] = "COMPLETED"
    touch(stop)
    H.touch_route(route)
    return ok(H.serialize("route_stops", stop))


@bp.post("/api/route-stops/<stop_id>/events")
def stop_event(stop_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.STOP_EVENT_TYPES)
    makeup_route_id = None
    if event_type == "RESCHEDULE":
        makeup_route_id = H.req_str(body, "makeup_route_id")
    uid, role = H.actor()
    H.require_role(role, {"RouteDriver", "PlatformAdmin"})
    stop = H.get_or_404("route_stops", stop_id)
    if stop["status"] in H.STOP_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Stop is in a terminal state")

    if event_type == "MISS":
        if stop["status"] != "PLANNED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a PLANNED stop can be missed")
        route = db["routes"].get(stop["route_id"])
        if route is None or route["status"] != "IN_PROGRESS":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Route is not IN_PROGRESS")
        stop["status"] = "MISSED"
        touch(stop)
        sub = db["subscriptions"].get(stop["subscription_id"])
        if sub is not None:
            sub["missed_stop_count"] += 1
            touch(sub)
        if route is not None:
            H.touch_route(route)
    elif event_type == "SKIP":
        if stop["status"] != "PLANNED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a PLANNED stop can be skipped")
        stop["status"] = "SKIPPED"
        touch(stop)
        route = db["routes"].get(stop["route_id"])
        if route is not None:
            H.touch_route(route)
    elif event_type == "RESCHEDULE":
        if stop["status"] != "MISSED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a MISSED stop can be rescheduled")
        makeup = db["routes"].get(makeup_route_id)
        if makeup is None:
            raise ApiError(errors.ERR_REFERENCE_NOT_FOUND, 404,
                           "Referenced makeup_route_id does not exist")
        if makeup["status"] not in ("PLANNED", "SEQUENCED"):
            raise ApiError(errors.ERR_ROUTE_LOCKED, 409,
                           "Makeup route must be PLANNED or SEQUENCED")
        sub = db["subscriptions"].get(stop["subscription_id"])
        w_start = sub["window_start_minutes"] if sub else stop["window_start_minutes"]
        w_end = sub["window_end_minutes"] if sub else stop["window_end_minutes"]
        if H.window_conflicts(makeup_route_id, w_start, w_end):
            raise ApiError(errors.ERR_STOP_WINDOW_CONFLICT, 409,
                           "Stop window collides with a non-terminal stop on the makeup route")
        new_stop = new_resource({
            "route_id": makeup_route_id,
            "subscription_id": stop["subscription_id"],
            "stop_seq": None,
            "window_start_minutes": w_start,
            "window_end_minutes": w_end,
            "status": "PLANNED",
            "clean_items_delivered": 0,
            "soiled_bags_collected": 0,
            "is_makeup": True,
            "rescheduled_to_stop_id": None,
        })
        db["route_stops"][new_stop["id"]] = new_stop
        H.touch_route(makeup)
        stop["rescheduled_to_stop_id"] = new_stop["id"]
        stop["status"] = "RESCHEDULED"
        touch(stop)
    elif event_type == "FORFEIT":
        if stop["status"] != "MISSED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a MISSED stop can be forfeited")
        stop["status"] = "FORFEITED"
        touch(stop)
    return ok(H.serialize("route_stops", stop))


# ---------------------------------------------------------------------------
# SoiledIntake
# ---------------------------------------------------------------------------

@bp.post("/api/soiled-intakes")
def create_intake():
    body = H.parse_body()
    route_stop_id = H.req_str(body, "route_stop_id")
    scale_weight_g = H.req_int(body, "scale_weight_g", lo=1)
    soil_level = H.req_enum(body, "soil_level", {"LIGHT", "NORMAL", "HEAVY"})
    uid, role = H.actor()
    H.require_role(role, {"PlantOperator", "PlatformAdmin"})
    stop = H.ref_or_404("route_stops", route_stop_id)
    for intake in db["soiled_intakes"].values():
        if intake["route_stop_id"] == route_stop_id:
            raise errors.bad_request("At most one intake may exist per route stop")
    if stop["status"] != "COMPLETED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "An intake can only be recorded against a completed stop")
    sub = db["subscriptions"].get(stop["subscription_id"])
    if sub is None or sub["service_status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE, 409,
                       "Subscription is not ACTIVE")
    plan = db["subscription_plans"].get(sub["subscription_plan_id"])
    intake = new_resource({
        "route_stop_id": route_stop_id,
        "wash_batch_id": None,
        "scale_weight_g": scale_weight_g,
        "soil_level": soil_level,
        "expected_weight_g": 0,
        "variance_pct": 0.0,
        "verified_count": 0,
        "status": "RECONCILED",
        "resolution": None,
    })
    H.reconcile_intake(intake, stop, sub, plan)
    db["soiled_intakes"][intake["id"]] = intake
    return ok(H.serialize("soiled_intakes", intake), 201)


@bp.get("/api/soiled-intakes")
def list_intakes():
    return H.do_list("soiled_intakes", [("route_stop_id", request.args.get("route_stop_id")),
                                        ("wash_batch_id", request.args.get("wash_batch_id")),
                                        ("status", request.args.get("status"))])


@bp.get("/api/soiled-intakes/<intake_id>")
def get_intake(intake_id):
    return H.do_get_one("soiled_intakes", intake_id)


@bp.post("/api/soiled-intakes/<intake_id>/events")
def intake_event(intake_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.INTAKE_EVENT_TYPES)
    scale_weight_g = None
    resolution = None
    if event_type == "REWEIGH":
        scale_weight_g = H.req_int(body, "scale_weight_g", lo=1)
    if event_type == "RESOLVE":
        resolution = H.req_enum(body, "resolution", {"ACCEPT_COUNT", "ACCEPT_WEIGHT"})
    uid, role = H.actor()
    H.require_role(role, {"PlantOperator", "PlatformAdmin"})
    intake = H.get_or_404("soiled_intakes", intake_id)
    if intake["status"] in H.INTAKE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Intake is RESOLVED")
    stop = db["route_stops"].get(intake["route_stop_id"])
    sub = db["subscriptions"].get(stop["subscription_id"]) if stop else None
    plan = db["subscription_plans"].get(sub["subscription_plan_id"]) if sub else None

    if event_type == "DISPUTE":
        if intake["status"] != "RECONCILED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a RECONCILED intake can be disputed")
        intake["status"] = "DISPUTED"
        touch(intake)
    elif event_type == "REWEIGH":
        if intake["status"] != "DISPUTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a DISPUTED intake can be reweighed")
        intake["scale_weight_g"] = scale_weight_g
        H.reconcile_intake(intake, stop, sub, plan)
        touch(intake)
    elif event_type == "RESOLVE":
        if intake["status"] != "DISPUTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a DISPUTED intake can be resolved")
        per_item = H.per_item_soiled_g(sub["current_size_code"])
        if resolution == "ACCEPT_COUNT":
            intake["verified_count"] = stop["clean_items_delivered"]
        else:  # ACCEPT_WEIGHT
            intake["verified_count"] = H.round_half_up_int(
                intake["scale_weight_g"] / per_item if per_item else 0)
        intake["resolution"] = resolution
        intake["status"] = "RESOLVED"
        touch(intake)
    return ok(H.serialize("soiled_intakes", intake))


# ---------------------------------------------------------------------------
# WashBatch
# ---------------------------------------------------------------------------

@bp.post("/api/wash-batches")
def create_batch():
    body = H.parse_body()
    wash_formula_id = H.req_str(body, "wash_formula_id")
    soil_level = H.req_enum(body, "soil_level", {"LIGHT", "NORMAL", "HEAVY"})
    water_hardness = H.req_enum(body, "water_hardness", {"SOFT", "MEDIUM", "HARD"})
    uid, role = H.actor()
    H.require_role(role, {"PlantOperator", "PlatformAdmin"})
    formula = H.ref_or_404("wash_formulas", wash_formula_id)
    batch = new_resource({
        "wash_formula_id": wash_formula_id,
        "formula_version": formula["version"],
        "soil_level": soil_level,
        "water_hardness": water_hardness,
        "status": "RECEIVING",
        "total_load_g": 0,
        "dosed_detergent_ml": None,
        "dosed_sanitizer_ml": None,
        "rewash_count": 0,
        "wash_started_by": None,
        "validated_by": None,
        "validation_passed": None,
    })
    db["wash_batches"][batch["id"]] = batch
    return ok(H.serialize("wash_batches", batch), 201)


@bp.get("/api/wash-batches")
def list_batches():
    return H.do_list("wash_batches", [("wash_formula_id", request.args.get("wash_formula_id")),
                                      ("status", request.args.get("status"))])


@bp.get("/api/wash-batches/<batch_id>")
def get_batch(batch_id):
    return H.do_get_one("wash_batches", batch_id)


@bp.post("/api/wash-batches/<batch_id>/load")
def load_batch(batch_id):
    body = H.parse_body()
    ids = body.get("soiled_intake_ids")
    if not isinstance(ids, list) or len(ids) == 0:
        raise errors.bad_request("soiled_intake_ids must be a non-empty array")
    if any(not isinstance(i, str) for i in ids):
        raise errors.bad_request("soiled_intake_ids must be an array of strings")
    uid, role = H.actor()
    H.require_role(role, {"PlantOperator", "PlatformAdmin"})
    batch = H.get_or_404("wash_batches", batch_id)
    if batch["status"] in H.BATCH_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Batch is in a terminal state")
    if batch["status"] != "RECEIVING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a RECEIVING batch can be loaded")
    intakes = []
    for iid in ids:
        intakes.append(H.ref_or_404("soiled_intakes", iid))
    for intake in intakes:
        if intake["status"] not in ("RECONCILED", "RESOLVED"):
            raise ApiError(errors.ERR_WEIGHT_VARIANCE_EXCEEDED, 422,
                           "A DISPUTED intake cannot be loaded into a wash batch")
    for intake in intakes:
        if intake["wash_batch_id"] is not None:
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Intake is already loaded into a wash batch")
    for intake in intakes:
        intake["wash_batch_id"] = batch_id
        touch(intake)
        batch["total_load_g"] += intake["scale_weight_g"]
        stop = db["route_stops"].get(intake["route_stop_id"])
        sub = db["subscriptions"].get(stop["subscription_id"]) if stop else None
        pool = H.pool_for_size(sub["current_size_code"]) if sub else None
        if pool is not None:
            pool["checked_out_units"] -= intake["verified_count"]
            pool["in_wash_units"] += intake["verified_count"]
            touch(pool)
    batch["status"] = "LOADED"
    touch(batch)
    return ok(H.serialize("wash_batches", batch))


def _loaded_intakes(batch_id):
    return [i for i in db["soiled_intakes"].values() if i["wash_batch_id"] == batch_id]


@bp.post("/api/wash-batches/<batch_id>/events")
def batch_event(batch_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.BATCH_EVENT_TYPES)
    peak_temp_celsius = dwell_seconds = chlorine_ppm = None
    if event_type == "RECORD_SANITIZATION":
        peak_temp_celsius = H.req_int(body, "peak_temp_celsius")
        dwell_seconds = H.req_int(body, "dwell_seconds")
        chlorine_ppm = H.req_int(body, "chlorine_ppm")
    uid, role = H.actor()
    H.require_role(role, {"PlantOperator", "PlatformAdmin"})
    batch = H.get_or_404("wash_batches", batch_id)
    if batch["status"] in H.BATCH_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Batch is in a terminal state")
    formula = db["wash_formulas"].get(batch["wash_formula_id"])

    if event_type == "START_WASH":
        if batch["status"] != "LOADED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a LOADED batch can start washing")
        detergent, sanitizer = H.compute_dosing(batch, formula)
        batch["dosed_detergent_ml"] = detergent
        batch["dosed_sanitizer_ml"] = sanitizer
        batch["wash_started_by"] = uid
        batch["status"] = "WASHING"
        touch(batch)
    elif event_type == "RECORD_SANITIZATION":
        if batch["status"] != "WASHING":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a WASHING batch can record sanitization")
        passed = (peak_temp_celsius >= formula["min_temp_celsius"]
                  and dwell_seconds >= formula["min_dwell_seconds"]
                  and formula["chlorine_ppm_min"] <= chlorine_ppm <= formula["chlorine_ppm_max"])
        batch["validation_passed"] = passed
        batch["validated_by"] = uid
        batch["status"] = "VALIDATING"
        touch(batch)
    elif event_type == "REWASH":
        if batch["status"] != "VALIDATING":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a VALIDATING batch can be rewashed")
        if batch["validation_passed"] is not False:
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Rewash requires validation_passed to be false")
        if batch["rewash_count"] >= formula["max_rewash_count"]:
            raise ApiError(errors.ERR_REWASH_LIMIT_EXCEEDED, 409,
                           "The pinned formula's max_rewash_count has been reached")
        batch["rewash_count"] += 1
        batch["validation_passed"] = None
        batch["validated_by"] = None
        batch["status"] = "WASHING"
        touch(batch)
    elif event_type == "RELEASE":
        if batch["status"] != "VALIDATING":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a VALIDATING batch can be released")
        if batch["validation_passed"] is not True:
            raise ApiError(errors.ERR_SANITIZATION_NOT_VALIDATED, 422,
                           "Release requires validation_passed to be true")
        if batch["validated_by"] == batch["wash_started_by"]:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                           "Validator must differ from the operator who started the wash")
        for intake in _loaded_intakes(batch_id):
            if intake["status"] not in ("RECONCILED", "RESOLVED"):
                raise ApiError(errors.ERR_WEIGHT_VARIANCE_EXCEEDED, 422,
                               "Every loaded intake must be RECONCILED or RESOLVED at release")
        for intake in _loaded_intakes(batch_id):
            stop = db["route_stops"].get(intake["route_stop_id"])
            sub = db["subscriptions"].get(stop["subscription_id"]) if stop else None
            pool = H.pool_for_size(sub["current_size_code"]) if sub else None
            if pool is not None:
                pool["in_wash_units"] -= intake["verified_count"]
                pool["on_hand_units"] += intake["verified_count"]
                touch(pool)
        batch["status"] = "RELEASED"
        touch(batch)
    elif event_type == "QUARANTINE":
        if batch["status"] != "VALIDATING":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a VALIDATING batch can be quarantined")
        touched_pools = []
        for intake in _loaded_intakes(batch_id):
            stop = db["route_stops"].get(intake["route_stop_id"])
            sub = db["subscriptions"].get(stop["subscription_id"]) if stop else None
            pool = H.pool_for_size(sub["current_size_code"]) if sub else None
            if pool is not None:
                pool["in_wash_units"] -= intake["verified_count"]
                pool["quarantined_units"] += intake["verified_count"]
                touch(pool)
                if pool not in touched_pools:
                    touched_pools.append(pool)
        # Cascade link 2: while a touched pool's availability is negative, deny
        # the newest APPROVED swap on that size (created_at DESC), releasing
        # its reservation, until availability is non-negative or none remain.
        for pool in touched_pools:
            while H.available_units(pool) < 0:
                candidates = [s for s in db["inventory_swaps"].values()
                              if s["status"] == "APPROVED"
                              and s["to_size_code"] == pool["size_code"]]
                if not candidates:
                    break
                candidates.sort(key=lambda s: (s["created_at"], s["_seq"]), reverse=True)
                H.deny_swap_with_compensation(candidates[0])
                touch(pool)
        batch["status"] = "QUARANTINED"
        touch(batch)
    return ok(H.serialize("wash_batches", batch))


# ---------------------------------------------------------------------------
# InventorySwap
# ---------------------------------------------------------------------------

@bp.post("/api/inventory-swaps")
def create_swap():
    body = H.parse_body()
    subscription_id = H.req_str(body, "subscription_id")
    to_size_code = H.req_enum(body, "to_size_code", set(H.SIZES))
    uid, role = H.actor()
    H.require_role(role, {"Customer", "PlatformAdmin"})
    sub = db["subscriptions"].get(subscription_id)
    if role == "Customer":
        H.customer_owns_or_forbid(role, uid, H.chain_customer_id("subscriptions", sub))
    if sub is None:
        raise ApiError(errors.ERR_REFERENCE_NOT_FOUND, 404,
                       "Referenced subscription_id does not exist")
    if sub["service_status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE, 409,
                       "Subscription is not ACTIVE")
    from_idx = H.SIZES.index(sub["current_size_code"])
    to_idx = H.SIZES.index(to_size_code)
    if abs(to_idx - from_idx) != 1:
        raise ApiError(errors.ERR_SIZE_TRANSITION_INVALID, 422,
                       "Swap target must be exactly one size step from the current size")
    plan = db["subscription_plans"].get(sub["subscription_plan_id"])
    quantity = H.kit_item_count(plan)
    swap = new_resource({
        "subscription_id": subscription_id,
        "from_size_code": sub["current_size_code"],
        "to_size_code": to_size_code,
        "quantity": quantity,
        "returned_old_count": 0,
        "shortage_count": 0,
        "status": "REQUESTED",
    })
    db["inventory_swaps"][swap["id"]] = swap
    return ok(H.serialize("inventory_swaps", swap), 201)


@bp.get("/api/inventory-swaps")
def list_swaps():
    return H.do_list("inventory_swaps", [("subscription_id", request.args.get("subscription_id")),
                                         ("status", request.args.get("status"))])


@bp.get("/api/inventory-swaps/<swap_id>")
def get_swap(swap_id):
    return H.do_get_one("inventory_swaps", swap_id)


@bp.post("/api/inventory-swaps/<swap_id>/approve")
def approve_swap(swap_id):
    body = H.parse_body()
    expected_inventory_pool_version = H.req_int(body, "expected_inventory_pool_version")
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    swap = H.get_or_404("inventory_swaps", swap_id)
    if swap["status"] in H.SWAP_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Swap is in a terminal state")
    if swap["status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a REQUESTED swap can be approved")
    pool = H.pool_for_size(swap["to_size_code"])
    if pool is not None and expected_inventory_pool_version != pool["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_inventory_pool_version does not match the pool version")
    sub = db["subscriptions"].get(swap["subscription_id"])
    if sub is None or sub["service_status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE, 409,
                       "Subscription is not ACTIVE")
    if pool is None or H.available_units(pool) < swap["quantity"]:
        raise ApiError(errors.ERR_INVENTORY_SHORTFALL, 409,
                       "Target pool has insufficient available units")
    pool["on_hand_units"] -= swap["quantity"]
    pool["reserved_units"] += swap["quantity"]
    touch(pool)
    swap["status"] = "APPROVED"
    touch(swap)
    return ok(H.serialize("inventory_swaps", swap))


@bp.post("/api/inventory-swaps/<swap_id>/events")
def swap_event(swap_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.SWAP_EVENT_TYPES)
    returned_old_count = None
    if event_type == "COMPLETE":
        returned_old_count = H.req_int(body, "returned_old_count", lo=0)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin", "PlantOperator"})
    if event_type == "DENY" and role != "PlatformAdmin":
        raise ApiError(errors.ERR_FORBIDDEN, 403, "Only a PlatformAdmin may deny a swap")
    swap = H.get_or_404("inventory_swaps", swap_id)
    if swap["status"] in H.SWAP_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Swap is in a terminal state")

    if event_type == "STAGE":
        if swap["status"] != "APPROVED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an APPROVED swap can be staged")
        pool = H.pool_for_size(swap["to_size_code"])
        if pool is not None:
            pool["reserved_units"] -= swap["quantity"]
            pool["in_transit_units"] += swap["quantity"]
            touch(pool)
        swap["status"] = "STAGED"
        touch(swap)
    elif event_type == "COMPLETE":
        if swap["status"] != "STAGED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a STAGED swap can be completed")
        sub = db["subscriptions"].get(swap["subscription_id"])
        kit = H.kit_for_subscription(swap["subscription_id"])
        kit_count = kit["item_count"] if kit else 0
        if returned_old_count > kit_count:
            raise ApiError(errors.ERR_RETURN_COUNT_MISMATCH, 422,
                           "returned_old_count exceeds the starter kit item_count")
        to_pool = H.pool_for_size(swap["to_size_code"])
        from_pool = H.pool_for_size(swap["from_size_code"])
        if to_pool is not None:
            to_pool["in_transit_units"] -= swap["quantity"]
            to_pool["checked_out_units"] += swap["quantity"]
            touch(to_pool)
        shortage = max(0, kit_count - returned_old_count)
        if from_pool is not None:
            from_pool["checked_out_units"] -= returned_old_count
            from_pool["in_wash_units"] += returned_old_count
        if shortage > 0:
            first_issued = kit["created_at"][:10] if kit else clock_today().isoformat()
            H.auto_lost_case(swap["subscription_id"],
                             from_pool["id"] if from_pool is not None else None,
                             swap["from_size_code"], shortage, first_issued)
            if from_pool is not None:
                from_pool["checked_out_units"] -= shortage
                from_pool["lost_units"] += shortage
        if from_pool is not None:
            touch(from_pool)
        swap["returned_old_count"] = returned_old_count
        swap["shortage_count"] = shortage
        swap["status"] = "COMPLETED"
        touch(swap)
        if sub is not None:
            sub["current_size_code"] = swap["to_size_code"]
            touch(sub)
        if kit is not None:
            kit["size_code"] = swap["to_size_code"]
            kit["item_count"] = swap["quantity"]
            touch(kit)
    elif event_type == "DENY":
        if swap["status"] != "REQUESTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a REQUESTED swap can be denied")
        swap["status"] = "DENIED"
        touch(swap)
    elif event_type == "CANCEL":
        if swap["status"] == "REQUESTED":
            swap["status"] = "CANCELLED"
            touch(swap)
        elif swap["status"] == "APPROVED":
            pool = H.pool_for_size(swap["to_size_code"])
            if pool is not None:
                pool["reserved_units"] -= swap["quantity"]
                pool["on_hand_units"] += swap["quantity"]
                touch(pool)
            swap["status"] = "CANCELLED"
            touch(swap)
        else:
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a REQUESTED or APPROVED swap can be cancelled")
    return ok(H.serialize("inventory_swaps", swap))


# ---------------------------------------------------------------------------
# LostItemCase
# ---------------------------------------------------------------------------

@bp.post("/api/lost-item-cases")
def create_case():
    body = H.parse_body()
    subscription_id = H.req_str(body, "subscription_id")
    inventory_pool_id = H.req_str(body, "inventory_pool_id")
    case_type = H.req_enum(body, "case_type", {"LOST", "DAMAGED"})
    item_count = H.req_int(body, "item_count", lo=1)
    first_issued_date = H.req_date(body, "first_issued_date")
    assessed_fee_cents = None
    if case_type == "DAMAGED":
        assessed_fee_cents = H.req_int(body, "assessed_fee_cents", lo=0)
    elif "assessed_fee_cents" in body and body["assessed_fee_cents"] is not None:
        H.req_int(body, "assessed_fee_cents", lo=0)  # validate type if provided; ignored for LOST
    uid, role = H.actor()
    H.require_role(role, {"BillingAdmin", "PlantOperator", "PlatformAdmin"})
    H.ref_or_404("subscriptions", subscription_id)
    H.ref_or_404("inventory_pools", inventory_pool_id)
    case = new_resource({
        "subscription_id": subscription_id,
        "inventory_pool_id": inventory_pool_id,
        "case_type": case_type,
        "item_count": item_count,
        "first_issued_date": first_issued_date.isoformat(),
        "assessed_fee_cents": assessed_fee_cents,
        "charge_cents": None,
        "status": "OPEN",
        "_first_issued_date": first_issued_date,
    })
    db["lost_item_cases"][case["id"]] = case
    return ok(H.serialize("lost_item_cases", case), 201)


@bp.get("/api/lost-item-cases")
def list_cases():
    return H.do_list("lost_item_cases",
                     [("subscription_id", request.args.get("subscription_id")),
                      ("inventory_pool_id", request.args.get("inventory_pool_id")),
                      ("status", request.args.get("status"))])


@bp.get("/api/lost-item-cases/<case_id>")
def get_case(case_id):
    return H.do_get_one("lost_item_cases", case_id)


def _apply_case_charge(case):
    """Compute the charge and debit the customer deposit ledger (PRD §3.8)."""
    sub = db["subscriptions"].get(case["subscription_id"])
    customer = db["customers"].get(sub["customer_id"]) if sub else None
    charge = H.compute_case_charge(case, customer)
    if customer is None or customer["deposit_held_cents"] < charge:
        raise ApiError(errors.ERR_DEPOSIT_INSUFFICIENT, 402,
                       "deposit_held_cents does not cover the computed charge")
    case["charge_cents"] = charge
    customer["deposit_held_cents"] -= charge
    customer["deposit_applied_cents"] += charge
    touch(customer)


@bp.post("/api/lost-item-cases/<case_id>/events")
def case_event(case_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.CASE_EVENT_TYPES)
    uid, role = H.actor()
    H.require_role(role, {"BillingAdmin", "PlatformAdmin"})
    if event_type == "WAIVE" and role != "BillingAdmin":
        raise ApiError(errors.ERR_FORBIDDEN, 403, "Only a BillingAdmin may waive a case")
    case = H.get_or_404("lost_item_cases", case_id)
    if case["status"] in H.CASE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Case is in a terminal state")

    if event_type == "CHARGE":
        if case["status"] != "OPEN":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an OPEN case can be charged")
        sub = db["subscriptions"].get(case["subscription_id"])
        if sub is not None and sub["service_status"] == "TERMINATED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Subscription is TERMINATED")
        _apply_case_charge(case)
        case["status"] = "CHARGED"
        touch(case)
    elif event_type == "DISPUTE":
        if case["status"] not in ("OPEN", "CHARGED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only an OPEN or CHARGED case can be disputed")
        case["status"] = "DISPUTED"
        touch(case)
    elif event_type == "SETTLE":
        if case["status"] not in ("CHARGED", "DISPUTED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a CHARGED or DISPUTED case can be settled")
        if case["status"] == "DISPUTED" and case["charge_cents"] is None:
            # Disputed from OPEN and never charged: compute and apply the
            # charge exactly as a charge event would.
            _apply_case_charge(case)
        case["status"] = "SETTLED"
        touch(case)
    elif event_type == "WAIVE":
        if case["status"] not in ("OPEN", "DISPUTED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only an OPEN or DISPUTED case can be waived")
        if case["charge_cents"] is not None:
            # Previously charged: refund the applied charge (compensation keeps
            # the deposit ledger conserved).
            sub = db["subscriptions"].get(case["subscription_id"])
            customer = db["customers"].get(sub["customer_id"]) if sub else None
            if customer is not None:
                customer["deposit_held_cents"] += case["charge_cents"]
                customer["deposit_applied_cents"] -= case["charge_cents"]
                touch(customer)
        case["status"] = "WAIVED"
        touch(case)
    return ok(H.serialize("lost_item_cases", case))


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

@bp.post("/api/invoices/generate")
def generate_invoice():
    body = H.parse_body()
    subscription_id = H.req_str(body, "subscription_id")
    period_start = H.req_date(body, "period_start")
    period_end = H.req_date(body, "period_end")
    uid, role = H.actor()
    H.require_role(role, {"BillingAdmin", "PlatformAdmin"})
    sub = H.ref_or_404("subscriptions", subscription_id)
    if (period_end - period_start).days != 7:
        raise ApiError(errors.ERR_BILLING_CYCLE_CLOSED, 409,
                       "Invoice period must be exactly 7 days")
    for inv in db["invoices"].values():
        if inv["subscription_id"] != subscription_id or inv["status"] == "VOID":
            continue
        if period_start < inv["_period_end"] and inv["_period_start"] < period_end:
            raise ApiError(errors.ERR_BILLING_CYCLE_CLOSED, 409,
                           "Invoice period overlaps a non-VOID invoice of the subscription")
    lines = H.compute_invoice_lines(sub, period_start, period_end)
    invoice = new_resource({
        "subscription_id": subscription_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "status": "DRAFT",
        "base_fee_cents": lines["base_fee_cents"],
        "overage_cents": lines["overage_cents"],
        "pause_credit_cents": lines["pause_credit_cents"],
        "total_cents": lines["total_cents"],
        "issued_at": None,
        "_period_start": period_start,
        "_period_end": period_end,
    })
    db["invoices"][invoice["id"]] = invoice
    return ok(H.serialize("invoices", invoice), 201)


@bp.get("/api/invoices")
def list_invoices():
    return H.do_list("invoices", [("subscription_id", request.args.get("subscription_id")),
                                  ("status", request.args.get("status"))])


@bp.get("/api/invoices/<invoice_id>")
def get_invoice(invoice_id):
    return H.do_get_one("invoices", invoice_id)


def _set_billing_status(sub, value):
    if sub is not None and sub["billing_status"] != value:
        sub["billing_status"] = value
        touch(sub)


@bp.post("/api/invoices/<invoice_id>/events")
def invoice_event(invoice_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.INVOICE_EVENT_TYPES)
    uid, role = H.actor()
    H.require_role(role, {"BillingAdmin", "PlatformAdmin"})
    if event_type == "WRITE_OFF" and role != "BillingAdmin":
        raise ApiError(errors.ERR_FORBIDDEN, 403, "Only a BillingAdmin may write off an invoice")
    invoice = H.get_or_404("invoices", invoice_id)
    if invoice["status"] in H.INVOICE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Invoice is in a terminal state")
    sub = db["subscriptions"].get(invoice["subscription_id"])

    if event_type == "ISSUE":
        if invoice["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a DRAFT invoice can be issued")
        if sub is not None:
            lines = H.compute_invoice_lines(sub, invoice["_period_start"], invoice["_period_end"])
            invoice["base_fee_cents"] = lines["base_fee_cents"]
            invoice["overage_cents"] = lines["overage_cents"]
            invoice["pause_credit_cents"] = lines["pause_credit_cents"]
            invoice["total_cents"] = lines["total_cents"]
        invoice["issued_at"] = fmt_ts(clock_now())
        invoice["status"] = "ISSUED"
        touch(invoice)
    elif event_type == "REISSUE":
        if invoice["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an ISSUED invoice can be reissued")
        invoice["issued_at"] = None
        invoice["status"] = "DRAFT"
        touch(invoice)
    elif event_type == "PAY":
        if invoice["status"] not in ("ISSUED", "PAST_DUE"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only an ISSUED or PAST_DUE invoice can be paid")
        invoice["status"] = "PAID"
        touch(invoice)
        if sub is not None and sub["billing_status"] == "PAST_DUE":
            _set_billing_status(sub, "CURRENT")
    elif event_type == "MARK_PAST_DUE":
        if invoice["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only an ISSUED invoice can be marked past due")
        issued_dt = datetime.fromisoformat(invoice["issued_at"].replace("Z", "+00:00"))
        if not clock_now() >= issued_dt + timedelta(days=14):
            raise ApiError(errors.ERR_INVOICE_NOT_PAST_DUE, 422,
                           "Invoice is not yet 14 days past issuance")
        invoice["status"] = "PAST_DUE"
        touch(invoice)
        if sub is not None and sub["billing_status"] == "CURRENT":
            _set_billing_status(sub, "PAST_DUE")
    elif event_type == "VOID":
        if invoice["status"] not in ("DRAFT", "ISSUED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a DRAFT or ISSUED invoice can be voided")
        invoice["status"] = "VOID"
        touch(invoice)
    elif event_type == "WRITE_OFF":
        if invoice["status"] != "PAST_DUE":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Only a PAST_DUE invoice can be written off")
        invoice["status"] = "WRITTEN_OFF"
        touch(invoice)
    return ok(H.serialize("invoices", invoice))


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability, PRD §2.5)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    body = H.parse_body()
    to_iso8601 = H.req_str(body, "to_iso8601")
    target = H.parse_iso8601_to_utc(to_iso8601)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    set_clock(target)
    H.process_clock_cascades()
    return ok({"current_utc": fmt_ts_seconds(clock_now())})
