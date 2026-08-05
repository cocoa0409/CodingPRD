"""Laboratory dispatch, the two overlap checks, the QC resend cycle, and the
shelf-life mutate-then-reject leg."""

from test_helpers import (
    ApiErrorId,
    assert_lab_case,
    assert_money,
    assert_same_instant,
    fixtures as fx,
    make_lab_technician_headers,
    validate_error,
    validate_success,
)


class TestQcResendCycle:
    def test_the_same_lab_case_cycles_through_returned_twice_before_passing(self, api, prosthodontist_headers):
        """PRD §3.5: "A fail moves the case to `QC_FAILED`, leaves the parent arch in
        `LAB_FABRICATION`, and opens the resend leg."
        PRD §3.5: "A permitted resend moves the case `QC_FAILED → RESENT`, increases
        `resend_count` by one, clears `received_at` back to null, and — critically —
        **leaves `shelf_life_expires_at` exactly where it was**, so the 45-day
        shelf-life clock keeps running from the original dispatch and is not renewed
        by the resend."

        Design: Difficulty/non_linear_state_machine/lab_case_qc_fail_resend_cycle_returns_to_returned_three_times
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Ivar Sandoval", date_of_birth="1950-10-08", phone="555-0299"
        )
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 95)
        lab_case = fx.draft_lab_case(built["arch"]["id"], lab["id"])
        fx.dispatch_lab_case(lab_case["id"])

        for _ in range(2):
            fx.receive_lab_case(lab_case["id"], lab["id"])
            failed = fx.qc_lab_case(lab_case["id"], "FAIL")
            assert failed["lab_status"] == "QC_FAILED"
            resent = fx.resend_lab_case(lab_case["id"])
            assert resent["lab_status"] == "RESENT"
            assert resent["received_at"] is None

        fx.receive_lab_case(lab_case["id"], lab["id"])
        passed = validate_success(
            api.qc_lab_case(lab_case["id"], {"qc_result": "PASS"}, prosthodontist_headers), 200
        )

        assert_lab_case(passed)
        assert passed["lab_status"] == "QC_PASSED"
        assert passed["resend_count"] == 2
        assert passed["qc_result"] == "PASS"

    def test_the_shelf_life_clock_is_not_renewed_by_either_resend(self, api):
        """PRD §3.5: "`shelf_life_expires_at` is `dispatched_at` plus 45 calendar
        days, and it is computed identically for both turnaround classes."
        PRD §3.5: "A pass moves the case to `QC_PASSED`; when the case's `purpose` is
        `FABRICATION` or `REMAKE` this also advances the parent arch
        `LAB_FABRICATION → READY_FOR_DELIVERY` with a `version` increment on the
        arch"

        Design: Difficulty/non_linear_state_machine/lab_case_qc_fail_resend_cycle_returns_to_returned_three_times
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Ivar Sandoval", date_of_birth="1950-10-08", phone="555-0299"
        )
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 95)
        lab_case = fx.draft_lab_case(built["arch"]["id"], lab["id"])
        dispatched = fx.dispatch_lab_case(lab_case["id"])
        assert_same_instant(
            dispatched["shelf_life_expires_at"],
            "2026-06-15T00:00:00.000Z",
            "LabCase.shelf_life_expires_at at dispatch",
        )

        for _ in range(2):
            fx.receive_lab_case(lab_case["id"], lab["id"])
            fx.qc_lab_case(lab_case["id"], "FAIL")
            fx.resend_lab_case(lab_case["id"])
        fx.receive_lab_case(lab_case["id"], lab["id"])
        fx.qc_lab_case(lab_case["id"], "PASS")

        final = fx.read_lab_case(lab_case["id"])
        assert_same_instant(
            final["shelf_life_expires_at"],
            "2026-06-15T00:00:00.000Z",
            "LabCase.shelf_life_expires_at after two resends",
        )
        assert fx.read_arch(built["arch"]["id"])["arch_status"] == "READY_FOR_DELIVERY"

    def test_third_resend_is_refused_by_the_resend_ceiling(self, api, front_office_headers):
        """PRD §3.5: "The case's `resend_count` must be strictly below 2, so a case
        may be resent twice and a third resend is refused with
        `ERR_QC_RESEND_LIMIT_EXCEEDED`; and the logical clock must still be at or
        before `shelf_life_expires_at`, a resend attempted after that instant being
        refused with `ERR_LAB_CASE_EXPIRED` — without, on this path, any accompanying
        write, because the mutate-then-reject behaviour belongs to the receive path
        alone."

        Design: Corner/state_machines/qc_resend_ceiling_blocks_the_third_resend
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Sami Toivonen", date_of_birth="1948-08-20", phone="555-1017"
        )
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 90)
        lab_case = fx.draft_lab_case(built["arch"]["id"], lab["id"])
        fx.dispatch_lab_case(lab_case["id"])
        for _ in range(2):
            fx.receive_lab_case(lab_case["id"], lab["id"])
            fx.qc_lab_case(lab_case["id"], "FAIL")
            fx.resend_lab_case(lab_case["id"])
        fx.receive_lab_case(lab_case["id"], lab["id"])
        fx.qc_lab_case(lab_case["id"], "FAIL")

        response = api.resend_lab_case(lab_case["id"], front_office_headers)
        validate_error(response, ApiErrorId.ERR_QC_RESEND_LIMIT_EXCEEDED.value, 409)

        after = fx.read_lab_case(lab_case["id"])
        assert after["lab_status"] == "QC_FAILED"
        assert after["resend_count"] == 2
        assert fx.read_arch(built["arch"]["id"])["arch_status"] == "LAB_FABRICATION"


class TestDispatchDerivations:
    def test_standard_dispatch_charges_no_rush_fee_and_uses_the_ten_day_formula(self, api, front_office_headers):
        """PRD §3.5: "`promised_due_at` is `dispatched_at` plus the laboratory's
        `standard_turnaround_days` when `turnaround_class` is `STANDARD`, or plus its
        `rush_turnaround_days` when it is `RUSH`; on a laboratory left at its
        defaults that is ten calendar days for a standard case and four for a rush
        case, with the time-of-day of the dispatch preserved."
        PRD §3.5: "`rush_fee_amount` is 0.00 for a standard case; for a rush case it
        is 120.00 plus 35.00 multiplied by the case's `unit_count`, rounded half up to
        two decimal places — so a rush case of three units carries a rush fee of
        225.00."

        Design: Corner/calculations/standard_turnaround_charges_no_rush_fee_and_uses_the_ten_day_formula
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Ugo Beninati", date_of_birth="1944-10-22", phone="555-1019"
        )
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 90)
        lab_case = fx.draft_lab_case(
            built["arch"]["id"], lab["id"], turnaround_class="STANDARD", unit_count=4
        )

        dispatched = validate_success(
            api.dispatch_lab_case(lab_case["id"], front_office_headers), 200
        )

        assert_same_instant(
            dispatched["promised_due_at"], "2026-05-11T00:00:00.000Z", "LabCase.promised_due_at"
        )
        assert_same_instant(
            dispatched["shelf_life_expires_at"],
            "2026-06-15T00:00:00.000Z",
            "LabCase.shelf_life_expires_at",
        )
        assert_money(dispatched["rush_fee_amount"], 0.00, "rush_fee_amount despite unit_count 4")

        case = fx.read_case(built["case"]["id"])
        assert_money(case["billed_amount"], 1200.00, "ProsthesisCase.billed_amount")
        assert_money(
            case["patient_responsibility_amount"], 1200.00, "patient_responsibility_amount"
        )


class TestBenchLineOverlap:
    def _two_arches_on_one_bench_line(self):
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Solveig Ntanda", date_of_birth="1949-09-09", phone="555-0411"
        )
        lab = fx.register_lab()
        first = fx.drive_arch_to_lab_fabrication(
            patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 93
        )
        lab_case_one = fx.draft_lab_case(first["arch"]["id"], lab["id"], bench_line=1)
        dispatched_one = fx.dispatch_lab_case(lab_case_one["id"])
        second = fx.drive_arch_to_lab_fabrication(
            patient["id"], "FLEXIBLE_PARTIAL", "MANDIBULAR", 93
        )
        lab_case_two = fx.draft_lab_case(second["arch"]["id"], lab["id"], bench_line=1)
        return dispatched_one, lab_case_two

    def test_a_dispatch_one_second_inside_the_occupied_window_collides(self, api, front_office_headers):
        """PRD §3.5: "The second check, at rung 21, is about the laboratory's
        capacity: the interval running from the dispatch instant up to but **not
        including** the new case's `promised_due_at` must not intersect the same
        half-open interval of any other lab case sharing the same `dental_lab_id` and
        `bench_line` whose `lab_status` is `DISPATCHED`, `RETURNED`, `QC_FAILED`, or
        `RESENT`."
        PRD §3.5: "Because the intervals are half-open, touching is permitted: a
        dispatch landing exactly on another case's `promised_due_at` passes, while a
        dispatch one millisecond earlier collides with `ERR_LAB_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/lab_bench_line_half_open_interval_allows_touching_dispatch
        """
        dispatched_one, lab_case_two = self._two_arches_on_one_bench_line()
        assert_same_instant(
            dispatched_one["dispatched_at"], "2026-05-01T00:00:00.000Z", "LabCase.dispatched_at"
        )
        assert_same_instant(
            dispatched_one["promised_due_at"], "2026-05-11T00:00:00.000Z", "LabCase.promised_due_at"
        )

        fx.set_clock("2026-05-10T23:59:59Z")
        response = api.dispatch_lab_case(lab_case_two["id"], front_office_headers)
        validate_error(response, ApiErrorId.ERR_LAB_SLOT_CONFLICT.value, 409)

        assert fx.read_lab_case(lab_case_two["id"])["lab_status"] == "DRAFT"

    def test_a_dispatch_landing_exactly_on_the_promised_due_instant_is_accepted(self, api, front_office_headers):
        """PRD §3.5: "Because the intervals are half-open, touching is permitted: a
        dispatch landing exactly on another case's `promised_due_at` passes, while a
        dispatch one millisecond earlier collides with `ERR_LAB_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/lab_bench_line_half_open_interval_allows_touching_dispatch
        """
        _, lab_case_two = self._two_arches_on_one_bench_line()

        fx.set_clock("2026-05-10T23:59:59Z")
        validate_error(
            api.dispatch_lab_case(lab_case_two["id"], front_office_headers),
            ApiErrorId.ERR_LAB_SLOT_CONFLICT.value,
            409,
        )

        fx.set_clock("2026-05-11T00:00:00Z")
        dispatched = validate_success(
            api.dispatch_lab_case(lab_case_two["id"], front_office_headers), 200
        )

        assert dispatched["lab_status"] == "DISPATCHED"
        assert_same_instant(
            dispatched["dispatched_at"], "2026-05-11T00:00:00.000Z", "LabCase.dispatched_at"
        )
        assert_same_instant(
            dispatched["promised_due_at"], "2026-05-21T00:00:00.000Z", "LabCase.promised_due_at"
        )


class TestArchTurnaroundBuffer:
    def _delivered_arch_with_a_lab_service(self):
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Tamsin Okonjo", "date_of_birth": "1953-03-03", "phone": "555-0422"
            }
        )
        service = fx.request_service(
            ctx["prosthesis"]["id"],
            "HARD_RELINE_LAB",
            dental_lab_id=ctx["lab"]["id"],
            bench_line=2,
        )
        ctx["service"] = service
        return ctx

    def test_redispatch_at_exactly_twenty_four_hours_after_the_return_still_conflicts(self, api, front_office_headers):
        """PRD §3.5: "the arch must hold no other lab case whose `lab_status` is
        `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT`, and — when the arch's
        `last_lab_received_at` is not null — the logical clock must be strictly after
        `last_lab_received_at` plus 24 hours."
        PRD §3.5: "That buffer is a closed interval on the wrong side: a dispatch at
        exactly 24 hours after the last return is still a conflict and yields
        `ERR_ARCH_OCCUPIED`; only 24 hours and one millisecond later does it pass."

        Design: Difficulty/resource_temporal_overlap/arch_turnaround_buffer_closed_interval_blocks_redispatch_at_exactly_24h
        """
        ctx = self._delivered_arch_with_a_lab_service()
        arch = fx.read_arch(ctx["arch"]["id"])
        assert_same_instant(
            arch["last_lab_received_at"],
            "2026-05-01T00:00:00.000Z",
            "CaseArch.last_lab_received_at",
        )
        service = fx.read_service(ctx["service"]["id"])
        assert service["service_status"] == "AT_LAB"
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["in_patient_possession"] is False
        service_lab_case_id = service["lab_case_id"]

        fx.set_clock("2026-05-02T00:00:00Z")
        response = api.dispatch_lab_case(service_lab_case_id, front_office_headers)
        validate_error(response, ApiErrorId.ERR_ARCH_OCCUPIED.value, 409)

        assert fx.read_lab_case(service_lab_case_id)["lab_status"] == "DRAFT"

    def test_redispatch_one_second_past_the_buffer_is_accepted(self, api, front_office_headers):
        """PRD §3.5: "That buffer is a closed interval on the wrong side: a dispatch
        at exactly 24 hours after the last return is still a conflict and yields
        `ERR_ARCH_OCCUPIED`; only 24 hours and one millisecond later does it pass."
        PRD §2.5: "**Deadlines are instants, never end-of-day markers.** When a rule
        adds a whole number of calendar days or months to an anchor instant, the
        time-of-day component of the anchor is preserved exactly."

        Design: Difficulty/resource_temporal_overlap/arch_turnaround_buffer_closed_interval_blocks_redispatch_at_exactly_24h
        """
        ctx = self._delivered_arch_with_a_lab_service()
        service_lab_case_id = fx.read_service(ctx["service"]["id"])["lab_case_id"]

        fx.set_clock("2026-05-02T00:00:00Z")
        validate_error(
            api.dispatch_lab_case(service_lab_case_id, front_office_headers),
            ApiErrorId.ERR_ARCH_OCCUPIED.value,
            409,
        )

        fx.set_clock("2026-05-02T00:00:01Z")
        dispatched = validate_success(
            api.dispatch_lab_case(service_lab_case_id, front_office_headers), 200
        )

        assert dispatched["lab_status"] == "DISPATCHED"
        assert_same_instant(
            dispatched["dispatched_at"], "2026-05-02T00:00:01.000Z", "LabCase.dispatched_at"
        )
        assert_same_instant(
            dispatched["promised_due_at"], "2026-05-12T00:00:01.000Z", "LabCase.promised_due_at"
        )


class TestShelfLifeMutateThenReject:
    def _dispatched_case_past_its_shelf_life(self, name, dob, phone):
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
        lab = fx.register_lab()
        built = fx.drive_arch_to_lab_fabrication(patient["id"], "FLEXIBLE_PARTIAL", "MAXILLARY", 90)
        lab_case = fx.draft_lab_case(built["arch"]["id"], lab["id"])
        fx.dispatch_lab_case(lab_case["id"])
        fx.set_clock("2026-06-16T00:00:00Z")
        return lab, built["arch"], lab_case

    def test_receiving_past_the_shelf_life_commits_the_expiry_then_raises(self, api):
        """PRD §2.12: "**Rung 15 — receiving a lab case past its shelf life.** When a
        laboratory tries to return a case and the logical clock is strictly after that
        case's `shelf_life_expires_at`, the server first sets `lab_status` to
        `EXPIRED`, stamps `expired_at` with the logical clock, releases both the
        laboratory bench-line occupation and the arch occupation the case was holding,
        and increments the lab case's `version` by 1. That write is committed. Only
        then does the call fail with `ERR_LAB_CASE_EXPIRED` and HTTP 409."
        PRD §2.12: "If the parent arch was in `LAB_FABRICATION` it stays in
        `LAB_FABRICATION`, so a fresh lab case can be drafted and dispatched for it."

        Design: Corner/state_machines/lab_case_expired_mutate_then_reject_persists_before_raising
        """
        lab, arch, lab_case = self._dispatched_case_past_its_shelf_life(
            "Quique Ramires", "1954-06-18", "555-1015"
        )

        response = api.receive_lab_case(lab_case["id"], make_lab_technician_headers(lab["id"]))
        validate_error(response, ApiErrorId.ERR_LAB_CASE_EXPIRED.value, 409)

        after = fx.read_lab_case(lab_case["id"])
        assert after["lab_status"] == "EXPIRED"
        assert_same_instant(
            after["expired_at"], "2026-06-16T00:00:00.000Z", "LabCase.expired_at"
        )
        assert after["received_at"] is None

        arch_after = fx.read_arch(arch["id"])
        assert arch_after["arch_status"] == "LAB_FABRICATION"
        assert arch_after["last_lab_received_at"] is None

    def test_second_receive_on_the_expired_row_reports_the_terminal_gate_instead(self, api):
        """PRD §2.12: "*On a subsequent receive attempt against that same lab case*,
        the row is now sitting in `EXPIRED`, which is a terminal state of the lab-case
        axis. Rung 10 therefore fires first, the call returns **`ERR_TERMINAL_STATE`
        with HTTP 409 — not `ERR_LAB_CASE_EXPIRED`** — and no further write of any
        kind is performed."

        Design: Corner/state_machines/second_receive_on_an_expired_lab_case_is_pre_empted_by_the_terminal_gate
        """
        lab, _, lab_case = self._dispatched_case_past_its_shelf_life(
            "Rosa Delgado", "1951-07-19", "555-1016"
        )
        validate_error(
            api.receive_lab_case(lab_case["id"], make_lab_technician_headers(lab["id"])),
            ApiErrorId.ERR_LAB_CASE_EXPIRED.value,
            409,
        )
        version_after_expiry = fx.read_lab_case(lab_case["id"])["version"]

        response = api.receive_lab_case(lab_case["id"], make_lab_technician_headers(lab["id"]))
        validate_error(response, ApiErrorId.ERR_TERMINAL_STATE.value, 409)

        final = fx.read_lab_case(lab_case["id"])
        assert final["lab_status"] == "EXPIRED"
        assert final["version"] == version_after_expiry, (
            "the pre-empted call performs no further write of any kind"
        )
