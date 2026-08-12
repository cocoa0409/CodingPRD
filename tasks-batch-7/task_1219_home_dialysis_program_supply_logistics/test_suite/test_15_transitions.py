"""Corner coverage: transition request conditional validation, reversal shape
validation, and temporary-transition lazy completion with terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_program, create_patient, create_active_home_patient, set_clock,
    get_patient, request_transition, approve_transition, activate_transition,
    api_client, make_admin_headers, make_patient_headers,
    make_nurse_headers, make_nephrologist_headers,
    create_transition_payload,
)


class TestTransitionRequestBattery:
    """Conditional reason coding plus open-transition uniqueness, approve
    replay, future effective_from, and patient-state gating on activation."""

    def test_reason_coding_and_open_transition_uniqueness(self, api):
        """PRD §3.9: "The `MEDICAL_COMPLICATION` reason may be requested only
        by a `Nephrologist` (`ERR_REASON_REQUIRES_PHYSICIAN`). Three reasons
        must be substantiated by recent history, else
        `ERR_REASON_NOT_SUBSTANTIATED`: `MACHINE_FAILURE` requires a `REPAIR`
        maintenance event `IN_PROGRESS` or `COMPLETED` on the patient's
        assigned machine with `window_end` within the last thirty days;
        `SUPPLY_FAILURE` requires a `FAILED` delivery appointment with
        `window_start` within the last thirty days; and `TRAINING_INCOMPLETE`
        requires the patient's posture to currently be `NOT_READY`."
        PRD §3.9: "One more guard: a new `HOME_TO_CENTER` is rejected with
        `ERR_OPEN_TRANSITION_EXISTS` while another `HOME_TO_CENTER` for the
        patient sits in `REQUESTED`, `APPROVED`, or `ACTIVE` and not reversed."

        Design: Corner/state_machines/transition_request_battery
        """
        program = create_program()
        patient = create_patient(program["id"])
        pat = patient["id"]
        # MEDICAL_COMPLICATION requested by the Patient caller.
        resp = api.create_transition_record(
            create_transition_payload(pat, "HOME_TO_CENTER",
                                      "MEDICAL_COMPLICATION", "2026-05-10",
                                      effective_to="2026-05-20"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_REASON_REQUIRES_PHYSICIAN)
        # MACHINE_FAILURE with no REPAIR event in the last 30 days.
        resp = api.create_transition_record(
            create_transition_payload(pat, "HOME_TO_CENTER", "MACHINE_FAILURE",
                                      "2026-05-10", effective_to="2026-05-20"),
            make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_REASON_NOT_SUBSTANTIATED)
        tr = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                "2026-05-10", effective_to="2026-05-20")
        # A second open HOME_TO_CENTER while the first is REQUESTED.
        resp = api.create_transition_record(
            create_transition_payload(pat, "HOME_TO_CENTER", "HOME_UNSUITABLE",
                                      "2026-06-01"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_OPEN_TRANSITION_EXISTS)

    def test_approve_replay_and_activation_gates(self, api):
        """PRD §3.9: "A `Nephrologist` approves or denies a `REQUESTED` record
        (`ERR_TRANSITION_INVALID_STATE` from any other state), moving it to
        `APPROVED` or the terminal `DENIED`. Activation, also by a
        `Nephrologist`, requires the record `APPROVED`
        (`ERR_TRANSITION_INVALID_STATE`), the `effective_from` date reached on
        the logical clock (`ERR_TRANSITION_EFFECTIVE_IN_FUTURE`), and a
        compatible patient state — `HOME_TO_CENTER` requires `ACTIVE_HOME` or
        `SUSPENDED`, while `CENTER_TO_HOME` requires `SUSPENDED`
        (`ERR_PATIENT_STATE_BLOCKS_TRANSITION`)."

        Design: Corner/state_machines/transition_request_battery
        """
        program = create_program()
        patient = create_patient(program["id"])
        pat = patient["id"]
        tr = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                "2026-05-10", effective_to="2026-05-20")
        approve_transition(tr["id"])
        resp = api.approve_transition(tr["id"],
                                      make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_TRANSITION_INVALID_STATE)
        # Activate before effective_from (clock is 2026-05-01).
        resp = api.activate_transition(tr["id"],
                                       make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_TRANSITION_EFFECTIVE_IN_FUTURE)
        # Activate at the effective date while the patient is TRAINING.
        set_clock("2026-05-10T00:00:00Z")
        resp = api.activate_transition(tr["id"],
                                       make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_PATIENT_STATE_BLOCKS_TRANSITION)


class TestTransitionReversalValidationBattery:
    """Range and reversal-target shape rules."""

    def test_effective_range_and_reversal_target_rules(self, api):
        """PRD §3.9: "The shape rules come first: a temporary `HOME_TO_CENTER`
        requires `effective_to` strictly after `effective_from`; a permanent
        `HOME_TO_CENTER` leaves `effective_to` null; a `CENTER_TO_HOME` must
        leave `effective_to` null; violations of these range rules are
        `ERR_INVALID_EFFECTIVE_RANGE`. A `CENTER_TO_HOME` without
        `reversal_of_id` is `ERR_REVERSAL_TARGET_REQUIRED`, and the referenced
        record must be an `ACTIVE` `HOME_TO_CENTER` transition of the same
        patient (`ERR_REVERSAL_TARGET_INVALID`) — the link is self-referential,
        record to record."

        Design: Corner/state_machines/transition_reversal_validation_battery
        """
        program = create_program()
        patient = create_patient(program["id"])
        pat = patient["id"]
        tr = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                "2026-05-10", effective_to="2026-05-20")
        validate_success(api.deny_transition(
            tr["id"], make_nephrologist_headers("nephro-1")))
        # effective_to before effective_from.
        resp = api.create_transition_record(
            create_transition_payload(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                      "2026-05-10", effective_to="2026-05-09"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_INVALID_EFFECTIVE_RANGE)
        # CENTER_TO_HOME without reversal_of_id.
        resp = api.create_transition_record(
            create_transition_payload(pat, "CENTER_TO_HOME", "PATIENT_CHOICE",
                                      "2026-05-21"),
            make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_REVERSAL_TARGET_REQUIRED)
        # reversal_of_id pointing at a DENIED transition.
        resp = api.create_transition_record(
            create_transition_payload(pat, "CENTER_TO_HOME", "PATIENT_CHOICE",
                                      "2026-05-21", reversal_of_id=tr["id"]),
            make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_REVERSAL_TARGET_INVALID)


class TestTemporaryTransitionLazyCompletionAndTerminalLockdown:
    """Lazy completion past effective_to with no gate recheck, then permanent
    transition terminal lockdown."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        tr1 = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                 "2026-05-10", effective_to="2026-05-20")
        approve_transition(tr1["id"])
        set_clock("2026-05-10T00:00:00Z")
        activate_transition(tr1["id"])
        return ctx, pat, mach, tr1

    def test_lazy_completion_returns_patient_without_gate_recheck(self, api):
        """PRD §3.9: "A temporary transition completes lazily: once the clock
        passes `effective_to`, the record moves from `ACTIVE` to `COMPLETED`
        and the patient returns from `SUSPENDED` to `ACTIVE_HOME` with **no**
        readiness-gate recheck — the posture recompute applies and may well
        land the patient at `AT_RISK`."
        PRD §2.10: "Failing that, the patient is `AT_RISK` when any of the
        following holds: no machine with status `ASSIGNED` is assigned to the
        patient; the assigned machine is `maintenance_due` or
        `UNDER_MAINTENANCE`; no EmergencyBackupPlan is `ACTIVE` (the plan is
        missing, `EXPIRED`, `SUPERSEDED`, or `CLOSED`); the `missed_log_streak`
        has reached the program's `max_missed_log_streak`; or
        `waste_alert_active` is true."

        Design: Corner/state_machines/temporary_transition_lazy_completion_and_terminal_lockdown
        """
        ctx, pat, mach, tr1 = self._setup(api)
        machine = get_success_data(api.get_machine(
            mach, make_admin_headers("admin-1")))
        assert machine["status"] == "IN_STOCK", "suspension cascade"
        set_clock("2026-05-21T00:00:00Z")
        record = get_success_data(api.get_transition_record(
            tr1["id"], make_admin_headers("admin-1")))
        assert record["status"] == "COMPLETED", "lazy completion past effective_to"
        patient = get_patient(pat)
        assert patient["program_status"] == "ACTIVE_HOME"
        assert patient["posture"] == "AT_RISK", (
            "no gate recheck on lazy completion; machine gate is lost")

    def test_terminal_lockdown_after_permanent_transition(self, api):
        """PRD §3.1: "Lifecycle actions attempted from a state that lacks the
        transition — suspending a `TRAINING` patient, activating a patient
        already activated, or any lifecycle action after `TRANSITIONED_OUT` —
        are rejected with `ERR_PATIENT_INVALID_STATE`."
        PRD §3.9: "Activating a `HOME_TO_CENTER` fires the full cascade. A
        temporary transition (one with an `effective_to`) drops the patient to
        `SUSPENDED`; a permanent one moves the patient to the terminal
        `TRANSITIONED_OUT` — including directly from `SUSPENDED` when the
        patient was already suspended."

        Design: Corner/state_machines/temporary_transition_lazy_completion_and_terminal_lockdown
        """
        ctx, pat, mach, tr1 = self._setup(api)
        set_clock("2026-05-21T00:00:00Z")
        # Lazy completion returns the patient to ACTIVE_HOME.
        get_patient(pat)
        tr2 = request_transition(pat, "HOME_TO_CENTER", "HOME_UNSUITABLE",
                                 "2026-05-22")
        approve_transition(tr2["id"])
        set_clock("2026-05-22T00:00:00Z")
        activate_transition(tr2["id"])
        assert get_patient(pat)["program_status"] == "TRANSITIONED_OUT"
        resp = api.suspend_patient(pat, {"reason": "no longer applicable"},
                                   make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_PATIENT_INVALID_STATE)
        resp = api.reinstate_patient(pat, make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_PATIENT_INVALID_STATE)
