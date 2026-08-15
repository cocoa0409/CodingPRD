"""Alternate care sites: registration, commitment windows, activation, demobilize."""

from datetime import timedelta

from flask import Blueprint, request

from db import clock, store
from domain import (demobilize_site, get_or_404, list_response,
                    recompute_all_items, recompute_incident_surge, ser_site,
                    site_census)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_int, field_str, new_entity, require_body, touch

bp = Blueprint("sites", __name__)

_BUFFER = timedelta(hours=4)


@bp.post("/alternate-care-sites")
@authorize(["LogisticsChief"])
def create_site():
    body = require_body()
    site_name = field_str(body, "site_name", required=True)
    address = field_str(body, "address", required=True)
    bed_capacity = field_int(body, "bed_capacity", required=True, minimum=1)

    site = new_entity()
    site.update({
        "site_name": site_name,
        "address": address,
        "bed_capacity": bed_capacity,
        "status": "STANDBY",
        "commitments": [],
        "activated_incident_id": None,
    })
    store["sites"][site["id"]] = site
    return success(ser_site(site), "object", 201)


@bp.get("/alternate-care-sites")
@authorize(ALL_ROLES)
def list_sites():
    activated_incident_id = request.args.get("activated_incident_id")
    status = request.args.get("status")

    def predicate(s):
        if activated_incident_id is not None and s["activated_incident_id"] != activated_incident_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True

    return list_response("sites", ser_site, predicate)


@bp.get("/alternate-care-sites/<site_id>")
@authorize(ALL_ROLES)
def get_site(site_id):
    return success(ser_site(get_or_404("sites", site_id)), "object", 200)


@bp.post("/alternate-care-sites/<site_id>/commit")
@authorize(["IncidentCommander"])
def commit_site(site_id):
    site = get_or_404("sites", site_id)
    body = require_body()
    incident_id = field_str(body, "incident_id", required=True)
    window_start = field_dt(body, "window_start", required=True)
    window_end = field_dt(body, "window_end", required=True)

    incident = get_or_404("incidents", incident_id)

    # Posture gate.
    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "commitments require an ACTIVATED incident")

    if not window_start < window_end:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "window_start must be strictly before window_end")

    # Buffered +/-4h overlap against every existing commitment.
    for c in site["commitments"]:
        if window_start < c["window_end"] + _BUFFER and window_end > c["window_start"] - _BUFFER:
            raise ApiError("ERR_SITE_WINDOW_CONFLICT", 409,
                           "proposed window conflicts with an existing commitment "
                           "under the buffered 4h turnaround rule")

    site["commitments"].append({
        "incident_id": incident_id,
        "window_start": window_start,
        "window_end": window_end,
    })
    if site["status"] in ("STANDBY", "DEMOBILIZED"):
        site["status"] = "COMMITTED"
    touch(site)
    return success(ser_site(site), "object", 200)


@bp.post("/alternate-care-sites/<site_id>/activate")
@authorize(["IncidentCommander"])
def activate_site(site_id):
    site = get_or_404("sites", site_id)
    if site["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a COMMITTED site can be activated")

    now = clock.now()
    containing = None
    for c in site["commitments"]:
        if c["window_start"] <= now <= c["window_end"]:
            containing = c
            break
    if containing is None:
        raise ApiError("ERR_OUTSIDE_COMMIT_WINDOW", 422,
                       "no commitment window contains the current clock time")

    incident = store["incidents"].get(containing["incident_id"])
    if incident is None or incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "the containing commitment's incident is not ACTIVATED")

    site["status"] = "ACTIVATED"
    site["activated_incident_id"] = containing["incident_id"]
    touch(site)

    # Cascade: capacity -> tier -> burn projections.
    recompute_incident_surge(incident)
    recompute_all_items()
    return success(ser_site(site), "object", 200)


@bp.post("/alternate-care-sites/<site_id>/demobilize")
@authorize(["IncidentCommander"])
def demobilize_site_endpoint(site_id):
    site = get_or_404("sites", site_id)
    if site["status"] != "ACTIVATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an ACTIVATED site can be demobilized")
    if site_census(site["id"]) != 0:
        raise ApiError("ERR_PATIENTS_STILL_ON_SITE", 409,
                       "patients remain TRANSFERRED at this site")
    demobilize_site(site)
    return success(ser_site(site), "object", 200)
