"""Escalation ladder, welfare checks, segregation of duties, OCC on create."""
from test_helpers import (
    ApiErrorId,
    assert_escalation,
    create_assignment,
    get_assignment,
    get_open_escalation_id,
    list_welfare_checks_of,
    log_call,
    make_coordinator_headers,
    make_responder_headers,
    make_reviewer_headers,
    open_escalation,
    set_clock,
    setup_calling_environment,
    setup_enrolled_participant,
    validate_error,
    validate_success,
)


class TestManualEscalationCreation:
    def test_manual_escalation_creation_fields(self, api, coordinator_headers):
        """PRD §3.7: "A coordinator may also open a case by hand — the request names the `participant_id`, a `trigger_type` of `MANUAL` (which enters at `STEP_1_RETRY`) or `CONCERN_IMMEDIATE` (which enters at `STEP_3_WELFARE` with the welfare check and hold cascade), an optional `note`, and the concurrency anchor `expected_participant_version` (§2.7)."
        PRD §3.7: "Every opening records the caller's `X-User-ID` as `opened_by_user_id` — the literal value `system` for auto-opened cases — stamps `opened_at` and `stage_entered_at`, and increments the participant's `version`."

        Design: Corner/entities/manual_escalation_creation_fields
        """
        program, participant = setup_enrolled_participant(schedules=())
        escalation = open_escalation(
            participant["id"], trigger_type="MANUAL", opener_user_id="coord-1",
            note="family called in",
        )
        assert_escalation(escalation)
        assert escalation["stage"] == "STEP_1_RETRY"
        assert escalation["trigger_type"] == "MANUAL"
        assert escalation["opened_by_user_id"] == "coord-1"
        assert escalation.get("supersedes_escalation_id") is None
        assert escalation["opened_at"].startswith("2026-08-01T00:00:00"), (
            f"opened_at is stamped from the logical clock, got {escalation['opened_at']!r}"
        )
        participant_after = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        assert participant_after.get("open_escalation_id") == escalation["id"]


class TestTerminalEscalation:
    def test_advance_terminal_escalation_rejected(self, api, coordinator_headers):
        """PRD §3.7: "Any advance, resolution, or contact-attempt recording attempted on a terminal case fails with `ERR_NO_OPEN_ESCALATION`."

        Design: Corner/state_machines/advance_terminal_escalation_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        escalation = open_escalation(participant["id"], opener_user_id="coord-1")
        resolved = validate_success(api.resolve_escalation(
            escalation["id"],
            {"resolution": "CLOSED_FALSE_ALARM", "note": "participant was on vacation"},
            make_reviewer_headers("qr-1"),
        ))
        assert resolved["stage"] == "CLOSED_FALSE_ALARM"
        err1 = api.advance_escalation(escalation["id"], coordinator_headers)
        validate_error(err1, ApiErrorId.ERR_NO_OPEN_ESCALATION, 409)
        err2 = api.resolve_escalation(
            escalation["id"], {"resolution": "RESOLVED_OK"},
            make_reviewer_headers("qr-2"),
        )
        validate_error(err2, ApiErrorId.ERR_NO_OPEN_ESCALATION, 409)
        after = validate_success(api.get_escalation(escalation["id"], coordinator_headers))
        assert after["stage"] == "CLOSED_FALSE_ALARM"


class TestEscalationStepDeadline:
    def test_escalation_advance_before_step_deadline_rejected(self, api, coordinator_headers):
        """PRD §3.7: "From `STEP_1_RETRY` to `STEP_2_CONTACT`, advancement requires either at least one no-answer-family log (`NO_ANSWER`, `BUSY`, or `WRONG_NUMBER`) recorded on the retry assignment, or the clock having reached `stage_entered_at` plus the program's `escalation_retry_hours` (four hours by default); otherwise the advance fails with `ERR_ESCALATION_STEP_NOT_DUE`."

        Design: Corner/state_machines/escalation_advance_before_step_deadline_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        set_clock("2026-08-03T10:00:00Z")
        escalation = open_escalation(participant["id"], opener_user_id="coord-1")
        # No no-answer-family log exists on the retry assignment; +1h is early.
        set_clock("2026-08-03T11:00:00Z")
        err = api.advance_escalation(escalation["id"], coordinator_headers)
        validate_error(err, ApiErrorId.ERR_ESCALATION_STEP_NOT_DUE, 409)
        # Exactly stage_entered_at + 4h: the deadline is inclusive.
        set_clock("2026-08-03T14:00:00Z")
        advanced = validate_success(api.advance_escalation(escalation["id"], coordinator_headers))
        assert advanced["stage"] == "STEP_2_CONTACT"


class TestWelfareCheckStates:
    def _setup_concern_immediate(self, api, coordinator_headers):
        program, participant = setup_enrolled_participant(schedules=())
        escalation = open_escalation(
            participant["id"], trigger_type="CONCERN_IMMEDIATE",
            opener_user_id="coord-1", note="coordinator observed crisis",
        )
        checks = list_welfare_checks_of(escalation["id"])
        assert len(checks) == 1, "STEP_3 entry auto-creates the welfare check"
        return program, participant, escalation, checks[0]

    def test_welfare_complete_before_dispatch_rejected(self, api, coordinator_headers, responder_headers):
        """PRD §3.8: "Acting on a request in the wrong state fails with `ERR_INVALID_STATE`."
        PRD §3.8: "From there an `ExternalResponder` drives it: dispatch moves `REQUESTED` → `DISPATCHED` and stamps `dispatched_at`; completion of a dispatched request stamps `completed_at`, records the partner's optional `note` as `responder_note`, and sets a `disposition` of `OK`, `ASSIST_NEEDED`, or `NOT_FOUND`"

        Design: Corner/state_machines/welfare_complete_before_dispatch_rejected
        """
        program, participant, escalation, check = self._setup_concern_immediate(
            api, coordinator_headers
        )
        assert escalation["stage"] == "STEP_3_WELFARE", (
            "CONCERN_IMMEDIATE opens directly at STEP_3 with the auto welfare check"
        )
        resp = api.complete_welfare_check(check["id"], {"disposition": "OK"}, responder_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = validate_success(api.get_welfare_check(check["id"], responder_headers))
        assert after["status"] == "REQUESTED"

    def test_welfare_check_ok_releases_hold_and_resets_streak(self, api, coordinator_headers, responder_headers):
        """PRD §3.8: "`OK` resolves the case as `RESOLVED_OK`."
        PRD §3.8: "The resolving dispositions also release the participant from `WELFARE_HOLD` back to `ENROLLED` per §3.6, resetting the streak and clearing `open_escalation_id`."
        PRD §3.7: "During the contact phase, a coordinator records each emergency-contact attempt with a `contact_id` and an `outcome` of `REACHED`, `UNREACHABLE`, or `REFUSED`; the attempt is appended to the case's `contact_attempts` with its `attempted_at`, and an `UNREACHABLE` outcome marks that emergency contact `UNREACHABLE`."

        Design: Corner/state_machines/welfare_check_ok_releases_hold_and_resets_streak
        """
        program, participant, volunteer = setup_calling_environment(
            schedules=(("MON", "09:00", "11:00"), ("TUE", "09:00", "11:00")),
            volunteer_weekdays=("MON", "TUE"),
        )
        w1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="09:00", window_end="09:30")
        w2 = create_assignment(participant["id"], volunteer["id"], "2026-08-03",
                               window_start="10:00", window_end="10:30")
        w3 = create_assignment(participant["id"], volunteer["id"], "2026-08-04")
        set_clock("2026-08-04T12:00:00Z")
        log_call(w1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        log_call(w2["id"], volunteer["id"], "2026-08-03T10:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        log_call(w3["id"], volunteer["id"], "2026-08-04T09:05:00Z", "NO_ANSWER",
                 duration_seconds=0)
        escalation_id = get_open_escalation_id(participant["id"])
        # STEP_1 -> STEP_2 at 16:05 >= stage entry 12:00 + 4h.
        set_clock("2026-08-04T16:05:00Z")
        stg2 = validate_success(api.advance_escalation(escalation_id, coordinator_headers))
        assert stg2["stage"] == "STEP_2_CONTACT"
        contacts = validate_success(
            api.list_emergency_contacts(participant["id"], coordinator_headers)
        )
        validate_success(api.record_contact_attempt(
            escalation_id, {"contact_id": contacts[0]["id"], "outcome": "UNREACHABLE"},
            coordinator_headers,
        ))
        # The single contact is now UNREACHABLE, so every remaining ACTIVE
        # contact has an attempt (vacuously) — advance to STEP_3 is due.
        stg3 = validate_success(api.advance_escalation(escalation_id, coordinator_headers))
        assert stg3["stage"] == "STEP_3_WELFARE"
        check = list_welfare_checks_of(escalation_id)[0]
        validate_success(api.dispatch_welfare_check(check["id"], responder_headers))
        completed = validate_success(api.complete_welfare_check(
            check["id"],
            {"disposition": "OK", "note": "participant fine, phone unplugged"},
            responder_headers,
        ))
        assert completed["status"] == "COMPLETED"
        assert completed["disposition"] == "OK"
        escalation_after = validate_success(api.get_escalation(escalation_id, coordinator_headers))
        assert escalation_after["stage"] == "RESOLVED_OK", "disposition OK auto-resolves"
        participant_after = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        assert participant_after["status"] == "ENROLLED", "WELFARE_HOLD released"
        assert participant_after["consecutive_no_answer_count"] == 0
        assert participant_after.get("open_escalation_id") is None
        contacts_after = validate_success(
            api.list_emergency_contacts(participant["id"], coordinator_headers)
        )
        assert contacts_after[0]["status"] == "UNREACHABLE", (
            "side effect of the UNREACHABLE attempt"
        )


class TestEscalationRbac:
    def test_escalation_resolver_same_user_as_opener_rejected(self, api, coordinator_headers):
        """PRD §3.8: "Manual resolution belongs to the `QualityReviewer`, and it is where segregation of duties bites: the resolver's `X-User-ID` must differ from the case's `opened_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise, and the case must still be open, failing with `ERR_NO_OPEN_ESCALATION` on a terminal one."

        Design: Corner/rbac/escalation_resolver_same_user_as_opener_rejected
        """
        program, participant = setup_enrolled_participant(schedules=())
        escalation = open_escalation(participant["id"], opener_user_id="staff-7")
        assert escalation["opened_by_user_id"] == "staff-7"
        err = api.resolve_escalation(
            escalation["id"], {"resolution": "CLOSED_FALSE_ALARM"},
            make_reviewer_headers("staff-7"),
        )
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        resolved = validate_success(api.resolve_escalation(
            escalation["id"],
            {"resolution": "CLOSED_FALSE_ALARM", "note": "verified false alarm"},
            make_reviewer_headers("staff-9"),
        ))
        assert resolved["stage"] == "CLOSED_FALSE_ALARM"

    def test_external_responder_cannot_resolve_escalation(self, api, coordinator_headers):
        """PRD §2.1: "A caller whose role is not listed for an endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.8: "Manual resolution belongs to the `QualityReviewer`, and it is where segregation of duties bites: the resolver's `X-User-ID` must differ from the case's `opened_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise, and the case must still be open, failing with `ERR_NO_OPEN_ESCALATION` on a terminal one."

        Design: Corner/rbac/external_responder_cannot_resolve_escalation
        """
        program, participant = setup_enrolled_participant(schedules=())
        escalation = open_escalation(participant["id"], opener_user_id="coord-1")
        err = api.resolve_escalation(
            escalation["id"], {"resolution": "CLOSED_FALSE_ALARM"},
            make_responder_headers("ext-1"),
        )
        validate_error(err, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        after = validate_success(api.get_escalation(escalation["id"], coordinator_headers))
        assert after["stage"] == "STEP_1_RETRY"


class TestOccEscalationCreate:
    def test_occ_escalation_create_stale_then_supersede(self, api, coordinator_headers):
        """PRD §2.7: "`POST /api/escalations` requires the non-optional field `expected_participant_version`: opening a case legitimately supersedes whatever case is currently open for the participant, so the create must be anchored to the participant's current `version`; a value that no longer matches means the caller's view of the participant's escalation state is stale, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Opening a case while another is open for the same participant supersedes the old one: the prior case closes as `CLOSED_SUPERSEDED`, the new case records it in `supersedes_escalation_id`, and the participant's `open_escalation_id` repoints to the new case."

        Design: Corner/complexity_layers/occ_escalation_create_stale_then_supersede
        """
        program, participant = setup_enrolled_participant(schedules=())
        before = validate_success(api.get_participant(participant["id"], coordinator_headers))
        version = before["version"]
        payload = {"participant_id": participant["id"], "trigger_type": "MANUAL",
                   "expected_participant_version": version}
        first = validate_success(
            api.create_escalation(payload, make_coordinator_headers("coord-1")), 201
        )
        # The create itself bumps Participant.version; replaying the stale
        # version is rejected.
        stale = api.create_escalation(payload, make_coordinator_headers("coord-1"))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        refreshed = validate_success(api.get_participant(participant["id"], coordinator_headers))
        second = validate_success(api.create_escalation(
            {"participant_id": participant["id"], "trigger_type": "MANUAL",
             "expected_participant_version": refreshed["version"]},
            make_coordinator_headers("coord-1"),
        ), 201)
        assert second.get("supersedes_escalation_id") == first["id"]
        old = validate_success(api.get_escalation(first["id"], coordinator_headers))
        assert old["stage"] == "CLOSED_SUPERSEDED"


class TestImmediateDangerCallLogCascade:
    """CallLog(IMMEDIATE_DANGER) -> EscalationCase at STEP_3_WELFARE ->
    WelfareCheckRequest REQUESTED -> Participant WELFARE_HOLD -> future
    SCHEDULED assignments CANCELLED (WELFARE_HOLD)."""

    def _setup_danger(self, api, coordinator_headers):
        program, participant, volunteer = setup_calling_environment()
        a1 = create_assignment(participant["id"], volunteer["id"], "2026-08-03")
        a2 = create_assignment(participant["id"], volunteer["id"], "2026-08-10")
        set_clock("2026-08-03T10:00:00Z")
        log = log_call(
            a1["id"], volunteer["id"], "2026-08-03T09:05:00Z", "REACHED_CONCERN",
            duration_seconds=600, concern_level="IMMEDIATE_DANGER",
            concern_categories=["SAFETY"], follow_up_needed=True,
            follow_up_plan="participant reported gas smell; advised evacuation and called 911",
            supervisor_notified=True,
        )
        return program, participant, volunteer, a1, a2, log

    def test_concern_immediate_opens_escalation_at_step_3_with_welfare_check(self, api, coordinator_headers):
        """PRD §3.7: "A separate, faster path exists for immediate danger: when a logged call has outcome `REACHED_CONCERN` with `concern_level` `IMMEDIATE_DANGER`, the system opens an escalation with `trigger_type` `CONCERN_IMMEDIATE` directly at `STEP_3_WELFARE`, creating the welfare check request and running the welfare-hold cascade at once."
        PRD §3.7: "The `concern_flag` is computed — true exactly when the outcome is `REACHED_CONCERN` or the `concern_level` is anything other than `NONE`."

        Design: Difficulty/transitive_cascade/immediate_danger_call_log_cascade
        """
        program, participant, volunteer, a1, a2, log = self._setup_danger(api, coordinator_headers)
        assert log["concern_flag"] is True
        participant_after = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        escalation_id = participant_after.get("open_escalation_id")
        assert escalation_id, "the IMMEDIATE_DANGER log opened an escalation"
        escalation = validate_success(api.get_escalation(escalation_id, coordinator_headers))
        assert escalation["stage"] == "STEP_3_WELFARE", (
            "opened directly at STEP_3, skipping STEP_1/STEP_2"
        )
        assert escalation["trigger_type"] == "CONCERN_IMMEDIATE"
        checks = list_welfare_checks_of(escalation_id)
        assert len(checks) == 1
        assert checks[0]["status"] == "REQUESTED", "auto-created by the STEP_3 entry"

    def test_welfare_hold_cancels_future_assignments_only(self, api, coordinator_headers):
        """PRD §3.6: "When an escalation for the participant enters `STEP_3_WELFARE` (§3.7), an `ENROLLED` participant moves to `WELFARE_HOLD`: every future-dated `SCHEDULED` assignment is cancelled with `cancel_reason` `WELFARE_HOLD`, each cancellation recomputing its volunteer's weekly minutes, and the participant continues to occupy a slot."

        Design: Difficulty/transitive_cascade/immediate_danger_call_log_cascade
        """
        program, participant, volunteer, a1, a2, log = self._setup_danger(api, coordinator_headers)
        participant_after = validate_success(
            api.get_participant(participant["id"], coordinator_headers)
        )
        assert participant_after["status"] == "WELFARE_HOLD"
        future = get_assignment(a2["id"])
        assert future["status"] == "CANCELLED"
        assert future["cancel_reason"] == "WELFARE_HOLD"
        logged = get_assignment(a1["id"])
        assert logged["status"] == "COMPLETED", (
            "the logged assignment is terminal and untouched by the hold cascade"
        )
