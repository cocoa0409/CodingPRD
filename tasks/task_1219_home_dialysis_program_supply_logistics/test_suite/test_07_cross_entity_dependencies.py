"""Cross-entity state dependencies: slot booking gated by lazy plan expiry,
and reinstate/reversal blocked by an ACTIVE transition."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_active_home_patient, create_chair, create_slot, set_clock,
    get_patient, request_transition, approve_transition, activate_transition,
    assign_machine, api_client, make_admin_headers, make_patient_headers,
    make_nurse_headers, make_nephrologist_headers,
)


class TestSlotBookingBlockedByExpiredPlan:
    """BackupSlotReservation depends on EmergencyBackupPlan state: the plan
    flips EXPIRED lazily and the slot rejects until a drill refreshes it."""

    def test_expired_plan_rejects_slot(self, api):
        """PRD §3.4: "Plans age lazily: once the clock reaches ninety days past
        `last_drill_at`, the plan reads as `EXPIRED` and the plan gate is lost
        at the next posture evaluation."
        PRD §3.7: "The guards, in their pipeline stages: an `ACTIVE`
        EmergencyBackupPlan must exist for the patient (`ERR_PLAN_NOT_ACTIVE`);
        the chair must be in service (`ERR_CHAIR_OUT_OF_SERVICE`);"

        Design: Difficulty/cross_entity_state_dependency/slot_booking_blocked_by_expired_plan_then_allowed_after_drill
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        plan = ctx["plan"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        # 2026-05-01 + 90 days = 2026-07-30; 2026-08-05 is beyond validity.
        set_clock("2026-08-05T00:00:00Z")
        plans = get_success_data(api.list_patient_backup_plans(
            pat, make_admin_headers("admin-1")))
        assert plans[0]["status"] == "EXPIRED", "lazy expiry applied at read"
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-08-06T10:00:00Z",
             "slot_end": "2026-08-06T12:00:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_drill_restores_active_and_slot_books(self, api):
        """PRD §3.4: "A `HomeNurse` records an emergency drill on a plan that
        is `ACTIVE` or `EXPIRED` — on `SUPERSEDED` or `CLOSED` plans the drill
        is rejected with `ERR_PLAN_NOT_ACTIVE` — which sets `last_drill_at` to
        now, returns an `EXPIRED` plan to `ACTIVE`, and recomputes posture."

        Design: Difficulty/cross_entity_state_dependency/slot_booking_blocked_by_expired_plan_then_allowed_after_drill
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        plan = ctx["plan"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        set_clock("2026-08-05T00:00:00Z")
        drilled = validate_success(api.drill_backup_plan(
            plan, make_nurse_headers("nurse-1")))
        assert drilled["status"] == "ACTIVE"
        slot = validate_success(api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-08-06T10:00:00Z",
             "slot_end": "2026-08-06T12:00:00Z"},
            make_patient_headers(pat)), 201)
        assert slot["status"] == "RESERVED"


class TestReinstateBlockedByActiveTransitionThenReversal:
    """Patient -> TransitionRecord: reinstate blocked while an ACTIVE
    HOME_TO_CENTER exists; the CENTER_TO_HOME reversal then needs its
    readiness gates re-met before it flips the original to REVERSED."""

    def _setup_suspended_via_temporary_transition(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        trans = request_transition(pat, "HOME_TO_CENTER", "PATIENT_CHOICE",
                                   "2026-05-10", effective_to="2026-05-20")
        approve_transition(trans["id"])
        set_clock("2026-05-10T00:00:00Z")
        activate_transition(trans["id"])
        assert get_patient(pat)["program_status"] == "SUSPENDED"
        return ctx, trans

    def test_reinstate_blocked_and_reversal_gate_failure(self, api):
        """PRD §3.1: "Reinstatement by a `Nephrologist` moves `SUSPENDED` back
        to `ACTIVE_HOME`; the checks run in a pinned order — first, no
        `HOME_TO_CENTER` TransitionRecord in `ACTIVE` may exist for the patient
        (`ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE` is reported ahead of any gate
        failure), and then all four readiness gates must pass or the
        reinstatement is rejected with `ERR_READINESS_GATES_NOT_MET`."
        PRD §3.9: "Activating a `CENTER_TO_HOME` reversal re-checks all four
        readiness gates of §2.10 — certification current, assessment current,
        machine assigned, plan active — so the machine must have been
        re-assigned and the plan re-drilled beforehand; any gate failure is
        `ERR_READINESS_GATES_NOT_MET`."

        Design: Difficulty/cross_entity_state_dependency/reinstate_blocked_by_active_transition_then_reversal_roundtrip
        """
        ctx, trans = self._setup_suspended_via_temporary_transition(api)
        pat = ctx["patient"]["id"]
        resp = api.reinstate_patient(pat, make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE)
        rev = request_transition(pat, "CENTER_TO_HOME", "PATIENT_CHOICE",
                                 "2026-05-10", as_nephrologist=True,
                                 reversal_of_id=trans["id"])
        approve_transition(rev["id"])
        # The machine was cascade-unassigned, so the gate re-check fails.
        resp = api.activate_transition(rev["id"],
                                       make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_READINESS_GATES_NOT_MET)

    def test_reversal_roundtrip_flips_original_to_reversed(self, api):
        """PRD §3.9: "On success the patient returns from `SUSPENDED` to
        `ACTIVE_HOME`, and the reversed `HOME_TO_CENTER` record flips from
        `ACTIVE` to `REVERSED`."

        Design: Difficulty/cross_entity_state_dependency/reinstate_blocked_by_active_transition_then_reversal_roundtrip
        """
        ctx, trans = self._setup_suspended_via_temporary_transition(api)
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        rev = request_transition(pat, "CENTER_TO_HOME", "PATIENT_CHOICE",
                                 "2026-05-10", as_nephrologist=True,
                                 reversal_of_id=trans["id"])
        approve_transition(rev["id"])
        # Re-meet the gates: re-assign the cascade-unassigned machine.
        assign_machine(mach, pat)
        activated = activate_transition(rev["id"])
        assert activated["status"] == "ACTIVE"
        assert get_patient(pat)["program_status"] == "ACTIVE_HOME"
        original = get_success_data(api.get_transition_record(
            trans["id"], make_admin_headers("admin-1")))
        assert original["status"] == "REVERSED", (
            "the self-referential link resolved: original flips to REVERSED")
