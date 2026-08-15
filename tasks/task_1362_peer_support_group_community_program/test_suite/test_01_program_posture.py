"""Program creation, safety posture derivation, and posture gating (PRD §2.7, §3.1, §3.7)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_program,
    create_incident_payload,
    get_success_data,
    make_active_group,
    make_active_participant,
    make_confirmed_enrollment,
    make_enrollment,
    make_facilitator_headers,
    make_incident,
    make_participant,
    make_program,
    make_session,
    NON_EXISTENT_UUID,
    reset_clock,
    schedule_session,
    setup_in_progress_session,
    setup_program_in_posture,
    sign_agreement,
    validate_error,
    validate_success,
)


class TestProgramCreation:
    def test_program_creation_required_fields(self, api):
        """PRD §3.1: "Creation fixes `posture` at `OPEN` and zeroes
        `active_critical_incident_count`, `active_standard_incident_count`, and
        `scheduled_session_count`, the last of which tracks how many sessions
        under the program currently sit in `SCHEDULED`."

        Design: Corner/entities/program_creation_required_fields
        """
        reset_clock()
        resp = api.create_program({"name": "P", "focus_area": "GRIEF"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["posture"] == "OPEN", f"new program posture must be OPEN, got {data['posture']}"
        assert data["active_critical_incident_count"] == 0
        assert data["active_standard_incident_count"] == 0
        assert data["scheduled_session_count"] == 0

    def test_program_get_not_found_returns_404(self, api):
        """PRD §2.6: "the server validates existence strictly left to right and
        rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing resource".

        Design: Corner/entities/program_get_not_found_returns_404
        """
        reset_clock()
        resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPostureDerivation:
    def test_posture_open_when_zero_incidents_at_creation(self, api):
        """PRD §2.7: "When the critical count is greater than zero, posture is
        `LOCKDOWN`. Otherwise, when the standard count is greater than zero,
        posture is `CAUTION`. Otherwise posture is `OPEN`."
        PRD §2.7: "A new program starts with `posture` `OPEN` and both counters
        at zero."

        Design: Corner/calculations/program_posture_threshold_boundary_one_critical_locks_down
        """
        reset_clock()
        program = make_program(name="P", focus_area="GRIEF")
        fetched = validate_success(api.get_program(program["id"], ADMIN))
        assert fetched["posture"] == "OPEN"
        assert fetched["active_critical_incident_count"] == 0
        assert fetched["active_standard_incident_count"] == 0

    def test_posture_caution_when_only_standard_incidents(self, api):
        """PRD §2.7: "Otherwise, when the standard count is greater than zero,
        posture is `CAUTION`."
        PRD §3.7: "Creation immediately feeds the program's posture derivation
        of §2.7: a new open critical report pushes the program into `LOCKDOWN`,
        and a standard one into `CAUTION`."

        Design: Corner/state_machines/program_posture_caution_when_only_standard_incidents
        """
        env = setup_in_progress_session()
        make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="STANDARD", category="OTHER",
            description="minor")
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "CAUTION", (
            f"expected CAUTION with one STANDARD incident, got {program['posture']}")
        assert program["active_standard_incident_count"] == 1
        assert program["active_critical_incident_count"] == 0


class TestCriticalIncidentLockdownCascade:
    def test_critical_incident_pushes_program_to_lockdown(self, api):
        """PRD §3.7: "Creation immediately feeds the program's posture
        derivation of §2.7: a new open critical report pushes the program into
        `LOCKDOWN`, and a standard one into `CAUTION`."
        PRD §2.7: "The threshold is strict: a count of exactly one is already
        past zero, so a single open critical incident forces lockdown."

        Design: Difficulty/transitive_cascade/incident_critical_cascade_lockdown_then_session_cascade
        """
        env = setup_in_progress_session()
        program_before = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program_before["posture"] == "OPEN"

        incident = make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="CRITICAL", category="SAFETY",
            description="Critical incident during session")
        assert incident["status"] == "OPEN"

        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "LOCKDOWN", (
            f"one open CRITICAL incident must force LOCKDOWN, got {program['posture']}")
        assert program["active_critical_incident_count"] == 1

    def test_lockdown_blocks_session_scheduling_and_check_in(self, api):
        """PRD §2.7: "Under `LOCKDOWN`, three write operations are blocked and
        rejected with `ERR_PROGRAM_LOCKED_DOWN` (HTTP 409): scheduling a
        session, confirming an enrollment, and checking in an attendance
        record."

        Design: Difficulty/transitive_cascade/incident_critical_cascade_lockdown_then_session_cascade
        """
        env = setup_in_progress_session()
        participant, _ = make_active_participant()
        make_confirmed_enrollment(env.program["id"], env.group["id"], participant["id"])
        make_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.facilitator["id"], severity="CRITICAL", category="SAFETY",
            description="critical")
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "LOCKDOWN"

        # Check-in on the IN_PROGRESS session is blocked.
        checkin = api.check_in(
            env.program["id"], env.group["id"], env.session["id"],
            {"participant_id": participant["id"], "access_modality": "IN_PERSON"},
            make_facilitator_headers(env.facilitator["id"]))
        validate_error(checkin, ApiErrorId.ERR_PROGRAM_LOCKED_DOWN)

        # Scheduling a fresh DRAFT session is blocked.
        draft = make_session(
            env.program["id"], env.group["id"], env.facilitator["id"],
            start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z",
            room_id=env.room["id"])
        version_resp = get_success_data(api.get_facilitator(env.facilitator["id"], ADMIN))
        sched = api.schedule_session(
            env.program["id"], env.group["id"], draft["id"],
            {"expected_facilitator_version": version_resp["version"]}, ADMIN)
        validate_error(sched, ApiErrorId.ERR_PROGRAM_LOCKED_DOWN)


class TestPostureGatesEnrollmentCreation:
    def test_lockdown_blocks_new_enrollment_creation(self, api):
        """PRD §3.4: "The group must be `ACTIVE` (otherwise
        `ERR_GROUP_NOT_ACTIVE`), and the program must not be in `CAUTION` or
        `LOCKDOWN`: caution blocks creation with
        `ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT`."
        PRD §2.7: "Only incident-resolution work (acknowledge, resolve,
        escalate) and read operations remain available under lockdown."

        Design: Corner/cross_cutting/posture_lockdown_blocks_new_enrollment_creation
        """
        env = setup_program_in_posture(severity="CRITICAL")
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "LOCKDOWN"
        participant, _ = make_active_participant()
        resp = api.create_enrollment(
            env.program["id"], env.group["id"],
            {"participant_id": participant["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_LOCKED_DOWN)

    def test_caution_blocks_new_enrollments_but_allows_scheduling(self, api):
        """PRD §2.7: "Under `CAUTION`, the creation of new enrollments is
        blocked with `ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT` (HTTP 409), while
        existing `CONFIRMED` enrollments are unaffected and sessions may
        proceed and may be newly scheduled."

        Design: Corner/cross_cutting/posture_caution_allows_sessions_but_blocks_new_enrollments
        """
        env = setup_program_in_posture(severity="STANDARD")
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "CAUTION"

        participant, _ = make_active_participant()
        resp = api.create_enrollment(
            env.program["id"], env.group["id"],
            {"participant_id": participant["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT)

        # Sessions may still be newly scheduled under CAUTION.
        draft = make_session(
            env.program["id"], env.group["id"], env.facilitator["id"],
            start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z",
            room_id=env.room["id"])
        scheduled = schedule_session(env.program["id"], env.group["id"], draft["id"])
        assert scheduled["status"] == "SCHEDULED"


class TestIncidentHandlingSideEffects:
    def test_acknowledge_preserves_lockdown_posture(self, api):
        """PRD §3.7: "Acknowledging moves `OPEN` → `ACKNOWLEDGED` and
        re-evaluates posture; the report remains in the active set, so
        acknowledgment alone does not relax the posture."

        Design: Corner/endpoints/incident_acknowledge_side_effect_preserves_posture
        """
        env = setup_program_in_posture(severity="CRITICAL")
        ack = validate_success(api.acknowledge_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.incident["id"], ADMIN))
        assert ack["status"] == "ACKNOWLEDGED"
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["posture"] == "LOCKDOWN", (
            "acknowledgment alone must not relax the posture")
        assert program["active_critical_incident_count"] == 1

    def test_resolve_last_critical_restores_open(self, api):
        """PRD §3.7: "Resolving moves `ACKNOWLEDGED` → `RESOLVED`, decrements
        the program's `active_critical_incident_count` or
        `active_standard_incident_count` according to the report's severity,
        and re-evaluates posture — so when the last critical report is
        resolved and no standard reports remain, the program returns to
        `OPEN`."

        Design: Corner/endpoints/incident_resolve_side_effect_decrements_count_and_restores_open
        """
        env = setup_program_in_posture(severity="CRITICAL")
        get_success_data(api.acknowledge_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.incident["id"], ADMIN))
        resolved = validate_success(api.resolve_incident(
            env.program["id"], env.group["id"], env.session["id"],
            env.incident["id"], ADMIN))
        assert resolved["status"] == "RESOLVED"
        program = validate_success(api.get_program(env.program["id"], ADMIN))
        assert program["active_critical_incident_count"] == 0
        assert program["posture"] == "OPEN", (
            f"resolving the last critical report must return posture to OPEN, got {program['posture']}")
