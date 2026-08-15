"""Appointment scheduling and lifecycle (PRD §3.3).

Pipeline order for writes (PRD §2.8): auth -> role -> existence (canonical
left-to-right: site, volunteer, taxpayer, appointment) -> schema -> cardinality
(station capacity, tier 7) -> temporal (window before volunteer overlap,
tier 8) -> cross-entity state gates (site CERTIFIED/OPEN, volunteer ACTIVE,
tier 9).
"""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import cascades, scheduling
from services.serialize import appointment_json
from validation import get_body, parse_body, require_entity

bp = Blueprint("appointments", __name__)

APPOINTMENT_STATUSES = ["SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED",
                        "NO_SHOW"]

CREATE_SCHEMA = {
    "site_id": {"kind": "string", "required": True},
    "taxpayer_id": {"kind": "string", "required": True},
    "volunteer_id": {"kind": "string", "required": True},
    "purpose": {"kind": "enum", "required": True,
                "values": ["INTAKE", "PREPARATION", "FOLLOW_UP"]},
    "start_at": {"kind": "datetime", "required": True},
    "end_at": {"kind": "datetime", "required": True},
}

PATCH_SCHEMA = {
    "start_at": {"kind": "datetime"},
    "end_at": {"kind": "datetime"},
    "volunteer_id": {"kind": "string"},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": APPOINTMENT_STATUSES},
}


def _run_write_gates(site, volunteer_id, start_at, end_at, exclude_id=None):
    """Cardinality (tier 7) then temporal (tier 8): capacity, window, overlap."""
    count = scheduling.overlapping_site_count(site["id"], start_at, end_at,
                                              exclude_id=exclude_id)
    if count >= site["station_capacity"]:
        raise ApiError("ERR_SITE_CAPACITY_FULL", 409,
                       "Overlapping-appointment count has reached station_capacity")
    if scheduling.violates_window(site, start_at, end_at):
        raise ApiError("ERR_OUTSIDE_SITE_WINDOW", 422,
                       "Appointment violates season bounds, daily hours, "
                       "past-start, or the 15..120 minute duration")
    if scheduling.volunteer_conflict(volunteer_id, start_at, end_at,
                                     exclude_id=exclude_id):
        raise ApiError("ERR_APPOINTMENT_OVERLAP_VOLUNTEER", 409,
                       "Assigned volunteer already has an overlapping appointment")


@bp.post("/appointments")
def create_appointment():
    get_context()
    require_roles(["Screener", "SiteCoordinator"])
    raw = get_body()
    # Existence (tier 3) in canonical order: site, volunteer, taxpayer.
    site_id = raw.get("site_id")
    volunteer_id = raw.get("volunteer_id")
    taxpayer_id = raw.get("taxpayer_id")
    if isinstance(site_id, str) and site_id not in store.sites:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced site does not exist")
    if isinstance(volunteer_id, str) and volunteer_id not in store.volunteers:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced volunteer does not exist")
    if isinstance(taxpayer_id, str) and taxpayer_id not in store.taxpayers:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced taxpayer does not exist")
    body = parse_body(CREATE_SCHEMA)
    site = store.sites[body["site_id"]]
    volunteer = store.volunteers[body["volunteer_id"]]

    _run_write_gates(site, body["volunteer_id"], body["start_at"], body["end_at"])

    # Cross-entity state gates (tier 9).
    if site["status"] not in ("CERTIFIED", "OPEN"):
        raise ApiError("ERR_SITE_NOT_OPEN", 409,
                       "Appointment creation requires the site to be CERTIFIED or OPEN")
    if volunteer["status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_NOT_ACTIVE", 409,
                       "Assigned volunteer is not ACTIVE")

    appt = db.new_common({
        "site_id": body["site_id"],
        "taxpayer_id": body["taxpayer_id"],
        "volunteer_id": body["volunteer_id"],
        "purpose": body["purpose"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "SCHEDULED",
    })
    store.appointments[appt["id"]] = appt
    return created(appointment_json(appt))


@bp.get("/appointments")
def list_appointments():
    get_context()
    rows = list(store.appointments.values())
    for f in ("site_id", "taxpayer_id", "volunteer_id", "status"):
        rows = paginate.filter(rows, f)
    page = paginate(rows)
    return ok([appointment_json(a) for a in page], rtype="array",
              pagination=paginate)


@bp.get("/appointments/<appt_id>")
def get_appointment(appt_id):
    get_context()
    appt = require_entity(store.appointments, appt_id)
    return ok(appointment_json(appt))


@bp.patch("/appointments/<appt_id>")
def patch_appointment(appt_id):
    get_context()
    require_roles(["Screener", "SiteCoordinator"])
    raw = get_body()
    # Existence (tier 3), canonical order: a referenced volunteer id ranks
    # before the appointment in the path.
    vid = raw.get("volunteer_id")
    if isinstance(vid, str) and vid not in store.volunteers:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced volunteer does not exist")
    appt = require_entity(store.appointments, appt_id)
    body = parse_body(PATCH_SCHEMA)

    # State legality (tier 5): rescheduling only while SCHEDULED.
    if appt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Only a SCHEDULED appointment may be rescheduled")

    start_at = body.get("start_at", appt["start_at"])
    end_at = body.get("end_at", appt["end_at"])
    volunteer_id = body.get("volunteer_id", appt["volunteer_id"])

    window_changed = (("start_at" in body and start_at != appt["start_at"])
                      or ("end_at" in body and end_at != appt["end_at"]))
    conflict_changed = (window_changed
                        or ("volunteer_id" in body
                            and volunteer_id != appt["volunteer_id"]))

    if conflict_changed or window_changed:
        site = store.sites[appt["site_id"]]
        # Capacity (tier 7) and volunteer exclusion (tier 8) re-run when the
        # interval or assignee changes; window rules (tier 8) only when the
        # interval endpoints change. Self is excluded from the counts.
        if conflict_changed:
            count = scheduling.overlapping_site_count(
                appt["site_id"], start_at, end_at, exclude_id=appt["id"])
            if count >= site["station_capacity"]:
                raise ApiError("ERR_SITE_CAPACITY_FULL", 409,
                               "Overlapping-appointment count has reached "
                               "station_capacity")
        if window_changed and scheduling.violates_window(site, start_at, end_at):
            raise ApiError("ERR_OUTSIDE_SITE_WINDOW", 422,
                           "Appointment violates season bounds, daily hours, "
                           "past-start, or the 15..120 minute duration")
        if conflict_changed and scheduling.volunteer_conflict(
                volunteer_id, start_at, end_at, exclude_id=appt["id"]):
            raise ApiError("ERR_APPOINTMENT_OVERLAP_VOLUNTEER", 409,
                           "Assigned volunteer already has an overlapping "
                           "appointment")

    appt["start_at"] = start_at
    appt["end_at"] = end_at
    appt["volunteer_id"] = volunteer_id
    db.touch(appt)
    return ok(appointment_json(appt))


@bp.post("/appointments/<appt_id>/state")
def transition_appointment(appt_id):
    get_context()
    require_roles(["Screener", "SiteCoordinator"])
    appt = require_entity(store.appointments, appt_id)
    body = parse_body(STATE_SCHEMA)
    current = appt["status"]
    target = body["to_status"]

    if current == "SCHEDULED" and target == "CHECKED_IN":
        # Cross-entity gate (tier 9): the hosting site must be OPEN.
        site = store.sites[appt["site_id"]]
        if site["status"] != "OPEN":
            raise ApiError("ERR_SITE_NOT_OPEN", 409,
                           "Check-in requires the site to be OPEN")
        appt["status"] = "CHECKED_IN"
        db.touch(appt)
    elif current == "CHECKED_IN" and target == "COMPLETED":
        appt["status"] = "COMPLETED"
        db.touch(appt)
    elif current in ("SCHEDULED", "CHECKED_IN") and target == "CANCELLED":
        cascades.cancel_appointment(appt, "APPOINTMENT_CANCELLED")
    elif current == "SCHEDULED" and target == "NO_SHOW":
        if db.LOGICAL_CLOCK < appt["start_at"]:
            raise ApiError("ERR_INVALID_TRANSITION", 409,
                           "Appointment cannot be marked NO_SHOW before start_at")
        appt["status"] = "NO_SHOW"
        db.touch(appt)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move appointment from %s to %s" % (current, target))

    return ok(appointment_json(appt))
