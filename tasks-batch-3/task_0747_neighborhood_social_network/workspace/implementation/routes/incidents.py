"""Incident endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from clock import CLOCK, iso_format, parse_iso
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    ResidentSuspended,
    NotVerifiedInNeighborhood,
    LocationOutsideGeofence,
    InvalidState,
)
from geo import point_inside
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import refresh_neighborhood_derived
from validators import as_str, as_number, as_enum


bp = Blueprint("incidents", __name__)

SEVERITIES = {"INFO", "WARNING", "CRITICAL"}
CATEGORIES = {
    "SUSPICIOUS_ACTIVITY", "PROPERTY_CRIME", "TRAFFIC_HAZARD",
    "ENVIRONMENTAL", "PERSON_MISSING", "ANIMAL",
}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


@bp.post("/neighborhood/incidents")
@require_roles("Resident", "Moderator")
def create_incident():
    payload = request.get_json(silent=True) or {}
    reporter_resident_id = as_str(payload, "reporter_resident_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    incident_lat = as_number(payload, "incident_lat")
    incident_lng = as_number(payload, "incident_lng")
    severity = as_enum(payload, "severity", SEVERITIES)
    category = as_enum(payload, "category", CATEGORIES)
    description = as_str(payload, "description")
    occurred_at_str = as_str(payload, "occurred_at")

    reporter = DB.residents.get(reporter_resident_id)
    if reporter is None:
        raise ReferenceNotFound(f"Resident {reporter_resident_id} not found")
    n = DB.neighborhoods.get(neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    # Suspension check (priority 90)
    acting = DB.residents.get(g.user_id)
    if acting is not None and acting.get("is_suspended", False):
        raise ResidentSuspended("Resident is suspended")

    # Verified-in-neighborhood (priority 100)
    if not _resident_verified_in(neighborhood_id, g.user_id):
        raise NotVerifiedInNeighborhood(
            "Acting resident is not verified in the target neighborhood"
        )

    try:
        occurred_at = parse_iso(occurred_at_str)
    except ValueError:
        raise InvalidRequest("occurred_at is not a valid ISO 8601 timestamp")
    now = CLOCK.now()
    if occurred_at > now:
        raise InvalidRequest("occurred_at must be <= current logical clock")

    # Geofence (priority 150)
    if not point_inside(n, incident_lat, incident_lng):
        raise LocationOutsideGeofence("incident coordinates outside neighborhood geofence")

    i = {
        "reporter_resident_id": reporter_resident_id,
        "neighborhood_id": neighborhood_id,
        "incident_lat": incident_lat,
        "incident_lng": incident_lng,
        "severity": severity,
        "category": category,
        "description": description,
        "occurred_at": iso_format(occurred_at),
        "status": "OPEN",
        "acknowledged_by_officer_id": None,
        "resolved_at": None,
    }
    stamp_new(i)
    DB.incidents[i["id"]] = i

    # Recompute neighborhood derived state (unresolved_critical_count, safety_posture)
    refresh_neighborhood_derived(neighborhood_id)
    return success(i, status=201)


@bp.get("/neighborhood/incidents/<iid>")
@require_roles(*ALL_ROLES)
def get_incident(iid: str):
    i = DB.incidents.get(iid)
    if i is None:
        raise NotFound(f"Incident {iid} not found")
    return success(i)


@bp.get("/neighborhood/incidents")
@require_roles(*ALL_ROLES)
def list_incidents():
    nid = request.args.get("neighborhood_id")
    rid = request.args.get("reporter_resident_id")
    oid = request.args.get("acknowledged_by_officer_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    rows = list(DB.incidents.values())
    if nid is not None:
        rows = [r for r in rows if r["neighborhood_id"] == nid]
    if rid is not None:
        rows = [r for r in rows if r["reporter_resident_id"] == rid]
    if oid is not None:
        rows = [r for r in rows if r.get("acknowledged_by_officer_id") == oid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/incidents/<iid>/acknowledge")
@require_roles("AgencyOfficer")
def acknowledge_incident(iid: str):
    i = DB.incidents.get(iid)
    if i is None:
        raise NotFound(f"Incident {iid} not found")
    if i["status"] != "OPEN":
        raise InvalidState(f"Incident.status is {i['status']}, expected OPEN")
    i["status"] = "ACKNOWLEDGED"
    i["acknowledged_by_officer_id"] = g.user_id
    bump(i)
    refresh_neighborhood_derived(i["neighborhood_id"])
    return success(i)


@bp.post("/neighborhood/incidents/<iid>/resolve")
@require_roles("AgencyOfficer")
def resolve_incident(iid: str):
    i = DB.incidents.get(iid)
    if i is None:
        raise NotFound(f"Incident {iid} not found")
    if i["status"] != "ACKNOWLEDGED":
        raise InvalidState(f"Incident.status is {i['status']}, expected ACKNOWLEDGED")
    if i.get("acknowledged_by_officer_id") != g.user_id:
        raise Forbidden("Only the acknowledging officer may resolve this incident")
    i["status"] = "RESOLVED"
    i["resolved_at"] = iso_format(CLOCK.now())
    bump(i)
    # Cascade: refresh unresolved_critical_count + safety_posture + affected post feed scores
    refresh_neighborhood_derived(i["neighborhood_id"])
    return success(i)


@bp.post("/neighborhood/incidents/<iid>/dismiss")
@require_roles("AgencyOfficer", "PlatformAdmin")
def dismiss_incident(iid: str):
    i = DB.incidents.get(iid)
    if i is None:
        raise NotFound(f"Incident {iid} not found")
    if i["status"] != "OPEN":
        raise InvalidState(f"Incident.status is {i['status']}, expected OPEN")
    i["status"] = "DISMISSED"
    i["resolved_at"] = iso_format(CLOCK.now())
    bump(i)
    refresh_neighborhood_derived(i["neighborhood_id"])
    return success(i)
