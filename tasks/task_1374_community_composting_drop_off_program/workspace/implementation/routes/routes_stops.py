"""CollectionRoute, RouteStop, ProcessingPartner, ProcessingBatch endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_int, require_number,
    require_dt_field, occ_check, parse_bool_param,
    get_program_or_404, get_site_or_404, get_route_or_404,
    get_partner_or_404, get_stop_or_404, get_batch_or_404,
    paginate, sort_created,
)
from services import posture as posture_svc
from services.drops import reconcile_batch_accepted, reconcile_batch_rejected
from services.programs import touch, site_posture_touch
from services.serializers import (
    route as serialize_route, stop as serialize_stop,
    partner as serialize_partner, batch as serialize_batch,
)

bp = Blueprint("routes_stops", __name__)

ROUTE_READ_ROLES = ("ProgramAdmin", "RouteOperator", "ProcessingPartner", "MunicipalAuditor")
STOP_READ_ROLES = ("ProgramAdmin", "RouteOperator", "ProcessingPartner", "MunicipalAuditor")
PARTNER_READ_ROLES = ("ProgramAdmin", "RouteOperator", "ProcessingPartner", "MunicipalAuditor")
BATCH_READ_ROLES = ("ProgramAdmin", "ProcessingPartner", "MunicipalAuditor")


# ---------------------------------------------------------------------------
# ProcessingPartner
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/partners", methods=["POST"])
def create_partner(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "name", "intake_capacity_kg_per_day", "yield_ratio",
                   "contamination_reject_threshold_pct")
    name = require_str(data, "name")
    intake = require_int(data, "intake_capacity_kg_per_day")
    yield_ratio = require_number(data, "yield_ratio")
    reject_threshold = require_number(data, "contamination_reject_threshold_pct")
    active = data.get("active", True)
    if not isinstance(active, bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "active must be a boolean")

    now = db.iso_now()
    partner = {
        "id": db.new_id(),
        "program_id": program["id"],
        "name": name,
        "intake_capacity_kg_per_day": intake,
        "yield_ratio": yield_ratio,
        "contamination_reject_threshold_pct": reject_threshold,
        "active": active,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.partners[partner["id"]] = partner
    return success_object(serialize_partner(partner), status=201)


@bp.route("/programs/<program_id>/partners", methods=["GET"])
def list_partners(program_id):
    require_roles(*PARTNER_READ_ROLES)
    get_program_or_404(program_id)
    items = [p for p in db.partners.values() if p["program_id"] == program_id]
    active_filter = parse_bool_param("active")
    if active_filter is not None:
        items = [p for p in items if p["active"] == active_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_partner(p) for p in page], limit, offset, total)


@bp.route("/partners", methods=["GET"])
def list_partners_flat():
    require_roles(*PARTNER_READ_ROLES)
    items = list(db.partners.values())
    if request.args.get("program_id"):
        items = [p for p in items if p["program_id"] == request.args["program_id"]]
    active_filter = parse_bool_param("active")
    if active_filter is not None:
        items = [p for p in items if p["active"] == active_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_partner(p) for p in page], limit, offset, total)


@bp.route("/partners/<partner_id>", methods=["GET"])
def get_partner_flat(partner_id):
    require_roles(*PARTNER_READ_ROLES)
    partner = get_partner_or_404(partner_id)
    return success_object(serialize_partner(partner))


# ---------------------------------------------------------------------------
# CollectionRoute
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/routes", methods=["POST"])
def create_route(program_id):
    require_roles("RouteOperator")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "route_code", "vehicle_capacity_kg",
                   "processing_partner_id", "scheduled_start", "scheduled_end")
    route_code = require_str(data, "route_code")
    capacity = require_int(data, "vehicle_capacity_kg")
    partner = get_partner_or_404(data["processing_partner_id"], program_id)
    start = require_dt_field(data, "scheduled_start")
    end = require_dt_field(data, "scheduled_end")

    now = db.iso_now()
    route = {
        "id": db.new_id(),
        "program_id": program["id"],
        "route_code": route_code,
        "vehicle_capacity_kg": capacity,
        "processing_partner_id": partner["id"],
        "status": "PLANNED",
        "scheduled_start": start,
        "scheduled_end": end,
        "assigned_load_kg": 0.0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.routes[route["id"]] = route
    return success_object(serialize_route(route), status=201)


@bp.route("/programs/<program_id>/routes", methods=["GET"])
def list_routes(program_id):
    require_roles(*ROUTE_READ_ROLES)
    get_program_or_404(program_id)
    items = [r for r in db.routes.values() if r["program_id"] == program_id]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    if request.args.get("processing_partner_id"):
        items = [r for r in items if r["processing_partner_id"] == request.args["processing_partner_id"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_route(r) for r in page], limit, offset, total)


@bp.route("/programs/<program_id>/routes/<route_id>", methods=["GET"])
def get_route(program_id, route_id):
    require_roles(*ROUTE_READ_ROLES)
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    return success_object(serialize_route(route))


@bp.route("/programs/<program_id>/routes/<route_id>/dispatch", methods=["POST"])
def dispatch_route(program_id, route_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    if route["status"] != "PLANNED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Route must be PLANNED to dispatch")

    has_scheduled = any(
        s["route_id"] == route["id"] and s["status"] == "SCHEDULED"
        for s in db.stops.values()
    )
    if not has_scheduled:
        errors.raise_err(errors.ERR_ROUTE_HAS_NO_STOPS, "Dispatch requires at least one SCHEDULED stop")

    if float(route["assigned_load_kg"]) > route["vehicle_capacity_kg"]:
        errors.raise_err(
            errors.ERR_ROUTE_OVER_CAPACITY,
            "assigned_load_kg exceeds vehicle_capacity_kg",
        )

    partner = db.partners.get(route["processing_partner_id"])
    if not partner or not partner["active"]:
        errors.raise_err(errors.ERR_PARTNER_INACTIVE, "Route's processing partner is inactive")

    # Half-open window overlap with other DISPATCHED routes at same partner
    for other in db.routes.values():
        if other["id"] == route["id"]:
            continue
        if other["program_id"] != program_id:
            continue
        if other["status"] != "DISPATCHED":
            continue
        if other["processing_partner_id"] != route["processing_partner_id"]:
            continue
        if route["scheduled_start"] < other["scheduled_end"] and \
                other["scheduled_start"] < route["scheduled_end"]:
            errors.raise_err(
                errors.ERR_PARTNER_DOUBLE_BOOKED,
                "Another DISPATCHED route at the same partner overlaps the requested window",
            )

    route["status"] = "DISPATCHED"
    touch(route)
    return success_object(serialize_route(route))


@bp.route("/programs/<program_id>/routes/<route_id>/complete", methods=["POST"])
def complete_route(program_id, route_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    if route["status"] != "DISPATCHED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Route must be DISPATCHED to complete")
    pending = [s for s in db.stops.values()
               if s["route_id"] == route["id"] and s["status"] == "SCHEDULED"]
    if pending:
        errors.raise_err(
            errors.ERR_ROUTE_STOPS_PENDING,
            "Route complete blocked while any stop remains SCHEDULED",
        )

    collected = [s for s in db.stops.values()
                 if s["route_id"] == route["id"] and s["status"] == "COLLECTED"]
    total_actual = 0.0
    affected_sites = {}
    for stop in collected:
        site = db.sites.get(stop["site_id"])
        if not site:
            continue
        site["stored_kg"] = db.round_kg(float(site["stored_kg"]) - float(stop["actual_pickup_kg"]))
        site["pending_pickup_kg"] = db.round_kg(
            float(site["pending_pickup_kg"]) - float(stop["planned_pickup_kg"])
        )
        affected_sites[site["id"]] = site
        total_actual += float(stop["actual_pickup_kg"])

    route["status"] = "COMPLETED"
    touch(route)

    for site in affected_sites.values():
        site_posture_touch(site)

    # Open a ProcessingBatch at the route's partner when there are COLLECTED stops
    if collected:
        now = db.iso_now()
        batch = {
            "id": db.new_id(),
            "partner_id": route["processing_partner_id"],
            "route_id": route["id"],
            "input_gross_kg": db.round_kg(total_actual),
            "measured_contamination_kg": None,
            "measured_net_kg": None,
            "contamination_pct": None,
            "finished_compost_kg": None,
            "status": "OPEN",
            "closed_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.batches[batch["id"]] = batch

    return success_object(serialize_route(route))


@bp.route("/programs/<program_id>/routes/<route_id>/cancel", methods=["POST"])
def cancel_route(program_id, route_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    if route["status"] != "PLANNED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Route must be PLANNED to cancel")
    route["status"] = "CANCELLED"
    touch(route)
    affected_sites = {}
    for stop in db.stops.values():
        if stop["route_id"] == route["id"] and stop["status"] == "SCHEDULED":
            stop["status"] = "CANCELLED"
            touch(stop)
            site = db.sites.get(stop["site_id"])
            if site:
                site["pending_pickup_kg"] = db.round_kg(
                    float(site["pending_pickup_kg"]) - float(stop["planned_pickup_kg"])
                )
                affected_sites[site["id"]] = site
    for site in affected_sites.values():
        site_posture_touch(site)
    return success_object(serialize_route(route))


@bp.route("/routes", methods=["GET"])
def list_routes_flat():
    require_roles(*ROUTE_READ_ROLES)
    items = list(db.routes.values())
    if request.args.get("program_id"):
        items = [r for r in items if r["program_id"] == request.args["program_id"]]
    if request.args.get("processing_partner_id"):
        items = [r for r in items if r["processing_partner_id"] == request.args["processing_partner_id"]]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_route(r) for r in page], limit, offset, total)


@bp.route("/routes/<route_id>", methods=["GET"])
def get_route_flat(route_id):
    require_roles(*ROUTE_READ_ROLES)
    route = get_route_or_404(route_id)
    return success_object(serialize_route(route))


# ---------------------------------------------------------------------------
# RouteStop
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/routes/<route_id>/stops", methods=["POST"])
def create_stop(program_id, route_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    data = body()
    require_fields(data, "site_id", "planned_pickup_kg", "stop_sequence")
    site = get_site_or_404(data["site_id"], program_id)
    planned = require_int(data, "planned_pickup_kg")
    sequence = require_int(data, "stop_sequence")

    occ_check(route, data.get("expected_route_version"), "expected_route_version")

    if route["status"] != "PLANNED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Stops can only be added to PLANNED routes")

    now = db.iso_now()
    stop = {
        "id": db.new_id(),
        "route_id": route["id"],
        "site_id": site["id"],
        "planned_pickup_kg": planned,
        "actual_pickup_kg": None,
        "stop_sequence": sequence,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.stops[stop["id"]] = stop

    site["pending_pickup_kg"] = db.round_kg(float(site["pending_pickup_kg"]) + planned)
    site_posture_touch(site)

    route["assigned_load_kg"] = db.round_kg(float(route["assigned_load_kg"]) + planned)
    touch(route)

    return success_object(serialize_stop(stop), status=201)


@bp.route("/programs/<program_id>/routes/<route_id>/stops", methods=["GET"])
def list_stops(program_id, route_id):
    require_roles(*STOP_READ_ROLES)
    get_program_or_404(program_id)
    get_route_or_404(route_id, program_id)
    items = [s for s in db.stops.values() if s["route_id"] == route_id]
    if request.args.get("site_id"):
        items = [s for s in items if s["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_stop(s) for s in page], limit, offset, total)


@bp.route("/programs/<program_id>/routes/<route_id>/stops/<stop_id>/collect", methods=["POST"])
def collect_stop(program_id, route_id, stop_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    stop = get_stop_or_404(stop_id, route_id)
    if stop["status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Stop must be SCHEDULED to collect")
    if route["status"] != "DISPATCHED":
        errors.raise_err(errors.ERR_ROUTE_NOT_DISPATCHED, "Stop collect requires route DISPATCHED")
    data = body()
    require_fields(data, "actual_pickup_kg")
    actual = require_number(data, "actual_pickup_kg")
    site = db.sites.get(stop["site_id"])
    if site:
        available = float(site["stored_kg"]) + float(site["pending_pickup_kg"])
        if actual < 0 or actual > available:
            errors.raise_err(
                errors.ERR_PICKUP_EXCEEDS_AVAILABLE,
                "actual_pickup_kg out of bounds relative to site available mass",
            )
    stop["actual_pickup_kg"] = actual
    stop["status"] = "COLLECTED"
    touch(stop)
    return success_object(serialize_stop(stop))


@bp.route("/programs/<program_id>/routes/<route_id>/stops/<stop_id>/skip", methods=["POST"])
def skip_stop(program_id, route_id, stop_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    stop = get_stop_or_404(stop_id, route_id)
    if stop["status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Stop must be SCHEDULED to skip")
    if route["status"] != "DISPATCHED":
        errors.raise_err(errors.ERR_ROUTE_NOT_DISPATCHED, "Stop skip requires route DISPATCHED")
    stop["status"] = "SKIPPED"
    touch(stop)
    site = db.sites.get(stop["site_id"])
    if site:
        site["pending_pickup_kg"] = db.round_kg(
            float(site["pending_pickup_kg"]) - float(stop["planned_pickup_kg"])
        )
        site_posture_touch(site)
    return success_object(serialize_stop(stop))


@bp.route("/programs/<program_id>/routes/<route_id>/stops/<stop_id>/cancel", methods=["POST"])
def cancel_stop(program_id, route_id, stop_id):
    require_roles("RouteOperator")
    get_program_or_404(program_id)
    route = get_route_or_404(route_id, program_id)
    stop = get_stop_or_404(stop_id, route_id)
    if stop["status"] != "SCHEDULED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Stop must be SCHEDULED to cancel")
    if route["status"] != "PLANNED":
        errors.raise_err(errors.ERR_ROUTE_NOT_PLANNED, "Direct stop cancel requires route PLANNED")
    stop["status"] = "CANCELLED"
    touch(stop)
    site = db.sites.get(stop["site_id"])
    if site:
        site["pending_pickup_kg"] = db.round_kg(
            float(site["pending_pickup_kg"]) - float(stop["planned_pickup_kg"])
        )
        site_posture_touch(site)
    return success_object(serialize_stop(stop))


@bp.route("/stops", methods=["GET"])
def list_stops_flat():
    require_roles(*STOP_READ_ROLES)
    items = list(db.stops.values())
    if request.args.get("route_id"):
        items = [s for s in items if s["route_id"] == request.args["route_id"]]
    if request.args.get("site_id"):
        items = [s for s in items if s["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_stop(s) for s in page], limit, offset, total)


@bp.route("/stops/<stop_id>", methods=["GET"])
def get_stop_flat(stop_id):
    require_roles(*STOP_READ_ROLES)
    stop = get_stop_or_404(stop_id)
    return success_object(serialize_stop(stop))


# ---------------------------------------------------------------------------
# ProcessingBatch
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/partners/<partner_id>/batches", methods=["GET"])
def list_batches(program_id, partner_id):
    require_roles(*BATCH_READ_ROLES)
    get_program_or_404(program_id)
    get_partner_or_404(partner_id, program_id)
    items = [b for b in db.batches.values() if b["partner_id"] == partner_id]
    if request.args.get("status"):
        items = [b for b in items if b["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_batch(b) for b in page], limit, offset, total)


@bp.route("/programs/<program_id>/partners/<partner_id>/batches/<batch_id>", methods=["GET"])
def get_batch(program_id, partner_id, batch_id):
    require_roles(*BATCH_READ_ROLES)
    get_program_or_404(program_id)
    get_partner_or_404(partner_id, program_id)
    batch = get_batch_or_404(batch_id, partner_id)
    return success_object(serialize_batch(batch))


@bp.route(
    "/programs/<program_id>/partners/<partner_id>/batches/<batch_id>/close",
    methods=["POST"],
)
def close_batch(program_id, partner_id, batch_id):
    require_roles("ProcessingPartner")
    program = get_program_or_404(program_id)
    partner = get_partner_or_404(partner_id, program_id)
    batch = get_batch_or_404(batch_id, partner_id)
    if batch["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Batch must be OPEN to close")
    data = body()
    require_fields(data, "measured_contamination_kg")
    measured_contam = require_number(data, "measured_contamination_kg")

    input_gross = float(batch["input_gross_kg"])
    measured_net = db.round_kg(input_gross - measured_contam)
    if input_gross == 0:
        contam_pct = 0.0
    else:
        contam_pct = db.round_kg(measured_contam / input_gross * 100)

    batch["measured_contamination_kg"] = measured_contam
    batch["measured_net_kg"] = measured_net
    batch["contamination_pct"] = contam_pct
    batch["closed_at"] = db.clock_now()

    if contam_pct < float(partner["contamination_reject_threshold_pct"]):
        batch["status"] = "CLOSED_ACCEPTED"
        finished = db.round_kg(measured_net * float(partner["yield_ratio"]))
        batch["finished_compost_kg"] = finished
        touch(batch)
        reconcile_batch_accepted(batch)
    else:
        batch["status"] = "CLOSED_REJECTED"
        batch["finished_compost_kg"] = 0.0
        touch(batch)
        reconcile_batch_rejected(batch)

    # Refresh program totals
    from services.programs import recompute_program_totals
    recompute_program_totals(program)

    return success_object(serialize_batch(batch))


@bp.route("/batches", methods=["GET"])
def list_batches_flat():
    require_roles(*BATCH_READ_ROLES)
    items = list(db.batches.values())
    if request.args.get("partner_id"):
        items = [b for b in items if b["partner_id"] == request.args["partner_id"]]
    if request.args.get("route_id"):
        items = [b for b in items if b["route_id"] == request.args["route_id"]]
    if request.args.get("status"):
        items = [b for b in items if b["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_batch(b) for b in page], limit, offset, total)


@bp.route("/batches/<batch_id>", methods=["GET"])
def get_batch_flat(batch_id):
    require_roles(*BATCH_READ_ROLES)
    batch = get_batch_or_404(batch_id)
    return success_object(serialize_batch(batch))
