"""UnitAssignment endpoints + temporal overlap checks (PRD §3.2)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_CREW_CERT_INSUFFICIENT,
    ERR_CREW_DOUBLE_BOOKED,
    ERR_INVALID_WINDOW,
    ERR_RESOURCE_OUT_OF_SERVICE,
    ERR_VEHICLE_DOUBLE_BOOKED,
    err,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
)
from services.serialize import serialize, serialize_list
from services.timeutil import add_minutes, parse_iso

bp = Blueprint("unit_assignments", __name__)

# Certification coverage: which LOS codes each certification may serve.
CERT_COVERAGE = {
    "EMT": {"BLS"},
    "AEMT": {"BLS", "ALS1"},
    "PARAMEDIC": {"BLS", "ALS1", "ALS2", "SCT"},
}


@bp.route("/unit-assignments", methods=["POST"])
def create_unit_assignment():
    principal = authenticate()
    require_role(principal, ["Dispatcher"])
    body = get_json_body()

    # priority 4: body FK existence
    if body.get("transport_id") is not None:
        transport = resolve_fk(store.transports, body["transport_id"])
    else:
        transport = None
    if body.get("vehicle_id") is not None:
        vehicle = resolve_fk(store.vehicles, body["vehicle_id"])
    else:
        vehicle = None
    if body.get("crew_member_id") is not None:
        crew = resolve_fk(store.crew_members, body["crew_member_id"])
    else:
        crew = None

    # priority 5: required fields
    require_fields(
        body,
        ["transport_id", "vehicle_id", "crew_member_id", "window_start_iso", "window_end_iso"],
    )

    # priority 27: window_end strictly after window_start
    start = parse_iso(body["window_start_iso"], "window_start_iso")
    end = parse_iso(body["window_end_iso"], "window_end_iso")
    if end <= start:
        raise err(ERR_INVALID_WINDOW, "window_end_iso must be strictly after window_start_iso")

    # priority 28: vehicle IN_SERVICE and crew ACTIVE
    if vehicle["status"] != "IN_SERVICE" or crew["status"] != "ACTIVE":
        raise err(ERR_RESOURCE_OUT_OF_SERVICE, "Assigned vehicle or crew member is unavailable")

    # priority 29: crew certification covers coded LOS (only when transport CODED)
    los = transport.get("level_of_service")
    if los is not None:
        coverage = CERT_COVERAGE.get(crew["certification"], set())
        if los not in coverage:
            raise err(ERR_CREW_CERT_INSUFFICIENT, "Crew certification does not cover the coded level of service")

    # priority 30: vehicle overlap — CLOSED interval + turnaround buffer, touch counts.
    turnaround = vehicle.get("turnaround_minutes", 30)
    cand_v_start = start
    cand_v_end = add_minutes(end, turnaround)
    for ua in store.unit_assignments.values():
        if ua["vehicle_id"] != vehicle["id"]:
            continue
        ex_start = parse_iso(ua["window_start_iso"], "window_start_iso")
        ex_end = add_minutes(parse_iso(ua["window_end_iso"], "window_end_iso"), turnaround)
        # closed intervals intersect iff a1 <= b2 and a2 <= b1 (touch counts)
        if cand_v_start <= ex_end and ex_start <= cand_v_end:
            raise err(ERR_VEHICLE_DOUBLE_BOOKED, "Vehicle is double-booked")

    # priority 31: crew overlap — HALF-OPEN interval [start, end), no buffer.
    for ua in store.unit_assignments.values():
        if ua["crew_member_id"] != crew["id"]:
            continue
        ex_start = parse_iso(ua["window_start_iso"], "window_start_iso")
        ex_end = parse_iso(ua["window_end_iso"], "window_end_iso")
        # half-open intervals intersect iff a1 < b2 and a2 < b1 (touch allowed)
        if start < ex_end and ex_start < end:
            raise err(ERR_CREW_DOUBLE_BOOKED, "Crew member is double-booked")

    rec = {
        "transport_id": body["transport_id"],
        "vehicle_id": body["vehicle_id"],
        "crew_member_id": body["crew_member_id"],
        "window_start_iso": body["window_start_iso"],
        "window_end_iso": body["window_end_iso"],
    }
    init_common(rec)
    store.unit_assignments[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/unit-assignments/<ua_id>", methods=["GET"])
def get_unit_assignment(ua_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    rec = get_or_404(store.unit_assignments, ua_id)
    return success(serialize(rec), 200)


@bp.route("/transports/<transport_id>/unit-assignments", methods=["GET"])
def list_transport_unit_assignments(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    get_or_404(store.transports, transport_id)
    limit, offset = parse_pagination()
    items = [u for u in store.unit_assignments.values() if u["transport_id"] == transport_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


@bp.route("/unit-assignments", methods=["GET"])
def list_unit_assignments():
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    limit, offset = parse_pagination()
    vehicle_id = request.args.get("vehicle_id")
    crew_member_id = request.args.get("crew_member_id")
    items = list(store.unit_assignments.values())
    if vehicle_id is not None:
        items = [u for u in items if u["vehicle_id"] == vehicle_id]
    if crew_member_id is not None:
        items = [u for u in items if u["crew_member_id"] == crew_member_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
