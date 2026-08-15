"""Incident reports: file (severity escalation ladder), read, list, clear,
order-shutdown (license REVOKED cascade)."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DAY_POSTURE,
    ERR_CROSS_FAIR_REFERENCE,
    ERR_INCIDENT_INVALID_STATE,
)
from helpers import get_or_404, paginate, qparam, fair_id_of_incident
from middleware import authenticate, scope_to_fair
from response import ok
from services.cascades import (
    minor_incident_cascade,
    serious_incident_cascade,
    revoke_license_cascade,
)
from validators import get_body, reject_unknown, req_str, req_int, req_enum

bp = Blueprint("incidents", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

SEVERITIES = ["NEAR_MISS", "MINOR", "SERIOUS", "FATAL"]


@bp.post("/incident-reports")
def create_incident():
    ctx = authenticate(["FairManager", "RideOperator"])
    body = get_body()
    reject_unknown(body, {"ride_id", "operating_day_id", "severity", "injury_count", "description"})
    ride_id = req_str(body, "ride_id")
    day_id = req_str(body, "operating_day_id")
    severity = req_enum(body, "severity", SEVERITIES)
    injury_count = req_int(body, "injury_count", lo=0)
    description = req_str(body, "description")
    if severity in ("SERIOUS", "FATAL") and injury_count < 1:
        raise_err(ERR_INVALID_REQUEST, "SERIOUS and FATAL reports require injury_count >= 1")
    ride = db.get("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"] if ride else None)
    ride = get_or_404("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"])
    day = get_or_404("operating_days", day_id)
    if day["posture"] not in ("OPEN", "WEATHER_HOLD"):
        raise_err(ERR_INVALID_DAY_POSTURE, "Incidents are filed only while the day is OPEN or WEATHER_HOLD")
    if day["fair_id"] != ride["fair_id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The operating day belongs to a different fair than the ride")
    incident = db.register(
        "incidents",
        {
            "ride_id": ride_id,
            "operating_day_id": day_id,
            "reporter_staff_id": ctx["user_id"],
            "severity": severity,
            "injury_count": injury_count,
            "description": description,
            "status": "FILED",
            "cleared_by_inspector_id": None,
            "cleared_at": None,
        },
    )
    if severity == "MINOR":
        minor_incident_cascade(ride)
    elif severity == "SERIOUS":
        serious_incident_cascade(ride)
    elif severity == "FATAL":
        revoke_license_cascade(ride, day_id, from_statuses=("LICENSED",))
    # NEAR_MISS: informational, no counter moves
    return ok(serialize(incident), 201)


@bp.get("/incident-reports/<iid>")
def get_incident(iid):
    ctx = authenticate(ALL)
    incident = get_or_404("incidents", iid)
    scope_to_fair(ctx, fair_id_of_incident(incident))
    return ok(serialize(incident))


@bp.get("/incident-reports")
def list_incidents():
    authenticate(ALL)
    return paginate(
        "incidents",
        {
            "ride_id": qparam("ride_id"),
            "operating_day_id": qparam("operating_day_id"),
            "reporter_staff_id": qparam("reporter_staff_id"),
            "cleared_by_inspector_id": qparam("cleared_by_inspector_id"),
            "severity": qparam("severity"),
            "status": qparam("status"),
        },
    )


@bp.post("/incident-reports/<iid>/clear")
def clear_incident(iid):
    ctx = authenticate(["StateInspector"])
    incident = get_or_404("incidents", iid)
    body = get_body()
    reject_unknown(body, set())
    if incident["status"] != "FILED":
        raise_err(ERR_INCIDENT_INVALID_STATE, "Only a FILED incident can be cleared")
    incident["status"] = "CLEARED"
    incident["cleared_by_inspector_id"] = ctx["user_id"]
    incident["cleared_at"] = db.now_iso()
    touch(incident)
    open_remaining = any(
        other
        for other in store["incidents"].values()
        if other["ride_id"] == incident["ride_id"]
        and other["operating_day_id"] == incident["operating_day_id"]
        and other["id"] != incident["id"]
        and other["status"] in ("FILED", "SHUTDOWN_ORDERED")
    )
    ride = db.get("rides", incident["ride_id"])
    if not open_remaining and ride is not None and ride["daily_status"] == "INCIDENT_HOLD":
        ride["daily_status"] = "CLOSED"
        touch(ride)
    return ok(serialize(incident))


@bp.post("/incident-reports/<iid>/order-shutdown")
def order_shutdown(iid):
    authenticate(["StateInspector"])
    incident = get_or_404("incidents", iid)
    body = get_body()
    reject_unknown(body, set())
    if incident["status"] != "FILED":
        raise_err(ERR_INCIDENT_INVALID_STATE, "Only a FILED incident can receive a shutdown order")
    incident["status"] = "SHUTDOWN_ORDERED"
    touch(incident)
    ride = db.get("rides", incident["ride_id"])
    if ride is not None:
        revoke_license_cascade(ride, incident["operating_day_id"], from_statuses=("LICENSED", "SUSPENDED"))
    return ok(serialize(incident))
