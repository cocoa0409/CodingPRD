"""Ground/flight testing: gates, buffered flight windows, retests, rework cascade."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_test_event_payload,
    get_test_event,
    get_work_order,
    record_test_result,
    reschedule_event,
    schedule_test_event,
    setup_installation_work_order,
    setup_testing_work_order,
    validate_error,
    validate_paginated,
    validate_success,
    work_task_to_completed,
    work_task_to_verified,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestBeginTestingGates:
    def test_begin_testing_without_any_tasks_rejected(self, api):
        """PRD §3.5: "The move is gated, and the gates are checked in order: at least one install task must be `VERIFIED` (`ERR_NO_INSTALL_TASKS`), and then no task may remain unverified — `tasks_unverified_count` must be zero (`ERR_TASKS_UNVERIFIED`)."

        Design: Corner/state_machines/begin_testing_without_tasks_rejected
        """
        bundle = setup_installation_work_order(customer_name="NoTask Nate",
                                               customer_email="n2@x.com",
                                               equipment_list=[])
        response = api.begin_testing(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_NO_INSTALL_TASKS)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "INSTALLATION"

    def test_begin_testing_with_unverified_task_rejected(self, api):
        """PRD §3.5: "The move is gated, and the gates are checked in order: at least one install task must be `VERIFIED` (`ERR_NO_INSTALL_TASKS`), and then no task may remain unverified — `tasks_unverified_count` must be zero (`ERR_TASKS_UNVERIFIED`)."

        Design: Corner/state_machines/begin_testing_with_unverified_task_rejected
        """
        bundle = setup_installation_work_order(customer_name="Unver Uma",
                                               customer_email="u@x.com",
                                               equipment_list=[])
        work_task_to_completed(bundle["work_order"]["id"], task_kind="INSTALLATION",
                               estimated_hours=2.0, actual_hours=2.0,
                               technician_id="tech-1")
        response = api.begin_testing(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_TASKS_UNVERIFIED)
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["tasks_unverified_count"] == 1
        assert work_order["status"] == "INSTALLATION"


class TestEventSchedulingGate:
    def test_event_create_rejected_before_testing(self, api):
        """PRD §3.5: "Events can exist only while the work order is in `TESTING` (`ERR_INVALID_STATE`), and a new event starts `SCHEDULED` with `attempt` 1 and `result` `NONE`."

        Design: Difficulty/cross_entity_state_dependency/test_event_create_requires_testing_work_order
        """
        bundle = setup_installation_work_order(customer_name="Gate Owner",
                                               customer_email="g@x.com",
                                               equipment_list=[])
        work_task_to_verified(bundle["work_order"]["id"], task_kind="INSTALLATION",
                              estimated_hours=2.0, actual_hours=2.0)
        response = api.create_test_event(
            create_test_event_payload(bundle["work_order"]["id"], test_kind="GROUND"),
            MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        events, meta = validate_paginated(
            api.list_test_events(MANAGER,
                                 params={"work_order_id": bundle["work_order"]["id"]}))
        assert events == [] and meta["total_count"] == 0

    def test_event_create_accepted_once_testing(self, api):
        """PRD §3.5: "Events can exist only while the work order is in `TESTING` (`ERR_INVALID_STATE`), and a new event starts `SCHEDULED` with `attempt` 1 and `result` `NONE`."

        Design: Difficulty/cross_entity_state_dependency/test_event_create_requires_testing_work_order
        """
        bundle = setup_testing_work_order(customer_name="Gate Owner",
                                          customer_email="g@x.com",
                                          equipment_list=[], task_kind="INSTALLATION",
                                          estimated_hours=2.0, actual_hours=2.0)
        event = validate_success(api.create_test_event(
            create_test_event_payload(bundle["work_order"]["id"], test_kind="GROUND"),
            MANAGER), 201)
        assert event["status"] == "SCHEDULED"
        assert event["attempt"] == 1
        assert event["result"] == "NONE"


class TestGroundBeforeFlight:
    def test_flight_create_without_ground_pass_rejected(self, api):
        """PRD §3.5: "Flight carries two extra gates: at least one `GROUND` event of the same work order must already be `PASSED` (`ERR_GROUND_TEST_REQUIRED`), and the new window must clear the 60-minute buffered separation rule of §2.6 against every other `SCHEDULED` or `FAILED` flight of the same aircraft (`ERR_FLIGHT_WINDOW_CONFLICT`)."

        Design: Corner/errors/flight_create_without_ground_pass_rejected
        """
        bundle = setup_testing_work_order(customer_name="Ground Gail",
                                          customer_email="g2@x.com",
                                          equipment_list=[], task_kind="INSTALLATION",
                                          estimated_hours=2.0, actual_hours=2.0,
                                          work_order_overrides={
                                              "estimated_downtime_days": 15,
                                              "bay_window_end": "2026-08-25T00:00:00Z"})
        response = api.create_test_event(
            create_test_event_payload(
                bundle["work_order"]["id"], test_kind="FLIGHT",
                scheduled_start="2026-08-10T14:00:00Z",
                scheduled_end="2026-08-10T15:30:00Z"),
            MANAGER)
        validate_error(response, ApiErrorId.ERR_GROUND_TEST_REQUIRED)
        events, meta = validate_paginated(
            api.list_test_events(MANAGER,
                                 params={"work_order_id": bundle["work_order"]["id"]}))
        assert events == [], "the rejected flight event must not persist"


class TestFlightWindowBuffer:
    def _testing_bundle_with_first_flight(self, api):
        bundle = setup_testing_work_order(
            customer_name="Buffer Owner", customer_email="buf@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=2.0, actual_hours=2.0,
            work_order_overrides={"estimated_downtime_days": 25,
                                  "bay_window_end": "2026-08-31T00:00:00Z"})
        ground = schedule_test_event(
            bundle["work_order"]["id"], test_kind="GROUND",
            scheduled_start="2026-08-05T10:00:00Z",
            scheduled_end="2026-08-05T11:00:00Z")
        record_test_result(ground["id"], "PASS")
        first = schedule_test_event(
            bundle["work_order"]["id"], test_kind="FLIGHT",
            scheduled_start="2026-08-18T14:00:00Z",
            scheduled_end="2026-08-18T15:30:00Z")
        return bundle, first

    def test_flight_at_exactly_buffer_edge_accepted(self, api):
        """PRD §2.6: "Every flight test in `SCHEDULED` or `FAILED` status owns a buffered window that runs from 60 minutes before its `scheduled_start` to 60 minutes after its `scheduled_end`, again half-open. When a flight is first scheduled, and again whenever a failed flight is rescheduled, the new window must not intersect the buffered window of any other `SCHEDULED` or `FAILED` flight belonging to the same aircraft; a violation is rejected with `ERR_FLIGHT_WINDOW_CONFLICT` (HTTP 409), while a window that only touches a buffer's edge is acceptable."

        Design: Difficulty/resource_temporal_overlap/flight_window_sixty_minute_buffer
        """
        bundle, _first = self._testing_bundle_with_first_flight(api)
        # Buffered window of flight-1: [13:00, 16:30); starting at exactly 16:30
        # only touches the buffer's edge.
        edge = validate_success(api.create_test_event(
            create_test_event_payload(
                bundle["work_order"]["id"], test_kind="FLIGHT",
                scheduled_start="2026-08-18T16:30:00Z",
                scheduled_end="2026-08-18T17:30:00Z"),
            MANAGER), 201)
        assert edge["status"] == "SCHEDULED"

    def test_flight_inside_or_adjacent_to_buffer_rejected(self, api):
        """PRD §2.6: "Every flight test in `SCHEDULED` or `FAILED` status owns a buffered window that runs from 60 minutes before its `scheduled_start` to 60 minutes after its `scheduled_end`, again half-open. When a flight is first scheduled, and again whenever a failed flight is rescheduled, the new window must not intersect the buffered window of any other `SCHEDULED` or `FAILED` flight belonging to the same aircraft; a violation is rejected with `ERR_FLIGHT_WINDOW_CONFLICT` (HTTP 409), while a window that only touches a buffer's edge is acceptable."

        Design: Difficulty/resource_temporal_overlap/flight_window_sixty_minute_buffer
        """
        bundle, _first = self._testing_bundle_with_first_flight(api)
        inside_buffer = api.create_test_event(
            create_test_event_payload(
                bundle["work_order"]["id"], test_kind="FLIGHT",
                scheduled_start="2026-08-18T16:29:00Z",
                scheduled_end="2026-08-18T17:29:00Z"),
            MANAGER)
        validate_error(inside_buffer, ApiErrorId.ERR_FLIGHT_WINDOW_CONFLICT)
        # Adjacent to the flight itself (start == prior end) still falls inside
        # the 60-minute post-buffer, unlike the bay half-open rule.
        adjacent = api.create_test_event(
            create_test_event_payload(
                bundle["work_order"]["id"], test_kind="FLIGHT",
                scheduled_start="2026-08-18T15:30:00Z",
                scheduled_end="2026-08-18T16:00:00Z"),
            MANAGER)
        validate_error(adjacent, ApiErrorId.ERR_FLIGHT_WINDOW_CONFLICT)


class TestRetestCycle:
    def test_fail_then_reschedule_increments_attempt(self, api):
        """PRD §3.5: "A failed event may be rescheduled by a `ShopManager`, moving it from `FAILED` back to `SCHEDULED` with a fresh `scheduled_start` and `scheduled_end`; the reschedule increments `attempt` by one and resets `result` to `NONE`."

        Design: Difficulty/non_linear_state_machine/test_event_retest_cycle
        """
        bundle = setup_testing_work_order(customer_name="Test Owner",
                                          customer_email="t@x.com",
                                          equipment_list=[],
                                          task_kind="HARNESS_FABRICATION",
                                          estimated_hours=2.0, actual_hours=2.0)
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        failed = record_test_result(ground["id"], "FAIL")
        assert failed["status"] == "FAILED"
        assert failed["attempt"] == 1
        assert failed["result"] == "FAIL"

        rescheduled = reschedule_event(ground["id"], "2026-08-06T10:00:00Z",
                                       "2026-08-06T11:00:00Z")
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["attempt"] == 2
        assert rescheduled["result"] == "NONE"

    def test_second_attempt_passes_and_ground_fail_skips_rework(self, api):
        """PRD §3.5: "A failed ground run is a bench matter: no cascade fires, and the event simply awaits reschedule."
        PRD §3.5: "A `result` of `PASS` moves the event from `SCHEDULED` to `PASSED`; a `result` of `FAIL` moves it to `FAILED`, and either recording requires the parent work order in `TESTING` (`ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/test_event_retest_cycle
        """
        bundle = setup_testing_work_order(customer_name="Test Owner",
                                          customer_email="t@x.com",
                                          equipment_list=[],
                                          task_kind="HARNESS_FABRICATION",
                                          estimated_hours=2.0, actual_hours=2.0)
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        record_test_result(ground["id"], "FAIL")
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING", (
            "a ground failure fires no rework cascade, so the work order stays TESTING")
        reschedule_event(ground["id"], "2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z")
        passed = record_test_result(ground["id"], "PASS")
        assert passed["status"] == "PASSED"
        assert passed["attempt"] == 2
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING"


class TestAttemptCeiling:
    def test_third_reschedule_rejected(self, api):
        """PRD §3.5: "Three attempts is the ceiling — the initial run plus two reschedules — so rescheduling is refused once `attempt` has reached 3 (`ERR_TEST_ATTEMPT_LIMIT`), and a rescheduled flight re-runs the buffered-window conflict check (`ERR_FLIGHT_WINDOW_CONFLICT`)."

        Design: Corner/state_machines/test_attempt_limit_enforced
        """
        bundle = setup_testing_work_order(
            customer_name="Attempt Amy", customer_email="a@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0,
            work_order_overrides={"estimated_downtime_days": 20,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        record_test_result(ground["id"], "FAIL")
        second = reschedule_event(ground["id"], "2026-08-06T10:00:00Z",
                                  "2026-08-06T11:00:00Z")
        assert second["attempt"] == 2
        record_test_result(ground["id"], "FAIL")
        third = reschedule_event(ground["id"], "2026-08-07T10:00:00Z",
                                 "2026-08-07T11:00:00Z")
        assert third["attempt"] == 3
        record_test_result(ground["id"], "FAIL")
        response = api.reschedule_test_event(ground["id"], "2026-08-08T10:00:00Z",
                                             "2026-08-08T11:00:00Z", MANAGER)
        validate_error(response, ApiErrorId.ERR_TEST_ATTEMPT_LIMIT)
        event = get_test_event(ground["id"])
        assert event["status"] == "FAILED"
        assert event["attempt"] == 3
        assert get_work_order(bundle["work_order"]["id"])["status"] == "TESTING"


class TestFlightFailReworkCascade:
    def test_flight_fail_reverts_verified_tasks(self, api):
        """PRD §3.5: "A failed flight check is heavier. Every install task of the same work order currently `VERIFIED` reverts to `IN_PROGRESS`; its `billed_labor_cents` and `verified_by_user_id` are cleared to null, and the parent's `total_billed_labor_cents` and `tasks_unverified_count` are recomputed."

        Design: Difficulty/transitive_cascade/flight_fail_rework_regresses_work_order
        """
        bundle = setup_testing_work_order(
            customer_name="Cascade Owner", customer_email="c@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=8.0, actual_hours=8.0)
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        record_test_result(ground["id"], "PASS")
        flight = schedule_test_event(
            bundle["work_order"]["id"], test_kind="FLIGHT",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-06T15:30:00Z")
        failed = record_test_result(flight["id"], "FAIL")
        assert failed["status"] == "FAILED"
        task = validate_success(api.get_install_task(bundle["tasks"][0]["id"], MANAGER))
        assert task["status"] == "IN_PROGRESS", (
            f"verified task must revert to IN_PROGRESS, got {task['status']}")
        assert task["billed_labor_cents"] is None, (
            "the revert clears the billed figure to null")
        assert task["verified_by_user_id"] is None

    def test_flight_fail_regresses_work_order_to_installation(self, api):
        """PRD §3.5: "While unverified tasks remain after that revert, the work order itself regresses from `TESTING` back to `INSTALLATION` and its `version` advances; if no task reverted, the work order stays in `TESTING`."
        PRD §2.9: "`total_billed_labor_cents` sums `billed_labor_cents` over its install tasks in `VERIFIED` only."

        Design: Difficulty/transitive_cascade/flight_fail_rework_regresses_work_order
        """
        bundle = setup_testing_work_order(
            customer_name="Cascade Owner", customer_email="c@x.com",
            equipment_list=[], task_kind="INSTALLATION",
            estimated_hours=8.0, actual_hours=8.0)
        before = get_work_order(bundle["work_order"]["id"])
        assert before["total_billed_labor_cents"] == 145000  # 8.0 h INSTALLATION
        ground = schedule_test_event(bundle["work_order"]["id"], test_kind="GROUND")
        record_test_result(ground["id"], "PASS")
        flight = schedule_test_event(
            bundle["work_order"]["id"], test_kind="FLIGHT",
            scheduled_start="2026-08-06T14:00:00Z",
            scheduled_end="2026-08-06T15:30:00Z")
        record_test_result(flight["id"], "FAIL")
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "INSTALLATION", (
            "with an unverified task after the revert, the work order regresses")
        assert work_order["tasks_unverified_count"] == 1
        assert work_order["total_billed_labor_cents"] == 0, (
            "no VERIFIED tasks remain, so the billed roll-up empties")
        assert work_order["version"] > before["version"], (
            "the regression transition advances the work order's version")
