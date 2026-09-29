"""Invitation waves, interview blocks, invitations and panel staffing."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import endpoint, require_owns_applicant
from envelope import object_response
from errors import ApiError
from store import (
    WAVE_MIN_GAP_HOURS,
    dt_of,
    find,
    hours,
    insert,
    iso,
    must_find,
    new_row,
    now,
    now_iso,
    parse_iso,
    rows,
    touch,
)
from validators import (
    body,
    fk,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_id_list,
    req_int,
    req_str,
)
from routes.common import keep, listing

bp = Blueprint("waves", __name__)

WAVE_STATUSES = ("PLANNED", "RELEASED", "CLOSED")
SLOT_STATUSES = ("OPEN", "BOOKED", "COMPLETED", "CANCELLED")
INVITATION_STATUSES = (
    "ISSUED",
    "WAITLISTED",
    "ACCEPTED",
    "DECLINED",
    "EXPIRED",
    "WITHDRAWN",
)
ASSIGNMENT_STATUSES = ("ASSIGNED", "RELEASED")
POST_INTERVIEW_PHASES = (
    "RANKING",
    "LIST_CERTIFIED",
    "MATCH_COMPLETE",
    "SOAP_ACTIVE",
    "SEASON_CLOSED",
)


# ============================================================== InterviewWave
@bp.post("/interview-waves")
@endpoint("ProgramCoordinator")
def create_wave():
    data = body()
    program = fk(data, "program_id", "programs")
    if program is None:
        req_str(data, "program_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    wave_index = req_int(data, "wave_index", minimum=1)
    release_at = req_dt(data, "invite_release_at")
    deadline_at = req_dt(data, "response_deadline_at")
    seat_capacity = req_int(data, "seat_capacity", minimum=1)
    if deadline_at <= release_at:
        raise ApiError(
            "ERR_VALIDATION", "response_deadline_at must be strictly after invite_release_at."
        )

    gap = hours(WAVE_MIN_GAP_HOURS)
    for other in calc.program_waves(program["id"]):
        other_release = dt_of(other, "invite_release_at")
        other_deadline = dt_of(other, "response_deadline_at")
        separated = (
            release_at >= other_deadline + gap or deadline_at + gap <= other_release
        )
        if not separated:
            raise ApiError(
                "ERR_WAVE_WINDOW_CONFLICT",
                "The wave window is less than %d hours from an existing wave."
                % WAVE_MIN_GAP_HOURS,
            )

    for other in calc.program_waves(program["id"]):
        if other["wave_index"] == wave_index:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "wave_index is already used by this program.")

    row = new_row(
        program_id=program["id"],
        wave_index=wave_index,
        invite_release_at=iso(release_at),
        response_deadline_at=iso(deadline_at),
        seat_capacity=seat_capacity,
        status="PLANNED",
    )
    insert("interview_waves", row)
    return object_response(serializers.interview_wave(row), 201)


@bp.get("/interview-waves")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin")
def list_waves():
    items = rows("interview_waves")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "status", q_enum("status", WAVE_STATUSES))
    return listing(items, serializers.interview_wave)


@bp.get("/interview-waves/<wave_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin")
def read_wave(wave_id):
    return object_response(serializers.interview_wave(must_find("interview_waves", wave_id)))


@bp.post("/interview-waves/<wave_id>/release")
@endpoint("ProgramCoordinator")
def release_wave(wave_id):
    wave = must_find("interview_waves", wave_id)
    program = helpers.program_of_wave(wave)
    helpers.require_state(wave, "status", ("PLANNED",))
    helpers.require_phase(program, ("INTERVIEWS_OPEN",))
    if now() < dt_of(wave, "invite_release_at"):
        helpers.invalid_state("The wave's invite_release_at instant has not been reached.")

    wave["status"] = "RELEASED"
    touch(wave)
    return object_response(serializers.interview_wave(wave))


@bp.post("/interview-waves/<wave_id>/close")
@endpoint("ProgramCoordinator")
def close_wave(wave_id):
    wave = must_find("interview_waves", wave_id)
    helpers.require_state(wave, "status", ("RELEASED",))

    wave["status"] = "CLOSED"
    helpers.close_wave_cascade(wave)
    touch(wave)
    return object_response(serializers.interview_wave(wave))


@bp.post("/interview-waves/<wave_id>/invitations")
@endpoint("ProgramCoordinator")
def issue_invitation(wave_id):
    wave = must_find("interview_waves", wave_id)
    data = body()
    application = fk(data, "application_id", "applications")
    if application is None:
        req_str(data, "application_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    expected_version = req_int(data, "expected_wave_version", minimum=0)

    program = helpers.program_of_wave(wave)

    # priority 5 - state admissibility that no later row owns
    if wave["status"] == "PLANNED":
        helpers.invalid_state("The wave has not been released.")
    if program["season_phase"] in ("PRE_SEASON", "REVIEW_OPEN"):
        helpers.invalid_state(
            "Program.season_phase is %s; invitations require INTERVIEWS_OPEN."
            % program["season_phase"]
        )
    if application["screening_status"] != "ADVANCED":
        helpers.invalid_state("Only an ADVANCED application may be invited.")
    if application["program_id"] != wave["program_id"]:
        helpers.invalid_state("The application belongs to a different program.")

    # priority 6 - optimistic concurrency on the wave
    if expected_version != wave["version"]:
        raise ApiError("ERR_STALE_WAVE_VERSION")

    # priority 11 - wave headroom
    issued = calc.issued_count(wave)
    waitlisted = calc.waitlisted_count(wave)
    capacity = wave["seat_capacity"]
    if wave["status"] == "CLOSED" or program["season_phase"] in POST_INTERVIEW_PHASES:
        raise ApiError("ERR_WAVE_CAPACITY_REACHED", "The wave can no longer absorb invitations.")
    if issued >= capacity and waitlisted >= capacity:
        raise ApiError(
            "ERR_WAVE_CAPACITY_REACHED", "Both the seats and the waitlist are full."
        )

    invitation = new_row(
        application_id=application["id"],
        wave_id=wave["id"],
        slot_id=None,
        status="ISSUED" if issued < capacity else "WAITLISTED",
        issued_at=None,
        expires_at=None,
        responded_at=None,
    )
    if invitation["status"] == "ISSUED":
        helpers.stamp_issued(invitation, wave)
    insert("interview_invitations", invitation)

    if invitation["status"] == "ISSUED" and application["interview_status"] == "NOT_INVITED":
        application["interview_status"] = "INVITED"
        touch(application)

    touch(wave)
    helpers.recompute_program_counters(program)
    return object_response(serializers.interview_invitation(invitation), 201)


# ============================================================== InterviewSlot
@bp.post("/interview-slots")
@endpoint("ProgramCoordinator")
def create_slot():
    data = body()
    wave = fk(data, "wave_id", "interview_waves")
    if wave is None:
        req_str(data, "wave_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    start_at = req_dt(data, "start_at")
    end_at = req_dt(data, "end_at")
    room_label = req_str(data, "room_label")
    capacity = req_int(data, "applicant_capacity", minimum=1)

    if end_at <= start_at:
        raise ApiError("ERR_SLOT_TIMING_VIOLATION", "end_at must be strictly after start_at.")
    window_open = dt_of(wave, "invite_release_at")
    window_close = dt_of(wave, "response_deadline_at")
    if start_at < window_open or end_at > window_close:
        raise ApiError(
            "ERR_SLOT_TIMING_VIOLATION", "The slot must lie inside the wave's window."
        )

    row = new_row(
        wave_id=wave["id"],
        start_at=iso(start_at),
        end_at=iso(end_at),
        room_label=room_label,
        applicant_capacity=capacity,
        status="OPEN",
    )
    insert("interview_slots", row)
    return object_response(serializers.interview_slot(row), 201)


@bp.get("/interview-slots")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "NrmpAdmin", "Applicant")
def list_slots():
    items = rows("interview_slots")
    items = keep(items, "wave_id", q_str("wave_id"))
    items = keep(items, "status", q_enum("status", SLOT_STATUSES))
    return listing(items, serializers.interview_slot)


@bp.get("/interview-slots/<slot_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "NrmpAdmin", "Applicant")
def read_slot(slot_id):
    return object_response(serializers.interview_slot(must_find("interview_slots", slot_id)))


@bp.post("/interview-slots/<slot_id>/complete")
@endpoint("ProgramCoordinator")
def complete_slot(slot_id):
    slot = must_find("interview_slots", slot_id)
    data = body()
    no_show_ids = req_id_list(data, "no_show_application_ids", [])
    for application_id in no_show_ids:
        if find("applications", application_id) is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND")

    helpers.require_state(slot, "status", ("OPEN", "BOOKED"))
    if now() < dt_of(slot, "end_at"):
        raise ApiError(
            "ERR_SLOT_TIMING_VIOLATION", "The slot cannot be completed before its end_at."
        )

    slot["status"] = "COMPLETED"
    for invitation in calc.slot_invitations(slot["id"]):
        if invitation["status"] != "ACCEPTED":
            continue
        application = helpers.application_of_invitation(invitation)
        if application is None:
            continue
        if application["interview_status"] == "SCHEDULED":
            application["interview_status"] = (
                "NO_SHOW" if application["id"] in no_show_ids else "COMPLETED"
            )
            touch(application)

    helpers.refresh_faculty(
        [a["faculty_member_id"] for a in calc.slot_assignments(slot["id"])]
    )
    touch(slot)
    return object_response(serializers.interview_slot(slot))


@bp.post("/interview-slots/<slot_id>/cancel")
@endpoint("ProgramCoordinator")
def cancel_slot(slot_id):
    slot = must_find("interview_slots", slot_id)
    helpers.require_state(slot, "status", ("OPEN", "BOOKED"))
    if now() >= dt_of(slot, "start_at"):
        raise ApiError(
            "ERR_SLOT_TIMING_VIOLATION", "The slot has already started and cannot be cancelled."
        )

    helpers.cancel_slot_cascade(slot)
    slot["status"] = "CANCELLED"
    touch(slot)
    return object_response(serializers.interview_slot(slot))


# ========================================================= InterviewInvitation
@bp.get("/interview-invitations")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def list_invitations():
    items = rows("interview_invitations")
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "wave_id", q_str("wave_id"))
    items = keep(items, "slot_id", q_str("slot_id"))
    items = keep(items, "status", q_enum("status", INVITATION_STATUSES))
    return listing(items, serializers.interview_invitation)


@bp.get("/interview-invitations/<invitation_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "ComplianceOfficer", "NrmpAdmin", "Applicant")
def read_invitation(invitation_id):
    return object_response(
        serializers.interview_invitation(must_find("interview_invitations", invitation_id))
    )


@bp.post("/interview-invitations/<invitation_id>/accept")
@endpoint("Applicant")
def accept_invitation(invitation_id):
    invitation = must_find("interview_invitations", invitation_id)
    data = body()
    slot = fk(data, "slot_id", "interview_slots")
    if slot is None:
        req_str(data, "slot_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    wave = helpers.wave_of_invitation(invitation)
    application = helpers.application_of_invitation(invitation)

    helpers.require_state(invitation, "status", ("ISSUED",))
    if wave is None or wave["status"] != "RELEASED":
        helpers.invalid_state("The invitation's wave is not RELEASED.")
    if slot["status"] in ("COMPLETED", "CANCELLED"):
        helpers.invalid_state("The chosen slot is %s." % slot["status"])
    for other in calc.application_invitations(invitation["application_id"]):
        if other["id"] != invitation["id"] and other["status"] == "ACCEPTED":
            helpers.invalid_state("The application already holds an accepted invitation.")

    require_owns_applicant(application["applicant_id"] if application else None)

    if slot["wave_id"] != invitation["wave_id"]:
        raise ApiError(
            "ERR_CROSS_REFERENCE_MISMATCH", "The slot belongs to a different wave."
        )

    expires_at = dt_of(invitation, "expires_at")
    if expires_at is not None and now() >= expires_at:
        raise ApiError("ERR_INVITATION_EXPIRED")

    if calc.booked_count(slot) >= slot["applicant_capacity"]:
        raise ApiError("ERR_SLOT_FULL")

    invitation["status"] = "ACCEPTED"
    invitation["slot_id"] = slot["id"]
    invitation["responded_at"] = now_iso()
    touch(invitation)

    helpers.consume_seat(slot)

    if application is not None and application["interview_status"] == "INVITED":
        application["interview_status"] = "SCHEDULED"
        touch(application)

    return object_response(serializers.interview_invitation(invitation))


@bp.post("/interview-invitations/<invitation_id>/decline")
@endpoint("Applicant")
def decline_invitation(invitation_id):
    invitation = must_find("interview_invitations", invitation_id)
    wave = helpers.wave_of_invitation(invitation)
    application = helpers.application_of_invitation(invitation)

    helpers.require_state(invitation, "status", ("ISSUED", "ACCEPTED"))
    if wave is None or wave["status"] != "RELEASED":
        helpers.invalid_state("The invitation's wave is not RELEASED.")
    slot = find("interview_slots", invitation.get("slot_id"))
    if invitation["status"] == "ACCEPTED" and slot is not None:
        start_at = dt_of(slot, "start_at")
        if start_at is not None and now() >= start_at:
            helpers.invalid_state("The booked interview has already started.")

    require_owns_applicant(application["applicant_id"] if application else None)

    was_accepted = invitation["status"] == "ACCEPTED"
    invitation["status"] = "DECLINED"
    invitation["responded_at"] = now_iso()
    invitation["slot_id"] = None
    touch(invitation)

    if was_accepted:
        helpers.release_seat(slot)

    if application is not None:
        if application["interview_status"] in ("INVITED", "SCHEDULED"):
            helpers.revert_to_not_invited(application)

    helpers.promote_waitlist(wave)
    touch(wave)
    helpers.recompute_program_counters(helpers.program_of_wave(wave))
    return object_response(serializers.interview_invitation(invitation))


@bp.post("/interview-invitations/<invitation_id>/reschedule")
@endpoint("Applicant")
def reschedule_invitation(invitation_id):
    invitation = must_find("interview_invitations", invitation_id)
    wave = helpers.wave_of_invitation(invitation)
    application = helpers.application_of_invitation(invitation)

    helpers.require_state(invitation, "status", ("ACCEPTED",))
    if wave is None or wave["status"] != "RELEASED":
        helpers.invalid_state("The invitation's wave is not RELEASED.")
    if now() >= dt_of(wave, "response_deadline_at"):
        helpers.invalid_state("The wave's response deadline has passed.")

    require_owns_applicant(application["applicant_id"] if application else None)

    slot = find("interview_slots", invitation.get("slot_id"))
    if slot is not None:
        start_at = dt_of(slot, "start_at")
        if start_at is not None and now() >= start_at:
            raise ApiError(
                "ERR_SLOT_TIMING_VIOLATION",
                "The booked interview has started; it can no longer be rescheduled.",
            )

    invitation["status"] = "ISSUED"
    invitation["slot_id"] = None
    invitation["responded_at"] = None
    helpers.stamp_issued(invitation, wave)
    touch(invitation)

    helpers.release_seat(slot)

    if application is not None and application["interview_status"] == "SCHEDULED":
        application["interview_status"] = "INVITED"
        touch(application)

    helpers.promote_waitlist(wave)
    return object_response(serializers.interview_invitation(invitation))


# ========================================================= InterviewAssignment
@bp.post("/interview-assignments")
@endpoint("ProgramCoordinator")
def create_assignment():
    data = body()
    slot = fk(data, "slot_id", "interview_slots")
    faculty = fk(data, "faculty_member_id", "faculty_members")
    if slot is None or faculty is None:
        req_str(data, "slot_id")
        req_str(data, "faculty_member_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    panel_role = req_enum(data, "panel_role", ("LEAD", "MEMBER"))

    # priority 7 - conflict of interest against every applicant booked here
    conflicts = faculty.get("conflict_applicant_ids") or []
    if conflicts:
        for invitation in calc.slot_invitations(slot["id"]):
            if invitation["status"] != "ACCEPTED":
                continue
            application = helpers.application_of_invitation(invitation)
            if application is not None and application["applicant_id"] in conflicts:
                raise ApiError("ERR_CONFLICT_OF_INTEREST")

    # priority 9 - half-open, unbuffered double booking
    start_at = dt_of(slot, "start_at")
    end_at = dt_of(slot, "end_at")
    for other in calc.faculty_assignments(faculty["id"]):
        if other["status"] != "ASSIGNED" or other["slot_id"] == slot["id"]:
            continue
        other_slot = find("interview_slots", other["slot_id"])
        if other_slot is None:
            continue
        other_start = dt_of(other_slot, "start_at")
        other_end = dt_of(other_slot, "end_at")
        if start_at < other_end and other_start < end_at:
            raise ApiError("ERR_INTERVIEWER_DOUBLE_BOOKED")

    # priority 10 - one panel seat per (slot, faculty member)
    for other in calc.slot_assignments(slot["id"]):
        if other["faculty_member_id"] == faculty["id"]:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "This interviewer is already staffed on the slot."
            )

    row = new_row(
        slot_id=slot["id"],
        faculty_member_id=faculty["id"],
        panel_role=panel_role,
        status="ASSIGNED",
    )
    insert("interview_assignments", row)
    touch(faculty)
    return object_response(serializers.interview_assignment(row), 201)


@bp.get("/interview-assignments")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "NrmpAdmin")
def list_assignments():
    items = rows("interview_assignments")
    items = keep(items, "slot_id", q_str("slot_id"))
    items = keep(items, "faculty_member_id", q_str("faculty_member_id"))
    items = keep(items, "status", q_enum("status", ASSIGNMENT_STATUSES))
    return listing(items, serializers.interview_assignment)


@bp.get("/interview-assignments/<assignment_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "NrmpAdmin")
def read_assignment(assignment_id):
    return object_response(
        serializers.interview_assignment(must_find("interview_assignments", assignment_id))
    )


@bp.post("/interview-assignments/<assignment_id>/release")
@endpoint("ProgramCoordinator")
def release_assignment(assignment_id):
    assignment = must_find("interview_assignments", assignment_id)
    helpers.require_state(assignment, "status", ("ASSIGNED",))

    assignment["status"] = "RELEASED"
    touch(assignment)
    helpers.refresh_faculty([assignment["faculty_member_id"]])
    return object_response(serializers.interview_assignment(assignment))
