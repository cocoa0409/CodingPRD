"""Medical Courier & Specimen Logistics API — Flask entry point.

Implements PRD.md / SCAFFOLD.yaml. Storage is in-memory and starts EMPTY on
every boot: nothing is seeded, preloaded or hardcoded.
"""
import os
from functools import wraps

from flask import Flask, request, g

import calc as C
import serializers as S
import validate as V
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_VALIDATION,
    ERR_ROUTE_NOT_FOUND, ERR_STOP_NOT_FOUND, ERR_SPECIMEN_NOT_FOUND,
    ERR_DRIVER_NOT_FOUND, ERR_VEHICLE_NOT_FOUND, ERR_LAB_CLIENT_NOT_FOUND,
    ERR_RATE_CARD_NOT_FOUND, ERR_TEMPLATE_NOT_FOUND, ERR_EXCEPTION_NOT_FOUND,
    ERR_BILLING_NOT_FOUND, ERR_SCAN_EVENT_NOT_FOUND,
    ERR_ROUTE_INVALID_STATE, ERR_STOP_INVALID_STATE, ERR_SPECIMEN_INVALID_STATE,
    ERR_BILLING_INVALID_STATE, ERR_EXCEPTION_INVALID_STATE, ERR_DRIVER_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_DRIVER_CREDENTIAL_INVALID, ERR_CREDENTIAL_TYPE_INSUFFICIENT,
    ERR_VEHICLE_REFRIGERATION_REQUIRED, ERR_VEHICLE_NOT_AVAILABLE,
    ERR_DRIVER_SCHEDULE_CONFLICT, ERR_VEHICLE_BUFFER_CONFLICT,
    ERR_ROUTE_HAS_NO_STOPS, ERR_DUPLICATE_STOP_SEQUENCE,
    ERR_SPECIMEN_STOP_MISMATCH, ERR_STOPS_NOT_RESOLVED, ERR_BUDGET_EXCEEDED,
)
from response import object_response, array_response, error_response
from store import db, ROLES, now, new_record, new_lean_record, touch, parse_dt

from datetime import timedelta

app = Flask(__name__)
app.url_map.strict_slashes = False

API = "/med-courier"

DISPATCHER = "Dispatcher"
DRIVER = "Driver"
LAB_CLIENT = "LabClient"
COMPLIANCE = "ComplianceOfficer"


# =============================================================================
# Error handling
# =============================================================================

@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def _handle_uncaught(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)


# =============================================================================
# Auth / RBAC (PRD 2.1, 2.8 steps 1-2)
# =============================================================================

def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err(ERR_UNAUTHENTICATED,
                          "X-User-ID and a known X-User-Role header are required")
            if role not in allowed:
                raise err(ERR_UNAUTHORIZED,
                          "Role '%s' may not perform this operation" % role)
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def _forbidden():
    return err(ERR_UNAUTHORIZED, "Caller does not own this resource")


def assert_route_access(route):
    """Ownership gate for the two entity-backed roles (PRD 2.1)."""
    if g.role == LAB_CLIENT and route["lab_client_id"] != g.uid:
        raise _forbidden()
    if g.role == DRIVER and route["driver_id"] != g.uid:
        raise _forbidden()


def route_visible(route):
    if g.role == LAB_CLIENT:
        return route["lab_client_id"] == g.uid
    if g.role == DRIVER:
        return route["driver_id"] == g.uid
    return True


# =============================================================================
# Generic helpers
# =============================================================================

def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return b


def find(coll, rid, err_pair):
    rec = coll.get(rid)
    if rec is None:
        raise err(err_pair, "Referenced resource does not exist")
    return rec


def find_ref(coll, raw, err_pair):
    """Existence check (PRD 2.8 step 3) for a body-referenced id.

    A missing / non-string id is left to body validation (step 4) to reject.
    """
    if not isinstance(raw, str) or raw == "":
        return None
    return find(coll, raw, err_pair)


def ordered(records):
    """Default list ordering: created_at ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items):
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        offset = max(0, offset)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def list_response(records, serializer):
    page, limit, offset, total = paginate(ordered(records))
    return array_response([serializer(r) for r in page], limit, offset, total)


def q(name):
    return request.args.get(name)


def matches(rec, *pairs):
    for field, value in pairs:
        if value is not None and rec.get(field) != value:
            return False
    return True


# ---- domain lookups --------------------------------------------------------

def stops_of(route_id):
    return [s for s in db.stops.values() if s["route_id"] == route_id]


def specimens_of(route_id):
    return [s for s in db.specimens.values() if s["route_id"] == route_id]


def rate_card_of(route):
    return db.rate_cards[route["rate_card_id"]]


def open_exception(route_id, exception_type, detail, stop_id=None, specimen_id=None):
    exc = new_record({
        "route_id": route_id,
        "stop_id": stop_id,
        "specimen_id": specimen_id,
        "exception_type": exception_type,
        "detail": detail,
        "resolution_note": None,
        "status": "OPEN",
    })
    db.exceptions[exc["id"]] = exc
    return exc


def credential_valid(driver):
    return driver["status"] == "ACTIVE" and driver["credential_expiry"] > now()


# =============================================================================
# Logical clock (PRD 2.9)
# =============================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(DISPATCHER)
def clock_set():
    body = get_body()
    db.clock = V.req_dt(body, "to_iso8601")
    return object_response({}, 200)


# =============================================================================
# RateCard
# =============================================================================

@app.route(API + "/rate-cards", methods=["POST"])
@require_roles(DISPATCHER)
def create_rate_card():
    body = get_body()
    rec = new_record({
        "name": V.req_str(body, "name"),
        "per_stop_fee_cents": V.req_int_nn(body, "per_stop_fee_cents"),
        "per_mile_rate_cents": V.req_int_nn(body, "per_mile_rate_cents"),
        "stat_surcharge_pct": V.req_num_nn(body, "stat_surcharge_pct"),
        "stat_surcharge_cap_cents": V.req_int_nn(body, "stat_surcharge_cap_cents"),
        "temp_handling_fee_cents": V.req_int_nn(body, "temp_handling_fee_cents"),
    })
    db.rate_cards[rec["id"]] = rec
    return object_response(S.rate_card(rec), 201)


@app.route(API + "/rate-cards/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def get_rate_card(rid):
    return object_response(S.rate_card(find(db.rate_cards, rid, ERR_RATE_CARD_NOT_FOUND)))


# =============================================================================
# LabClient
# =============================================================================

@app.route(API + "/lab-clients", methods=["POST"])
@require_roles(DISPATCHER)
def create_lab_client():
    body = get_body()
    rec = new_record({
        "name": V.req_str(body, "name"),
        "budget_cents": V.req_int_nn(body, "budget_cents"),
        "contact": V.opt_str(body, "contact"),
        "billed_balance_cents": 0,
    })
    db.lab_clients[rec["id"]] = rec
    return object_response(S.lab_client(rec), 201)


@app.route(API + "/lab-clients/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def get_lab_client(rid):
    return object_response(S.lab_client(find(db.lab_clients, rid, ERR_LAB_CLIENT_NOT_FOUND)))


# =============================================================================
# Driver
# =============================================================================

@app.route(API + "/drivers", methods=["POST"])
@require_roles(DISPATCHER, COMPLIANCE)
def create_driver():
    body = get_body()
    rec = new_record({
        "name": V.req_str(body, "name"),
        "credential_type": V.req_enum(body, "credential_type", C.CREDENTIAL_TYPES),
        "credential_expiry": V.req_dt(body, "credential_expiry"),
        "status": "ACTIVE",
    })
    db.drivers[rec["id"]] = rec
    return object_response(S.driver(rec), 201)


@app.route(API + "/drivers/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE)
def get_driver(rid):
    return object_response(S.driver(find(db.drivers, rid, ERR_DRIVER_NOT_FOUND)))


@app.route(API + "/drivers/<rid>/credential", methods=["POST"])
@require_roles(COMPLIANCE)
def driver_credential(rid):
    driver = find(db.drivers, rid, ERR_DRIVER_NOT_FOUND)
    body = get_body()
    action = V.req_enum(body, "action", {"SUSPEND", "REINSTATE", "RENEW"})
    expiry = V.req_dt(body, "credential_expiry") if action == "RENEW" else None

    required = "SUSPENDED" if action == "REINSTATE" else "ACTIVE"
    if driver["status"] != required:
        raise err(ERR_DRIVER_INVALID_STATE,
                  "Driver is %s; action %s requires %s" % (driver["status"], action, required))

    if action == "SUSPEND":
        driver["status"] = "SUSPENDED"
    elif action == "REINSTATE":
        driver["status"] = "ACTIVE"
    else:
        driver["credential_expiry"] = expiry
    touch(driver)
    return object_response(S.driver(driver), 200)


# =============================================================================
# Vehicle
# =============================================================================

@app.route(API + "/vehicles", methods=["POST"])
@require_roles(DISPATCHER)
def create_vehicle():
    body = get_body()
    buffer_minutes = V.opt_int(body, "sanitation_buffer_minutes", 30)
    V.non_negative(buffer_minutes, "sanitation_buffer_minutes")
    rec = new_record({
        "plate": V.req_str(body, "plate"),
        "has_refrigeration": V.req_bool(body, "has_refrigeration"),
        "sanitation_buffer_minutes": buffer_minutes,
        "status": "AVAILABLE",
        "last_released_at": None,
    })
    db.vehicles[rec["id"]] = rec
    return object_response(S.vehicle(rec), 201)


@app.route(API + "/vehicles/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE)
def get_vehicle(rid):
    return object_response(S.vehicle(find(db.vehicles, rid, ERR_VEHICLE_NOT_FOUND)))


# =============================================================================
# RouteTemplate
# =============================================================================

def _validate_stop_specs(body):
    raw = V.req(body, "stop_specs")
    if not isinstance(raw, list):
        raise err(ERR_VALIDATION, "Field 'stop_specs' must be an array")
    specs = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err(ERR_VALIDATION, "Each stop_specs entry must be an object")
        specs.append({
            "sequence": V.at_least(V.req_int(entry, "sequence"), "sequence", 1),
            "address": V.req_str(entry, "address"),
            "stop_kind": V.req_enum(entry, "stop_kind", C.STOP_KINDS),
            "planned_leg_miles": V.req_num_nn(entry, "planned_leg_miles"),
        })
    return specs


@app.route(API + "/route-templates", methods=["POST"])
@require_roles(DISPATCHER)
def create_route_template():
    body = get_body()
    find_ref(db.lab_clients, body.get("lab_client_id"), ERR_LAB_CLIENT_NOT_FOUND)
    find_ref(db.rate_cards, body.get("rate_card_id"), ERR_RATE_CARD_NOT_FOUND)
    rec = new_record({
        "lab_client_id": V.req_str(body, "lab_client_id"),
        "rate_card_id": V.req_str(body, "rate_card_id"),
        "cadence": V.req_enum(body, "cadence", C.CADENCES),
        "default_run_type": V.req_enum(body, "default_run_type", C.RUN_TYPES),
        "stop_specs": _validate_stop_specs(body),
    })
    db.route_templates[rec["id"]] = rec
    return object_response(S.route_template(rec), 201)


@app.route(API + "/route-templates", methods=["GET"])
@require_roles(DISPATCHER, LAB_CLIENT)
def list_route_templates():
    items = [
        t for t in db.route_templates.values()
        if matches(t, ("lab_client_id", q("lab_client_id")), ("rate_card_id", q("rate_card_id")))
        and (g.role != LAB_CLIENT or t["lab_client_id"] == g.uid)
    ]
    return list_response(items, S.route_template)


@app.route(API + "/route-templates/<rid>", methods=["GET"])
@require_roles(DISPATCHER, LAB_CLIENT)
def get_route_template(rid):
    tmpl = find(db.route_templates, rid, ERR_TEMPLATE_NOT_FOUND)
    if g.role == LAB_CLIENT and tmpl["lab_client_id"] != g.uid:
        raise _forbidden()
    return object_response(S.route_template(tmpl))


def _make_route(lab_client_id, rate_card_id, template_id, run_type,
                scheduled_start, scheduled_end, planned_total_miles):
    rec = new_record({
        "lab_client_id": lab_client_id,
        "rate_card_id": rate_card_id,
        "template_id": template_id,
        "driver_id": None,
        "vehicle_id": None,
        "run_type": run_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "planned_total_miles": planned_total_miles,
        "sla_deadline": C.sla_deadline(scheduled_start, run_type),
        "provisional_charge_cents": None,
        "final_charge_cents": None,
        "status": "PLANNED",
        # internal: final base / surcharge split, snapshotted onto the billing
        "_final_gross_cents": None,
        "_final_surcharge_cents": None,
    })
    db.routes[rec["id"]] = rec
    return rec


def _make_stop(route_id, sequence, address, stop_kind, planned_leg_miles):
    rec = new_record({
        "route_id": route_id,
        "sequence": sequence,
        "address": address,
        "stop_kind": stop_kind,
        "planned_leg_miles": planned_leg_miles,
        "actual_leg_miles": None,
        "leg_charge_cents": None,
        "arrived_at": None,
        "completed_at": None,
        "status": "SCHEDULED",
    })
    db.stops[rec["id"]] = rec
    return rec


@app.route(API + "/route-templates/<rid>/generate-route", methods=["POST"])
@require_roles(DISPATCHER)
def generate_route(rid):
    tmpl = find(db.route_templates, rid, ERR_TEMPLATE_NOT_FOUND)
    body = get_body()
    start = V.req_dt(body, "scheduled_start")
    end = V.req_dt(body, "scheduled_end")
    if end <= start:
        raise err(ERR_VALIDATION, "scheduled_end must be later than scheduled_start")
    run_type = V.opt_enum(body, "run_type", C.RUN_TYPES, tmpl["default_run_type"])

    planned_total_miles = sum(spec["planned_leg_miles"] for spec in tmpl["stop_specs"])
    route = _make_route(tmpl["lab_client_id"], tmpl["rate_card_id"], tmpl["id"],
                        run_type, start, end, planned_total_miles)
    for spec in tmpl["stop_specs"]:
        _make_stop(route["id"], spec["sequence"], spec["address"],
                   spec["stop_kind"], spec["planned_leg_miles"])
    return object_response(S.route(route), 201)


# =============================================================================
# Route — creation, manifest, listing
# =============================================================================

@app.route(API + "/routes", methods=["POST"])
@require_roles(DISPATCHER, LAB_CLIENT)
def create_route():
    body = get_body()
    raw_lab = body.get("lab_client_id")
    # Ownership (step 2) precedes existence (step 3): a lab may only build its own.
    if g.role == LAB_CLIENT and isinstance(raw_lab, str) and raw_lab != g.uid:
        raise _forbidden()
    find_ref(db.lab_clients, raw_lab, ERR_LAB_CLIENT_NOT_FOUND)
    find_ref(db.rate_cards, body.get("rate_card_id"), ERR_RATE_CARD_NOT_FOUND)

    lab_client_id = V.req_str(body, "lab_client_id")
    rate_card_id = V.req_str(body, "rate_card_id")
    run_type = V.req_enum(body, "run_type", C.RUN_TYPES)
    start = V.req_dt(body, "scheduled_start")
    end = V.req_dt(body, "scheduled_end")
    if end <= start:
        raise err(ERR_VALIDATION, "scheduled_end must be later than scheduled_start")
    miles = V.req_num_nn(body, "planned_total_miles")

    route = _make_route(lab_client_id, rate_card_id, None, run_type, start, end, miles)
    return object_response(S.route(route), 201)


@app.route(API + "/routes", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def list_routes():
    items = [
        r for r in db.routes.values()
        if matches(r,
                   ("lab_client_id", q("lab_client_id")),
                   ("rate_card_id", q("rate_card_id")),
                   ("template_id", q("template_id")),
                   ("driver_id", q("driver_id")),
                   ("vehicle_id", q("vehicle_id")),
                   ("status", q("status")))
        and route_visible(r)
    ]
    return list_response(items, S.route)


@app.route(API + "/routes/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def get_route(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    assert_route_access(route)
    return object_response(S.route(route))


@app.route(API + "/routes/<rid>/stops", methods=["POST"])
@require_roles(DISPATCHER, LAB_CLIENT)
def add_stop(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    assert_route_access(route)
    body = get_body()
    sequence = V.at_least(V.req_int(body, "sequence"), "sequence", 1)
    address = V.req_str(body, "address")
    stop_kind = V.req_enum(body, "stop_kind", C.STOP_KINDS)
    miles = V.req_num_nn(body, "planned_leg_miles")

    if route["status"] != "PLANNED":
        raise err(ERR_ROUTE_INVALID_STATE, "Stops may only be attached to a PLANNED route")
    if any(s["sequence"] == sequence for s in stops_of(route["id"])):
        raise err(ERR_DUPLICATE_STOP_SEQUENCE,
                  "Sequence %s is already used on this route" % sequence)

    stop = _make_stop(route["id"], sequence, address, stop_kind, miles)
    return object_response(S.stop(stop), 201)


@app.route(API + "/routes/<rid>/specimens", methods=["POST"])
@require_roles(DISPATCHER, LAB_CLIENT)
def add_specimen(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    assert_route_access(route)
    body = get_body()

    pickup = find_ref(db.stops, body.get("pickup_stop_id"), ERR_STOP_NOT_FOUND)
    dropoff = find_ref(db.stops, body.get("dropoff_stop_id"), ERR_STOP_NOT_FOUND)
    for st in (pickup, dropoff):
        if st is not None and st["route_id"] != route["id"]:
            raise err(ERR_STOP_NOT_FOUND, "Stop does not belong to this route")

    pickup_stop_id = V.req_str(body, "pickup_stop_id")
    dropoff_stop_id = V.req_str(body, "dropoff_stop_id")
    specimen_type = V.req_enum(body, "specimen_type", C.SPECIMEN_TYPES)
    temp_requirement = V.req_enum(body, "temp_requirement", C.TEMP_REQUIREMENTS)
    tmin = V.req_num(body, "required_temp_min_c")
    tmax = V.req_num(body, "required_temp_max_c")
    if tmax < tmin:
        raise err(ERR_VALIDATION,
                  "required_temp_max_c must be >= required_temp_min_c")

    if route["status"] != "PLANNED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Specimens may only be attached to a PLANNED route")

    rec = new_record({
        "route_id": route["id"],
        "pickup_stop_id": pickup_stop_id,
        "dropoff_stop_id": dropoff_stop_id,
        "specimen_type": specimen_type,
        "temp_requirement": temp_requirement,
        "required_temp_min_c": tmin,
        "required_temp_max_c": tmax,
        "custody_status": "AWAITING_PICKUP",
        "integrity_status": "INTACT",
        "excursion_count": 0,
        "picked_up_at": None,
        "delivered_at": None,
        "estimated_risk_score": None,
        "final_risk_score": None,
    })
    db.specimens[rec["id"]] = rec
    return object_response(S.specimen(rec), 201)


# =============================================================================
# Route lifecycle — assign / unassign / dispatch / complete (PRD 3.3, 3.4, 3.7)
# =============================================================================

def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end): adjacency (end == start) is not an overlap."""
    return a_start < b_end and b_start < a_end


@app.route(API + "/routes/<rid>/assign", methods=["POST"])
@require_roles(DISPATCHER)
def assign_route(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    body = get_body()
    find_ref(db.drivers, body.get("driver_id"), ERR_DRIVER_NOT_FOUND)
    find_ref(db.vehicles, body.get("vehicle_id"), ERR_VEHICLE_NOT_FOUND)
    driver = db.drivers[V.req_str(body, "driver_id")]
    vehicle = db.vehicles[V.req_str(body, "vehicle_id")]

    if route["status"] != "PLANNED":
        raise err(ERR_ROUTE_INVALID_STATE, "Route is %s; assign requires PLANNED" % route["status"])

    # tier-7 checks, in the precedence order of PRD 2.8
    if not credential_valid(driver):
        raise err(ERR_DRIVER_CREDENTIAL_INVALID, "Driver credential is not valid")
    if vehicle["status"] != "AVAILABLE":
        raise err(ERR_VEHICLE_NOT_AVAILABLE, "Vehicle is %s" % vehicle["status"])
    for other in db.routes.values():
        if other["id"] == route["id"]:
            continue
        if other["driver_id"] != driver["id"]:
            continue
        if other["status"] not in ("ASSIGNED", "DISPATCHED"):
            continue
        if _windows_overlap(route["scheduled_start"], route["scheduled_end"],
                            other["scheduled_start"], other["scheduled_end"]):
            raise err(ERR_DRIVER_SCHEDULE_CONFLICT,
                      "Driver already holds an overlapping route window")
    released = vehicle["last_released_at"]
    if released is not None:
        gap = released + timedelta(minutes=vehicle["sanitation_buffer_minutes"])
        if route["scheduled_start"] < gap:
            raise err(ERR_VEHICLE_BUFFER_CONFLICT,
                      "Route starts inside the vehicle sanitation buffer")

    route["driver_id"] = driver["id"]
    route["vehicle_id"] = vehicle["id"]
    route["status"] = "ASSIGNED"
    touch(route)
    vehicle["status"] = "IN_USE"
    touch(vehicle)
    return object_response(S.route(route), 200)


@app.route(API + "/routes/<rid>/unassign", methods=["POST"])
@require_roles(DISPATCHER)
def unassign_route(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    if route["status"] != "ASSIGNED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; unassign requires ASSIGNED" % route["status"])

    vehicle = db.vehicles.get(route["vehicle_id"])
    route["driver_id"] = None
    route["vehicle_id"] = None
    route["status"] = "PLANNED"
    touch(route)
    if vehicle is not None:
        # The run never executed: last_released_at is deliberately left unchanged.
        vehicle["status"] = "AVAILABLE"
        touch(vehicle)
    return object_response(S.route(route), 200)


@app.route(API + "/routes/<rid>/dispatch", methods=["POST"])
@require_roles(DISPATCHER)
def dispatch_route(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    if route["status"] != "ASSIGNED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; dispatch requires ASSIGNED" % route["status"])

    driver = db.drivers[route["driver_id"]]
    vehicle = db.vehicles[route["vehicle_id"]]
    stops = stops_of(route["id"])
    specimens = specimens_of(route["id"])
    rate_card = rate_card_of(route)
    lab = db.lab_clients[route["lab_client_id"]]

    # tier-7 checks, in the precedence order of PRD 2.8
    if not credential_valid(driver):
        raise err(ERR_DRIVER_CREDENTIAL_INVALID, "Driver credential is not valid")
    if not C.credential_sufficient(driver["credential_type"], specimens):
        raise err(ERR_CREDENTIAL_TYPE_INSUFFICIENT,
                  "Driver credential type is insufficient for the manifest")
    if not vehicle["has_refrigeration"] and any(
            s["temp_requirement"] in ("REFRIGERATED", "FROZEN") for s in specimens):
        raise err(ERR_VEHICLE_REFRIGERATION_REQUIRED,
                  "Vehicle lacks refrigeration for a temperature-controlled specimen")
    if not stops:
        raise err(ERR_ROUTE_HAS_NO_STOPS, "Route carries no stops")

    provisional = C.provisional_charge(route, rate_card, stops, specimens)
    if lab["billed_balance_cents"] + provisional > lab["budget_cents"]:
        raise err(ERR_BUDGET_EXCEEDED, "Provisional charge exceeds the laboratory budget")

    route["provisional_charge_cents"] = provisional
    route["status"] = "DISPATCHED"
    touch(route)
    return object_response(S.route(route), 200)


@app.route(API + "/routes/<rid>/complete", methods=["POST"])
@require_roles(DISPATCHER)
def complete_route(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    if route["status"] != "DISPATCHED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; complete requires DISPATCHED" % route["status"])

    stops = stops_of(route["id"])
    if any(s["status"] not in ("COMPLETED", "MISSED") for s in stops):
        raise err(ERR_STOPS_NOT_RESOLVED, "Every stop must be COMPLETED or MISSED")

    gross, surcharge, net = C.final_charge(
        route, rate_card_of(route), stops, specimens_of(route["id"]))
    route["_final_gross_cents"] = gross
    route["_final_surcharge_cents"] = surcharge
    route["final_charge_cents"] = net
    route["status"] = "COMPLETED"
    touch(route)

    vehicle = db.vehicles.get(route["vehicle_id"])
    if vehicle is not None:
        vehicle["status"] = "AVAILABLE"
        vehicle["last_released_at"] = now()
        touch(vehicle)
    return object_response(S.route(route), 200)


# =============================================================================
# Stops — read, scan, miss, reschedule (PRD 3.5, 3.6)
# =============================================================================

@app.route(API + "/stops", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def list_stops():
    items = [
        s for s in db.stops.values()
        if matches(s, ("route_id", q("route_id")), ("status", q("status")))
        and route_visible(db.routes[s["route_id"]])
    ]
    return list_response(items, S.stop)


@app.route(API + "/stops/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def get_stop(rid):
    stop = find(db.stops, rid, ERR_STOP_NOT_FOUND)
    assert_route_access(db.routes[stop["route_id"]])
    return object_response(S.stop(stop))


def _bubble_up_stops(route):
    """A stop in ARRIVED completes once every specimen it pickups has left
    AWAITING_PICKUP and every specimen it drops off has reached DELIVERED."""
    rate_card = rate_card_of(route)
    specimens = specimens_of(route["id"])
    for stop in stops_of(route["id"]):
        if stop["status"] != "ARRIVED":
            continue
        pickups_ready = all(
            sp["custody_status"] != "AWAITING_PICKUP"
            for sp in specimens if sp["pickup_stop_id"] == stop["id"]
        )
        dropoffs_ready = all(
            sp["custody_status"] == "DELIVERED"
            for sp in specimens if sp["dropoff_stop_id"] == stop["id"]
        )
        if pickups_ready and dropoffs_ready:
            stop["status"] = "COMPLETED"
            stop["completed_at"] = now()
            stop["leg_charge_cents"] = C.leg_charge(stop["actual_leg_miles"], rate_card)
            touch(stop)


@app.route(API + "/stops/<rid>/scan", methods=["POST"])
@require_roles(DRIVER)
def scan_stop(rid):
    stop = find(db.stops, rid, ERR_STOP_NOT_FOUND)
    route = db.routes[stop["route_id"]]
    # Only the assigned driver executes the run (PRD 3.5).
    if route["driver_id"] != g.uid:
        raise _forbidden()

    body = get_body()
    specimen = find_ref(db.specimens, body.get("specimen_id"), ERR_SPECIMEN_NOT_FOUND)

    V.req_str(body, "specimen_id")
    scan_type = V.req_enum(body, "scan_type", {"PICKUP", "DROPOFF"})
    temp_reading = V.req_num(body, "temp_reading_c")
    leg_miles = V.req_num_nn(body, "leg_miles")

    if route["status"] != "DISPATCHED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; scans require DISPATCHED" % route["status"])

    if scan_type == "PICKUP":
        if specimen["custody_status"] != "AWAITING_PICKUP":
            raise err(ERR_SPECIMEN_INVALID_STATE,
                      "Specimen custody is %s; pickup requires AWAITING_PICKUP"
                      % specimen["custody_status"])
        if specimen["pickup_stop_id"] != stop["id"]:
            raise err(ERR_SPECIMEN_STOP_MISMATCH,
                      "This stop is not the specimen's pickup stop")
    else:
        if specimen["custody_status"] != "IN_TRANSIT":
            raise err(ERR_SPECIMEN_INVALID_STATE,
                      "Specimen custody is %s; dropoff requires IN_TRANSIT"
                      % specimen["custody_status"])
        if specimen["dropoff_stop_id"] != stop["id"]:
            raise err(ERR_SPECIMEN_STOP_MISMATCH,
                      "This stop is not the specimen's dropoff stop")

    clock = now()
    excursion = C.is_excursion(temp_reading, specimen)

    # --- Stop: first scan drives SCHEDULED -> ARRIVED --------------------
    if stop["status"] == "SCHEDULED":
        stop["status"] = "ARRIVED"
        stop["arrived_at"] = clock
        stop["actual_leg_miles"] = leg_miles
        touch(stop)

    # --- ScanEvent: append-only chain-of-custody record -------------------
    event = new_lean_record({
        "specimen_id": specimen["id"],
        "driver_id": g.uid,
        "stop_id": stop["id"],
        "scan_type": scan_type,
        "temp_reading_c": temp_reading,
        "leg_miles": leg_miles,
        "scanned_at": clock,
        "is_excursion": excursion,
    })
    db.scan_events[event["id"]] = event

    # --- Specimen: custody dimension -------------------------------------
    if scan_type == "PICKUP":
        specimen["custody_status"] = "IN_TRANSIT"
        specimen["picked_up_at"] = clock
        specimen["estimated_risk_score"] = C.estimated_risk(specimen, route)
    else:
        specimen["custody_status"] = "DELIVERED"
        specimen["delivered_at"] = clock
        # Risk is scored before this scan's excursion is folded in (SCAFFOLD 1.2).
        specimen["final_risk_score"] = C.final_risk(specimen)

    # --- Specimen: integrity dimension (independent of custody) ------------
    if excursion:
        specimen["integrity_status"] = "COMPROMISED"
        specimen["excursion_count"] += 1
        open_exception(
            route["id"], "TEMP_EXCURSION",
            "Temperature reading %s C breached the band [%s, %s] at stop %s" % (
                temp_reading, specimen["required_temp_min_c"],
                specimen["required_temp_max_c"], stop["sequence"]),
            stop_id=stop["id"], specimen_id=specimen["id"],
        )
    touch(specimen)

    # --- Cascade: re-evaluate stop completion ------------------------------
    _bubble_up_stops(route)

    return object_response(S.scan_event(event), 201)


@app.route(API + "/stops/<rid>/miss", methods=["POST"])
@require_roles(DRIVER, DISPATCHER)
def miss_stop(rid):
    stop = find(db.stops, rid, ERR_STOP_NOT_FOUND)
    route = db.routes[stop["route_id"]]
    assert_route_access(route)

    if route["status"] != "DISPATCHED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; a stop may only be missed while DISPATCHED" % route["status"])
    if stop["status"] not in ("SCHEDULED", "ARRIVED"):
        raise err(ERR_STOP_INVALID_STATE,
                  "Stop is %s; miss requires SCHEDULED or ARRIVED" % stop["status"])

    stop["status"] = "MISSED"
    touch(stop)

    # CASCADE link 1: implicated specimens move to custody EXCEPTION.
    implicated = [
        sp for sp in specimens_of(route["id"])
        if (sp["pickup_stop_id"] == stop["id"] or sp["dropoff_stop_id"] == stop["id"])
        and sp["custody_status"] in ("AWAITING_PICKUP", "IN_TRANSIT")
    ]
    implicated.sort(key=lambda sp: (sp["created_at"], sp["_seq"]))

    # CASCADE link 2: each implicated specimen opens one MISSED_STOP exception.
    for sp in implicated:
        sp["custody_status"] = "EXCEPTION"
        touch(sp)
        open_exception(
            route["id"], "MISSED_STOP",
            "Stop %s (%s) was missed; specimen %s removed from the deliverable set"
            % (stop["sequence"], stop["address"], sp["id"]),
            stop_id=stop["id"], specimen_id=sp["id"],
        )
    if not implicated:
        open_exception(
            route["id"], "MISSED_STOP",
            "Stop %s (%s) was missed; no specimens were implicated"
            % (stop["sequence"], stop["address"]),
            stop_id=stop["id"], specimen_id=None,
        )
    return object_response(S.stop(stop), 200)


@app.route(API + "/stops/<rid>/reschedule", methods=["POST"])
@require_roles(DISPATCHER)
def reschedule_stop(rid):
    stop = find(db.stops, rid, ERR_STOP_NOT_FOUND)
    if stop["status"] != "MISSED":
        raise err(ERR_STOP_INVALID_STATE,
                  "Stop is %s; reschedule requires MISSED" % stop["status"])
    stop["status"] = "SCHEDULED"
    stop["arrived_at"] = None
    touch(stop)
    return object_response(S.stop(stop), 200)


# =============================================================================
# Specimens / ScanEvents (reads)
# =============================================================================

@app.route(API + "/specimens", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def list_specimens():
    items = [
        s for s in db.specimens.values()
        if matches(s,
                   ("route_id", q("route_id")),
                   ("pickup_stop_id", q("pickup_stop_id")),
                   ("dropoff_stop_id", q("dropoff_stop_id")),
                   ("custody_status", q("custody_status")))
        and route_visible(db.routes[s["route_id"]])
    ]
    return list_response(items, S.specimen)


@app.route(API + "/specimens/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def get_specimen(rid):
    sp = find(db.specimens, rid, ERR_SPECIMEN_NOT_FOUND)
    assert_route_access(db.routes[sp["route_id"]])
    return object_response(S.specimen(sp))


def _route_of_scan(event):
    return db.routes[db.stops[event["stop_id"]]["route_id"]]


@app.route(API + "/scan-events", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def list_scan_events():
    items = [
        e for e in db.scan_events.values()
        if matches(e,
                   ("specimen_id", q("specimen_id")),
                   ("driver_id", q("driver_id")),
                   ("stop_id", q("stop_id")))
        and route_visible(_route_of_scan(e))
    ]
    return list_response(items, S.scan_event)


@app.route(API + "/scan-events/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT, DRIVER)
def get_scan_event(rid):
    event = find(db.scan_events, rid, ERR_SCAN_EVENT_NOT_FOUND)
    assert_route_access(_route_of_scan(event))
    return object_response(S.scan_event(event))


# =============================================================================
# RouteExceptions
# =============================================================================

@app.route(API + "/exceptions", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def list_exceptions():
    items = [
        e for e in db.exceptions.values()
        if matches(e,
                   ("route_id", q("route_id")),
                   ("stop_id", q("stop_id")),
                   ("specimen_id", q("specimen_id")),
                   ("status", q("status")))
        and route_visible(db.routes[e["route_id"]])
    ]
    return list_response(items, S.route_exception)


@app.route(API + "/exceptions/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def get_exception(rid):
    exc = find(db.exceptions, rid, ERR_EXCEPTION_NOT_FOUND)
    assert_route_access(db.routes[exc["route_id"]])
    return object_response(S.route_exception(exc))


@app.route(API + "/exceptions/<rid>/resolve", methods=["POST"])
@require_roles(COMPLIANCE)
def resolve_exception(rid):
    exc = find(db.exceptions, rid, ERR_EXCEPTION_NOT_FOUND)
    body = get_body()
    note = V.opt_str(body, "resolution_note")
    if exc["status"] != "OPEN":
        raise err(ERR_EXCEPTION_INVALID_STATE,
                  "Exception is %s; resolve requires OPEN" % exc["status"])
    exc["status"] = "RESOLVED"
    exc["resolution_note"] = note
    touch(exc)
    return object_response(S.route_exception(exc), 200)


# =============================================================================
# RunBilling (PRD 2.7, 3.8)
# =============================================================================

@app.route(API + "/routes/<rid>/billing", methods=["POST"])
@require_roles(DISPATCHER)
def create_billing(rid):
    route = find(db.routes, rid, ERR_ROUTE_NOT_FOUND)
    body = get_body()
    expected = V.req_int(body, "expected_route_version")

    if route["status"] != "COMPLETED":
        raise err(ERR_ROUTE_INVALID_STATE,
                  "Route is %s; billing requires COMPLETED" % route["status"])
    if expected != route["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_route_version %s does not match route version %s"
                  % (expected, route["version"]))

    rec = new_record({
        "route_id": route["id"],
        "lab_client_id": route["lab_client_id"],
        "gross_charge_cents": route["_final_gross_cents"],
        "surcharge_cents": route["_final_surcharge_cents"],
        "net_charge_cents": route["final_charge_cents"],
        "status": "DRAFT",
    })
    db.billings[rec["id"]] = rec
    # Generating a billing supersedes any earlier draft and advances route.version.
    touch(route)
    return object_response(S.run_billing(rec), 201)


@app.route(API + "/billings", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def list_billings():
    items = [
        b for b in db.billings.values()
        if matches(b,
                   ("route_id", q("route_id")),
                   ("lab_client_id", q("lab_client_id")),
                   ("status", q("status")))
        and (g.role != LAB_CLIENT or b["lab_client_id"] == g.uid)
    ]
    return list_response(items, S.run_billing)


@app.route(API + "/billings/<rid>", methods=["GET"])
@require_roles(DISPATCHER, COMPLIANCE, LAB_CLIENT)
def get_billing(rid):
    bill = find(db.billings, rid, ERR_BILLING_NOT_FOUND)
    if g.role == LAB_CLIENT and bill["lab_client_id"] != g.uid:
        raise _forbidden()
    return object_response(S.run_billing(bill))


@app.route(API + "/billings/<rid>/issue", methods=["POST"])
@require_roles(DISPATCHER)
def issue_billing(rid):
    bill = find(db.billings, rid, ERR_BILLING_NOT_FOUND)
    if bill["status"] != "DRAFT":
        raise err(ERR_BILLING_INVALID_STATE,
                  "Billing is %s; issue requires DRAFT" % bill["status"])

    lab = db.lab_clients[bill["lab_client_id"]]
    if lab["billed_balance_cents"] + bill["net_charge_cents"] > lab["budget_cents"]:
        raise err(ERR_BUDGET_EXCEEDED, "Net charge exceeds the laboratory budget")

    lab["billed_balance_cents"] += bill["net_charge_cents"]
    touch(lab)
    bill["status"] = "ISSUED"
    touch(bill)
    return object_response(S.run_billing(bill), 200)


@app.route(API + "/billings/<rid>/void", methods=["POST"])
@require_roles(DISPATCHER)
def void_billing(rid):
    bill = find(db.billings, rid, ERR_BILLING_NOT_FOUND)
    if bill["status"] != "ISSUED":
        raise err(ERR_BILLING_INVALID_STATE,
                  "Billing is %s; void requires ISSUED" % bill["status"])

    lab = db.lab_clients[bill["lab_client_id"]]
    lab["billed_balance_cents"] -= bill["net_charge_cents"]
    touch(lab)
    bill["status"] = "VOIDED"
    touch(bill)
    return object_response(S.run_billing(bill), 200)


# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
