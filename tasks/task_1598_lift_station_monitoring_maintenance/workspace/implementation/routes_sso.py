"""SsoEvent routes: record/list/get and the regulatory reporting pipeline
(PRD 3.8; OCC via expected_station_version per PRD 2.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STATION_FROZEN,
    ERR_STALE_VERSION,
    ERR_REPORT_DEADLINE_MISSED,
)
from helpers import (
    body, bad, is_int, req_enum, req_instant, req_bool, opt_str, paginate,
    CAUSE_CODES,
)
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_sso_event

bp = Blueprint("sso_events", __name__)

SSO_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "Operator", "ComplianceOfficer",
    "RegulatorPortal",
)

STANDARD_DEADLINE_HOURS = 24
SURFACE_WATER_DEADLINE_HOURS = 12


def get_sso_or_404(eid):
    e = db.sso_events.get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "SSO event not found")
    return e


@bp.post("/stations/<sid>/sso-events")
def create_sso_event(sid):
    require_roles("ScadaWebhook", "Operator", "UtilityAdmin")
    st = get_station_or_404(sid)
    # posture gate; recording an SSO is an SSO-lifecycle action (EMERGENCY ok)
    if st["operational_posture"] == "FROZEN":
        raise ApiError(
            ERR_STATION_FROZEN, 409,
            "Station %s is FROZEN; child mutations are refused" % sid,
        )
    b = body()
    # OCC guard (PRD 2.6)
    expected = b.get("expected_station_version")
    if expected is None or not is_int(expected):
        bad("expected_station_version is required and must be an integer")
    if expected != st["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_station_version does not match the station's current version",
        )
    # shape (priority 30)
    started = req_instant(b, "started_at")
    cause = req_enum(b, "cause_code", CAUSE_CODES)
    surface = req_bool(b, "reached_surface_water")
    hours = SURFACE_WATER_DEADLINE_HOURS if surface else STANDARD_DEADLINE_HOURS
    e = {
        "id": db.new_id(),
        "station_id": sid,
        "started_at": started,
        "stopped_at": None,
        "estimated_volume_gal": None,
        "cause_code": cause,
        "status": "OPEN",
        "regulator_deadline_at": started + timedelta(hours=hours),
        "report_submitted_at": None,
        "report_accepted_at": None,
        "reached_surface_water": surface,
    }
    db.stamp(e)
    db.sso_events[e["id"]] = e
    # EMERGENCY cascade: abort scheduled generator tests, cancel draft permits.
    for t in db.generator_tests.values():
        if t["station_id"] == sid and t["status"] == "SCHEDULED":
            t["status"] = "ABORTED"
            db.touch(t)
    for p in db.confined_space_permits.values():
        if p["station_id"] == sid and p["status"] == "DRAFT":
            p["status"] = "CANCELLED"
            db.touch(p)
    # Posture -> EMERGENCY, last_sso_occurred_at set; explicit version bump.
    services.sync_station(st, force_bump=True)
    return success(ser_sso_event(e), 201)


@bp.get("/stations/<sid>/sso-events")
def list_station_sso_events(sid):
    require_roles(*SSO_READ_ROLES)
    get_station_or_404(sid)
    items = [e for e in db.sso_events.values() if e["station_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items)
    return success([ser_sso_event(e) for e in page], 200, meta)


@bp.get("/sso-events")
def list_sso_events():
    require_roles(*SSO_READ_ROLES)
    items = list(db.sso_events.values())
    stid = request.args.get("station_id")
    if stid is not None:
        items = [e for e in items if e["station_id"] == stid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    cause = request.args.get("cause_code")
    if cause is not None:
        items = [e for e in items if e["cause_code"] == cause]
    page, meta = paginate(items)
    return success([ser_sso_event(e) for e in page], 200, meta)


@bp.get("/sso-events/<eid>")
def get_sso_event(eid):
    require_roles(*SSO_READ_ROLES)
    return success(ser_sso_event(get_sso_or_404(eid)))


# --------------------------------------------------------------------- pipeline


def _sso_gate(e):
    """Shared guards for SSO lifecycle actions: station must not be FROZEN;
    EMERGENCY is the normal operating posture for these actions."""
    st = db.stations[e["station_id"]]
    if st["operational_posture"] == "FROZEN":
        raise ApiError(
            ERR_STATION_FROZEN, 409,
            "Station %s is FROZEN; child mutations are refused" % st["id"],
        )
    return st


@bp.post("/sso-events/<eid>/contain")
def contain_sso(eid):
    require_roles("Operator")
    e = get_sso_or_404(eid)
    if e["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN SSO event can be contained")
    st = _sso_gate(e)
    if st["operational_posture"] != "EMERGENCY":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Containment is only permitted while the station is in EMERGENCY",
        )
    e["stopped_at"] = db.now()
    # provisional volume variant: capacity as computed at stopped_at
    e["estimated_volume_gal"] = services.compute_sso_volume(e, st)
    e["status"] = "CONTAINED"
    db.touch(e)
    services.sync_station(st)
    return success(ser_sso_event(e))


@bp.post("/sso-events/<eid>/draft-report")
def draft_report(eid):
    require_roles("ComplianceOfficer")
    e = get_sso_or_404(eid)
    if e["status"] != "CONTAINED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a CONTAINED SSO event can move to REPORT_DRAFT"
        )
    st = _sso_gate(e)
    e["status"] = "REPORT_DRAFT"
    db.touch(e)
    services.sync_station(st)
    return success(ser_sso_event(e))


@bp.post("/sso-events/<eid>/submit-report")
def submit_report(eid):
    require_roles("ComplianceOfficer")
    e = get_sso_or_404(eid)
    if e["status"] != "REPORT_DRAFT":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a REPORT_DRAFT SSO event can be submitted",
        )
    st = _sso_gate(e)
    b = body()
    override = b.get("override_note")
    # temporal (priority 21): on-time submission, or late with an override note
    if db.now() > e["regulator_deadline_at"]:
        if not isinstance(override, str) or not override.strip():
            raise ApiError(
                ERR_REPORT_DEADLINE_MISSED, 422,
                "Submission is past regulator_deadline_at and no override_note "
                "was provided",
            )
    e["report_submitted_at"] = db.now()
    # final volume variant: capacity snapshot at submission time
    e["estimated_volume_gal"] = services.compute_sso_volume(e, st)
    e["status"] = "REPORT_SUBMITTED"
    db.touch(e)
    services.sync_station(st)
    return success(ser_sso_event(e))


@bp.post("/sso-events/<eid>/accept-report")
def accept_report(eid):
    require_roles("RegulatorPortal")
    e = get_sso_or_404(eid)
    if e["status"] != "REPORT_SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a REPORT_SUBMITTED SSO event can be accepted",
        )
    st = _sso_gate(e)
    e["report_accepted_at"] = db.now()
    e["status"] = "REPORT_ACCEPTED"
    db.touch(e)
    # last_sso_occurred_at and posture recompute (event leaves the active set)
    services.sync_station(st)
    return success(ser_sso_event(e))


@bp.post("/sso-events/<eid>/reject-report")
def reject_report(eid):
    require_roles("RegulatorPortal")
    e = get_sso_or_404(eid)
    if e["status"] != "REPORT_SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a REPORT_SUBMITTED SSO event can be rejected",
        )
    st = _sso_gate(e)
    e["status"] = "REPORT_DRAFT"
    db.touch(e)
    services.sync_station(st)
    return success(ser_sso_event(e))


@bp.post("/sso-events/<eid>/close")
def close_sso(eid):
    require_roles("ComplianceOfficer")
    e = get_sso_or_404(eid)
    if e["status"] != "REPORT_ACCEPTED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a REPORT_ACCEPTED SSO event can be closed",
        )
    st = _sso_gate(e)
    e["status"] = "CLOSED"
    db.touch(e)
    # last_sso_occurred_at and posture recompute
    services.sync_station(st)
    return success(ser_sso_event(e))
