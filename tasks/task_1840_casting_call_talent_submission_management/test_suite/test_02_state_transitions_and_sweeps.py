"""State-machine transition legality, terminal lockdown, revert branches, and
clock-driven sweeps (PRD sections 2.4, 2.8, 3.2, 3.3, 3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_session,
    get_success_data,
    place_hold,
    set_clock,
    setup_released_breakdown,
    setup_shortlisted_submission,
    setup_submission,
    submit_talent,
    create_session,
    propose_appointment,
    confirm_appointment,
    validate_error,
    validate_success,
)


class TestBreakdownTransitionLegality:
    def test_release_from_released_returns_invalid_state(self, api, director_headers):
        """PRD section 3.2: "Release branches on the payload's `distribution`.
        Releasing with `AGENT_ONLY` moves `DRAFT → RELEASED_AGENT_ONLY`; releasing
        with `OPEN_CALL` moves `DRAFT → RELEASED_OPEN`."
        PRD section 2.8: "State-machine legality of the requested transition from
        the target resource's current state, including terminal-state lockdown —
        failures produce `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/breakdown_release_from_released_returns_invalid_state
        """
        ctx = setup_released_breakdown(distribution="OPEN_CALL", clock="2026-08-01T00:00:00Z")
        resp = api.release_breakdown(ctx["breakdown"]["id"], {"distribution": "OPEN_CALL"}, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_terminal_lockdown(self, api, director_headers):
        """PRD section 3.2: "Cancelling a `DRAFT` breakdown simply moves it to
        `CANCELLED` and bumps its `version` — nothing has been published, so
        nothing cascades."
        PRD section 2.8: "State-machine legality of the requested transition from
        the target resource's current state, including terminal-state lockdown —
        failures produce `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/breakdown_cancel_terminal_lockdown
        """
        set_clock("2026-08-01T00:00:00Z")
        from test_helpers import create_breakdown, create_production, create_role

        production = create_production(title="SM2")
        role = create_role(production["id"])
        breakdown = create_breakdown(production["id"], role["id"])
        validate_success(api.cancel_breakdown(breakdown["id"], director_headers))
        resp = api.close_breakdown(breakdown["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSubmissionLifecycle:
    def test_submission_initial_state_submitted(self, api, director_headers):
        """PRD section 3.3: "A clean, non-duplicate submission begins in
        `SUBMITTED` and the breakdown's `submission_count` is recomputed to
        include it, bumping the breakdown's `version`."
        PRD section 3.3: "Starting review moves a submission `SUBMITTED →
        UNDER_REVIEW` — permitted only while the parent breakdown remains in a
        released state — and stamps `reviewed_at` with the current logical clock
        at the moment the submission first leaves `SUBMITTED`."

        Design: Corner/state_machines/submission_initial_state_submitted
        """
        ctx = setup_released_breakdown(clock="2026-08-01T00:00:00Z")
        from test_helpers import create_talent

        talent = create_talent()
        submission = submit_talent(ctx["breakdown"]["id"], talent["id"])
        assert submission["status"] == "SUBMITTED", "fresh submission must begin in SUBMITTED"
        assert submission.get("reviewed_at") is None, "reviewed_at is stamped only when the submission first leaves SUBMITTED"

    def test_reject_releases_active_holds(self, api, associate_headers, director_headers):
        """PRD section 3.3: "Rejection is available from either `UNDER_REVIEW` or
        `SHORTLISTED`, moves the submission to `REJECTED`, and releases every
        `ACTIVE` availability hold on it in the same operation."

        Design: Corner/state_machines/submission_reject_releases_active_holds_side_effect
        """
        ctx = setup_shortlisted_submission()
        hold = place_hold(ctx["submission"]["id"], ctx["talent"]["id"], hold_kind="PIN")
        assert hold["status"] == "ACTIVE"
        resp = api.reject_submission(ctx["submission"]["id"], associate_headers)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        hold_after = validate_success(api.get_hold(hold["id"], director_headers))
        assert hold_after["status"] == "RELEASED", "rejection must release ACTIVE holds on the submission"


class TestCallbackRevertBranch:
    def test_cancel_last_appointment_reverts_to_under_review(self, api, associate_headers):
        """PRD section 3.5: "Cancelling — from `PROPOSED` or `CONFIRMED` to
        `CANCELLED`, an associate's action — recomputes `booked_count` downward by
        one when the cancelled appointment had been `CONFIRMED`, applies the same
        no-remaining-appointment revert, and bumps the appointment's and
        session's `version`."
        PRD section 3.5: "if no appointment in `PROPOSED` or `CONFIRMED` remains
        on the submission, the submission reverts `CALLBACK_INVITED →
        UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/submission_branching_callback_revert
        """
        ctx = setup_shortlisted_submission()
        session = create_session(ctx["breakdown"]["id"])
        appointment = propose_appointment(session["id"], ctx["submission"]["id"])
        invited = validate_success(api.get_submission(ctx["submission"]["id"], associate_headers))
        assert invited["status"] == "CALLBACK_INVITED", "appointment creation advances SHORTLISTED to CALLBACK_INVITED"
        resp = api.cancel_appointment(appointment["id"], associate_headers)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        reverted = validate_success(api.get_submission(ctx["submission"]["id"], associate_headers))
        assert reverted["status"] == "UNDER_REVIEW", (
            "with no remaining PROPOSED/CONFIRMED appointment the submission reverts to UNDER_REVIEW"
        )

    def test_decline_last_appointment_reverts_to_under_review(self, api, associate_headers):
        """PRD section 3.5: "Declining — `PROPOSED → DECLINED`, by the agent (or
        associate for self-submissions) — simply bows the appointment out into
        `DECLINED`, with one hook: if no appointment in `PROPOSED` or `CONFIRMED`
        remains on the submission, the submission reverts `CALLBACK_INVITED →
        UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/submission_branching_callback_revert
        """
        ctx = setup_shortlisted_submission()
        session = create_session(ctx["breakdown"]["id"])
        appointment = propose_appointment(session["id"], ctx["submission"]["id"])
        resp = api.decline_appointment(appointment["id"], associate_headers)
        data = validate_success(resp)
        assert data["status"] == "DECLINED"
        reverted = validate_success(api.get_submission(ctx["submission"]["id"], associate_headers))
        assert reverted["status"] == "UNDER_REVIEW", (
            "declining the last active appointment reverts the submission to UNDER_REVIEW"
        )


class TestSessionCompletionGate:
    def _setup_in_progress_session(self, confirm: bool):
        ctx = setup_shortlisted_submission()
        session = create_session(ctx["breakdown"]["id"])
        appointment = propose_appointment(session["id"], ctx["submission"]["id"])
        if confirm:
            appointment = confirm_appointment(appointment["id"])
        # Clock reaching session_start sweeps SCHEDULED -> IN_PROGRESS (PRD 3.5).
        set_clock("2026-08-04T10:00:00Z")
        return ctx, session, appointment

    def test_complete_blocked_while_appointment_proposed(self, api, associate_headers):
        """PRD section 3.5: "Completing it — `IN_PROGRESS → COMPLETED`, driven by
        a `CastingAssociate` — requires that no child appointment remain
        `PROPOSED`; every appointment still `CONFIRMED` at completion becomes
        `NO_SHOW` unless it was individually completed beforehand, and the
        `booked_count` is recomputed as each confirmation converts."
        PRD section 2.8: "State-machine legality of the requested transition from
        the target resource's current state, including terminal-state lockdown —
        failures produce `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/session_complete_depends_on_appointment_states
        """
        _, session, appointment = self._setup_in_progress_session(confirm=False)
        current = validate_success(api.get_appointment(appointment["id"], associate_headers))
        assert current["status"] == "PROPOSED"
        resp = api.complete_session(session["id"], associate_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_converts_confirmed_appointments_to_no_show(self, api, associate_headers):
        """PRD section 3.5: "Completing it — `IN_PROGRESS → COMPLETED`, driven by
        a `CastingAssociate` — requires that no child appointment remain
        `PROPOSED`; every appointment still `CONFIRMED` at completion becomes
        `NO_SHOW` unless it was individually completed beforehand, and the
        `booked_count` is recomputed as each confirmation converts."
        PRD section 2.9: "A session's `booked_count` is the count of its child
        callback appointments in `CONFIRMED` status, recomputed whenever an
        appointment is confirmed, cancelled, completed, or swept to no-show."

        Design: Difficulty/cross_entity_state_dependency/session_complete_depends_on_appointment_states
        """
        _, session, appointment = self._setup_in_progress_session(confirm=True)
        assert validate_success(api.get_session(session["id"], associate_headers))["booked_count"] == 1
        resp = api.complete_session(session["id"], associate_headers)
        data = validate_success(resp)
        assert_session(data)
        assert data["status"] == "COMPLETED"
        appt_after = validate_success(api.get_appointment(appointment["id"], associate_headers))
        assert appt_after["status"] == "NO_SHOW", "unresolved CONFIRMED appointments become NO_SHOW at session completion"
        session_after = validate_success(api.get_session(session["id"], associate_headers))
        assert session_after["booked_count"] == 0, "booked_count recounts CONFIRMED appointments after the NO_SHOW sweep"


class TestHoldExpirySweep:
    def test_hold_expires_when_clock_reaches_expires_at(self, api, director_headers):
        """PRD section 2.4: "An `ACTIVE` availability hold lapses to `EXPIRED`
        once the clock reaches its `expires_at`."

        Design: Corner/cross_cutting_layers/hold_expiry_is_scheduled_action
        """
        ctx = setup_submission()
        hold = place_hold(
            ctx["submission"]["id"],
            ctx["talent"]["id"],
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-08T00:00:00Z",
            expires_at="2026-08-10T00:00:00Z",
        )
        assert hold["status"] == "ACTIVE"
        set_clock("2026-08-11T00:00:00Z")
        after = validate_success(api.get_hold(hold["id"], director_headers))
        assert after["status"] == "EXPIRED", "clock >= expires_at sweeps the hold to EXPIRED with no manual release"
