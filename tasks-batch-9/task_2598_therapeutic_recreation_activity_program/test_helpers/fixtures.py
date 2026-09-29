"""Setup builders.

The database is empty at the start of every test, so all state is built through
declared endpoints. Every builder here returns the response payload of the row
it created, and every builder uses the lenient setup validator so a broken
precondition is reported as a setup failure rather than as a test failure.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    AIDE_HEADERS,
    COMPLIANCE_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    THERAPIST_HEADERS,
    make_council_rep_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: the logical clock and version reads
# ---------------------------------------------------------------------------
def advance_clock(api, current_utc):
    """Move the logical clock forward; time is monotonic so this never rewinds."""
    return get_success_data(api.set_clock(current_utc, DIRECTOR_HEADERS))


def resident_version(api, resident_id):
    """The resident's current version, for the plan-create concurrency echo."""
    return get_success_data(api.get_resident(resident_id, THERAPIST_HEADERS))["version"]


def vehicle_version(api, vehicle_id):
    """The vehicle's current version, for the transport-booking concurrency echo."""
    return get_success_data(api.get_vehicle(vehicle_id, DIRECTOR_HEADERS))["version"]


def read_resident(api, resident_id, headers=None):
    return get_success_data(api.get_resident(resident_id, headers or DIRECTOR_HEADERS))


def read_plan(api, plan_id, headers=None):
    return get_success_data(api.get_activity_plan(plan_id, headers or THERAPIST_HEADERS))


def read_session(api, session_id, headers=None):
    return get_success_data(api.get_session(session_id, headers or DIRECTOR_HEADERS))


def read_record(api, record_id, headers=None):
    return get_success_data(api.get_participation(record_id, headers or AIDE_HEADERS))


def read_volunteer(api, volunteer_id, headers=None):
    return get_success_data(api.get_volunteer(volunteer_id, headers or COORDINATOR_HEADERS))


def read_assignment(api, assignment_id, headers=None):
    return get_success_data(
        api.get_volunteer_assignment(assignment_id, headers or COORDINATOR_HEADERS)
    )


def read_outing(api, outing_id, headers=None):
    return get_success_data(api.get_outing(outing_id, headers or DIRECTOR_HEADERS))


def read_vehicle(api, vehicle_id, headers=None):
    return get_success_data(api.get_vehicle(vehicle_id, headers or DIRECTOR_HEADERS))


def read_consent(api, consent_id, headers=None):
    return get_success_data(api.get_outing_consent(consent_id, headers or DIRECTOR_HEADERS))


def read_packet(api, packet_id, headers=None):
    return get_success_data(api.get_survey_packet(packet_id, headers or COMPLIANCE_HEADERS))


def read_program(api, program_id, headers=None):
    return get_success_data(api.get_program(program_id, headers or DIRECTOR_HEADERS))


def read_council_request(api, request_id, headers=None):
    return get_success_data(
        api.get_council_request(request_id, headers or DIRECTOR_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 1: single rows
# ---------------------------------------------------------------------------
def create_resident(api, **kwargs):
    """An admitted resident with no clinical record yet."""
    return get_success_data(
        api.create_resident(f.resident_payload(**kwargs), DIRECTOR_HEADERS)
    )


def file_assessment(api, resident_id, headers=None, **kwargs):
    """File one immutable assessment against a resident."""
    return get_success_data(
        api.create_assessment(
            resident_id, f.assessment_payload(**kwargs), headers or THERAPIST_HEADERS
        )
    )


def assessed_resident(api, resident_kwargs=None, **assessment_kwargs):
    """A resident plus their governing assessment, returned as a pair."""
    resident = create_resident(api, **(resident_kwargs or {}))
    assessment = file_assessment(api, resident["id"], **assessment_kwargs)
    return resident, assessment


def create_program(api, **kwargs):
    return get_success_data(
        api.create_program(f.program_payload(**kwargs), DIRECTOR_HEADERS)
    )


def create_room(api, **kwargs):
    return get_success_data(api.create_room(f.room_payload(**kwargs), DIRECTOR_HEADERS))


def create_vehicle(api, **kwargs):
    return get_success_data(
        api.create_vehicle(f.vehicle_payload(**kwargs), DIRECTOR_HEADERS)
    )


def create_session(api, program_id, room_id, **kwargs):
    """One SCHEDULED calendar slot."""
    return get_success_data(
        api.create_session(
            f.session_payload(program_id, room_id, **kwargs), DIRECTOR_HEADERS
        )
    )


def create_volunteer(api, **kwargs):
    """A volunteer applicant, screening level NONE."""
    return get_success_data(
        api.create_volunteer(f.volunteer_payload(**kwargs), COORDINATOR_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchies
# ---------------------------------------------------------------------------
def calendar(api, program_kwargs=None, room_kwargs=None):
    """A program plus a room, the two rows every session needs."""
    return (
        create_program(api, **(program_kwargs or {})),
        create_room(api, **(room_kwargs or {})),
    )


def draft_plan(api, resident_id, assessment_id, targets=None, **kwargs):
    """A DRAFT plan carrying a freshly read resident version."""
    payload = f.plan_payload(
        resident_id,
        assessment_id,
        resident_version(api, resident_id),
        targets=targets,
        **kwargs,
    )
    return get_success_data(api.create_activity_plan(payload, THERAPIST_HEADERS))


def active_plan(api, resident_id, assessment_id, targets=None, **kwargs):
    """A plan driven straight from DRAFT to ACTIVE."""
    plan = draft_plan(api, resident_id, assessment_id, targets=targets, **kwargs)
    get_success_data(
        api.transition_activity_plan(plan["id"], {"action": "ACTIVATE"}, THERAPIST_HEADERS)
    )
    return read_plan(api, plan["id"])


def resident_with_active_plan(api, targets=None, plan_kwargs=None, **assessment_kwargs):
    """An admitted, assessed resident whose plan is already ACTIVE."""
    resident, assessment = assessed_resident(api, **assessment_kwargs)
    plan = active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=targets,
        **(plan_kwargs or {}),
    )
    return resident, assessment, plan


def enroll(api, session_id, resident_id, headers=None, **kwargs):
    """Create one PLANNED participation row."""
    return get_success_data(
        api.create_enrollment(
            session_id,
            f.enrollment_payload(resident_id, **kwargs),
            headers or AIDE_HEADERS,
        )
    )


def assign_volunteer(api, volunteer_id, session_id, **kwargs):
    """Create one PROPOSED volunteer assignment."""
    return get_success_data(
        api.create_volunteer_assignment(
            f.assignment_payload(volunteer_id, session_id, **kwargs), COORDINATOR_HEADERS
        )
    )


def confirm_assignment(api, assignment_id):
    return get_success_data(
        api.update_volunteer_assignment(
            assignment_id, {"status": "CONFIRMED"}, COORDINATOR_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------
def screened_volunteer(api, cleared_on="2026-07-01", **kwargs):
    """A volunteer in SCREENING with screening_level BASIC."""
    volunteer = create_volunteer(api, **kwargs)
    get_success_data(
        api.volunteer_screening(
            volunteer["id"],
            {"event_type": "BACKGROUND_CHECK_CLEARED", "cleared_on": cleared_on},
            COORDINATOR_HEADERS,
        )
    )
    return read_volunteer(api, volunteer["id"])


def cleared_volunteer(
    api, cleared_on="2026-07-01", completed_on="2026-07-05", **kwargs
):
    """A volunteer in CLEARED with screening_level FULL."""
    volunteer = screened_volunteer(api, cleared_on=cleared_on, **kwargs)
    get_success_data(
        api.volunteer_screening(
            volunteer["id"],
            {"event_type": "ORIENTATION_COMPLETED", "completed_on": completed_on},
            COORDINATOR_HEADERS,
        )
    )
    return read_volunteer(api, volunteer["id"])


def start_session(api, session_id, headers=None):
    """Drive SCHEDULED to IN_PROGRESS; the clock must already have reached starts_at."""
    return get_success_data(
        api.session_status(session_id, {"action": "START"}, headers or AIDE_HEADERS)
    )


def close_documentation(api, session_id, headers=None):
    return get_success_data(
        api.session_status(
            session_id, {"action": "CLOSE_DOCUMENTATION"}, headers or AIDE_HEADERS
        )
    )


def cancel_session(api, session_id, cancel_reason="Cancelled for the test"):
    return get_success_data(
        api.session_status(
            session_id,
            {"action": "CANCEL", "cancel_reason": cancel_reason},
            DIRECTOR_HEADERS,
        )
    )


def document_attendance(api, record_id, engagement_level="ACTIVE", headers=None, **kw):
    return get_success_data(
        api.document_participation(
            record_id,
            f.attendance_payload(engagement_level=engagement_level, **kw),
            headers or AIDE_HEADERS,
        )
    )


def document_refusal(api, record_id, refusal_reason="FATIGUE", headers=None, **kw):
    return get_success_data(
        api.document_participation(
            record_id,
            f.refusal_payload(refusal_reason=refusal_reason, **kw),
            headers or AIDE_HEADERS,
        )
    )


def document_absence(api, record_id, headers=None, **kw):
    return get_success_data(
        api.document_participation(
            record_id, f.absence_payload(**kw), headers or AIDE_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------
def run_session_with_outcome(
    api,
    program_id,
    room_id,
    resident_id,
    starts_at,
    ends_at,
    outcome,
    engagement_level="ACTIVE",
    refusal_reason="FATIGUE",
    clock_at=None,
):
    """Schedule one slot, enrol the resident, start it and document one outcome.

    Returns the session and record payloads. ``clock_at`` defaults to the
    session's own ``starts_at``, which is the earliest instant a START is legal.
    """
    session = create_session(
        api, program_id, room_id, starts_at=starts_at, ends_at=ends_at
    )
    record = enroll(api, session["id"], resident_id)
    advance_clock(api, clock_at or starts_at)
    start_session(api, session["id"])
    if outcome == "ATTENDED":
        document_attendance(api, record["id"], engagement_level=engagement_level)
    elif outcome == "REFUSED":
        document_refusal(api, record["id"], refusal_reason=refusal_reason)
    elif outcome == "ABSENT":
        document_absence(api, record["id"])
    return session, read_record(api, record["id"])


def hourly_sessions(api, program_id, room_id, starts, duration_minutes=45):
    """One SCHEDULED slot per instant in ``starts``, all in the same room."""
    sessions = []
    for starts_at in starts:
        hour = int(starts_at[11:13])
        minute = int(starts_at[14:16]) + duration_minutes
        ends_at = f"{starts_at[:11]}{hour + minute // 60:02d}:{minute % 60:02d}:00Z"
        sessions.append(
            create_session(
                api, program_id, room_id, starts_at=starts_at, ends_at=ends_at
            )
        )
    return sessions


def build_refusal_streak(api, program_id, room_id, resident_id, starts, latest_clock):
    """Document a refusal on one slot per instant in ``starts``, oldest first."""
    sessions = hourly_sessions(api, program_id, room_id, starts)
    records = [enroll(api, s["id"], resident_id) for s in sessions]
    advance_clock(api, latest_clock)
    for session in sessions:
        start_session(api, session["id"])
    for record in records:
        document_refusal(api, record["id"])
    return sessions, [read_record(api, r["id"]) for r in records]


# ---------------------------------------------------------------------------
# Tier 5: outings, transport and terminal survey states
# ---------------------------------------------------------------------------
def create_outing(api, program_id, vehicle_id, **kwargs):
    """A PLANNING outing with a COLLECTING consent dimension."""
    return get_success_data(
        api.create_outing(f.outing_payload(program_id, vehicle_id, **kwargs), DIRECTOR_HEADERS)
    )


def add_rider(api, outing_id, resident_id, headers=None, **kwargs):
    """Add one REQUESTED consent row, which already counts toward the manifest."""
    return get_success_data(
        api.create_outing_consent(
            outing_id, f.consent_payload(resident_id, **kwargs), headers or DIRECTOR_HEADERS
        )
    )


def decide_consent(api, outing_id, consent_id, decision, headers=None, **kwargs):
    payload = {"decision": decision}
    payload.update({k: v for k, v in kwargs.items() if v is not None})
    return get_success_data(
        api.decide_outing_consent(
            outing_id, consent_id, payload, headers or DIRECTOR_HEADERS
        )
    )


def granted_rider(api, outing_id, resident_id, expires_on=None, **kwargs):
    """Add a rider and grant their consent in one step."""
    consent = add_rider(api, outing_id, resident_id, **kwargs)
    decide_consent(
        api, outing_id, consent["id"], "GRANTED", expires_on=expires_on
    )
    return read_consent(api, consent["id"])


def book_transport(api, outing_id, expected_version=None, vehicle_id=None):
    """Reserve seats, echoing a freshly read vehicle version by default."""
    if expected_version is None:
        expected_version = vehicle_version(api, vehicle_id)
    return get_success_data(
        api.book_transport(
            outing_id, {"expected_vehicle_version": expected_version}, DIRECTOR_HEADERS
        )
    )


def logistics(api, outing_id, action, **kwargs):
    payload = {"action": action}
    payload.update({k: v for k, v in kwargs.items() if v is not None})
    return get_success_data(api.outing_logistics(outing_id, payload, DIRECTOR_HEADERS))


def council_request(api, resident_id, **kwargs):
    """A SUBMITTED council request filed by the resident's own representative."""
    return get_success_data(
        api.create_council_request(
            f.council_request_payload(resident_id, **kwargs),
            make_council_rep_headers(resident_id),
        )
    )


def open_packet(api, headers=None, **kwargs):
    """An OPEN survey packet with every score field null."""
    return get_success_data(
        api.create_survey_packet(f.packet_payload(**kwargs), headers or COMPLIANCE_HEADERS)
    )


def compiled_packet(api, headers=None, **kwargs):
    """A COMPILED packet; the caller must have moved the clock past window_end."""
    packet = open_packet(api, headers=headers, **kwargs)
    return get_success_data(
        api.compile_survey_packet(packet["id"], {}, headers or COMPLIANCE_HEADERS)
    )


def attest_packet(api, packet_id, headers, remediation_note=None):
    payload = {"action": "ATTEST"}
    if remediation_note is not None:
        payload["remediation_note"] = remediation_note
    return get_success_data(api.attest_survey_packet(packet_id, payload, headers))
