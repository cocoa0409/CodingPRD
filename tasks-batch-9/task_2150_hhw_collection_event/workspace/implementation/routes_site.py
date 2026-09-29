"""Site endpoints and the containment screen (PRD §3.2)."""

from flask import Blueprint, request

import calc
import serializers
from cascades import site_suspension_cascade
from common import gate_frozen, list_response
from envelope import ok
from errors import ApiError
from rollups import events_of_site, refresh_world
from store import new_row, set_and_touch, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    authorize_action,
    body,
    context,
    lookup,
    opt_str,
    req_bool,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("sites", __name__)

SITE_ACTION_ROLES = {
    "APPROVE": ["ContainmentInspector"],
    "SUSPEND": ["ContainmentInspector"],
    "REINSTATE": ["ContainmentInspector"],
    "RETIRE": ["EventCoordinator"],
}

SITE_TRANSITIONS = {
    "APPROVE": {"CANDIDATE": "APPROVED"},
    "SUSPEND": {"APPROVED": "SUSPENDED"},
    "REINSTATE": {"SUSPENDED": "APPROVED"},
    "RETIRE": {"APPROVED": "RETIRED", "SUSPENDED": "RETIRED"},
}

LIVE_EVENT_STATUSES = ("PLANNED", "SITE_CONFIRMED", "OPEN_FOR_REGISTRATION",
                       "IN_PROGRESS")


def containment_screen_passes(site):
    if not site["impervious_surface"]:
        return False
    if site["secondary_containment_liters"] < calc.MIN_SECONDARY_CONTAINMENT_LITERS:
        return False
    if calc.dec(site["storm_drain_distance_m"]) < calc.MIN_STORM_DRAIN_DISTANCE_M:
        return False
    return True


@bp.post("/hhw/sites")
def create_site():
    user_id, role = context()
    authorize(role, ["EventCoordinator"])
    payload = body()
    program_id = req_str(payload, "program_id")
    name = req_str(payload, "name")
    address = req_str(payload, "address")
    impervious = req_bool(payload, "impervious_surface")
    liters = req_int(payload, "secondary_containment_liters", minimum=0)
    distance = req_num(payload, "storm_drain_distance_m", gte=0)
    lane_count = req_int(payload, "lane_count", minimum=1)
    replaces = payload.get("replaces_site_id")
    if replaces is not None and not isinstance(replaces, str):
        raise ApiError("ERR_INVALID_REQUEST", "replaces_site_id must be a string.")

    program = lookup("program", program_id)
    if replaces is not None:
        lookup("site", replaces)

    row = new_row({
        "program_id": program["id"],
        "replaces_site_id": replaces,
        "name": name,
        "address": address,
        "impervious_surface": impervious,
        "secondary_containment_liters": liters,
        "storm_drain_distance_m": distance,
        "lane_count": lane_count,
        "status": "CANDIDATE",
        "approved_by_user_id": None,
        "last_inspection_result": None,
    })
    store.sites[row["id"]] = row
    refresh_world()
    return ok(serializers.site(row), 201)


@bp.get("/hhw/sites")
def list_sites():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "replaces_site_id": request.args.get("replaces_site_id"),
        "status": request.args.get("status"),
    }
    return list_response(request.args, list(store.sites.values()),
                         serializers.site, filters)


@bp.get("/hhw/sites/<site_id>")
def read_site(site_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.site(lookup("site", site_id)))


@bp.post("/hhw/sites/<site_id>/transitions")
def site_transition(site_id):
    user_id, role = context()
    authorize(role, ["ContainmentInspector", "EventCoordinator"])
    payload = body()
    action = payload.get("action")
    authorize_action(role, action, SITE_ACTION_ROLES)
    action = req_enum(payload, "action", list(SITE_TRANSITIONS.keys()))
    finding_code = opt_str(payload, "finding_code")

    site = lookup("site", site_id)
    program = store.programs.get(site["program_id"])

    # Rung 9 — declared transition out of the current state.
    target = SITE_TRANSITIONS[action].get(site["status"])
    if target is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "RETIRE":
        for event in events_of_site(site["id"]):
            if event["lifecycle_status"] in LIVE_EVENT_STATUSES:
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "The site still hosts a live collection event.")

    if action in ("APPROVE", "REINSTATE"):
        gate_frozen(program)                                     # rung 14
        if not containment_screen_passes(site):                  # rung 16
            # A failed screen is a non-event: nothing is written at all.
            raise ApiError("ERR_CONTAINMENT_REQUIREMENTS_NOT_MET")
        set_and_touch(site, status="APPROVED",
                      approved_by_user_id=user_id,
                      last_inspection_result="PASS")
    elif action == "SUSPEND":
        set_and_touch(site, status="SUSPENDED", last_inspection_result="FAIL")
        site_suspension_cascade(site, user_id, finding_code)
    else:
        set_and_touch(site, status="RETIRED")

    refresh_world()
    return ok(serializers.site(site))
