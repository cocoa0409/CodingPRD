"""Manifest endpoints (PRD §3.7): chain-of-custody lifecycle including the
cyclic amendment loop."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FACILITY_CAPACITY_EXCEEDED,
    ERR_FACILITY_NOT_FOUND,
    ERR_FACILITY_REJECTS_HALOGENATED,
    ERR_FACILITY_SUSPENDED,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_MANIFEST_NOT_DELIVERED,
    ERR_MANIFEST_NOT_FOUND,
    ERR_MANIFEST_NOT_IN_TRANSIT,
    ERR_MANIFEST_NOT_PENDING_AMENDMENT,
    ERR_MANIFEST_NOT_SUBMITTABLE,
    ERR_MANIFEST_NOT_SUBMITTED,
    ERR_MANIFEST_SCHEDULED_DATE_PAST,
    ERR_OPEN_SPILL_EXISTS,
    ERR_ROUTE_NOT_COMPLETE,
    ERR_ROUTE_NOT_FOUND,
    ERR_ROUTE_NOT_READY_FOR_MANIFEST,
)
from middleware import get_body, req_str, require_roles
from response import success_list, success_object
from services import cascades

bp = Blueprint("manifests", __name__)

READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "Driver")
SPILL_TERMINAL_STATES = {"CLOSED_NO_ACTION", "CLOSED_WITH_LIABILITY"}


def get_manifest_or_404(manifest_id):
    manifest = db.get("manifests", manifest_id)
    if manifest is None:
        raise ApiError(ERR_MANIFEST_NOT_FOUND, "Manifest id not found", 404)
    return manifest


def _check_driver_owns_manifest_route(manifest):
    route = db.get("routes", manifest["route_id"])
    if route is not None and route["driver_id"] != request.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Driver may only act on routes assigned to them",
            403,
        )


@bp.post("/routes/<routeId>/manifest")
@require_roles("RoutePlanner")
def create_manifest(routeId):
    route = db.get("routes", routeId)
    if route is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "Route id not found", 404)
    body = get_body()
    tracking_number = req_str(body, "manifest_tracking_number")
    facility_id = req_str(body, "disposal_facility_id")
    if db.get("disposal_facilities", facility_id) is None:
        raise ApiError(ERR_FACILITY_NOT_FOUND, "DisposalFacility id not found", 404)
    for m in db.all_entities("manifests"):
        if m["manifest_tracking_number"] == tracking_number:
            raise ApiError(ERR_INVALID_REQUEST, "manifest_tracking_number must be unique", 400)
    if cascades.manifest_for_route(routeId) is not None:
        raise ApiError(ERR_INVALID_REQUEST, "A route has at most one manifest", 400)
    manifest = db.create_entity("manifests", {
        "route_id": routeId,
        "manifest_tracking_number": tracking_number,
        "disposal_facility_id": facility_id,
        "total_gallons_manifested": 0,
        "halogen_flag": False,
        "status": "DRAFT",
    })
    # Reconcile the draft against any stops already COMPLETED on the route.
    cascades.recompute_manifest_totals(manifest)
    return success_object(db.serialize(manifest), 201)


@bp.get("/manifests/<manifestId>")
@require_roles(*READ_ROLES)
def get_manifest(manifestId):
    return success_object(db.serialize(get_manifest_or_404(manifestId)))


@bp.get("/manifests")
@require_roles(*READ_ROLES)
def list_manifests():
    items = db.all_entities("manifests")
    for param in ("status", "disposal_facility_id", "route_id"):
        value = request.args.get(param)
        if value is not None:
            items = [m for m in items if m[param] == value]
    return success_list([db.serialize(m) for m in db.sorted_created(items)])


@bp.post("/manifests/<manifestId>/submit")
@require_roles("RoutePlanner")
def submit_manifest(manifestId):
    manifest = get_manifest_or_404(manifestId)
    if manifest["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError(ERR_MANIFEST_NOT_SUBMITTABLE, "Submit requires DRAFT or AMENDED", 409)
    route = db.get("routes", manifest["route_id"])
    if route is None or route["status"] not in ("IN_PROGRESS", "COMPLETE"):
        raise ApiError(ERR_ROUTE_NOT_READY_FOR_MANIFEST, "Manifest submit requires route IN_PROGRESS or COMPLETE", 409)
    facility = db.get("disposal_facilities", manifest["disposal_facility_id"])
    if facility is None:
        raise ApiError(ERR_FACILITY_NOT_FOUND, "DisposalFacility id not found", 404)
    if facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_SUSPENDED, "Facility not ACTIVE", 409)
    scheduled = cascades.facility_scheduled_gallons_today(facility["id"])
    if scheduled + manifest["total_gallons_manifested"] > facility["daily_capacity_gallons"]:
        raise ApiError(ERR_FACILITY_CAPACITY_EXCEEDED, "Facility daily capacity would be exceeded", 409)
    if manifest["halogen_flag"] and "HALOGENATED" not in facility["accepted_streams"]:
        raise ApiError(ERR_FACILITY_REJECTS_HALOGENATED, "Facility does not accept HALOGENATED stream", 409)
    if route["scheduled_date"] < db.today_iso():
        raise ApiError(ERR_MANIFEST_SCHEDULED_DATE_PAST, "Route scheduled_date is in the past at submit time", 422)
    manifest["status"] = "SUBMITTED"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/depart")
@require_roles("Driver")
def depart_manifest(manifestId):
    manifest = get_manifest_or_404(manifestId)
    _check_driver_owns_manifest_route(manifest)
    if manifest["status"] != "SUBMITTED":
        raise ApiError(ERR_MANIFEST_NOT_SUBMITTED, "Depart requires SUBMITTED", 409)
    route = db.get("routes", manifest["route_id"])
    if route is None or route["status"] != "COMPLETE":
        raise ApiError(ERR_ROUTE_NOT_COMPLETE, "Manifest depart requires route COMPLETE", 409)
    manifest["status"] = "IN_TRANSIT"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/deliver")
@require_roles("Driver")
def deliver_manifest(manifestId):
    manifest = get_manifest_or_404(manifestId)
    _check_driver_owns_manifest_route(manifest)
    if manifest["status"] != "IN_TRANSIT":
        raise ApiError(ERR_MANIFEST_NOT_IN_TRANSIT, "Deliver requires IN_TRANSIT", 409)
    manifest["status"] = "DELIVERED"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/close")
@require_roles("Regulator")
def close_manifest(manifestId):
    manifest = get_manifest_or_404(manifestId)
    if manifest["status"] != "DELIVERED":
        raise ApiError(ERR_MANIFEST_NOT_DELIVERED, "Close requires DELIVERED", 409)
    for spill in db.all_entities("spill_incidents"):
        if spill["route_id"] == manifest["route_id"] and spill["status"] not in SPILL_TERMINAL_STATES:
            raise ApiError(ERR_OPEN_SPILL_EXISTS, "Open spill blocks the operation", 409)
    manifest["status"] = "CLOSED"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/request-amendment")
@require_roles("RoutePlanner")
def request_amendment(manifestId):
    manifest = get_manifest_or_404(manifestId)
    if manifest["status"] != "DELIVERED":
        raise ApiError(ERR_MANIFEST_NOT_DELIVERED, "Request-amendment requires DELIVERED", 409)
    manifest["status"] = "AMENDMENT_PENDING"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/approve-amendment")
@require_roles("Regulator")
def approve_amendment(manifestId):
    manifest = get_manifest_or_404(manifestId)
    if manifest["status"] != "AMENDMENT_PENDING":
        raise ApiError(ERR_MANIFEST_NOT_PENDING_AMENDMENT, "Approve-amendment requires AMENDMENT_PENDING", 409)
    cascades.recompute_manifest_totals(manifest)
    manifest["status"] = "AMENDED"
    db.touch(manifest)
    return success_object(db.serialize(manifest))


@bp.post("/manifests/<manifestId>/facility-reject")
@require_roles("Regulator")
def facility_reject(manifestId):
    manifest = get_manifest_or_404(manifestId)
    if manifest["status"] != "SUBMITTED":
        raise ApiError(ERR_MANIFEST_NOT_SUBMITTED, "Facility-reject requires SUBMITTED", 409)
    manifest["status"] = "REJECTED_BY_FACILITY"
    db.touch(manifest)
    route = db.get("routes", manifest["route_id"])
    if route is not None and route["status"] not in ("COMPLETE", "CANCELLED"):
        route["_posture_override"] = True
        db.touch(route)
    return success_object(db.serialize(manifest))
