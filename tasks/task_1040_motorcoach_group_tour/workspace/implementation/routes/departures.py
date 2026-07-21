"""Departure endpoints: CRUD + lifecycle + assign + manifest + settlement."""
from flask import Blueprint, request

import services
from errors import ApiError
from store import db
from web import (
    authenticate,
    get_body,
    created,
    ok,
    ok_list,
    parse_pagination,
    req_str,
    req_int,
    opt_str,
)

bp = Blueprint("departures", __name__)


@bp.post("/api/departures")
def create_departure():
    authenticate({"OpsManager"})
    body = get_body()
    tour_product_id = req_str(body, "tour_product_id")
    name = req_str(body, "name")
    start_date = req_str(body, "start_date")
    end_date = req_str(body, "end_date")
    guaranteed_min_pax = req_int(body, "guaranteed_min_pax", min_val=1)
    itinerary_days = body.get("itinerary_days")
    if itinerary_days is None or not isinstance(itinerary_days, list):
        raise ApiError("ERR_VALIDATION", "itinerary_days must be an array")
    # FK existence (404)
    services.get_or_404(db.tour_products, tour_product_id)
    dep = services.create_departure(
        tour_product_id, name, start_date, end_date, guaranteed_min_pax, itinerary_days
    )
    return created(services.serialize(dep))


@bp.get("/api/departures/<departure_id>")
def get_departure(departure_id):
    authenticate("ALL")
    dep = services.get_or_404(db.departures, departure_id)
    return ok(services.serialize(dep))


@bp.get("/api/departures")
def list_departures():
    authenticate("ALL")
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.departures.values())
    for key in ("tour_product_id", "coach_id", "driver_id", "guide_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(d) for d in page], total, limit, offset)


@bp.post("/api/departures/<departure_id>/publish")
def publish(departure_id):
    authenticate({"OpsManager"})
    dep = services.get_or_404(db.departures, departure_id)
    services.publish_departure(dep)
    return ok(services.serialize(dep))


@bp.post("/api/departures/<departure_id>/assign")
def assign(departure_id):
    authenticate({"OpsManager"})
    dep = services.get_or_404(db.departures, departure_id)
    body = get_body()
    resource_kind = req_str(body, "resource_kind")
    if resource_kind not in ("COACH", "DRIVER", "GUIDE"):
        raise ApiError("ERR_VALIDATION", "resource_kind must be COACH, DRIVER, or GUIDE")
    expected_version = req_int(body, "expected_departure_version")
    id_field = {"COACH": "coach_id", "DRIVER": "driver_id", "GUIDE": "guide_id"}[resource_kind]
    resource_id = body.get(id_field)
    if not isinstance(resource_id, str) or resource_id == "":
        raise ApiError("ERR_VALIDATION", f"{id_field} is required for resource_kind {resource_kind}")
    # FK existence (404) — path already resolved, now the referenced resource
    collection = {"COACH": db.coaches, "DRIVER": db.drivers, "GUIDE": db.guides}[resource_kind]
    services.get_or_404(collection, resource_id)
    services.assign_resource(dep, resource_kind, resource_id, expected_version)
    return ok(services.serialize(dep))


@bp.post("/api/departures/<departure_id>/depart")
def depart(departure_id):
    authenticate({"OpsManager"})
    dep = services.get_or_404(db.departures, departure_id)
    services.depart_departure(dep)
    return ok(services.serialize(dep))


@bp.post("/api/departures/<departure_id>/cancel")
def cancel(departure_id):
    authenticate({"OpsManager"})
    dep = services.get_or_404(db.departures, departure_id)
    body = get_body()
    reason = opt_str(body, "reason")
    services.cancel_departure(dep, reason)
    return ok(services.serialize(dep))


@bp.post("/api/departures/<departure_id>/settle")
def settle(departure_id):
    authenticate({"Finance"})
    dep = services.get_or_404(db.departures, departure_id)
    services.settle_departure(dep)
    return ok(services.serialize(dep))


@bp.get("/api/departures/<departure_id>/manifest")
def manifest(departure_id):
    authenticate("ALL")
    dep = services.get_or_404(db.departures, departure_id)
    return ok(services.manifest_view(dep))


@bp.get("/api/departures/<departure_id>/settlement")
def settlement(departure_id):
    authenticate({"OpsManager", "Finance", "Auditor"})
    dep = services.get_or_404(db.departures, departure_id)
    return ok(services.settlement_view(dep))
