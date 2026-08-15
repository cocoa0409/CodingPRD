"""Completion gates, downtime accounting, overage acknowledgement, cancellation."""

from test_helpers import (
    ONE_RADIO_EQUIPMENT,
    TEST_USERS,
    ApiErrorId,
    assert_timestamp_equals,
    create_regulatory_package,
    create_task,
    get_aircraft,
    get_panel_design,
    get_work_order,
    make_customer_headers,
    pass_ground_and_flight,
    record_package_decision,
    record_test_result,
    schedule_test_event,
    set_clock,
    setup_approved_work_order,
    setup_closeout_ready_work_order,
    setup_draft_work_order,
    setup_installation_work_order,
    setup_testing_work_order,
    submit_package,
    validate_error,
    validate_success,
    create_and_accept_wb_revision,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestOverageAckThreshold:
    def test_overage_of_four_days_completes_without_ack(self, api):
        """PRD §3.8: "Fourth, the downtime gate: when the job has run five or more days beyond the estimate — measured as the complete 24-hour periods elapsed between `inducted_at` and the current logical clock, minus `estimated_downtime_days` — `overage_acknowledged` must be true, and an unacknowledged overage of that size rejects completion with `ERR_DOWNTIME_OVERAGE_UNACKED`."
        PRD §3.8: "The server stamps `completed_at` from the logical clock and settles the downtime ledger: `actual_downtime_days` counts the complete 24-hour periods between `inducted_at` and `completed_at`, discarding any partial final day, and `downtime_overage_days` is that actual figure minus `estimated_downtime_days`."

        Design: Difficulty/boundary_precision_check/overage_ack_threshold_four_vs_five_days
        """
        bundle = setup_closeout_ready_work_order(
            customer_name="Boundary Owner", customer_email="b@x.com",
            work_order_overrides={"estimated_downtime_days": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        set_clock("2026-08-15T09:00:00Z")
        completed = validate_success(
            api.complete_work_order(bundle["work_order"]["id"], MANAGER))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_downtime_days"] == 14, (
            "14 whole days elapsed since induction at 2026-08-01T09:00:00Z")
        assert completed["downtime_overage_days"] == 4, (
            "four days over the estimate stays below the five-day gate")

    def test_overage_of_five_days_blocked_without_ack(self, api):
        """PRD §3.8: "Fourth, the downtime gate: when the job has run five or more days beyond the estimate — measured as the complete 24-hour periods elapsed between `inducted_at` and the current logical clock, minus `estimated_downtime_days` — `overage_acknowledged` must be true, and an unacknowledged overage of that size rejects completion with `ERR_DOWNTIME_OVERAGE_UNACKED`."

        Design: Difficulty/boundary_precision_check/overage_ack_threshold_four_vs_five_days
        """
        bundle = setup_closeout_ready_work_order(
            customer_name="Boundary Owner", customer_email="b@x.com",
            work_order_overrides={"estimated_downtime_days": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        set_clock("2026-08-16T09:00:00Z")
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_DOWNTIME_OVERAGE_UNACKED)
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "TESTING", (
            "the blocked completion leaves the work order in TESTING")
        assert work_order["completed_at"] is None


class TestOverageAcknowledgement:
    def test_acknowledgement_unblocks_completion(self, api):
        """PRD §3.8: "Fourth, the downtime gate: when the job has run five or more days beyond the estimate — measured as the complete 24-hour periods elapsed between `inducted_at` and the current logical clock, minus `estimated_downtime_days` — `overage_acknowledged` must be true, and an unacknowledged overage of that size rejects completion with `ERR_DOWNTIME_OVERAGE_UNACKED`."
        PRD §3.8: "Acting under the `Customer` role with `X-User-ID` equal to the owning customer's `id` (`ERR_FORBIDDEN` otherwise), the owner records the acknowledgement, which sets `overage_acknowledged` to true and advances the work order's `version` by one."

        Design: Corner/validations/overage_ack_unblocks_completion
        """
        bundle = setup_closeout_ready_work_order(
            customer_name="Ack Abby", customer_email="a2@x.com",
            work_order_overrides={"estimated_downtime_days": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        set_clock("2026-08-16T09:00:00Z")
        blocked = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(blocked, ApiErrorId.ERR_DOWNTIME_OVERAGE_UNACKED)

        acknowledged = validate_success(api.acknowledge_overage(
            bundle["work_order"]["id"],
            make_customer_headers(bundle["customer"]["id"])))
        assert acknowledged["overage_acknowledged"] is True

        completed = validate_success(
            api.complete_work_order(bundle["work_order"]["id"], MANAGER))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_downtime_days"] == 15
        assert completed["downtime_overage_days"] == 5


class TestCompletionAccounting:
    def test_partial_day_floors_and_term_dates_shift(self, api):
        """PRD §3.8: "The server stamps `completed_at` from the logical clock and settles the downtime ledger: `actual_downtime_days` counts the complete 24-hour periods between `inducted_at` and `completed_at`, discarding any partial final day, and `downtime_overage_days` is that actual figure minus `estimated_downtime_days`."
        PRD §3.8: "Warranty and subscription clocks start at completion: `warranty_expires_at` is `completed_at` shifted forward by `warranty_term_months` calendar months, and `subscription_expires_at` is `completed_at` shifted forward by `software_subscription_months` calendar months; in both cases, when the target month lacks the completion's day-of-month, the date clamps to that month's last day."
        PRD §3.8: "Completion also returns the aircraft from `IN_SHOP` to `AVAILABLE` and advances the work order's `version` by one."

        Design: Corner/calculations/downtime_floor_and_warranty_dates
        """
        bundle = setup_closeout_ready_work_order(
            customer_name="Down Donna", customer_email="d2@x.com",
            work_order_overrides={"estimated_downtime_days": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z",
                                  "warranty_term_months": 12,
                                  "software_subscription_months": 6})
        set_clock("2026-08-11T08:30:00Z")
        completed = validate_success(
            api.complete_work_order(bundle["work_order"]["id"], MANAGER))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_downtime_days"] == 9, (
            "9 days 23.5 hours elapsed floors to 9 complete days, "
            f"got {completed['actual_downtime_days']}")
        assert completed["downtime_overage_days"] == -1
        assert_timestamp_equals(completed["warranty_expires_at"],
                                "2027-08-11T08:30:00Z")
        assert_timestamp_equals(completed["subscription_expires_at"],
                                "2027-02-11T08:30:00Z")
        assert get_aircraft(bundle["aircraft"]["id"])["status"] == "AVAILABLE", (
            "completion returns the aircraft from IN_SHOP to AVAILABLE")


class TestCompletionSafetyGates:
    def test_complete_without_flight_pass_rejected(self, api):
        """PRD §3.8: "First, testing: at least one `GROUND` event and at least one `FLIGHT` event of the work order must be `PASSED`, otherwise `ERR_TESTS_NOT_PASSED`."

        Design: Corner/errors/complete_without_flight_pass_rejected
        """
        bundle = setup_testing_work_order(
            customer_name="NoFly Flo", customer_email="f2@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=2.0, actual_hours=2.0)
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        record_test_result(ground["id"], "PASS")
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_TESTS_NOT_PASSED)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING"

    def test_complete_without_accepted_wb_rejected(self, api):
        """PRD §3.8: "Third, weight and balance: a revision in `ACCEPTED` must exist, otherwise `ERR_WB_NOT_ACCEPTED`."

        Design: Corner/errors/complete_without_accepted_wb_rejected
        """
        bundle = setup_testing_work_order(
            customer_name="NoWB Will", customer_email="w2@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=2.0, actual_hours=2.0)
        pass_ground_and_flight(bundle)
        bundle["package"] = create_regulatory_package(
            bundle["work_order"]["id"], approval_path="STC",
            stc_number="STC-SA4321")
        submit_package(bundle["package"]["id"])
        record_package_decision(bundle["package"]["id"], "APPROVED",
                                inspector_id="insp-1")
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_WB_NOT_ACCEPTED)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING"


class TestCompletionValidationOrder:
    def test_state_gate_beats_safety_gate(self, api):
        """PRD §2.11: "When several checks could reject the same request, the server does not choose among them freely: checks run in the fixed order below, and the request fails with the first violation found."
        PRD §2.11: "Fifth is state validity with `ERR_INVALID_STATE`: the target entity must sit in a valid from-state for the requested transition, which also covers terminal lockdown and actions attempted on superseded designs. Sixth come the safety and compliance gates, which keep their own internal order: segregation of duties on task verification (`ERR_SEGREGATION_OF_DUTIES`), then the ground-before-flight requirement on flight-test scheduling (`ERR_GROUND_TEST_REQUIRED`), then CG limits on weight-and-balance acceptance (`ERR_CG_OUT_OF_LIMITS`), and on work-order completion the trio of tests passed, regulatory approved, and weight-and-balance accepted in that sequence (`ERR_TESTS_NOT_PASSED`, then `ERR_REGULATORY_NOT_APPROVED`, then `ERR_WB_NOT_ACCEPTED`)."

        Design: Difficulty/priority_pair_validation_conflict/complete_state_beats_safety
        """
        bundle = setup_installation_work_order(customer_name="Pri Owner",
                                               customer_email="p@x.com",
                                               equipment_list=[])
        create_task(bundle["work_order"]["id"], task_kind="INSTALLATION",
                    estimated_hours=2.0)
        # No regulatory package exists, so the safety gate is also violated —
        # but the work order is not in TESTING, so the state gate fires first.
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_state_gate_leaves_work_order_untouched(self, api):
        """PRD §3.8: "Completing moves the work order from `TESTING` to the terminal `COMPLETED` state. Until this transition, `actual_downtime_days`, `downtime_overage_days`, `warranty_expires_at`, and `subscription_expires_at` all remain null."
        PRD §2.11: "When several checks could reject the same request, the server does not choose among them freely: checks run in the fixed order below, and the request fails with the first violation found."

        Design: Difficulty/priority_pair_validation_conflict/complete_state_beats_safety
        """
        bundle = setup_installation_work_order(customer_name="Pri Owner",
                                               customer_email="p@x.com",
                                               equipment_list=[])
        before = get_work_order(bundle["work_order"]["id"])
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        after = get_work_order(bundle["work_order"]["id"])
        assert after["status"] == "INSTALLATION"
        assert after["completed_at"] is None
        assert after["version"] == before["version"], (
            "a rejected transition must not advance the work order's version")

    def test_safety_gate_beats_temporal_gate(self, api):
        """PRD §2.11: "Sixth come the safety and compliance gates, which keep their own internal order: segregation of duties on task verification (`ERR_SEGREGATION_OF_DUTIES`), then the ground-before-flight requirement on flight-test scheduling (`ERR_GROUND_TEST_REQUIRED`), then CG limits on weight-and-balance acceptance (`ERR_CG_OUT_OF_LIMITS`), and on work-order completion the trio of tests passed, regulatory approved, and weight-and-balance accepted in that sequence (`ERR_TESTS_NOT_PASSED`, then `ERR_REGULATORY_NOT_APPROVED`, then `ERR_WB_NOT_ACCEPTED`). Seventh are the temporal conflicts: bay-window overlap on work-order creation (`ERR_BAY_WINDOW_CONFLICT`), flight-window buffer conflicts on test-event scheduling and rescheduling (`ERR_FLIGHT_WINDOW_CONFLICT`), and the unacknowledged downtime overage on completion (`ERR_DOWNTIME_OVERAGE_UNACKED`)."

        Design: Difficulty/priority_pair_validation_conflict/complete_safety_beats_temporal
        """
        bundle = self._closeout_ready_except_package(api)
        set_clock("2026-08-16T09:00:00Z")  # overage is exactly 5 days, unacknowledged
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_REGULATORY_NOT_APPROVED)
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "TESTING"

    def test_temporal_gate_fires_once_safety_is_satisfied(self, api):
        """PRD §2.11: "Seventh are the temporal conflicts: bay-window overlap on work-order creation (`ERR_BAY_WINDOW_CONFLICT`), flight-window buffer conflicts on test-event scheduling and rescheduling (`ERR_FLIGHT_WINDOW_CONFLICT`), and the unacknowledged downtime overage on completion (`ERR_DOWNTIME_OVERAGE_UNACKED`)."
        PRD §3.8: "Completion is the most heavily gated transition in the system, and its gates fire in a fixed order."

        Design: Difficulty/priority_pair_validation_conflict/complete_safety_beats_temporal
        """
        bundle = self._closeout_ready_except_package(api)
        set_clock("2026-08-16T09:00:00Z")
        # Satisfy the safety gate, leaving only the unacknowledged overage.
        record_package_decision(bundle["package"]["id"], "APPROVED",
                                inspector_id="insp-1")
        response = api.complete_work_order(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_DOWNTIME_OVERAGE_UNACKED)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING"

    def _closeout_ready_except_package(self, api):
        """TESTING with GROUND+FLIGHT PASSED, W&B ACCEPTED, and an STC package
        stuck in CONFORMITY_REVIEW (submitted but not decided)."""
        bundle = setup_testing_work_order(
            customer_name="Pri2 Owner", customer_email="p2@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=2.0, actual_hours=2.0,
            work_order_overrides={"bay_window_end": "2026-08-30T00:00:00Z"})
        pass_ground_and_flight(bundle)
        bundle["wb_revision"] = create_and_accept_wb_revision(
            bundle["work_order"]["id"])
        bundle["package"] = create_regulatory_package(
            bundle["work_order"]["id"], approval_path="STC",
            stc_number="STC-SA9999")
        submit_package(bundle["package"]["id"])
        return bundle


class TestCancellation:
    def test_cancelled_work_order_locks_actions(self, api):
        """PRD §3.8: "Work orders already `COMPLETED` or `CANCELLED` accept no further actions — terminal lockdown is reported as `ERR_INVALID_STATE`."
        PRD §3.8: "The derived counters `parts_pending_count` and `tasks_unverified_count` are recomputed, the aircraft returns from `IN_SHOP` to `AVAILABLE`, and the work order's `version` advances by one."

        Design: Corner/state_machines/cancelled_work_order_locks_actions
        """
        bundle = setup_draft_work_order(customer_name="Lock Lee",
                                        customer_email="l@x.com",
                                        with_design=False)
        validate_success(api.cancel_work_order(bundle["work_order"]["id"], MANAGER))
        response = api.begin_installation(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "CANCELLED"
        assert get_aircraft(bundle["aircraft"]["id"])["status"] == "AVAILABLE", (
            "the cancel cascade releases the aircraft back to AVAILABLE")

    def test_cancel_cascades_to_children(self, api):
        """PRD §3.8: "The cancel cascade resolves every child of the work order: equipment orders in `PLANNED` or `ORDERED` move to `CANCELLED`; install tasks in `PLANNED`, `IN_PROGRESS`, or `COMPLETED` move to `VOIDED`, while a `VERIFIED` task is left untouched; test events in `SCHEDULED` or `FAILED` move to `CANCELLED`; and panel designs in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` move to `SUPERSEDED`."
        PRD §3.8: "The derived counters `parts_pending_count` and `tasks_unverified_count` are recomputed, the aircraft returns from `IN_SHOP` to `AVAILABLE`, and the work order's `version` advances by one."

        Design: Corner/state_machines/work_order_cancel_cascades_children
        """
        bundle = setup_approved_work_order(
            customer_name="Cancel Cal", customer_email="c2@x.com",
            equipment_list=ONE_RADIO_EQUIPMENT, layout_notes="one radio",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        order = bundle["orders"][0]
        validate_success(api.mark_ordered(order["id"], MANAGER))
        task = create_task(bundle["work_order"]["id"],
                           task_kind="HARNESS_FABRICATION", estimated_hours=3.0,
                           description="bench harness")

        cancelled = validate_success(
            api.cancel_work_order(bundle["work_order"]["id"], MANAGER))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["parts_pending_count"] == 0
        assert cancelled["tasks_unverified_count"] == 0
        fetched_order = validate_success(api.get_equipment_order(order["id"], MANAGER))
        assert fetched_order["status"] == "CANCELLED", (
            "the ORDERED order is cancelled by the cascade")
        fetched_task = validate_success(api.get_install_task(task["id"], MANAGER))
        assert fetched_task["status"] == "VOIDED", (
            "the PLANNED task is voided by the cascade")
        assert get_aircraft(bundle["aircraft"]["id"])["status"] == "AVAILABLE"
        assert get_panel_design(bundle["design"]["id"])["status"] == "APPROVED", (
            "the APPROVED design is terminal and untouched by the cancel cascade")
