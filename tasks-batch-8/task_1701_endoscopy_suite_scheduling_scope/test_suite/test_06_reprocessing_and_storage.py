"""Reprocessing cycles: step ordering, dwell minimums, HLD gate, storage expiry."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_minutes,
    advance_clock,
    advance_step,
    assert_instants_equal,
    assess_prep,
    check_in,
    complete_procedure,
    confirm_prep,
    create_booking,
    create_cycle,
    create_in_progress_booking,
    create_patient,
    create_provider,
    create_reprocessed_scope,
    create_room,
    create_scope,
    create_colono_type,
    get_booking,
    get_cycle,
    get_scope,
    make_endoscopist_headers,
    make_registry,
    make_technician_headers,
    run_complete_cycle,
    run_procedure_to_complete,
    send_to_reprocessing,
    start_procedure,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestManualSend:
    def test_send_to_reprocessing_from_available_valid(self, api):
        """PRD §3.6: "A `ReprocessingTechnician` or `UnitAdmin` may manually send
        an `AVAILABLE` scope to reprocessing — a scope whose hang time has lapsed
        or that was touch-contaminated — moving it to `AWAITING_REPROCESS` and
        stamping `awaiting_reprocess_since` to the current logical time."

        Design: Corner/state_machines/send_to_reprocessing_from_available_valid
        """
        scope = create_scope(serial_number="SC-SEND")
        advance_clock("2026-08-01T12:00:00Z")
        data = validate_success(api.send_scope_to_reprocessing(
            scope["id"], make_technician_headers("tech-1")), 200)
        assert data["status"] == "AWAITING_REPROCESS"
        assert_instants_equal(data["awaiting_reprocess_since"], "2026-08-01T12:00:00Z")

    def test_send_to_reprocessing_in_use_rejected(self, api):
        """PRD §3.6: "A scope in any other status is not reprocessable through
        this route (`ERR_SCOPE_NOT_REPROCESSABLE`)."

        Design: Corner/errors/send_to_reprocessing_in_use_rejected
        """
        reg = make_registry(mrn="MRN-SIU", serial="SC-B2")
        booking = create_in_progress_booking(
            reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
            reg["room"]["id"], reg["scope"]["id"])
        resp = api.send_scope_to_reprocessing(reg["scope"]["id"],
                                              make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_REPROCESSABLE)
        assert get_scope(reg["scope"]["id"])["status"] == "IN_USE"


class TestStepOrdering:
    def test_cycle_step_skip_rejected(self, api):
        """PRD §3.6: "Each advance names a `to_step`, and it must be exactly the
        next step — skipping or repeating a step is refused with
        `ERR_CYCLE_STEP_OUT_OF_ORDER`".

        Design: Corner/state_machines/cycle_step_skip_rejected
        """
        scope = create_scope(serial_number="SC-SKIP")
        send_to_reprocessing(scope["id"])
        cycle = create_cycle(scope["id"])
        resp = api.advance_cycle_step(cycle["id"], {"to_step": "CLEANED"},
                                      make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_CYCLE_STEP_OUT_OF_ORDER)
        assert get_cycle(cycle["id"])["status"] == "INITIATED"

    def test_cycle_advance_after_complete_rejected(self, api):
        """PRD §3.6: "any advance against a terminal (`COMPLETE` or `FAILED`)
        cycle is refused with `ERR_CYCLE_NOT_ADVANCABLE`."

        Design: Corner/state_machines/cycle_advance_after_complete_rejected
        """
        scope, cycle = create_reprocessed_scope(serial_number="SC-DONE")
        assert cycle["status"] == "COMPLETE"
        resp = api.advance_cycle_step(cycle["id"], {"to_step": "COMPLETE"},
                                      make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ADVANCABLE)
        assert get_cycle(cycle["id"])["status"] == "COMPLETE"

    def test_scheduler_cannot_advance_reprocessing_step(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/reprocessing-cycles/{id}/steps/advance` |
        Advance exactly one step; enforces step minimums and the HLD concentration
        gate | ReprocessingTechnician |"

        Design: Corner/rbac/scheduler_cannot_advance_reprocessing_step
        """
        scope = create_scope(serial_number="SC-RB2")
        send_to_reprocessing(scope["id"])
        cycle = create_cycle(scope["id"])
        resp = api.advance_cycle_step(cycle["id"], {"to_step": "PRECLEANED"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_cycle(cycle["id"])["status"] == "INITIATED"

    def test_reprocessing_cycle_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/reprocessing_cycle_not_found_returns_404
        """
        resp = api.get_reprocessing_cycle(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPROCESSING_CYCLE_NOT_FOUND)


class TestHldGate:
    def _cycle_at_cleaned(self, serial="SC-HLD"):
        scope = create_scope(serial_number=serial)
        advance_clock("2026-08-01T08:00:00Z")
        send_to_reprocessing(scope["id"])
        cycle = create_cycle(scope["id"])
        advance_step(cycle["id"], "PRECLEANED")
        advance_clock("2026-08-01T08:06:00Z")
        advance_step(cycle["id"], "CLEANED")
        return scope, cycle

    def test_hld_concentration_failure_fails_cycle(self, api):
        """PRD §3.6: "A concentration below 300 ppm is rejected with
        `ERR_HLD_CONCENTRATION_TOO_LOW` — and the rejection itself has teeth: the
        cycle falls to `FAILED` and the scope returns to `AWAITING_REPROCESS` with
        `awaiting_reprocess_since` reset to the present."
        PRD §3.6: "any advance against a terminal (`COMPLETE` or `FAILED`) cycle
        is refused with `ERR_CYCLE_NOT_ADVANCABLE`."

        Design: Corner/state_machines/hld_concentration_failure_fails_cycle
        """
        scope, cycle = self._cycle_at_cleaned(serial="SC-PPM")
        advance_clock("2026-08-01T08:16:00Z")
        resp = api.advance_cycle_step(
            cycle["id"], {"to_step": "DISINFECTED", "hld_solution_lot": "LOT-BAD",
                          "hld_concentration_ppm": 250},
            make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_HLD_CONCENTRATION_TOO_LOW)
        assert resp.status_code == 422
        assert get_cycle(cycle["id"])["status"] == "FAILED"
        scope_now = get_scope(scope["id"])
        assert scope_now["status"] == "AWAITING_REPROCESS"
        assert_instants_equal(scope_now["awaiting_reprocess_since"],
                              "2026-08-01T08:16:00Z")
        resp2 = api.advance_cycle_step(
            cycle["id"], {"to_step": "DISINFECTED", "hld_solution_lot": "LOT-BAD",
                          "hld_concentration_ppm": 350},
            make_technician_headers("tech-1"))
        validate_error(resp2, ApiErrorId.ERR_CYCLE_NOT_ADVANCABLE)

    def test_hld_contact_599_seconds_rejected(self, api):
        """PRD §3.6: "From `CLEANED` to `DISINFECTED`: at least 600 seconds of
        high-level-disinfectant contact must have elapsed since `cleaned_at`
        (`ERR_STEP_DURATION_TOO_SHORT` otherwise)."
        PRD §2.8: "Elapsed-time comparisons against step minimums, storage expiry
        instants, and arrival or transport windows are evaluated at second
        resolution, and minimum-threshold comparisons are inclusive: arriving
        exactly at a minimum satisfies it."

        Design: Difficulty/boundary_precision_check/hld_contact_time_600_second_boundary
        """
        scope, cycle = self._cycle_at_cleaned(serial="SC-H599")
        advance_clock("2026-08-01T08:15:59Z")  # 599 seconds of contact
        resp = api.advance_cycle_step(
            cycle["id"], {"to_step": "DISINFECTED", "hld_solution_lot": "LOT-H",
                          "hld_concentration_ppm": 350},
            make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_STEP_DURATION_TOO_SHORT)
        assert get_cycle(cycle["id"])["status"] == "CLEANED", (
            "a failed duration gate does not fail the cycle")

    def test_hld_contact_exactly_600_seconds_accepted(self, api):
        """PRD §3.6: "From `CLEANED` to `DISINFECTED`: at least 600 seconds of
        high-level-disinfectant contact must have elapsed since `cleaned_at`
        (`ERR_STEP_DURATION_TOO_SHORT` otherwise)."
        PRD §2.8: "minimum-threshold comparisons are inclusive: arriving exactly
        at a minimum satisfies it."

        Design: Difficulty/boundary_precision_check/hld_contact_time_600_second_boundary
        """
        scope, cycle = self._cycle_at_cleaned(serial="SC-H600")
        advance_clock("2026-08-01T08:15:59Z")
        resp = api.advance_cycle_step(
            cycle["id"], {"to_step": "DISINFECTED", "hld_solution_lot": "LOT-H",
                          "hld_concentration_ppm": 350},
            make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_STEP_DURATION_TOO_SHORT)
        advance_clock("2026-08-01T08:16:00Z")  # exactly 600 seconds
        data = validate_success(api.advance_cycle_step(
            cycle["id"], {"to_step": "DISINFECTED", "hld_solution_lot": "LOT-H",
                          "hld_concentration_ppm": 350},
            make_technician_headers("tech-1")), 200)
        assert data["status"] == "DISINFECTED"
        assert_instants_equal(data["disinfected_at"], "2026-08-01T08:16:00Z")
        assert data["hld_concentration_ppm"] == 350
        assert data["hld_solution_lot"] == "LOT-H"


class TestPrecleanDeadline:
    def test_preclean_deadline_60_minute_boundary(self, api):
        """PRD §3.6: "immediately computes `requires_extended_soak`: true when
        strictly more than 60 minutes have elapsed since the scope's
        `awaiting_reprocess_since` — a scope at exactly 60 minutes is not
        extended."

        Design: Corner/calculations/preclean_deadline_60_minute_boundary
        """
        patient = create_patient(mrn="MRN-PD")
        provider = create_provider("Dr Pd")
        t_col = create_colono_type()
        r1 = create_room(name="R1")
        r2 = create_room(name="R2")
        s1 = create_scope(serial_number="PD-1")
        s2 = create_scope(serial_number="PD-2")
        b1 = create_booking(patient["id"], provider["id"], t_col["id"], r1["id"],
                            scheduled_start="2026-08-11T08:00:00Z")
        b2 = create_booking(patient["id"], provider["id"], t_col["id"], r2["id"],
                            scheduled_start="2026-08-11T08:00:00Z")
        confirm_prep(b1["id"])
        confirm_prep(b2["id"])
        # Both procedures run 08:00 -> 09:00 (clock only moves forward).
        advance_clock("2026-08-11T08:00:00Z")
        for b, s in ((b1, s1), (b2, s2)):
            check_in(b["id"])
            start_procedure(b["id"], provider["id"], s["id"])
            assess_prep(b["id"], provider["id"], 2, 2, 2)
        advance_clock("2026-08-11T09:00:00Z")
        complete_procedure(b1["id"], provider["id"])
        complete_procedure(b2["id"], provider["id"])

        advance_clock("2026-08-11T10:00:00Z")  # exactly 60 minutes after 09:00
        cy1 = create_cycle(s1["id"], booking_id=b1["id"])
        assert cy1["requires_extended_soak"] is False, "strict >: exactly 60 is not extended"
        advance_clock("2026-08-11T10:00:01Z")  # 60 minutes + 1 second
        cy2 = create_cycle(s2["id"], booking_id=b2["id"])
        assert cy2["requires_extended_soak"] is True

    def test_extended_soak_requires_20_minute_clean(self, api):
        """PRD §3.6: "From `PRECLEANED` to `CLEANED`: at least 20 minutes must
        have elapsed since `precleaned_at` when `requires_extended_soak` is true,
        otherwise at least 5 minutes; shortfalls are refused with
        `ERR_STEP_DURATION_TOO_SHORT`, and `cleaned_at` is stamped on success."

        Design: Corner/calculations/extended_soak_requires_20_minute_clean
        """
        patient = create_patient(mrn="MRN-ES")
        provider = create_provider("Dr Es")
        t_col = create_colono_type()
        room = create_room(name="R1")
        s1 = create_scope(serial_number="ES-1")
        b1 = create_booking(patient["id"], provider["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-11T08:00:00Z")
        confirm_prep(b1["id"])
        run_procedure_to_complete(b1["id"], provider["id"], s1["id"],
                                  "2026-08-11T08:00:00Z", "2026-08-11T09:00:00Z")
        advance_clock("2026-08-11T10:30:00Z")  # 90 minutes later: extended
        cycle = create_cycle(s1["id"], booking_id=b1["id"])
        assert cycle["requires_extended_soak"] is True
        advance_step(cycle["id"], "PRECLEANED")
        advance_clock("2026-08-11T10:49:00Z")  # 19 minutes of manual clean
        resp = api.advance_cycle_step(cycle["id"], {"to_step": "CLEANED"},
                                      make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_STEP_DURATION_TOO_SHORT)
        assert get_cycle(cycle["id"])["status"] == "PRECLEANED"
        advance_clock("2026-08-11T10:50:00Z")  # exactly 20 minutes
        data = validate_success(api.advance_cycle_step(
            cycle["id"], {"to_step": "CLEANED"}, make_technician_headers("tech-1")), 200)
        assert data["status"] == "CLEANED"
        assert_instants_equal(data["cleaned_at"], "2026-08-11T10:50:00Z")


class TestStorageExpiry:
    def _expired_scope_scenario(self, mrn, serial, booking_start):
        reg = make_registry(mrn=mrn, serial=serial)
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start=booking_start)
        confirm_prep(booking["id"])
        # Cycle dried 2026-08-01T08:26:00Z -> storage_expires_at +72h.
        run_complete_cycle(reg["scope"]["id"], "2026-08-01T08:00:00Z", lot="LOT-X",
                           send_first=True)
        return reg, booking

    def test_scope_storage_expiry_exact_instant_rejected(self, api):
        """PRD §3.6: "Storage currency is strict at the boundary: a scope is
        current while the logical now is strictly before `storage_expires_at`, a
        null `storage_expires_at` (a never-reprocessed scope) counts as current,
        and at the exact expiry instant the scope is already expired."
        PRD §3.4: "must be storage-current — its `is_storage_current` true,
        meaning a null `storage_expires_at` or a logical now strictly before it —
        with `ERR_SCOPE_STORAGE_EXPIRED` the refusal".

        Design: Difficulty/boundary_precision_check/scope_storage_expiry_exact_instant_rejected
        """
        reg, booking = self._expired_scope_scenario("M6101", "SC-X1",
                                                    "2026-08-04T08:26:00Z")
        advance_clock("2026-08-04T08:26:00Z")  # exactly the expiry instant
        check_in(booking["id"])
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_STORAGE_EXPIRED)
        assert get_booking(booking["id"])["status"] == "CHECKED_IN"

    def test_scope_fields_after_exact_instant_rejection(self, api):
        """PRD §3.6: "in either case the scope's `storage_expires_at` is set to
        the cycle's `dried_at` plus 72 hours."
        PRD §3.1: "Scope responses also expose the computed boolean
        `is_storage_current`, which is true when `storage_expires_at` is null or
        the logical now falls strictly before it."

        Design: Difficulty/boundary_precision_check/scope_storage_expiry_exact_instant_rejected
        """
        reg, booking = self._expired_scope_scenario("M6102", "SC-X2",
                                                    "2026-08-04T08:26:00Z")
        advance_clock("2026-08-04T08:26:00Z")
        check_in(booking["id"])
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCOPE_STORAGE_EXPIRED)
        scope = get_scope(reg["scope"]["id"])
        assert scope["status"] == "AVAILABLE", "rejection mutates nothing"
        assert scope["is_storage_current"] is False
        assert_instants_equal(scope["storage_expires_at"], "2026-08-04T08:26:00Z")

    def test_storage_current_until_instant_before_expiry(self, api):
        """PRD §3.6: "a scope is current while the logical now is strictly before
        `storage_expires_at`".
        PRD §3.4: "A successful start stamps `actual_start` to the current logical
        time and creates a ScopeUsage".

        Design: Corner/calculations/storage_current_until_instant_before_expiry
        """
        reg, booking = self._expired_scope_scenario("MRN-SC2", "SC-X3",
                                                    "2026-08-04T08:25:00Z")
        advance_clock("2026-08-04T08:25:00Z")  # 60 seconds before expiry
        check_in(booking["id"])
        data = validate_success(api.start_booking(
            booking["id"], {"scope_id": reg["scope"]["id"]},
            make_endoscopist_headers(reg["provider"]["id"])), 200)
        assert data["status"] == "IN_PROGRESS"
        scope = get_scope(reg["scope"]["id"])
        assert scope["status"] == "IN_USE"
        assert_instants_equal(scope["storage_expires_at"], "2026-08-04T08:26:00Z")
