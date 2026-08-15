"""Pressure testing, bay booking overlap, the rework loop, and certification
(PRD §3.7)."""
from test_helpers import (
    ADVISOR,
    INSPECTOR,
    ApiErrorId,
    approve_quote,
    begin_teardown,
    book_pressure_test,
    complete_assembly,
    consume_all_reservations,
    create_cylinder,
    create_inventory_item,
    create_pressure_test_payload,
    draft_quote,
    file_findings,
    get_success_data,
    issue_certificate,
    make_inspector_headers,
    make_technician_headers,
    open_work_order,
    record_passing_cleanliness,
    record_result_payload,
    send_quote,
    setup_certified,
    setup_in_repair,
    setup_master_data,
    setup_test_pending,
    start_repair,
    validate_error,
    validate_paginated,
    validate_success,
)


def _drive_to_assembled(api, md, cylinder, *, rod_needed, rod_cut_length_mm=400,
                        honing_passes=0, estimated_labor_hours=1.0):
    """Open a work order and drive it to ASSEMBLED under one shop."""
    wo = open_work_order(cylinder["id"], tier="EXPEDITE", promised_hours=30)
    begin_teardown(wo, md.tech)
    file_findings(wo, md.tech, rod_needed=rod_needed,
                  rod_cut_length_mm=rod_cut_length_mm, tube_needed=False,
                  honing_passes=honing_passes, estimated_labor_hours=estimated_labor_hours)
    quote = send_quote(draft_quote(wo))
    approve_quote(quote, md.customer)
    wo = get_success_data(api.get_work_order(wo["id"], ADVISOR))
    start_repair(wo, md.tech)
    consume_all_reservations(wo, md.tech)
    record_passing_cleanliness(wo, md.tech)
    return complete_assembly(wo, md.tech)


class TestPressureTestCreationGate:
    def test_create_requires_work_order_assembled(self, api):
        """PRD §3.7: "With the work order `ASSEMBLED`, a `QualityInspector` books
        a pressure test by supplying the `work_order_id`, the `test_bay_id`, and
        a booking `window_start` and `window_end`."
        PRD §2.7: "A non-terminal resource addressed from the wrong from-state
        for the requested transition is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/pressure_test_requires_work_order_assembled
        """
        sc = setup_in_repair(with_bay=True)  # repair under way, not ASSEMBLED
        resp = api.create_pressure_test(
            create_pressure_test_payload(sc.work_order["id"], sc.bay["id"]), INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        _data, meta = validate_paginated(
            api.list_pressure_tests(ADVISOR, params={"work_order_id": sc.work_order["id"]})
        )
        assert meta["total_count"] == 0

    def test_retest_booking_rules_in_test_pending(self, api):
        """PRD §3.7: "A work order already in `TEST_PENDING` — because a
        scheduled test was cancelled or a certificate was revoked — may have a
        fresh test booked, provided no `SCHEDULED` test is currently outstanding
        for it; booking while one exists is rejected with `ERR_INVALID_STATE`.
        The re-test keeps the work order in `TEST_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/pressure_test_requires_work_order_assembled
        """
        sc = setup_test_pending()
        # A SCHEDULED test is outstanding: a second booking is rejected.
        resp = api.create_pressure_test(
            create_pressure_test_payload(
                sc.work_order["id"], sc.bay["id"],
                window_start="2026-08-02T13:00:00Z", window_end="2026-08-02T14:00:00Z",
            ),
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Cancel frees the slot; a fresh booking succeeds and keeps TEST_PENDING.
        cancelled = validate_success(api.cancel_pressure_test(sc.pressure_test["id"], INSPECTOR))
        assert cancelled["status"] == "CANCELLED"
        retest = validate_success(
            api.create_pressure_test(
                create_pressure_test_payload(
                    sc.work_order["id"], sc.bay["id"],
                    window_start="2026-08-02T13:00:00Z", window_end="2026-08-02T14:00:00Z",
                ),
                INSPECTOR,
            ),
            201,
        )
        assert retest["status"] == "SCHEDULED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "TEST_PENDING"


class TestBayBookingBuffer:
    def _two_assembled_work_orders(self, api):
        md = setup_master_data(with_bay=True)
        cyl1 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-E01")
        cyl2 = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-E02")
        create_inventory_item(length_mm=2000)  # rod stock @42c/mm
        wo1 = _drive_to_assembled(api, md, cyl1, rod_needed=True, rod_cut_length_mm=400)
        wo2 = _drive_to_assembled(api, md, cyl2, rod_needed=False, honing_passes=1)
        book_pressure_test(wo1, md.bay)  # [2026-08-02T10:00, 11:00]
        return md, wo1, wo2

    def test_unbuffered_adjacent_booking_rejected(self, api):
        """PRD §3.7: "Bay bookings are closed intervals — both `window_start` and
        `window_end` are inclusive — and every booking additionally occupies the
        mandatory `bay_buffer_minutes` (30 minutes by default) of clearance on
        both sides of its window. A new booking whose buffer-extended interval
        collides with the buffer-extended interval of another booking of the same
        bay that is `SCHEDULED`, or that has passed but is still pending
        downstream resolution, is rejected with `ERR_TEST_BAY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/test_bay_booking_requires_thirty_minute_buffer
        """
        md, _wo1, wo2 = self._two_assembled_work_orders(api)
        # [11:00, 11:30] starts exactly when the prior booking ends: zero clearance.
        resp = api.create_pressure_test(
            create_pressure_test_payload(
                wo2["id"], md.bay["id"],
                window_start="2026-08-02T11:00:00Z", window_end="2026-08-02T11:30:00Z",
            ),
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_BAY_WINDOW_OVERLAP)
        _data, meta = validate_paginated(
            api.list_pressure_tests(ADVISOR, params={"work_order_id": wo2["id"]})
        )
        assert meta["total_count"] == 0
        wo2_after = get_success_data(api.get_work_order(wo2["id"], ADVISOR))
        assert wo2_after["status"] == "ASSEMBLED"

    def test_booking_with_ample_clearance_accepted(self, api):
        """PRD §3.7: "A new booking whose buffer-extended interval collides with
        the buffer-extended interval of another booking of the same bay that is
        `SCHEDULED`, or that has passed but is still pending downstream
        resolution, is rejected with `ERR_TEST_BAY_WINDOW_OVERLAP`."
        PRD §3.7: "Creation moves the work order from `ASSEMBLED` to
        `TEST_PENDING` and creates the test in `SCHEDULED`"

        Design: Difficulty/resource_temporal_overlap/test_bay_booking_requires_thirty_minute_buffer
        """
        md, _wo1, wo2 = self._two_assembled_work_orders(api)
        # [13:00, 14:00] leaves 120 minutes after the prior booking's end — well
        # clear of the mandatory 30-minute buffer on both sides.
        booking = validate_success(
            api.create_pressure_test(
                create_pressure_test_payload(
                    wo2["id"], md.bay["id"],
                    window_start="2026-08-02T13:00:00Z", window_end="2026-08-02T14:00:00Z",
                ),
                INSPECTOR,
            ),
            201,
        )
        assert booking["status"] == "SCHEDULED"
        wo2_after = get_success_data(api.get_work_order(wo2["id"], ADVISOR))
        assert wo2_after["status"] == "TEST_PENDING"


class TestReworkCycle:
    def test_failed_test_loops_back_and_resets_cleanliness(self, api):
        """PRD §3.7: "A recorded failure moves the test to `FAILED` and loops the
        work order back from `TEST_PENDING` to `IN_REPAIR`, resetting
        `cleanliness_passed` to false while retaining the latest cleanliness
        codes for history; the rework cycle is then repair again, re-verify
        cleanliness, complete assembly again, and book a fresh test."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle_test_fail_loops_to_in_repair
        """
        sc = setup_test_pending()
        failed = validate_success(
            api.record_pressure_test_result(
                sc.pressure_test["id"],
                record_result_payload(measured_hold_psi=4300, duration_min=10,
                                      leakage_drops=2, passed=False),
                INSPECTOR,
            )
        )
        assert failed["status"] == "FAILED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "IN_REPAIR"
        assert wo["cleanliness_passed"] is False
        # Latest codes retained for history (from the earlier passing sample).
        assert wo["latest_cleanliness_code14"] == 13

    def test_full_rework_cycle_returns_to_test_passed(self, api):
        """PRD §3.7: "A recorded failure moves the test to `FAILED` and loops the
        work order back from `TEST_PENDING` to `IN_REPAIR`, resetting
        `cleanliness_passed` to false while retaining the latest cleanliness
        codes for history; the rework cycle is then repair again, re-verify
        cleanliness, complete assembly again, and book a fresh test."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle_test_fail_loops_to_in_repair
        """
        sc = setup_test_pending()
        validate_success(
            api.record_pressure_test_result(
                sc.pressure_test["id"],
                record_result_payload(measured_hold_psi=4300, duration_min=10,
                                      leakage_drops=2, passed=False),
                INSPECTOR,
            )
        )
        wo = record_passing_cleanliness(sc.work_order, sc.tech)
        assert wo["cleanliness_passed"] is True
        wo = complete_assembly(wo, sc.tech)
        assert wo["status"] == "ASSEMBLED"
        retest = book_pressure_test(wo, sc.bay, window_start="2026-08-02T13:00:00Z",
                                    window_end="2026-08-02T14:00:00Z")
        passed = validate_success(
            api.record_pressure_test_result(
                retest["id"],
                record_result_payload(measured_hold_psi=4500, duration_min=12,
                                      leakage_drops=0, passed=True),
                INSPECTOR,
            )
        )
        assert passed["status"] == "PASSED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "TEST_PASSED"
        first = get_success_data(api.get_pressure_test(sc.pressure_test["id"], ADVISOR))
        assert first["status"] == "FAILED"


class TestCertificateRevokeCascade:
    def test_revoke_moves_work_order_back_to_test_pending(self, api):
        """PRD §3.7: "A `QualityInspector` revokes an `ISSUED` certificate by
        supplying a `reason`, which is recorded as `revoke_reason`, moving the
        certificate to the terminal `REVOKED` state. The revocation cascades: the
        work order falls back from `CERTIFIED` to `TEST_PENDING`, and the
        certificate's pressure test moves from `PASSED` to `VOIDED`."

        Design: Difficulty/transitive_cascade/certificate_revoke_cascade_depth2
        """
        sc = setup_certified()
        revoked = validate_success(
            api.revoke_certificate(
                sc.certificate["id"], {"reason": "contamination found in audit"}, INSPECTOR
            )
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoke_reason"] == "contamination found in audit"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "TEST_PENDING"

    def test_revoke_voids_the_underlying_passed_test(self, api):
        """PRD §3.7: "The revocation cascades: the work order falls back from
        `CERTIFIED` to `TEST_PENDING`, and the certificate's pressure test moves
        from `PASSED` to `VOIDED`. A fresh pressure test must then be booked and
        passed before the work order can be re-certified."

        Design: Difficulty/transitive_cascade/certificate_revoke_cascade_depth2
        """
        sc = setup_certified()
        validate_success(
            api.revoke_certificate(
                sc.certificate["id"], {"reason": "contamination found in audit"}, INSPECTOR
            )
        )
        test = get_success_data(api.get_pressure_test(sc.pressure_test["id"], ADVISOR))
        assert test["status"] == "VOIDED"
        # Recovery path: a fresh test can be booked from TEST_PENDING.
        retest = validate_success(
            api.create_pressure_test(
                create_pressure_test_payload(
                    sc.work_order["id"], sc.bay["id"],
                    window_start="2026-08-02T13:00:00Z", window_end="2026-08-02T14:00:00Z",
                ),
                INSPECTOR,
            ),
            201,
        )
        assert retest["status"] == "SCHEDULED"


class TestCertificationGuards:
    def test_segregation_of_duties_beats_certificate_exists(self, api):
        """PRD §2.9: "Validations are applied to every request in a fixed
        priority order, and an earlier failure masks every later one — the client
        always sees the first failing check's error, never a later check's."
        PRD §3.7: "Segregation of duties is enforced: the issuing inspector's
        `X-User-ID` must differ from the work order's `assigned_technician_id`,
        and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_certificate_issue
        """
        sc = setup_certified()
        # Caller id equals the assigned technician id (safety gate, priority 9)
        # AND a certificate is already ISSUED (structural guard, priority 11).
        resp = api.create_certificate(
            {"work_order_id": sc.work_order["id"]},
            make_inspector_headers(sc.tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 422

    def test_second_certificate_from_independent_inspector_rejected(self, api):
        """PRD §3.7: "At most one `ISSUED` certificate may exist per work order;
        a second issuance is rejected with `ERR_CERTIFICATE_EXISTS`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_certificate_issue
        """
        sc = setup_certified()
        # Independent inspector: safety gate passes, only the uniqueness
        # constraint fails.
        resp = api.create_certificate(
            {"work_order_id": sc.work_order["id"]}, make_inspector_headers("insp-10")
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXISTS)
        assert resp.status_code == 409


class TestPressurePassBoundary:
    def test_pass_boundary_exact_hold(self, api):
        """PRD §3.7: "A pass claim is valid only when the measured hold pressure
        is at least `required_hold_psi` — the boundary is inclusive — the
        `duration_min` is at least `test_hold_min_minutes` (10 minutes by
        default), and `leakage_drops` is exactly zero; a `passed` claim that
        violates any leg is rejected with `ERR_PRESSURE_HOLD_INSUFFICIENT`."
        PRD §3.7: "under the defaults yields a 4500 psi required hold for
        `CLASS_3000`"

        Design: Corner/calculations/pressure_pass_boundary_exact_hold
        """
        sc = setup_test_pending()
        assert sc.pressure_test["required_hold_psi"] == 4500
        # One psi short: the pass claim is rejected, the test stays SCHEDULED.
        resp = api.record_pressure_test_result(
            sc.pressure_test["id"],
            record_result_payload(measured_hold_psi=4499, duration_min=10,
                                  leakage_drops=0, passed=True),
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PRESSURE_HOLD_INSUFFICIENT)
        test = get_success_data(api.get_pressure_test(sc.pressure_test["id"], ADVISOR))
        assert test["status"] == "SCHEDULED"
        # Retry at exactly 4500 psi: the >= boundary is inclusive.
        passed = validate_success(
            api.record_pressure_test_result(
                sc.pressure_test["id"],
                record_result_payload(measured_hold_psi=4500, duration_min=10,
                                      leakage_drops=0, passed=True),
                INSPECTOR,
            )
        )
        assert passed["status"] == "PASSED"
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "TEST_PASSED"
