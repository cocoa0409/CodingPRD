"""Session crewing: leader and sidewalker assignments (PRD §3.4)."""

from flask import Blueprint, request

from core.constants import (
    CREW_ROLES_ASSIGNMENT,
    CREW_ROLE_MIN_AGE,
    HOLD_TYPES_CREW,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404, session_or_404
from core.store import all_rows, db, new_row, touch
from domain import derive, gates, policy, serialize, workload

bp = Blueprint("crew", __name__)

ASSIGNMENT_STATUSES = ["ASSIGNED", "RELEASED"]


@bp.post("/sessions/<session_id>/crew-assignments")
@endpoint(["VolunteerCoordinator", "ProgramAdmin", "Instructor"])
def create_assignment(session_id):
    payload = validate_body([
        Field("volunteer_id", "string", required=True),
        Field("crew_role", "enum", required=True, members=CREW_ROLES_ASSIGNMENT),
        Field("expected_session_version", "int", required=True),
        Field("hold_type", "enum", members=HOLD_TYPES_CREW),
    ])
    session = session_or_404(session_id)                                      # rung 10
    volunteer = resource_or_404("volunteers", payload["volunteer_id"])        # rung 13

    rider = db["riders"].get(session["rider_id"])
    horse = db["horses"].get(session["horse_id"])
    gates.gate_incident_hold(rider=rider, horse=horse, volunteer=volunteer,   # rung 14
                             instructors=policy.session_instructors(session))

    role = payload["crew_role"]
    sidewalkers, leaders = derive.crew_counts(session["id"])
    required_sidewalkers = rider.get("required_sidewalker_count") or 0
    requires_leader = bool(rider.get("requires_leader"))
    if role == "SIDEWALKER":                                                  # rung 33
        if required_sidewalkers <= 0 or sidewalkers >= required_sidewalkers:
            fail("ERR_CREW_ROLE_NOT_REQUIRED",
                 "The rider does not need another sidewalker.")
    else:
        if not requires_leader or leaders >= 1:
            fail("ERR_CREW_ROLE_NOT_REQUIRED", "The rider does not need another leader.")

    for assignment in derive.session_assignments(session["id"]):              # rung 34
        if assignment["status"] == "ASSIGNED" \
                and assignment["volunteer_id"] == volunteer["id"]:
            fail("ERR_DUPLICATE_CREW_ASSIGNMENT",
                 "That volunteer is already crewing this session.")

    if workload.volunteer_overlap(volunteer["id"], session) is not None:      # rung 35
        fail("ERR_VOLUNTEER_SCHEDULE_CONFLICT",
             "The volunteer is already crewing an overlapping session.")

    status = derive.volunteer_status(volunteer)                               # rung 36
    if status != "ACTIVE":
        fail("ERR_VOLUNTEER_SUSPENDED", "The volunteer is %s." % status)

    if derive.age_years(volunteer["date_of_birth"]) < CREW_ROLE_MIN_AGE[role]:  # 37
        fail("ERR_VOLUNTEER_UNDER_AGE",
             "The volunteer is below the minimum age for %s." % role)

    qualified = any(q["crew_role"] == role
                    and derive.qualification_status(q) == "QUALIFIED"
                    for q in derive.volunteer_qualifications(volunteer["id"]))
    if not qualified:                                                         # rung 38
        fail("ERR_VOLUNTEER_NOT_QUALIFIED",
             "The volunteer holds no QUALIFIED %s qualification." % role)

    hold_type = payload.get("hold_type")                                      # rung 39
    if role == "SIDEWALKER":
        if hold_type is None or hold_type != rider.get("sidewalker_hold_type"):
            fail("ERR_HOLD_TYPE_MISMATCH",
                 "A sidewalker must carry the rider's hold type.")
    elif hold_type is not None:
        fail("ERR_HOLD_TYPE_MISMATCH", "A leader assignment carries no hold type.")

    if payload["expected_session_version"] != session["version"]:             # rung 44
        fail("ERR_STALE_VERSION",
             "Expected session version %s but the stored version is %s."
             % (payload["expected_session_version"], session["version"]))

    row = new_row("crew_assignments")
    row.update({
        "session_id": session["id"],
        "volunteer_id": volunteer["id"],
        "crew_role": role,
        "hold_type": hold_type,
        "status": "ASSIGNED",
        "release_reason": None,
    })
    touch(session)
    return object_response(serialize.crew_assignment(row), 201)


@bp.get("/crew-assignments")
@endpoint(["VolunteerCoordinator", "ProgramAdmin", "Instructor"])
def list_assignments():
    limit, offset = pagination()
    status = query_enum("status", ASSIGNMENT_STATUSES)
    session_id = request.args.get("session_id")
    volunteer_id = request.args.get("volunteer_id")
    rows = all_rows("crew_assignments")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if volunteer_id is not None:
        rows = [r for r in rows if r["volunteer_id"] == volunteer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.crew_assignment(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/crew-assignments/<assignment_id>")
@endpoint(["VolunteerCoordinator", "ProgramAdmin", "Instructor"])
def read_assignment(assignment_id):
    row = resource_or_404("crew_assignments", assignment_id)
    return object_response(serialize.crew_assignment(row))


@bp.post("/crew-assignments/<assignment_id>/release")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def release_assignment(assignment_id):
    payload = validate_body([Field("reason", "string", required=True)])
    row = resource_or_404("crew_assignments", assignment_id)
    if row["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "That assignment is already released.")
    row["status"] = "RELEASED"
    row["release_reason"] = payload["reason"]
    touch(row)
    session = db["sessions"].get(row["session_id"])
    if session is not None and session["schedule_status"] == "CONFIRMED" \
            and not derive.crew_satisfied(session):
        # The reversible edge: a CONFIRMED session drops back to CREW_PENDING
        # without any operator touching the session itself.
        session["schedule_status"] = "CREW_PENDING"
        touch(session)
    return object_response(serialize.crew_assignment(row))
