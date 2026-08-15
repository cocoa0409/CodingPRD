"""Site onboarding and lifecycle (PRD §3.1)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, require_site_coordinator_of
from response import created, ok, paginate
from services import cascades
from services.serialize import site_json, volunteer_json
from validation import parse_body, require_entity

bp = Blueprint("sites", __name__)

SITE_STATUSES = ["SETUP", "CERTIFIED", "OPEN", "SUSPENDED", "CLOSED"]

# Returns blocking site closure (OPEN/SUSPENDED -> CLOSED open-work guard).
OPEN_RETURN_STATUSES = ("INTAKE_STARTED", "IN_PREPARATION", "PENDING_QR",
                        "QR_FAILED", "QR_PASSED", "TRANSMITTED", "REJECTED")

CREATE_SCHEMA = {
    "name": {"kind": "string", "required": True},
    "sponsor_org": {"kind": "string", "required": True},
    "station_capacity": {"kind": "integer", "required": True, "min": 1},
    "season_start": {"kind": "datetime", "required": True},
    "season_end": {"kind": "datetime", "required": True},
    "daily_open_hour": {"kind": "integer", "required": True, "min": 0, "max": 23},
    "daily_close_hour": {"kind": "integer", "required": True, "min": 1, "max": 24},
    "goal_returns": {"kind": "integer", "required": True, "min": 1},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": SITE_STATUSES},
}


@bp.post("/sites")
def create_site():
    get_context()
    require_roles(["SponsorAdmin"])
    body = parse_body(CREATE_SCHEMA)
    if body["daily_open_hour"] >= body["daily_close_hour"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "daily_open_hour must be strictly earlier than daily_close_hour")
    site = db.new_common({
        "name": body["name"],
        "sponsor_org": body["sponsor_org"],
        "station_capacity": body["station_capacity"],
        "season_start": body["season_start"],
        "season_end": body["season_end"],
        "daily_open_hour": body["daily_open_hour"],
        "daily_close_hour": body["daily_close_hour"],
        "goal_returns": body["goal_returns"],
        "status": "SETUP",
    })
    store.sites[site["id"]] = site
    return created(site_json(site))


@bp.get("/sites/<site_id>")
def get_site(site_id):
    get_context()
    site = require_entity(store.sites, site_id)
    return ok(site_json(site))


@bp.post("/sites/<site_id>/state")
def transition_site(site_id):
    get_context()
    # Authorization (tier 2) precedes existence (tier 3): the own-site binding
    # compares the acting volunteer's site_id against the path id directly.
    require_site_coordinator_of(site_id)
    site = require_entity(store.sites, site_id)
    body = parse_body(STATE_SCHEMA)
    current = site["status"]
    target = body["to_status"]

    if current == "SETUP" and target == "CERTIFIED":
        # Requires at least one ACTIVE coordinator-flagged volunteer of this site.
        if not any(v["site_id"] == site_id and v["is_coordinator"]
                   and v["status"] == "ACTIVE"
                   for v in store.volunteers.values()):
            raise ApiError("ERR_INVALID_TRANSITION", 409,
                           "Site has no ACTIVE coordinator volunteer")
    elif current == "CERTIFIED" and target == "OPEN":
        now = db.LOGICAL_CLOCK
        if not (site["season_start"] <= now <= site["season_end"]):
            raise ApiError("ERR_INVALID_TRANSITION", 409,
                           "Current logical time is outside the season window")
    elif current == "OPEN" and target == "SUSPENDED":
        cascades.site_suspension_cascade(site_id)
    elif current == "SUSPENDED" and target == "OPEN":
        pass
    elif current in ("OPEN", "SUSPENDED") and target == "CLOSED":
        if any(a["site_id"] == site_id and a["status"] in ("SCHEDULED", "CHECKED_IN")
               for a in store.appointments.values()):
            raise ApiError("ERR_SITE_HAS_OPEN_WORK", 409,
                           "Site has open appointments")
        if any(r["site_id"] == site_id and r["status"] in OPEN_RETURN_STATUSES
               for r in store.tax_returns.values()):
            raise ApiError("ERR_SITE_HAS_OPEN_WORK", 409,
                           "Site has open tax returns")
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move site from %s to %s" % (current, target))

    site["status"] = target
    db.touch(site)
    return ok(site_json(site))


@bp.get("/sites/<site_id>/volunteers")
def list_site_volunteers(site_id):
    get_context()
    require_entity(store.sites, site_id)
    rows = [v for v in store.volunteers.values() if v["site_id"] == site_id]
    page = paginate(rows)
    return ok([volunteer_json(v) for v in page], rtype="array", pagination=paginate)
