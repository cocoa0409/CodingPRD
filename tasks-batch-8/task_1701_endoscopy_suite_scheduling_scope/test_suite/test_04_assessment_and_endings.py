"""BBPS assessment, completion/abort gates, booking endings, usage voiding."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_instants_equal,
    assess_prep,
    cancel_booking,
    check_in,
    complete_procedure,
    confirm_prep,
    create_booking,
    create_in_progress_booking,
    create_patient,
    create_provider,
    create_room,
    create_scope,
    create_colono_type,
    first_usage_for_booking,
    get_booking,
    get_scope,
    make_endoscopist_headers,
    make_registry,
    prep_assessment_payload,
    run_procedure_to_complete,
    start_procedure,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _in_progress(api, mrn="MRN-IP", serial="SC-IP", start="2026-08-03T09:00:00Z"):
    reg = make_registry(mrn=mrn, serial=serial)
    booking = create_in_progress_booking(
        reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
        reg["room"]["id"], reg["scope"]["id"], scheduled_start=start)
    return reg, booking


class TestPrepAssessment:
    def test_prep_assessment_requires_in_progress_rejected(self, api):
        """PRD §3.5: "The act belongs to the booking's own endoscopist
        (`ERR_PROVIDER_OWNERSHIP_MISMATCH`), requires the booking axis at
        `IN_PROGRESS` (`ERR_BOOKING_NOT_IN_PROGRESS`)".

        Design: Corner/state_machines/prep_assessment_requires_in_progress_rejected
        """
        reg = make_registry(mrn="MRN-NIP", serial="SC-NIP", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(booking["id"])
        resp = api.record_prep_assessment(
            booking["id"], prep_assessment_payload(2, 2, 2),
            make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_IN_PROGRESS)
        assert get_booking(booking["id"])["prep_status"] == "PREP_CONFIRMED"

    def test_bbps_boundary_cluster(self, api):
        """PRD §3.5: "The scores decide the prep axis outcome: the prep is
        `PREP_ADEQUATE` when the three segments total at least 6 and every
        individual segment is at least 2, and `PREP_INADEQUATE` otherwise."

        Design: Corner/calculations/bbps_boundary_cluster
        """
        patient = create_patient(mrn="MRN-BB")
        provider = create_provider("Dr Bb")
        t_col = create_colono_type()
        rooms = [create_room(name=n) for n in ("R1", "R2", "R3")]
        scopes = [create_scope(serial_number=f"BB-{i}") for i in (1, 2, 3)]
        # All three bookings share one scheduled_start, so they must all be
        # created before the clock reaches it (scheduled_start must lie strictly
        # in the future, PRD §3.2).
        bookings = [
            create_booking(patient["id"], provider["id"], t_col["id"],
                           rooms[i]["id"],
                           scheduled_start="2026-08-03T09:00:00Z")
            for i in range(3)
        ]
        for b in bookings:
            confirm_prep(b["id"])
        advance_clock("2026-08-03T09:00:00Z")
        for i in range(3):
            check_in(bookings[i]["id"])
            start_procedure(bookings[i]["id"], provider["id"], scopes[i]["id"])
        adq = assess_prep(bookings[0]["id"], provider["id"], 2, 2, 2)
        assert adq["prep_status"] == "PREP_ADEQUATE", "total 6 and every segment 2"
        seg = assess_prep(bookings[1]["id"], provider["id"], 3, 3, 0)
        assert seg["prep_status"] == "PREP_INADEQUATE", "total 6 but a segment is 0"
        low = assess_prep(bookings[2]["id"], provider["id"], 2, 2, 1)
        assert low["prep_status"] == "PREP_INADEQUATE", "total 5 is below 6"

    def test_bbps_segment_out_of_range_rejected(self, api):
        """PRD §3.5: "`bbps_left`, `bbps_right`, and `bbps_transverse`, each an
        integer from 0 to 3 (out-of-range values fail schema validation with
        `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/bbps_segment_out_of_range_rejected
        """
        reg, booking = _in_progress(api, mrn="MRN-BR", serial="SC-BR")
        resp = api.record_prep_assessment(
            booking["id"], prep_assessment_payload(4, 2, 2),
            make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_booking(booking["id"])["prep_status"] == "PREP_CONFIRMED"

    def test_prep_assessment_twice_rejected(self, api):
        """
        PRD §3.5: "The act belongs to the booking's own endoscopist
        (`ERR_PROVIDER_OWNERSHIP_MISMATCH`), requires the booking axis at
        `IN_PROGRESS` (`ERR_BOOKING_NOT_IN_PROGRESS`), and is single-shot — all
        three segment fields must still be null, so a second assessment is refused
        with `ERR_PREP_ALREADY_ASSESSED`."

        PRD §3.5: "The scores are stored on the booking either way."

        Design: Corner/state_machines/prep_assessment_twice_rejected
        """
        reg, booking = _in_progress(api, mrn="MRN-2X", serial="SC-2X")
        first = assess_prep(booking["id"], reg["provider"]["id"], 1, 2, 2)
        assert first["prep_status"] == "PREP_INADEQUATE"
        resp = api.record_prep_assessment(
            booking["id"], prep_assessment_payload(3, 3, 3),
            make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREP_ALREADY_ASSESSED)
        after = get_booking(booking["id"])
        assert after["prep_status"] == "PREP_INADEQUATE"
        assert after["bbps_left"] == 1, "first assessment retained"


class TestCompletionAndAbort:
    def test_complete_requires_assessed_prep_rejected(self, api):
        """PRD §3.5: "Completion, again by the owning endoscopist, requires the
        prep axis to have been assessed — `PREP_ADEQUATE` or `PREP_INADEQUATE` —
        with `ERR_PREP_NOT_ASSESSED` the refusal otherwise."

        Design: Corner/state_machines/complete_requires_assessed_prep_rejected
        """
        reg, booking = _in_progress(api, mrn="MRN-CA", serial="SC-C1")
        resp = api.complete_booking(
            booking["id"],
            {"cecum_intubated": True, "withdrawal_time_seconds": 400,
             "adenomas_detected": 0},
            make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREP_NOT_ASSESSED)
        assert get_booking(booking["id"])["status"] == "IN_PROGRESS"
        assert get_scope(reg["scope"]["id"])["status"] == "IN_USE"

    def test_abort_requires_inadequate_prep_rejected(self, api):
        """PRD §3.5: "the endoscopist may instead abort: the prep axis must be
        exactly `PREP_INADEQUATE` (`ERR_PREP_NOT_INADEQUATE` otherwise)".

        Design: Corner/state_machines/abort_requires_inadequate_prep_rejected
        """
        reg, booking = _in_progress(api, mrn="MRN-AB", serial="SC-A2")
        assess_prep(booking["id"], reg["provider"]["id"], 2, 2, 2)
        resp = api.abort_booking(booking["id"], {"reason": "try"},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREP_NOT_INADEQUATE)
        assert get_booking(booking["id"])["status"] == "IN_PROGRESS"

    def test_occupancy_scheduled_variant_fields(self, api):
        """
        PRD §3.2: "The planned `procedure_minutes` is the procedure type's
        `base_duration_minutes`, plus an anesthesia add-on of 0 minutes for `NONE`,
        10 for `MAC`, or 15 for `GENERAL`, plus a further 5 minutes when the patient
        is at least 65 years old at the scheduled start."

        PRD §3.2: "The `scheduled_end` is then `scheduled_start` advanced by
        `procedure_minutes`, and the `room_block_end` adds a turnover buffer on top
        of `scheduled_end` — 15 minutes for a `STANDARD` room, 25 for an
        `ERCP_CAPABLE` one."

        PRD §3.5: "On completion the booking axis moves to `COMPLETED`, `actual_end`
        is stamped, and `actual_duration_minutes` is computed as the elapsed seconds
        between `actual_start` and `actual_end` truncated down to whole minutes — a
        measured figure that routinely differs from the forward-looking
        `procedure_minutes` estimate."

        Design: Difficulty/dual_variant_calc/occupancy_scheduled_vs_actual_minutes
        """
        reg = make_registry(mrn="M1001", serial="SC-001")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        confirm_prep(booking["id"])
        done = run_procedure_to_complete(
            booking["id"], reg["provider"]["id"], reg["scope"]["id"],
            "2026-08-02T09:00:00Z", "2026-08-02T09:47:00Z",
            bbps=(2, 2, 2), cecum_intubated=True, withdrawal_time_seconds=480,
            adenomas_detected=0)
        assert done["status"] == "COMPLETED"
        assert done["procedure_minutes"] == 40, "scheduled variant: 40 + 0 + 0"
        assert_instants_equal(done["scheduled_end"], "2026-08-02T09:40:00Z")

    def test_occupancy_actual_variant_differs_from_scheduled(self, api):
        """PRD §3.5: "`actual_duration_minutes` is computed as the elapsed seconds
        between `actual_start` and `actual_end` truncated down to whole minutes —
        a measured figure that routinely differs from the forward-looking
        `procedure_minutes` estimate."
        PRD §3.5: "If an `ACTIVE` ScopeUsage exists, its scope moves to
        `AWAITING_REPROCESS` with `awaiting_reprocess_since` stamped to the same
        instant".

        Design: Difficulty/dual_variant_calc/occupancy_scheduled_vs_actual_minutes
        """
        reg = make_registry(mrn="M1002", serial="SC-002")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        confirm_prep(booking["id"])
        done = run_procedure_to_complete(
            booking["id"], reg["provider"]["id"], reg["scope"]["id"],
            "2026-08-02T09:00:00Z", "2026-08-02T09:47:00Z",
            bbps=(2, 2, 2), cecum_intubated=True, withdrawal_time_seconds=480,
            adenomas_detected=0)
        assert done["actual_duration_minutes"] == 47, "09:00 -> 09:47 measured"
        assert done["actual_duration_minutes"] != done["procedure_minutes"]
        assert get_scope(reg["scope"]["id"])["status"] == "AWAITING_REPROCESS"


class TestParallelAxesAndTerminalStates:
    def test_cancel_leaves_prep_axis_untouched(self, api):
        """PRD §3.5: "A `SchedulingCoordinator` may cancel a booking whose axis is
        `SCHEDULED` or `CHECKED_IN`; any other state is refused with
        `ERR_BOOKING_NOT_CANCELLABLE`. An optional `reason` lands in
        `cancel_reason`, and the prep axis is deliberately left untouched — the
        two axes are independent".

        Design: Difficulty/non_linear_state_machine/booking_parallel_axes_status_times_prep
        """
        reg = make_registry(mrn="M3201", serial="SC-301", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-02T09:00:00Z")
        confirm_prep(booking["id"])
        data = cancel_booking(booking["id"], reason="patient request")
        assert data["status"] == "CANCELLED"
        assert data["prep_status"] == "PREP_CONFIRMED", "prep axis does not reset"
        assert data["cancel_reason"] == "patient request"

    def test_abort_from_combined_in_progress_inadequate_state(self, api):
        """PRD §3.5: "the prep axis must be exactly `PREP_INADEQUATE`
        (`ERR_PREP_NOT_INADEQUATE` otherwise), a `reason` is captured into
        `cancel_reason`, `actual_end` is stamped, and the booking axis settles at
        `ABORTED_PREP_INADEQUATE`."
        PRD §3.5: "The same scope and anesthesia cascades apply — the scope goes
        to `AWAITING_REPROCESS` when an active usage exists".

        Design: Difficulty/non_linear_state_machine/booking_parallel_axes_status_times_prep
        """
        reg, booking = _in_progress(api, mrn="M3202", serial="SC-302",
                                    start="2026-08-02T11:00:00Z")
        assess_prep(booking["id"], reg["provider"]["id"], 1, 2, 2)
        resp = api.abort_booking(booking["id"], {"reason": "prep inadequate"},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "ABORTED_PREP_INADEQUATE"
        assert data["prep_status"] == "PREP_INADEQUATE"
        assert data["cancel_reason"] == "prep inadequate"
        assert data["actual_end"] is not None
        assert get_scope(reg["scope"]["id"])["status"] == "AWAITING_REPROCESS"

    def test_cancel_from_completed_rejected(self, api):
        """PRD §3.5: "A `SchedulingCoordinator` may cancel a booking whose axis is
        `SCHEDULED` or `CHECKED_IN`; any other state is refused with
        `ERR_BOOKING_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_from_completed_rejected
        """
        reg = make_registry(mrn="MRN-TC", serial="SC-TC")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(booking["id"])
        run_procedure_to_complete(booking["id"], reg["provider"]["id"],
                                  reg["scope"]["id"], "2026-08-03T09:00:00Z",
                                  "2026-08-03T09:00:00Z")
        resp = api.cancel_booking(booking["id"], {"reason": "too late"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE)
        assert get_booking(booking["id"])["status"] == "COMPLETED"

    def test_cancelled_booking_rejects_reschedule(self, api):
        """PRD §3.5: "The old booking must still be `SCHEDULED`
        (`ERR_BOOKING_NOT_SCHEDULED`)."
        PRD §2.7: "`POST /endoscopy/bookings/{id}/reschedule` likewise requires
        `expected_booking_version`, with the same `ERR_STALE_BOOKING_VERSION`
        (HTTP 412) rejection on mismatch."

        Design: Corner/state_machines/cancelled_booking_rejects_reschedule
        """
        reg = make_registry(mrn="MRN-RC", serial="SC-RC", with_scope=False)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        cancel_booking(booking["id"], reason="changed mind")
        current = get_booking(booking["id"])
        resp = api.reschedule_booking(
            booking["id"], {"expected_booking_version": current["version"],
                            "new_scheduled_start": "2026-08-05T09:00:00Z"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_SCHEDULED)


class TestUsageVoiding:
    def test_scope_use_count_ledger_void_compensation(self, api):
        """PRD §3.4: "The chosen scope moves to `IN_USE` and its `use_count`
        increments by one, keeping `use_count` equal to the number of non-`VOID`
        usage rows the scope has accumulated."
        PRD §3.5: "The supplied `reason` is stored in `void_reason`, the usage
        moves to `VOID`, the scope's `use_count` is decremented — creation and
        voiding of the same usage being a compensating pair that leaves
        `use_count` unchanged — and an `IN_USE` scope returns to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/scope_use_count_ledger_void_compensation
        """
        reg, booking = _in_progress(api, mrn="M9001", serial="SC-V1")
        assert get_scope(reg["scope"]["id"])["use_count"] == 1, "start adds one"
        usage = first_usage_for_booking(booking["id"])
        data = validate_success(api.void_scope_usage(
            usage["id"], {"reason": "scope documented in error"},
            make_endoscopist_headers(reg["provider"]["id"])), 200)
        assert data["status"] == "VOID"
        assert data["void_reason"] == "scope documented in error"
        scope = get_scope(reg["scope"]["id"])
        assert scope["use_count"] == 0, "compensating pair restores the ledger"
        assert scope["status"] == "AVAILABLE"

    def test_completion_after_void_does_not_move_scope(self, api):
        """PRD §3.5: "If an `ACTIVE` ScopeUsage exists, its scope moves to
        `AWAITING_REPROCESS` with `awaiting_reprocess_since` stamped to the same
        instant" — the cascade is conditional on an active usage existing.

        Design: Difficulty/compensating_invariant/scope_use_count_ledger_void_compensation
        """
        reg, booking = _in_progress(api, mrn="M9002", serial="SC-V2")
        usage = first_usage_for_booking(booking["id"])
        validate_success(api.void_scope_usage(
            usage["id"], {"reason": "recorded in error"},
            make_endoscopist_headers(reg["provider"]["id"])), 200)
        assess_prep(booking["id"], reg["provider"]["id"], 3, 3, 3)
        complete_procedure(booking["id"], reg["provider"]["id"])
        scope = get_scope(reg["scope"]["id"])
        assert scope["status"] == "AVAILABLE", "no ACTIVE usage: no cascade"
        assert scope["use_count"] == 0

    def test_void_usage_after_complete_rejected(self, api):
        """PRD §3.5: "the usage must still be `ACTIVE` and its booking still
        `IN_PROGRESS`, otherwise `ERR_SCOPE_USAGE_NOT_VOIDABLE`."

        Design: Corner/state_machines/void_usage_after_complete_rejected
        """
        reg = make_registry(mrn="MRN-VU", serial="SC-VU")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z")
        confirm_prep(booking["id"])
        run_procedure_to_complete(booking["id"], reg["provider"]["id"],
                                  reg["scope"]["id"], "2026-08-03T09:00:00Z",
                                  "2026-08-03T09:00:00Z")
        usage = first_usage_for_booking(booking["id"])
        resp = api.void_scope_usage(usage["id"], {"reason": "too late"},
                                    make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_USAGE_NOT_VOIDABLE)
        assert get_scope(reg["scope"]["id"])["use_count"] == 1
        assert get_booking(booking["id"])["status"] == "COMPLETED"
