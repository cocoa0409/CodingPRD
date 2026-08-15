"""Program cycles and participants: window overlap, lifecycle state guards,
enrollment window, close/reopen compensation, and terminal-state lockdowns."""
from test_helpers import (
    ApiErrorId,
    assert_cycle,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import cycle_payload
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    enroll_participant,
    grant_consent,
    set_clock,
    setup_active_cycle,
    setup_participant_with_consent,
    setup_program_with_approved_model,
)
from test_helpers.test_users import DIRECTOR, PRIVACY


class TestCycleWindows:
    def test_cycle_window_closed_interval_touch_conflicts(self, api):
        """PRD section 2.6: "**Program cycles** occupy a *closed* interval
        from `cycle_start` through `cycle_end`, inclusive of both endpoints.
        When a new cycle is created, its interval must not intersect the
        interval of any other cycle of the same program - and because the
        intervals are closed, two cycles that merely share a boundary instant
        **do** intersect and are rejected with `ERR_CYCLE_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_touch_conflicts
        """
        program = create_active_program(name="Garden", code="GRD")
        cycle_a = create_cycle(program["id"], label="A")
        assert cycle_a["status"] == "SETUP"

        touch_resp = api.create_cycle(
            program["id"],
            cycle_payload(label="B-touching",
                          cycle_start="2026-09-30T23:59:59Z",
                          cycle_end="2026-10-31T23:59:59Z",
                          reporting_due_date="2026-11-15T00:00:00Z"),
            DIRECTOR,
        )
        validate_error(touch_resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

        disjoint_resp = api.create_cycle(
            program["id"],
            cycle_payload(label="C-disjoint",
                          cycle_start="2026-10-01T00:00:00Z",
                          cycle_end="2026-10-31T23:59:59Z",
                          reporting_due_date="2026-11-15T00:00:00Z"),
            DIRECTOR,
        )
        disjoint = validate_success(disjoint_resp, expected_status=201)
        assert_cycle(disjoint)
        assert disjoint["status"] == "SETUP"

    def test_cycle_window_touch_rejected_disjoint_accepted(self, api):
        """PRD section 2.6: "When a new cycle is created, its interval must
        not intersect the interval of any other cycle of the same program -
        and because the intervals are closed, two cycles that merely share a
        boundary instant **do** intersect and are rejected with
        `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_touch_conflicts
        """
        program = create_active_program(name="Garden2", code="GR2")
        create_cycle(program["id"], label="A")

        # One second past the end of A: accepted.
        ok_resp = api.create_cycle(
            program["id"],
            cycle_payload(label="C-ok",
                          cycle_start="2026-10-01T00:00:00Z",
                          cycle_end="2026-10-31T23:59:59Z",
                          reporting_due_date="2026-11-15T00:00:00Z"),
            DIRECTOR,
        )
        validate_success(ok_resp, expected_status=201)

    def test_cycle_create_window_order_validated(self, api):
        """PRD section 2.6: "Cycle creation also requires `enrollment_start`
        to be on or before `enrollment_end` and `cycle_start` to be on or
        before `cycle_end`; violations of these ordering constraints are
        rejected with the same `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Corner/entities/cycle_create_window_order_validated
        """
        program = create_active_program(name="Order", code="ORD")
        bad_resp = api.create_cycle(
            program["id"],
            cycle_payload(label="BAD",
                          cycle_start="2026-10-01T00:00:00Z",
                          cycle_end="2026-09-01T00:00:00Z"),
            DIRECTOR,
        )
        validate_error(bad_resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)


class TestParticipantUniqueness:
    def test_participant_external_ref_uniqueness_scoped_to_cycle(self, api):
        """PRD section 3.4: "A `ProgramDirector` enrolls a participant by
        supplying an `external_ref` - a pseudonymous code that must be unique
        within the cycle (`ERR_DUPLICATE_CODE` on collision)."

        Design: Corner/entities/participant_external_ref_uniqueness_scoped_to_cycle
        """
        program = create_active_program(name="Refs", code="REF")
        c1 = create_cycle(program["id"], label="C1")
        c2 = create_cycle(
            program["id"], label="C2",
            cycle_start="2026-10-01T00:00:00Z",
            cycle_end="2026-10-31T23:59:59Z",
            reporting_due_date="2026-11-15T00:00:00Z")
        get_success_data(api.open_enrollment(c1["id"], DIRECTOR))
        get_success_data(api.open_enrollment(c2["id"], DIRECTOR))
        enroll_participant(c1["id"], external_ref="P-1")

        dup_resp = api.enroll_participant(
            c1["id"], {"external_ref": "P-1"}, DIRECTOR)
        validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_CODE)

        ok_resp = api.enroll_participant(
            c2["id"], {"external_ref": "P-1"}, DIRECTOR)
        ok = validate_success(ok_resp, expected_status=201)
        assert ok["external_ref"] == "P-1"


class TestCycleLifecycle:
    def test_close_data_from_setup_returns_invalid_state(self, api):
        """PRD section 3.4: "Every transition into or out of the wrong state
        is `ERR_INVALID_STATE`."
        PRD section 3.4: "closing data moves `ACTIVE → DATA_CLOSED`".

        Design: Corner/state_machines/close_data_from_setup_returns_invalid_state
        """
        program = create_active_program(name="States", code="STT")
        cycle = create_cycle(program["id"])

        close_resp = api.close_data(cycle["id"], DIRECTOR)
        validate_error(close_resp, ApiErrorId.ERR_INVALID_STATE)

        cycle_after = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_after["status"] == "SETUP"

    def test_close_and_reopen_data_compensates_participants(self, api):
        """PRD section 3.4: "closing data moves `ACTIVE → DATA_CLOSED`, and
        every participant still `ACTIVE` hops to `COMPLETED` - the cycle's
        `active_participant_count` is recomputed and becomes zero. If late
        corrections are needed, reopening moves `DATA_CLOSED → ACTIVE` and
        compensates exactly: every participant in `COMPLETED` returns to
        `ACTIVE` and the count is recomputed again."

        Design: Corner/state_machines/close_and_reopen_data_compensates_participants
        """
        base = setup_program_with_approved_model(program_name="Comp",
                                                 program_code="CMP")
        cycle = setup_active_cycle(base["program"])
        p1 = enroll_participant(cycle["id"], external_ref="P-001")
        p2 = enroll_participant(cycle["id"], external_ref="P-002")
        grant_consent(p1["id"])
        grant_consent(p2["id"])

        cycle_mid = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_mid["active_participant_count"] == 2

        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        p1_closed = get_success_data(api.get_participant(p1["id"], DIRECTOR))
        assert p1_closed["status"] == "COMPLETED"
        cycle_closed = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_closed["active_participant_count"] == 0

        reopened = get_success_data(api.reopen_data(cycle["id"], DIRECTOR))
        assert reopened["status"] == "ACTIVE"
        p1_reopen = get_success_data(api.get_participant(p1["id"], DIRECTOR))
        assert p1_reopen["status"] == "ACTIVE"
        cycle_reopen = get_success_data(api.get_cycle(cycle["id"], DIRECTOR))
        assert cycle_reopen["active_participant_count"] == 2


class TestRevertSetup:
    def test_revert_setup_requires_zero_participants(self, api):
        """PRD section 3.4: "If enrollment was opened prematurely, reverting
        moves `ENROLLING → SETUP`, but only while the cycle still has zero
        participants."

        Design: Corner/state_machines/revert_setup_requires_zero_participants
        """
        program = create_active_program(name="Revert", code="RVT")
        c1 = create_cycle(program["id"], label="C1")
        c2 = create_cycle(program["id"], label="C2",
                          cycle_start="2026-10-01T00:00:00Z",
                          cycle_end="2026-10-31T23:59:59Z",
                          reporting_due_date="2026-11-15T00:00:00Z")
        get_success_data(api.open_enrollment(c1["id"], DIRECTOR))
        get_success_data(api.open_enrollment(c2["id"], DIRECTOR))
        enroll_participant(c1["id"], external_ref="P-001")

        blocked = api.revert_setup(c1["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        reverted = validate_success(api.revert_setup(c2["id"], DIRECTOR))
        assert reverted["status"] == "SETUP"


class TestParticipantTerminalLockdown:
    def test_withdrawn_participant_terminal_exit_rejected(self, api):
        """PRD section 3.4: "`WITHDRAWN` is terminal and is reachable only
        through the consent-revocation cascade of §3.5."
        PRD section 3.4: "Every transition into or out of the wrong state is
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdrawn_participant_terminal_exit_rejected
        """
        base = setup_program_with_approved_model(program_name="Term", program_code="TRM")
        cycle = setup_active_cycle(base["program"])
        pc = setup_participant_with_consent(cycle["id"])
        get_success_data(api.revoke_consent(pc["consent"]["id"], PRIVACY))

        participant_after = get_success_data(
            api.get_participant(pc["participant"]["id"], DIRECTOR))
        assert participant_after["status"] == "WITHDRAWN"

        exit_resp = api.exit_participant(
            pc["participant"]["id"], {"reason": "no longer interested"}, DIRECTOR)
        validate_error(exit_resp, ApiErrorId.ERR_INVALID_STATE)


class TestEnrollmentWindow:
    def test_enrollment_window_inclusive_boundary(self, api):
        """PRD section 3.4: "the current logical time must fall within the
        enrollment window, inclusive of both `enrollment_start` and
        `enrollment_end`; outside the window the enrollment is rejected with
        `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/validations/enrollment_window_inclusive_boundary
        """
        program = create_active_program(name="Window", code="WND")
        cycle = create_cycle(program["id"])
        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))

        set_clock("2026-08-31T23:59:59Z")
        ok_resp = api.enroll_participant(
            cycle["id"], {"external_ref": "P-LAST"}, DIRECTOR)
        ok = validate_success(ok_resp, expected_status=201)
        assert ok["external_ref"] == "P-LAST"

        set_clock("2026-09-01T00:00:00Z")
        late_resp = api.enroll_participant(
            cycle["id"], {"external_ref": "P-LATE"}, DIRECTOR)
        validate_error(late_resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED)


class TestInitialStates:
    def test_initial_state_defaults_on_create(self, api):
        """PRD section 3.4: "New cycles are `SETUP`, and the computed
        aggregates `active_participant_count`, `total_observation_count`,
        `validated_observation_count`, `data_completeness_pct`, and
        `latest_dq_score` start at zero or null."
        PRD section 3.4: "A new participant is `ENROLLED`, with `enrolled_at`
        stamped by the server."
        PRD section 3.3: "the first instrument bearing a given code within a
        program receives `instrument_version` 1, and new instruments start
        `DRAFT`."
        PRD section 3.5: "It is `NONE` otherwise - never granted, superseded
        without replacement, or revoked."

        Design: Corner/state_machines/initial_state_defaults_on_create
        """
        program = create_active_program(name="Init", code="INI")
        cycle_resp = api.create_cycle(program["id"], cycle_payload(), DIRECTOR)
        cycle = validate_success(cycle_resp, expected_status=201)
        assert_cycle(cycle)
        assert cycle["status"] == "SETUP"
        assert cycle["pinned_logic_model_id"] is None
        assert cycle["active_participant_count"] == 0
        assert cycle["data_completeness_pct"] is None
        assert cycle["latest_dq_score"] is None

        get_success_data(api.open_enrollment(cycle["id"], DIRECTOR))
        participant_resp = api.enroll_participant(
            cycle["id"], {"external_ref": "P-001"}, DIRECTOR)
        participant = validate_success(participant_resp, expected_status=201)
        assert participant["status"] == "ENROLLED"
        assert participant["consent_status"] == "NONE"

        instrument_resp = api.create_instrument(
            program["id"], {"code": "SURV", "title": "Survey"}, DIRECTOR)
        # ProgramDirector is not authorized for instrument creation; use LEAD.
        from test_helpers.test_users import LEAD
        instrument_resp = api.create_instrument(
            program["id"], {"code": "SURV", "title": "Survey"}, LEAD)
        instrument = validate_success(instrument_resp, expected_status=201)
        assert instrument["status"] == "DRAFT"
        assert instrument["instrument_version"] == 1
