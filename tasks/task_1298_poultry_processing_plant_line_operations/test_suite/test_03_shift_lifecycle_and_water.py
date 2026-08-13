"""Shift lifecycle (open/suspend/resume/close), the water-limit auto-suspend
cascade, boundary precision on the water rate, and water-breach QA clearance."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_utility_reading_payload,
    make_line, make_shift, fully_staffed_shift, book_and_receive_lot, queue_run,
    open_shift, set_clock, create_passed_preop,
    setup_running_shift_with_run, setup_completed_run, setup_chilled_lot,
    complete_run, make_order, make_batch,
    make_qa_technician_headers,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]


class TestSuspendResumeCycle:

    def test_shift_running_suspended_cycle(self, api):
        """PRD §3.4: "Runs also pause and resume with their shift (§3.5): when
        the shift suspends, every `RUNNING` run moves to `PAUSED` with
        `auto_paused` set to true, and when the shift resumes, exactly those
        runs with `auto_paused` true return to `RUNNING` and have the flag
        reset to false."
        PRD §3.5: "Closing a shift — from `RUNNING` or `SUSPENDED` to `CLOSED`
        — is a `ShiftSupervisor` action guarded by run terminality: no line run
        of the shift may remain in `RUNNING` or `PAUSED`, else
        `ERR_RUNS_NOT_TERMINAL`".

        Design: Difficulty/non_linear_state_machine/shift_running_suspended_cycle
        """
        env = setup_running_shift_with_run()
        sid, rid = env["shift"]["id"], env["run"]["id"]

        # Cycle 1: suspend -> run auto-paused
        s1 = validate_success(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "MANUAL"}, SUP))
        assert s1["status"] == "SUSPENDED"
        run = get_success_data(api.get_line_run(rid, OP))
        assert run["status"] == "PAUSED"
        assert run["auto_paused"] is True

        # Resume -> auto-paused run returns to RUNNING
        s2 = validate_success(api.transition_shift(
            sid, {"to_status": "RUNNING", "resolution_note": "cleared line jam"}, SUP))
        assert s2["status"] == "RUNNING"
        assert s2["suspend_reason"] == "NONE"
        run = get_success_data(api.get_line_run(rid, OP))
        assert run["status"] == "RUNNING"
        assert run["auto_paused"] is False

        # Cycle 2: suspend -> resume again (the cycle is re-traversable)
        get_success_data(api.transition_shift(
            sid, {"to_status": "SUSPENDED", "reason_code": "MANUAL"}, SUP))
        s3 = validate_success(api.transition_shift(
            sid, {"to_status": "RUNNING", "resolution_note": "second clearance ok"}, SUP))
        assert s3["status"] == "RUNNING"

        # Complete the run, then close the shift cleanly (terminal)
        complete_run(rid)
        closed = validate_success(api.transition_shift(sid, {"to_status": "CLOSED"}, SUP))
        assert closed["status"] == "CLOSED"

    def test_resume_from_running_rejected(self, api):
        """PRD §3.5: "carrying `resolution_note` makes it a resume attempt,
        rejected with `ERR_SHIFT_NOT_SUSPENDED`".

        Design: Corner/validations/resume_from_running_rejected
        """
        env = setup_running_shift_with_run()
        resp = api.transition_shift(
            env["shift"]["id"],
            {"to_status": "RUNNING", "resolution_note": "attempted resume"}, SUP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_SUSPENDED)

    def test_close_shift_with_running_run_rejected(self, api):
        """PRD §3.5: "no line run of the shift may remain in `RUNNING` or
        `PAUSED`, else `ERR_RUNS_NOT_TERMINAL`".

        Design: Corner/validations/close_shift_with_running_run_rejected
        """
        env = setup_running_shift_with_run()
        resp = api.transition_shift(env["shift"]["id"], {"to_status": "CLOSED"}, SUP)
        validate_error(resp, ApiErrorId.ERR_RUNS_NOT_TERMINAL)
        after = get_success_data(api.get_shift(env["shift"]["id"], SUP))
        assert after["status"] == "RUNNING"

    def test_shift_close_cancels_queued_runs(self, api):
        """PRD §3.5: "On close, every run still `QUEUED` is cancelled to
        `CANCELLED`, `closed_at` is stamped with the logical time".
        PRD §3.4: "A run with zero condemnation records is reconciled
        automatically at completion, moving straight to `RECONCILED`, because
        no certification events will ever occur for it."

        Design: Corner/state_machines/shift_close_cancels_queued_runs
        """
        line = make_line()
        shift = fully_staffed_shift()
        create_passed_preop(shift["id"], line["id"])
        lot_a = book_and_receive_lot(shift["id"], lot_code="FL-A",
                                     booked_head_count=9000, head_count_received=9000,
                                     doa_count=40, total_live_weight_lb=45000.0)
        lot_b = book_and_receive_lot(shift["id"], lot_code="FL-B", grower_name="GrowerB",
                                     booked_head_count=9000, head_count_received=9000,
                                     doa_count=40, total_live_weight_lb=45000.0)
        r1 = queue_run(shift["id"], line["id"], lot_a["id"])
        r2 = queue_run(shift["id"], line["id"], lot_b["id"], planned_speed_bpm=170)
        open_shift(shift["id"])
        get_success_data(api.advance_line_run(r1["id"], {"to_status": "RUNNING"}, OP))
        complete_run(r1["id"], birds_hung=8960, carcass_weight_lb=32400.0)

        closed = validate_success(api.transition_shift(shift["id"], {"to_status": "CLOSED"}, SUP))
        assert closed["status"] == "CLOSED"

        r2_after = get_success_data(api.get_line_run(r2["id"], OP))
        assert r2_after["status"] == "CANCELLED"
        r1_after = get_success_data(api.get_line_run(r1["id"], OP))
        assert r1_after["status"] == "RECONCILED"

    def test_closed_shift_rejects_staffing_terminal(self, api):
        """PRD §3.5: "`CLOSED` is terminal — any further mutation attempted
        against the shift is rejected with `ERR_SHIFT_TERMINAL`."
        PRD §2.6: "On the three writes listed in §2.7, the expected-version
        field is compared with the parent's current `version` before any
        business validation runs".

        Design: Corner/validations/closed_shift_rejects_staffing_terminal
        """
        env = setup_running_shift_with_run()
        complete_run(env["run"]["id"])
        closed = validate_success(api.transition_shift(
            env["shift"]["id"], {"to_status": "CLOSED"}, SUP))
        assert closed["status"] == "CLOSED"
        fresh = get_success_data(api.get_shift(env["shift"]["id"], SUP))
        resp = api.set_shift_staffing(
            env["shift"]["id"],
            {"shacklers_present": 9, "eviscerators_present": 20,
             "deboners_present": 12, "qa_techs_present": 2,
             "expected_shift_version": fresh["version"]}, SUP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_TERMINAL)
        after = get_success_data(api.get_shift(env["shift"]["id"], SUP))
        assert after["shacklers_present"] == 10


class TestWaterMetering:

    def test_shift_computed_read_aggregates_readings(self, api):
        """PRD §3.5: "Each posting updates the shift's aggregates:
        `process_water_gallons` and `chiller_water_gallons`, the per-meter sums
        of `gallons` over the shift's readings."

        Design: Corner/endpoints/shift_computed_read_aggregates_readings
        """
        shift = make_shift()
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(shift["id"], gallons=100.0), QA))
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(shift["id"], gallons=200.5), QA))
        after = get_success_data(api.get_shift(shift["id"], QA))
        assert after["process_water_gallons"] == pytest.approx(300.5)
        assert after["chiller_water_gallons"] == pytest.approx(0)

    def test_water_reading_with_zero_birds_no_breach(self, api):
        """PRD §3.5: "The birds-basis rate, `water_rate_birds_basis`, is
        `process_water_gallons` multiplied by 1000 and divided by
        `birds_processed` — null while `birds_processed` is zero."
        PRD §3.5: "A process-water reading that flips `water_breach_active`
        from false to true while the shift is `RUNNING` triggers the plant's
        automatic suspension".

        Design: Corner/calculations/water_reading_with_zero_birds_no_breach
        """
        env = setup_running_shift_with_run()
        # birds_processed == 0 (run RUNNING, not yet completed)
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=99999.0), QA))
        after = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert after["status"] == "RUNNING"
        assert after["water_breach_active"] is False
        assert after["water_rate_birds_basis"] is None

    def test_water_rate_exactly_at_limit_compliant(self, api):
        """PRD §2.8: "a rate must be strictly greater than its limit to breach;
        a rate exactly equal to its limit is compliant."
        PRD §3.5: "The flag `water_breach_active` is true exactly when the
        birds-basis rate is strictly greater than the 1500.0
        gallons-per-1000-birds limit of §2.8 — a rate exactly equal to the
        limit is compliant."

        Design: Difficulty/boundary_precision_check/water_rate_exactly_at_limit_compliant
        """
        env = setup_completed_run(completion_clock=None)
        # birds_processed == 9950; 14925 gal -> exactly 1500.0
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=14925.0), QA))
        at = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert at["water_rate_birds_basis"] == pytest.approx(1500.0)
        assert at["water_breach_active"] is False
        assert at["status"] == "RUNNING"

        # One more gallon -> 14926 gal -> 1500.10... breaches and suspends
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=1.0), QA))
        over = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert over["water_rate_birds_basis"] == pytest.approx(1500.1)
        assert over["water_breach_active"] is True
        assert over["status"] == "SUSPENDED"
        assert over["suspend_reason"] == "WATER_LIMIT_BREACH"

    def test_water_intensity_birds_vs_weight_basis_diverge(self, api):
        """PRD §2.8: "Process-water intensity is tracked on two denominators
        that can legitimately disagree about compliance for identical meter
        readings: the birds basis, limited to 1500.0 gallons per 1000 birds
        processed, governs operational compliance and drives the automatic
        shift suspension described in §3.5; the weight basis, limited to 200.0
        gallons per 100 pounds of chilled weight, is maintained for permit
        reporting."
        PRD §3.5: "Because the denominators differ, identical readings can be
        breaching on the birds basis while compliant on the weight basis."

        Design: Difficulty/dual_variant_calc/water_intensity_birds_vs_weight_basis_diverge
        """
        env = setup_completed_run(completion_clock=None)
        # 15000 gal over 9950 birds -> 1507.54 (breach); over 36000 lb -> 41.67 (compliant)
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=15000.0), QA))
        after = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert after["water_rate_birds_basis"] == pytest.approx(1507.54)
        assert after["water_rate_weight_basis"] == pytest.approx(41.67)
        assert after["water_breach_active"] is True
        assert after["status"] == "SUSPENDED"
        assert after["suspend_reason"] == "WATER_LIMIT_BREACH"

    def test_water_breach_suspend_pause_hold_cascade(self, api):
        """PRD §3.5: "A process-water reading that flips `water_breach_active`
        from false to true while the shift is `RUNNING` triggers the plant's
        automatic suspension: the shift moves `RUNNING` → `SUSPENDED` with
        `suspend_reason` set to `WATER_LIMIT_BREACH`, every line run of the
        shift in `RUNNING` moves to `PAUSED` with `auto_paused` set to true,
        and every deboning batch of the shift in `IN_PROGRESS` moves to
        `ON_HOLD` — all atomically within the reading's request."

        Design: Difficulty/transitive_cascade/water_breach_suspend_pause_hold_cascade
        """
        env = setup_chilled_lot()  # run R1 COMPLETED, lot CHILLED
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order(pounds_ordered=500.0)
        batch = make_batch(order["id"], env["lot"]["id"], env["shift"]["id"], db_line["id"])
        get_success_data(api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP))
        # Second lot with a RUNNING run
        lot2 = book_and_receive_lot(env["shift"]["id"], lot_code="FL-200",
                                    grower_name="GrowerB")
        r2 = queue_run(env["shift"]["id"], env["line"]["id"], lot2["id"])
        get_success_data(api.advance_line_run(r2["id"], {"to_status": "RUNNING"}, OP))

        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=15000.0), QA))

        shift = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert shift["status"] == "SUSPENDED"
        assert shift["suspend_reason"] == "WATER_LIMIT_BREACH"

        r2_after = get_success_data(api.get_line_run(r2["id"], OP))
        assert r2_after["status"] == "PAUSED"
        assert r2_after["auto_paused"] is True

        batch_after = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert batch_after["status"] == "ON_HOLD"

        r1_after = get_success_data(api.get_line_run(env["run"]["id"], OP))
        assert r1_after["status"] == "RECONCILED"  # completed run untouched

    def test_water_breach_resume_requires_qa_clearance(self, api):
        """PRD §3.5: "When the shift's `suspend_reason` is `WATER_LIMIT_BREACH`,
        only a `QATechnician` may clear it — regulatory water clearance — and
        any other role's attempt is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.5: "On resume, every run paused automatically (those with
        `auto_paused` true) returns to `RUNNING` with the flag reset to false,
        and `suspend_reason` resets to `NONE`."

        Design: Corner/validations/water_breach_resume_requires_qa_clearance
        """
        env = setup_completed_run(completion_clock=None)
        get_success_data(api.create_utility_reading(
            create_utility_reading_payload(env["shift"]["id"], gallons=15000.0), QA))
        shift = get_success_data(api.get_shift(env["shift"]["id"], QA))
        assert shift["suspend_reason"] == "WATER_LIMIT_BREACH"

        resp = api.transition_shift(
            env["shift"]["id"],
            {"to_status": "RUNNING", "resolution_note": "supervisor attempt"}, SUP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        resumed = validate_success(api.transition_shift(
            env["shift"]["id"],
            {"to_status": "RUNNING", "resolution_note": "water corrective action verified"},
            make_qa_technician_headers("qa-1")))
        assert resumed["status"] == "RUNNING"
        assert resumed["suspend_reason"] == "NONE"
