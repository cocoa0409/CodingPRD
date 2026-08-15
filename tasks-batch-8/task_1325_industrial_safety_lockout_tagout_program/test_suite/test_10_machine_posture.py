"""Machine service posture: out-of-service guards, return-to-service, and the
modification-driven cascade through procedure, session, and lock."""
from test_helpers import (
    ApiErrorId,
    bootstrap_manager,
    create_lockout_session_payload,
    get_lock,
    get_machine,
    get_procedure,
    get_session,
    issue_lock,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_qualified_employee,
    register_modification,
    run_session_to_released,
    setup_machine_with_active_procedure,
    setup_session_in_setup,
    setup_session_locked,
    validate_error,
    validate_success,
)


class TestOutOfService:
    def test_out_of_service_blocked_while_session_locked(self, api):
        """PRD §3.1: "The transition is refused with
        `ERR_MACHINE_HAS_OPEN_SESSIONS` if any session of the machine is
        currently `LOCKED` — active work under lock is never interrupted
        administratively."

        Design: Corner/validations/out_of_service_blocked_by_locked_session
        """
        ctx = setup_session_locked(asset_tag="A-OS-1")
        resp = api.out_of_service_machine(
            ctx["machine"]["id"], make_ehs_manager_headers(ctx["mgr"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MACHINE_HAS_OPEN_SESSIONS)
        assert get_machine(ctx["mgr"], ctx["machine"]["id"])["status"] == "IN_SERVICE"

        run_session_to_released(ctx["primary"], ctx["session"]["id"],
                                ctx["lock"]["id"])
        machine = validate_success(api.out_of_service_machine(
            ctx["machine"]["id"], make_ehs_manager_headers(ctx["mgr"]["id"])))
        assert machine["status"] == "OUT_OF_SERVICE", \
            "with no LOCKED session the transition succeeds"


class TestReturnToService:
    def test_return_to_service_restores_in_service(self, api):
        """PRD §3.1: "Returning a machine to service is stricter, and its checks
        run in a fixed order: the machine must have a procedure in `ACTIVE`
        status (`ERR_PROCEDURE_NOT_ACTIVE`); that procedure's audit must not be
        overdue — the clock must not be strictly later than the procedure's
        `audit_due_at` (`ERR_AUDIT_OVERDUE`); and `open_session_count` must be
        zero (`ERR_MACHINE_HAS_OPEN_SESSIONS`). Only then does the machine return
        to `IN_SERVICE`."

        Design: Corner/validations/return_to_service_restores_in_service
        """
        mgr = bootstrap_manager("E-MGR-RTS", "Mgr RTS")
        surveyor = register_qualified_employee(mgr, "E-W1-RTS", "W1 RTS")
        machine, survey, procedure = setup_machine_with_active_procedure(
            mgr, surveyor, asset_tag="A-RTS-1")
        machine = validate_success(api.out_of_service_machine(
            machine["id"], make_ehs_manager_headers(mgr["id"])))
        assert machine["status"] == "OUT_OF_SERVICE"

        machine = validate_success(api.return_to_service_machine(
            machine["id"], make_ehs_manager_headers(mgr["id"])))
        assert machine["status"] == "IN_SERVICE"


class TestSessionCreateOnOutOfServiceMachine:
    def test_session_create_on_out_of_service_machine_rejected(self, api):
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

        Design: Corner/validations/session_create_on_out_of_service_machine_rejected
        """
        ctx = setup_session_in_setup(asset_tag="A-MIS-1")
        # Cancel the SETUP session so the machine may leave service.
        validate_success(api.cancel_lockout_session(
            ctx["session"]["id"],
            make_authorized_employee_headers(ctx["primary"]["id"])))
        machine = validate_success(api.out_of_service_machine(
            ctx["machine"]["id"], make_ehs_manager_headers(ctx["mgr"]["id"])))
        assert machine["status"] == "OUT_OF_SERVICE"

        resp = api.create_lockout_session(
            create_lockout_session_payload(ctx["machine"]["id"],
                                           ctx["procedure"]["id"],
                                           session_type="INDIVIDUAL"),
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_IN_SERVICE)


class TestModificationCascade:
    def _setup_cascade(self, api, suffix):
        """Machine + ACTIVE procedure + session in SETUP + one ISSUED lock."""
        ctx = setup_session_in_setup(asset_tag=f"A-MC-{suffix}")
        ctx["lock"] = issue_lock(ctx["primary"], ctx["session"]["id"],
                                 f"L-MC-{suffix}", f"T-MC-{suffix}")
        return ctx

    def test_modification_cascades_to_session_and_lock(self, api):
        """PRD §3.3: "Second, the modification is logged with `review_status`
        `UNREVIEWED`, and if the machine has an `ACTIVE` procedure, that
        procedure is automatically pushed to `UNDER_REVISION`; that cascade in
        turn cancels every session of the machine still in `SETUP`, voids each
        cancelled session's `ISSUED` locks, and recomputes the machine's
        `open_session_count`."

        Design: Difficulty/transitive_cascade/modification_cascade_to_locks
        """
        ctx = self._setup_cascade(api, "A")
        register_modification(ctx["mgr"], ctx["machine"]["id"],
                              "Replaced motor starter")

        assert get_procedure(ctx["mgr"], ctx["procedure"]["id"])["status"] == \
            "UNDER_REVISION", "hop 1: procedure pushed to UNDER_REVISION"
        assert get_session(ctx["mgr"], ctx["session"]["id"])["status"] == \
            "CANCELLED", "hop 2: SETUP session cancelled by the cascade"
        assert get_lock(ctx["mgr"], ctx["lock"]["id"])["status"] == "VOIDED", \
            "hop 3: the cancelled session's ISSUED lock is voided"

    def test_modification_cascade_restores_open_count_and_bumps_version(self, api):
        """PRD §3.3: "Second, the modification is logged with `review_status`
        `UNREVIEWED`, and if the machine has an `ACTIVE` procedure, that
        procedure is automatically pushed to `UNDER_REVISION`; that cascade in
        turn cancels every session of the machine still in `SETUP`, voids each
        cancelled session's `ISSUED` locks, and recomputes the machine's
        `open_session_count`."
        PRD §3.3: "First, the optimistic-concurrency rule of §2.7 applies: the
        request must carry `expected_machine_version` equal to the machine's
        current `version`, or it fails with `ERR_STALE_VERSION`, and a successful
        registration increments the machine's `version` by one."

        Design: Difficulty/transitive_cascade/modification_cascade_to_locks
        """
        ctx = self._setup_cascade(api, "B")
        machine_before = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine_before["open_session_count"] == 1

        register_modification(ctx["mgr"], ctx["machine"]["id"],
                              "Replaced motor starter")

        machine_after = get_machine(ctx["mgr"], ctx["machine"]["id"])
        assert machine_after["open_session_count"] == 0, \
            "cancelling the only SETUP session returns the count to zero"
        assert machine_after["version"] == machine_before["version"] + 1, \
            "a successful registration increments the machine's version by one"
