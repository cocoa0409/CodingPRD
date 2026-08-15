"""Lockout session lifecycle: lock/clear/release/cancel transitions, guards,
terminal lockdown, machine occupation, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_lockout_session,
    bootstrap_manager,
    create_lockout_session_payload,
    create_session,
    get_employee,
    get_lock,
    get_machine,
    get_session,
    issue_lock,
    apply_lock,
    lock_session,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_qualified_employee,
    run_session_to_released,
    setup_machine_with_active_procedure,
    setup_procedure_failed_audit,
    setup_session_in_setup,
    setup_session_locked,
    setup_session_released,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSessionInvalidTransitions:
    def test_lock_from_locked_returns_invalid_state(self, api):
        """PRD §3.5: "Once at least one lock is applied, the primary employee
        completes energy isolation, moving the session from `SETUP` to
        `LOCKED`."
        PRD §2.8: "State-machine legality — the requested transition must exist
        from the entity's current state — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/session_lock_from_locked_returns_invalid_state
        """
        ctx = setup_session_locked(asset_tag="A-IV1-1")
        started_at = ctx["session"]["started_at"]
        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["status"] == "LOCKED", "no side effects fire on the rejection"
        assert_instant_equal(session["started_at"], started_at)

    def test_release_from_locked_returns_invalid_state(self, api):
        """PRD §3.5: "Releasing then moves the session from `CLEARED` to the
        terminal `RELEASED` state: `ended_at` is stamped with the clock, the
        machine's `open_session_count` is recomputed, and any contractor permit
        bound to this session in `ACTIVE` status is automatically closed."
        PRD §2.8: "State-machine legality — the requested transition must exist
        from the entity's current state — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/session_release_from_locked_returns_invalid_state
        """
        ctx = setup_session_locked(asset_tag="A-IV2-1")
        resp = api.release_lockout_session(
            ctx["session"]["id"],
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["status"] == "LOCKED"
        assert session["ended_at"] is None

    def test_released_session_is_terminal(self, api):
        """PRD §3.5: "Releasing then moves the session from `CLEARED` to the
        terminal `RELEASED` state: `ended_at` is stamped with the clock, the
        machine's `open_session_count` is recomputed, and any contractor permit
        bound to this session in `ACTIVE` status is automatically closed."
        PRD §3.5: "A session still in `SETUP` may instead be cancelled by its
        primary employee; cancellation voids the session's `ISSUED` locks and
        recomputes `open_session_count`."
        PRD §2.8: "State-machine legality — the requested transition must exist
        from the entity's current state — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/session_terminal_lockdown_released
        """
        ctx = setup_session_released(asset_tag="A-TL1-1")
        assert ctx["session"]["status"] == "RELEASED"
        resp = api.cancel_lockout_session(
            ctx["session"]["id"],
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "RELEASED"


class TestSessionCancelCascade:
    def test_cancel_setup_session_voids_issued_locks(self, api):
        """PRD §3.5: "A session still in `SETUP` may instead be cancelled by its
        primary employee; cancellation voids the session's `ISSUED` locks and
        recomputes `open_session_count`."
        PRD §3.6: "Finally, locks still in `ISSUED` when their session is
        cancelled are voided automatically, moving to `VOIDED` and recomputing
        the owner's `outstanding_lock_count`."

        Design: Corner/state_machines/session_cancel_voids_issued_locks
        """
        ctx = setup_session_in_setup(asset_tag="A-SE-1")
        lock = issue_lock(ctx["primary"], ctx["session"]["id"], "L-SE-1", "T-SE-1")
        assert lock["status"] == "ISSUED"

        cancelled = validate_success(api.cancel_lockout_session(
            ctx["session"]["id"],
            make_authorized_employee_headers(ctx["primary"]["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert get_lock(ctx["mgr"], lock["id"])["status"] == "VOIDED"
        machine = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine["open_session_count"] == 0
        assert get_employee(ctx["mgr"], ctx["primary"]["id"])["outstanding_lock_count"] == 0


class TestLockTransitionGuards:
    def test_lock_with_zero_energy_false_rejected(self, api):
        """PRD §3.5: "The checks run in order: the caller must be the session's
        `primary_employee_id` (`ERR_FORBIDDEN`); the machine must still be
        `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the governing procedure must
        still be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`) — this is the point at
        which sessions orphaned by an audit failure are held, since that cascade
        leaves `SETUP` sessions standing while their procedure is no longer
        active; at least one lock must be applied, meaning `applied_lock_count`
        is at least 1 (`ERR_NO_LOCKS_APPLIED`); and the payload's
        `zero_energy_verified` must be true (`ERR_ZERO_ENERGY_NOT_VERIFIED`)."

        Design: Corner/validations/zero_energy_not_verified_rejected
        """
        ctx = setup_session_in_setup(asset_tag="A-ZE-1")
        lock = issue_lock(ctx["primary"], ctx["session"]["id"], "L-ZE-1", "T-ZE-1")
        apply_lock(ctx["primary"], lock["id"])

        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": False},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ZERO_ENERGY_NOT_VERIFIED)
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["status"] == "SETUP"
        assert session["zero_energy_verified"] is False

    def test_lock_with_no_locks_applied_rejected(self, api):
        """PRD §3.5: "The checks run in order: the caller must be the session's
        `primary_employee_id` (`ERR_FORBIDDEN`); the machine must still be
        `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the governing procedure must
        still be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`) — this is the point at
        which sessions orphaned by an audit failure are held, since that cascade
        leaves `SETUP` sessions standing while their procedure is no longer
        active; at least one lock must be applied, meaning `applied_lock_count`
        is at least 1 (`ERR_NO_LOCKS_APPLIED`); and the payload's
        `zero_energy_verified` must be true (`ERR_ZERO_ENERGY_NOT_VERIFIED`)."

        Design: Corner/validations/lock_with_no_locks_applied_rejected
        """
        ctx = setup_session_in_setup(asset_tag="A-NL-1")
        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_LOCKS_APPLIED)
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "SETUP"


class TestClearTransitionGuards:
    def test_clear_with_locks_still_applied_rejected(self, api):
        """PRD §3.5: "When the work is done, the primary employee clears the
        session, moving it from `LOCKED` to `CLEARED`; clearing requires every
        lock off the machine, meaning `applied_lock_count` is exactly zero,
        failing which the request is rejected with `ERR_LOCKS_STILL_APPLIED`."

        Design: Corner/validations/clear_with_locks_still_applied_rejected
        """
        ctx = setup_session_locked(asset_tag="A-LS-1")
        resp = api.clear_lockout_session(
            ctx["session"]["id"],
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LOCKS_STILL_APPLIED)
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "LOCKED"

        primary_headers = make_authorized_employee_headers(ctx["primary"]["id"])
        validate_success(api.remove_employee_lock(ctx["lock"]["id"], primary_headers))
        cleared = validate_success(api.clear_lockout_session(
            ctx["session"]["id"], primary_headers))
        assert cleared["status"] == "CLEARED", "with applied_lock_count 0 the clear succeeds"


class TestImmediateConsistency:
    def test_lock_response_reflects_new_state_immediately(self, api):
        """PRD §2.10: "Several operations in this program mutate more than one
        resource at once, and every cascade applies immediately, within the same
        request/response cycle."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.5: "On success the server stamps `started_at` with the clock and
        records `zero_energy_verified` as true on the session."
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Corner/consistency_model/mutation_response_reflects_new_state_immediately
        """
        ctx = setup_session_in_setup(asset_tag="A-IMX-1")
        lock = issue_lock(ctx["primary"], ctx["session"]["id"], "L-IMX-1", "T-IMX-1")
        apply_lock(ctx["primary"], lock["id"])
        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        session = validate_success(resp)
        assert_lockout_session(session)
        assert session["status"] == "LOCKED"
        assert session["zero_energy_verified"] is True
        assert_instant_equal(session["started_at"], "2026-08-01T00:00:00Z")
        assert session["applied_lock_count"] == 1


class TestSessionLockGatedByProcedureState:
    def test_lock_rejected_while_procedure_under_revision(self, api):
        """PRD §3.5: "The checks run in order: the caller must be the session's
        `primary_employee_id` (`ERR_FORBIDDEN`); the machine must still be
        `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the governing procedure must
        still be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`) — this is the point at
        which sessions orphaned by an audit failure are held, since that cascade
        leaves `SETUP` sessions standing while their procedure is no longer
        active; at least one lock must be applied, meaning `applied_lock_count`
        is at least 1 (`ERR_NO_LOCKS_APPLIED`); and the payload's
        `zero_energy_verified` must be true (`ERR_ZERO_ENERGY_NOT_VERIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/session_lock_gated_by_procedure_state
        """
        ctx = setup_procedure_failed_audit(with_applied_lock=True,
                                           asset_tag="A-SG-100")
        assert ctx["procedure"]["status"] == "UNDER_REVISION"
        assert ctx["session"]["status"] == "SETUP", \
            "the audit-FAIL cascade leaves SETUP sessions standing"

        resp = api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True},
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_NOT_ACTIVE)
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == "SETUP"

    def test_lock_succeeds_after_procedure_reactivation(self, api):
        """PRD §3.5: "The checks run in order: the caller must be the session's
        `primary_employee_id` (`ERR_FORBIDDEN`); the machine must still be
        `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the governing procedure must
        still be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`) — this is the point at
        which sessions orphaned by an audit failure are held, since that cascade
        leaves `SETUP` sessions standing while their procedure is no longer
        active; at least one lock must be applied, meaning `applied_lock_count`
        is at least 1 (`ERR_NO_LOCKS_APPLIED`); and the payload's
        `zero_energy_verified` must be true (`ERR_ZERO_ENERGY_NOT_VERIFIED`)."
        PRD §3.5: "On success the server stamps `started_at` with the clock and
        records `zero_energy_verified` as true on the session."

        Design: Difficulty/cross_entity_state_dependency/session_lock_gated_by_procedure_state
        """
        ctx = setup_procedure_failed_audit(with_applied_lock=True,
                                           asset_tag="A-SG-200")
        reactivated = validate_success(api.activate_lockout_procedure(
            ctx["procedure"]["id"],
            {"revalidation_note": "Corrective actions verified"},
            make_ehs_manager_headers(ctx["mgr"]["id"])))
        assert reactivated["status"] == "ACTIVE"

        locked = validate_success(api.lock_lockout_session(
            ctx["session"]["id"], {"zero_energy_verified": True},
            make_authorized_employee_headers(ctx["primary"]["id"])))
        assert locked["status"] == "LOCKED"
        assert locked["started_at"] is not None
        assert locked["zero_energy_verified"] is True


class TestMachineOccupationHalfOpen:
    def test_second_session_rejected_while_first_is_open(self, api):
        """PRD §3.5: "no other session may be occupying the machine — occupation
        is the half-open interval from a session's creation to its release, so
        any session in `SETUP`, `LOCKED`, or `CLEARED` conflicts, while a
        predecessor released at exactly the current instant does not
        (`ERR_MACHINE_SESSION_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/machine_session_exclusion_half_open
        """
        ctx = setup_session_in_setup(asset_tag="A-HS-100")
        resp = api.create_lockout_session(
            create_lockout_session_payload(ctx["machine"]["id"],
                                           ctx["procedure"]["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MACHINE_SESSION_CONFLICT)
        _sessions, meta = validate_paginated(api.list_lockout_sessions(
            make_ehs_manager_headers(ctx["mgr"]["id"]),
            params={"machine_id": ctx["machine"]["id"]}))
        assert meta["total_count"] == 1, "the conflicting session is not persisted"

    def test_session_at_predecessor_release_instant_accepted(self, api):
        """PRD §3.5: "no other session may be occupying the machine — occupation
        is the half-open interval from a session's creation to its release, so
        any session in `SETUP`, `LOCKED`, or `CLEARED` conflicts, while a
        predecessor released at exactly the current instant does not
        (`ERR_MACHINE_SESSION_CONFLICT`)"
        PRD §2.4: "Before the clock has been explicitly set, it reads exactly
        2026-08-01T00:00:00Z; the server must never fall back to wall-clock time."

        Design: Difficulty/resource_temporal_overlap/machine_session_exclusion_half_open
        """
        ctx = setup_session_locked(asset_tag="A-HS-200")
        released = run_session_to_released(
            ctx["primary"], ctx["session"]["id"], ctx["lock"]["id"])
        assert released["status"] == "RELEASED"
        assert_instant_equal(released["ended_at"], "2026-08-01T00:00:00Z")

        successor = validate_success(api.create_lockout_session(
            create_lockout_session_payload(ctx["machine"]["id"],
                                           ctx["procedure"]["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(ctx["primary"]["id"])),
            expected_status=201)
        assert successor["status"] == "SETUP", \
            "half-open occupation: release at this exact instant frees the machine"
        machine = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine["open_session_count"] == 1


class TestOpenSessionCountConservation:
    def test_open_count_tracks_create_lock_clear(self, api):
        """PRD §3.1: "A machine's `open_session_count` is the number of its
        lockout sessions currently in `SETUP`, `LOCKED`, or `CLEARED`; it is
        recomputed whenever a session is created or transitions into or out of
        that set."

        Design: Difficulty/compensating_invariant/session_open_release_conserves_open_count
        """
        ctx = setup_session_in_setup(asset_tag="A-SI-100")
        machine_id = ctx["machine"]["id"]
        assert get_machine(ctx["mgr"], machine_id)["open_session_count"] == 1, \
            "creation enters the counted set SETUP"

        lock = issue_lock(ctx["primary"], ctx["session"]["id"], "L-SI-1", "T-SI-1")
        apply_lock(ctx["primary"], lock["id"])
        lock_session(ctx["primary"], ctx["session"]["id"])
        assert get_machine(ctx["mgr"], machine_id)["open_session_count"] == 1, \
            "LOCKED is still a counted state"

        primary_headers = make_authorized_employee_headers(ctx["primary"]["id"])
        validate_success(api.remove_employee_lock(lock["id"], primary_headers))
        validate_success(api.clear_lockout_session(
            ctx["session"]["id"], primary_headers))
        assert get_machine(ctx["mgr"], machine_id)["open_session_count"] == 1, \
            "CLEARED is still a counted state"

    def test_open_count_returns_to_zero_after_release(self, api):
        """PRD §3.1: "A machine's `open_session_count` is the number of its
        lockout sessions currently in `SETUP`, `LOCKED`, or `CLEARED`; it is
        recomputed whenever a session is created or transitions into or out of
        that set."
        PRD §3.5: "Releasing then moves the session from `CLEARED` to the
        terminal `RELEASED` state: `ended_at` is stamped with the clock, the
        machine's `open_session_count` is recomputed, and any contractor permit
        bound to this session in `ACTIVE` status is automatically closed."

        Design: Difficulty/compensating_invariant/session_open_release_conserves_open_count
        """
        mgr = bootstrap_manager("E-MGR-SI2", "Mgr SI2")
        primary = register_qualified_employee(mgr, "E-W1-SI2", "W1 SI2")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, primary, asset_tag="A-SI-200")
        assert get_machine(mgr, machine["id"])["open_session_count"] == 0

        session = create_session(primary, machine["id"], procedure["id"],
                                 "INDIVIDUAL")
        lock = issue_lock(primary, session["id"], "L-SI-2", "T-SI-2")
        apply_lock(primary, lock["id"])
        lock_session(primary, session["id"])
        released = run_session_to_released(primary, session["id"], lock["id"])

        assert released["status"] == "RELEASED"
        assert released["ended_at"] is not None
        assert get_machine(mgr, machine["id"])["open_session_count"] == 0, \
            "the forward cycle leaves no drift in the counted set"
