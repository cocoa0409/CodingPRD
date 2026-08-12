"""Safety incidents, holds and the return to service (PRD §3.9)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import (
    CREW_RELEASE_REASON_CASCADE,
    HORSE_HOLD_REASON_INCIDENT,
    HORSE_POST_INCIDENT_REST_DAYS,
    INCIDENT_HOLD_MATRIX,
    INCIDENT_REPORT_DEADLINE_HOURS,
    INCIDENT_SEVERITY_MATRIX,
    INCIDENT_TYPES,
    OPEN_ENDED_SUSPENSION_INSTANT,
    VOLUNTEER_SUSPENSION_DAYS_SEV_1,
    VOLUNTEER_SUSPENSION_REASON_SEV_1,
    VOLUNTEER_SUSPENSION_REASON_SEV_2,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404, session_or_404
from core.store import all_rows, clock, db, new_row, touch
from domain import derive, policy, serialize

bp = Blueprint("incidents", __name__)

INCIDENT_STATUSES = ["OPEN", "UNDER_REVIEW", "CLOSED"]
SEVERITIES = ["SEV_1", "SEV_2", "SEV_3"]


@bp.post("/sessions/<session_id>/incidents")
@endpoint(["Instructor", "ProgramAdmin"])
def file_incident(session_id):
    payload = validate_body([
        Field("incident_type", "enum", required=True, members=INCIDENT_TYPES),
        Field("injury_reported", "bool", required=True),
        Field("occurred_at", "instant", required=True),
        Field("narrative", "string", required=True),
        Field("implicated_volunteer_id", "string"),
    ])
    session = session_or_404(session_id)
    volunteer = None
    if payload.get("implicated_volunteer_id"):
        volunteer = resource_or_404("volunteers", payload["implicated_volunteer_id"])

    occurred_at = T.echoed(payload["occurred_at"])
    severity = INCIDENT_SEVERITY_MATRIX[(payload["incident_type"],
                                         payload["injury_reported"])]
    reported_at = clock.stamp()
    report_due_at = T.derived(T.plus_hours(occurred_at.dt,
                                           INCIDENT_REPORT_DEADLINE_HOURS[severity]))
    matrix = INCIDENT_HOLD_MATRIX[severity]

    row = new_row("incidents")
    row.update({
        "session_id": session["id"],
        "implicated_volunteer_id": volunteer["id"] if volunteer else None,
        "incident_type": payload["incident_type"],
        "injury_reported": payload["injury_reported"],
        "occurred_at": occurred_at,
        "narrative": payload["narrative"],
        "severity": severity,
        "reported_at": reported_at,
        "report_due_at": report_due_at,
        "reported_late": reported_at.dt > report_due_at.dt,
        "rider_hold_applied": matrix["rider_medical_hold"],
        "horse_hold_applied": matrix["horse_rest_hold"],
        "volunteer_suspension_applied": bool(matrix["volunteer_suspension"] and volunteer),
        "instructor_suspension_applied": matrix["instructor_suspension"],
        "cancelled_session_count": 0,
        "status": "OPEN",
        "reviewer_notes": None,
        "resolution": None,
    })

    if row["rider_hold_applied"]:
        _apply_rider_hold(row, session)
    if row["horse_hold_applied"]:
        _apply_horse_hold(row, session, occurred_at)
    if row["volunteer_suspension_applied"]:
        _apply_volunteer_suspension(row, volunteer, severity, occurred_at)
    if row["instructor_suspension_applied"]:
        _apply_instructor_suspension(row, session)
    return object_response(serialize.incident(row), 201)


def _apply_rider_hold(incident, session):
    """HOP 1 -> HOP 2 -> HOP 3 -> HOP 4 of incident_hold_cascade."""
    rider = db["riders"].get(session["rider_id"])
    if rider is None or rider["status"] != "ACTIVE":
        return
    rider["status"] = "MEDICAL_HOLD"
    rider["medical_hold_incident_id"] = incident["id"]
    touch(rider)

    now = clock.now()
    cancelled = 0
    for other in all_rows("sessions"):
        if other["rider_id"] != rider["id"]:
            continue
        if other["schedule_status"] not in ("CREW_PENDING", "CONFIRMED"):
            continue
        if other["scheduled_start"].dt <= now:
            continue
        # HOP 2: cancelled with RIDER_HOLD and NO fee, whatever the notice window.
        other["schedule_status"] = "CANCELLED"
        other["cancellation_reason"] = "RIDER_HOLD"
        touch(other)
        cancelled += 1
        # HOP 3: every ASSIGNED crew assignment on it is released.
        for assignment in derive.session_assignments(other["id"]):
            if assignment["status"] != "ASSIGNED":
                continue
            assignment["status"] = "RELEASED"
            assignment["release_reason"] = CREW_RELEASE_REASON_CASCADE
            touch(assignment)
        # HOP 4: Volunteer.open_assignment_count is derived from the assignments
        # above, so releasing them IS the downward re-derivation.
    incident["cancelled_session_count"] = cancelled


def _apply_horse_hold(incident, session, occurred_at):
    horse = db["horses"].get(session["horse_id"])
    if horse is None or horse["status"] != "AVAILABLE":
        return
    horse["status"] = "REST_HOLD"
    # §2.5: a cascade-placed hold_release_at is DERIVED and therefore renders
    # with three fractional digits, unlike a manual hold's echoed release_at.
    horse["hold_release_at"] = T.derived(T.plus_days(occurred_at.dt,
                                                     HORSE_POST_INCIDENT_REST_DAYS))
    horse["hold_reason"] = HORSE_HOLD_REASON_INCIDENT
    horse["_hold_incident_id"] = incident["id"]
    touch(horse)


def _apply_volunteer_suspension(incident, volunteer, severity, occurred_at):
    if volunteer is None:
        return
    if severity == "SEV_1":
        volunteer["suspended_until"] = T.derived(
            T.plus_days(occurred_at.dt, VOLUNTEER_SUSPENSION_DAYS_SEV_1))
        volunteer["suspension_reason"] = VOLUNTEER_SUSPENSION_REASON_SEV_1
    else:
        volunteer["suspended_until"] = T.echoed(OPEN_ENDED_SUSPENSION_INSTANT)
        volunteer["suspension_reason"] = VOLUNTEER_SUSPENSION_REASON_SEV_2
    volunteer["_suspension_incident_id"] = incident["id"]
    touch(volunteer)


def _apply_instructor_suspension(incident, session):
    # Adjudication of friction 6 (§3.9): when a session names BOTH an instructor
    # of record and a supervising instructor, a SEV_1 suspension attaches to
    # BOTH.  Gate 1 and gate 4 each evaluate the supervising instructor's
    # SUSPENDED status and the incident cascade is the only producer of
    # SUSPENDED, so suspending both is the reading that keeps those declared
    # refusals reachable.
    for instructor in policy.session_instructors(session):
        if instructor.get("suspended_until") is not None:
            continue
        instructor["suspended_until"] = T.echoed(OPEN_ENDED_SUSPENSION_INSTANT)
        instructor["_suspension_incident_id"] = incident["id"]
        touch(instructor)


@bp.get("/incidents")
@endpoint(["Instructor", "ProgramAdmin"])
def list_incidents():
    limit, offset = pagination()
    status = query_enum("status", INCIDENT_STATUSES)
    severity = query_enum("severity", SEVERITIES)
    session_id = request.args.get("session_id")
    volunteer_id = request.args.get("implicated_volunteer_id")
    rows = all_rows("incidents")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if volunteer_id is not None:
        rows = [r for r in rows if r.get("implicated_volunteer_id") == volunteer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    page = paginate(rows, limit, offset)
    return list_response([serialize.incident(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/incidents/<incident_id>")
@endpoint(["Instructor", "ProgramAdmin"])
def read_incident(incident_id):
    return object_response(serialize.incident(
        resource_or_404("incidents", incident_id)))


@bp.post("/incidents/<incident_id>/review")
@endpoint(["ProgramAdmin"])
def review_incident(incident_id):
    payload = validate_body([Field("reviewer_notes", "string", required=True)])
    row = resource_or_404("incidents", incident_id)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN incident may be reviewed.")
    row["status"] = "UNDER_REVIEW"
    row["reviewer_notes"] = payload["reviewer_notes"]
    touch(row)
    return object_response(serialize.incident(row))


@bp.post("/incidents/<incident_id>/close")
@endpoint(["ProgramAdmin"])
def close_incident(incident_id):
    payload = validate_body([
        Field("resolution", "string", required=True),
        Field("release_rider_hold", "bool", required=True),
        Field("release_horse_hold", "bool", required=True),
        Field("release_volunteer_suspension", "bool", required=True),
    ])
    row = resource_or_404("incidents", incident_id)
    if row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW incident may be closed.")

    row["status"] = "CLOSED"
    row["resolution"] = payload["resolution"]

    if payload["release_rider_hold"]:
        for rider in db["riders"].values():
            if rider.get("medical_hold_incident_id") == row["id"]:
                # The rider STAYS in MEDICAL_HOLD; only a fresh physician
                # clearance returns them to riding.
                rider["medical_hold_incident_id"] = None
                touch(rider)
    if payload["release_horse_hold"]:
        for horse in db["horses"].values():
            if horse.get("_hold_incident_id") == row["id"] \
                    and horse["status"] == "REST_HOLD" \
                    and horse.get("hold_reason") == HORSE_HOLD_REASON_INCIDENT:
                horse["status"] = "AVAILABLE"
                horse["hold_release_at"] = None
                horse["hold_reason"] = None
                horse["_hold_incident_id"] = None
                touch(horse)
    if payload["release_volunteer_suspension"]:
        volunteer = db["volunteers"].get(row.get("implicated_volunteer_id"))
        if volunteer is not None and volunteer.get("suspended_until") is not None:
            volunteer["suspended_until"] = None
            volunteer["suspension_reason"] = None
            volunteer["_suspension_incident_id"] = None
            touch(volunteer)
    # The suspended instructor is released UNCONDITIONALLY on close.
    for instructor in db["instructors"].values():
        if instructor.get("_suspension_incident_id") == row["id"]:
            instructor["suspended_until"] = None
            instructor["_suspension_incident_id"] = None
            touch(instructor)
    touch(row)
    return object_response(serialize.incident(row))
