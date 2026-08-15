"""Validation precedence and work-in-progress guards: the fixed check pipeline
picks the first failing rule when several are violated at once."""
from test_helpers import (
    ApiErrorId,
    create_lockout_session_payload,
    get_procedure,
    get_session,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    setup_procedure_failed_audit,
    setup_session_in_setup,
    setup_session_locked,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProcedureRetirementGuard:
    def test_retire_blocked_by_open_session(self, api):
        """PRD §3.3: "Retirement is available from `DRAFT`, from `ACTIVE`, and
        from `UNDER_REVISION`, but only while no session referencing the
        procedure is in `SETUP`, `LOCKED`, or `CLEARED`; otherwise the request
        fails with `ERR_PROCEDURE_IN_USE`. Both `RETIRED` and `SUPERSEDED` are
        terminal."

        Design: Corner/validations/procedure_retire_blocked_by_open_session
        """
        ctx = setup_session_in_setup(asset_tag="A-PU-1")
        resp = api.retire_lockout_procedure(
            ctx["procedure"]["id"], make_ehs_manager_headers(ctx["mgr"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_IN_USE)
        assert get_procedure(ctx["mgr"], ctx["procedure"]["id"])["status"] == "ACTIVE"


class TestStateBeatsSafetyOnSessionLock:
    def _setup_cleared_session_on_out_of_service_machine(self, api, suffix):
        """Session walked to CLEARED, then the machine placed OUT_OF_SERVICE
        (permitted: only LOCKED sessions block the manual transition)."""
        ctx = setup_session_locked(asset_tag=f"A-SS-{suffix}",
                                   lock_no=f"L-SS-{suffix}", tag_no=f"T-SS-{suffix}")
        primary_headers = make_authorized_employee_headers(ctx["primary"]["id"])
        validate_success(api.remove_employee_lock(ctx["lock"]["id"], primary_headers))
        validate_success(api.clear_lockout_session(
            ctx["session"]["id"], primary_headers))
        validate_success(api.out_of_service_machine(
            ctx["machine"]["id"], make_ehs_manager_headers(ctx["mgr"]["id"])))
        return ctx, primary_headers

    def test_lock_on_cleared_session_reports_invalid_state_not_machine_posture(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed pipeline of
        checks; the first failing check determines the error returned, and later
        checks are not consulted."
        PRD §2.8: "State-machine legality — the requested transition must exist
        from the entity's current state — otherwise `ERR_INVALID_STATE`." (check
        7, ahead of the business-safety machine-posture check
        `ERR_MACHINE_NOT_IN_SERVICE` at 9)

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_session_lock
        """
        ctx, primary_headers = \
            self._setup_cleared_session_on_out_of_service_machine(api, "A")
        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True}, primary_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_lock_leaves_cleared_session_untouched(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed pipeline of
        checks; the first failing check determines the error returned, and later
        checks are not consulted."
        PRD §3.5: "Once at least one lock is applied, the primary employee
        completes energy isolation, moving the session from `SETUP` to
        `LOCKED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_session_lock
        """
        ctx, primary_headers = \
            self._setup_cleared_session_on_out_of_service_machine(api, "B")
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["status"] == "CLEARED"
        validate_error(
            api.lock_lockout_session(
                ctx["session"]["id"], {"zero_energy_verified": True},
                primary_headers),
            ApiErrorId.ERR_INVALID_STATE)
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["status"] == "CLEARED", "no side effects fire"


class TestSafetyBeatsTemporalOnSessionCreate:
    def test_create_reports_procedure_not_active_not_occupation(self, api):
        """PRD §3.5: "Creation is guarded, and the guards run in this order: the
        machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the
        procedure must be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`); the procedure's
        audit must not be overdue, with the clock exactly equal to `audit_due_at`
        still passing (`ERR_AUDIT_OVERDUE`); the creator must be currently
        qualified (`ERR_TRAINING_NOT_CURRENT`); no other session may be occupying
        the machine — occupation is the half-open interval from a session's
        creation to its release, so any session in `SETUP`, `LOCKED`, or
        `CLEARED` conflicts, while a predecessor released at exactly the current
        instant does not (`ERR_MACHINE_SESSION_CONFLICT`); and, for a
        `CONTRACTOR` session, an `APPROVED` contractor permit must exist for the
        machine (`ERR_PERMIT_REQUIRED`)."
        PRD §3.7: "A `FAIL` result additionally pushes the procedure, if it is
        `ACTIVE`, into `UNDER_REVISION` — and here the cascade is deliberately
        narrower than the modification cascade of §3.3: no sessions are
        cancelled, though sessions still in `SETUP` find themselves blocked at
        the lock transition until the procedure returns to `ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_session_create
        """
        ctx = setup_procedure_failed_audit(with_applied_lock=False,
                                           asset_tag="A-ST-100")
        assert ctx["procedure"]["status"] == "UNDER_REVISION"
        assert ctx["session"]["status"] == "SETUP", \
            "audit FAIL does not cancel SETUP sessions, so both guards are violated"

        resp = api.create_lockout_session(
            create_lockout_session_payload(ctx["machine"]["id"],
                                           ctx["procedure"]["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_NOT_ACTIVE)

    def test_rejected_create_changes_nothing(self, api):
        """PRD §3.5: "Creation is guarded, and the guards run in this order: the
        machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the
        procedure must be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`); the procedure's
        audit must not be overdue, with the clock exactly equal to `audit_due_at`
        still passing (`ERR_AUDIT_OVERDUE`); the creator must be currently
        qualified (`ERR_TRAINING_NOT_CURRENT`); no other session may be occupying
        the machine — occupation is the half-open interval from a session's
        creation to its release, so any session in `SETUP`, `LOCKED`, or
        `CLEARED` conflicts, while a predecessor released at exactly the current
        instant does not (`ERR_MACHINE_SESSION_CONFLICT`); and, for a
        `CONTRACTOR` session, an `APPROVED` contractor permit must exist for the
        machine (`ERR_PERMIT_REQUIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_session_create
        """
        ctx = setup_procedure_failed_audit(with_applied_lock=False,
                                           asset_tag="A-ST-200")
        validate_error(
            api.create_lockout_session(
                create_lockout_session_payload(ctx["machine"]["id"],
                                               ctx["procedure"]["id"],
                                               session_type="INDIVIDUAL"),
                make_authorized_employee_headers(ctx["primary"]["id"])),
            ApiErrorId.ERR_PROCEDURE_NOT_ACTIVE)

        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "SETUP"
        _sessions, meta = validate_paginated(api.list_lockout_sessions(
            make_ehs_manager_headers(ctx["mgr"]["id"]),
            params={"machine_id": ctx["machine"]["id"]}))
        assert meta["total_count"] == 1, "no new session is persisted"
