"""Incident declaration, surge assessment, demobilization, reactivation."""

from flask import Blueprint

from db import clock, store
from domain import (INCIDENT_TYPES, active_incident, demobilize_site, get_or_404,
                    recompute_all_items, recompute_incident_surge, ser_incident)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_enum, field_int, field_str, new_entity, require_body, touch

bp = Blueprint("incidents", __name__)


@bp.post("/incidents")
@authorize(["IncidentCommander"])
def create_incident():
    body = require_body()
    incident_name = field_str(body, "incident_name", required=True)
    incident_type = field_enum(body, "incident_type", INCIDENT_TYPES, required=True)
    declared_at = field_dt(body, "declared_at", required=True)

    if active_incident() is not None:
        raise ApiError("ERR_INCIDENT_ALREADY_ACTIVE", 409,
                       "another incident is currently ACTIVATED")

    incident = new_entity()
    incident.update({
        "incident_name": incident_name,
        "incident_type": incident_type,
        "declared_at": declared_at,
        "status": "ACTIVATED",
        "activation_count": 1,
        "activated_at": clock.now(),
        "deactivated_at": None,
        "staffed_bed_count": None,
        "projected_census": None,
        "licensed_surge_capacity": None,
        "operational_surge_capacity": None,
        "current_surge_tier": None,
    })
    store["incidents"][incident["id"]] = incident
    # Activation changes the surge-multiplier context; recompute projections.
    recompute_all_items()
    return success(ser_incident(incident), "object", 201)


@bp.get("/incidents/<incident_id>")
@authorize(ALL_ROLES)
def get_incident(incident_id):
    return success(ser_incident(get_or_404("incidents", incident_id)), "object", 200)


@bp.post("/incidents/<incident_id>/assess-surge")
@authorize(["IncidentCommander", "PlanningChief"])
def assess_surge(incident_id):
    incident = get_or_404("incidents", incident_id)
    body = require_body()
    staffed_bed_count = field_int(body, "staffed_bed_count", required=True, minimum=0)
    projected_census = field_int(body, "projected_census", required=True, minimum=0)

    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "surge assessment requires the incident to be ACTIVATED")

    incident["staffed_bed_count"] = staffed_bed_count
    incident["projected_census"] = projected_census
    recompute_incident_surge(incident)
    touch(incident)
    recompute_all_items()
    return success(ser_incident(incident), "object", 200)


@bp.post("/incidents/<incident_id>/demobilize")
@authorize(["IncidentCommander"])
def demobilize_incident(incident_id):
    incident = get_or_404("incidents", incident_id)
    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an ACTIVATED incident can be demobilized")

    for p in store["patients"].values():
        if p["incident_id"] == incident_id and p["status"] == "TRACKED":
            raise ApiError("ERR_PATIENTS_STILL_TRACKED", 409,
                           "patients of this incident are still TRACKED")
    for p in store["patients"].values():
        if p["status"] != "TRANSFERRED" or p["transfer_site_id"] is None:
            continue
        site = store["sites"].get(p["transfer_site_id"])
        if site is not None and site["activated_incident_id"] == incident_id:
            raise ApiError("ERR_PATIENTS_STILL_ON_SITE", 409,
                           "patients remain TRANSFERRED at sites serving this incident")

    # Step 1: pending callbacks expire; accepted callbacks complete.
    for cb in store["callback_requests"].values():
        if cb["incident_id"] != incident_id:
            continue
        if cb["status"] == "PENDING":
            cb["status"] = "EXPIRED"
            touch(cb)
        elif cb["status"] == "ACCEPTED":
            cb["status"] = "COMPLETED"
            touch(cb)

    # Step 2: every ACTIVATED site serving this incident demobilizes; each
    # transition recomputes capacity, tier, and every supply item's projections.
    for site in list(store["sites"].values()):
        if site["status"] == "ACTIVATED" and site["activated_incident_id"] == incident_id:
            demobilize_site(site)

    # Step 3: the incident itself demobilizes.
    incident["status"] = "DEACTIVATED"
    incident["deactivated_at"] = clock.now()
    touch(incident)

    # Step 4: no incident active anywhere; surge multiplier falls back to 1.0.
    recompute_all_items()
    return success(ser_incident(incident), "object", 200)


@bp.post("/incidents/<incident_id>/reactivate")
@authorize(["IncidentCommander"])
def reactivate_incident(incident_id):
    incident = get_or_404("incidents", incident_id)
    if incident["status"] != "DEACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a DEACTIVATED incident can be reactivated")
    other = active_incident()
    if other is not None and other["id"] != incident_id:
        raise ApiError("ERR_INCIDENT_ALREADY_ACTIVE", 409,
                       "another incident is currently ACTIVATED")

    incident["status"] = "ACTIVATED"
    incident["activation_count"] += 1
    incident["activated_at"] = clock.now()
    touch(incident)
    # The retained surge tier's multiplier resumes (1.0 when the tier is null).
    recompute_all_items()
    return success(ser_incident(incident), "object", 200)
