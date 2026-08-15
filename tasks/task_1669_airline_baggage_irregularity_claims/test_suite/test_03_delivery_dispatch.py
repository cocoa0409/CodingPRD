"""Delivery dispatch lifecycle: creation guards, window conflicts, delivery
cascade, failure/reschedule cycles (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    CLOCK_EPOCH,
    create_report_payload, create_tracing_event_payload, create_dispatch_payload,
    create_station, create_carrier, create_passenger, create_bag_tag, create_report,
    create_courier_service, set_clock, setup_bag_and_report,
    setup_found_pending_delivery, create_dispatch_for_report,
    assert_same_instant,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

PICKUP = "2026-08-02T10:00:00Z"


class TestDispatchCreationGuards:

    def test_dispatch_requires_report_found_pending_delivery(self, api):
        """PRD §3.5: "The report must be in `FOUND_PENDING_DELIVERY`, failing which
        the request is rejected with `ERR_REPORT_NOT_AWAITING_DELIVERY`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_report_found_pending_delivery
        """
        # Report still TRACING (no LOCATED event recorded).
        ctx = setup_bag_and_report(report_type="DELAYED")
        courier = create_courier_service([ctx["station"]["id"]])
        resp = api.create_dispatch(
            create_dispatch_payload(ctx["report"]["id"], courier["id"],
                                    pickup_at=PICKUP), AGENT)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_AWAITING_DELIVERY, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "TRACING"

    def test_dispatch_allowed_once_found_pending_delivery(self, api):
        """PRD §3.5: "Once a report reaches `FOUND_PENDING_DELIVERY`, a
        `BaggageServiceAgent` arranges the reunion by creating a **Delivery
        Dispatch**"
        PRD §3.5: "A freshly created dispatch starts in `DISPATCHED` with
        `attempt_count` at 1, the courier's `active_dispatch_count` is incremented,
        and the report advances from `FOUND_PENDING_DELIVERY` to
        `DELIVERY_IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_report_found_pending_delivery
        """
        ctx = setup_found_pending_delivery()
        resp = api.create_dispatch(
            create_dispatch_payload(ctx["report"]["id"], ctx["courier"]["id"],
                                    pickup_at=PICKUP), AGENT)
        dispatch = validate_success(resp, 201)
        assert dispatch["status"] == "DISPATCHED"
        assert dispatch["attempt_count"] == 1
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "DELIVERY_IN_PROGRESS"

    def test_dispatch_creation_side_effects(self, api):
        """PRD §3.5: "A freshly created dispatch starts in `DISPATCHED` with
        `attempt_count` at 1, the courier's `active_dispatch_count` is incremented,
        and the report advances from `FOUND_PENDING_DELIVERY` to
        `DELIVERY_IN_PROGRESS`."

        Design: Corner/state_machines/dispatch_create_side_effects_report_and_courier
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        assert dispatch["status"] == "DISPATCHED"
        assert dispatch["attempt_count"] == 1
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "DELIVERY_IN_PROGRESS"
        courier_now = get_success_data(api.get_courier_service(ctx["courier"]["id"],
                                                               AGENT))
        assert courier_now["active_dispatch_count"] == 1

    def test_pickup_in_past_rejected(self, api):
        """PRD §3.5: "The `pickup_at` must be at or after the current logical clock
        time; a window in the past is rejected with `ERR_PICKUP_IN_PAST`."

        Design: Corner/validations/pickup_in_past_rejected
        """
        ctx = setup_found_pending_delivery()
        resp = api.create_dispatch(
            create_dispatch_payload(ctx["report"]["id"], ctx["courier"]["id"],
                                    pickup_at="2026-07-31T10:00:00Z"), AGENT)
        validate_error(resp, ApiErrorId.ERR_PICKUP_IN_PAST, 409)
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "FOUND_PENDING_DELIVERY"


class TestDispatchWindowConflict:

    def _setup_three_reports(self, api):
        set_clock(CLOCK_EPOCH)
        station = create_station()
        carrier = create_carrier()
        courier = create_courier_service([station["id"]], turnaround_buffer_minutes=60)
        passenger = create_passenger()
        reports = []
        for _ in range(3):
            bag = create_bag_tag(passenger["id"], [carrier["id"]])
            report = create_report(passenger["id"], bag["id"], station["id"],
                                   report_type="DELAYED")
            get_success_data(api.record_tracing_event(
                report["id"],
                create_tracing_event_payload(carrier["id"], station["id"], "LOCATED"),
                AGENT))
            reports.append(report)
        return station, carrier, courier, passenger, reports

    def test_buffer_boundary_allowed_and_overlap_rejected(self, api):
        """PRD §3.5: "Under buffer-expanded closed-interval semantics, a conflict
        exists exactly when the new window's start, shifted earlier by the courier's
        `turnaround_buffer_minutes`, falls strictly before the existing window's end,
        and at the same time the existing window's start falls strictly before the
        new window's end shifted later by the same buffer; two windows separated by
        exactly the buffer do not conflict. A conflicting window is rejected with
        `ERR_DISPATCH_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/courier_dispatch_buffer_expanded_conflict
        """
        _, _, courier, _, reports = self._setup_three_reports(api)
        # Window A: [10:00, 12:00]; buffer 60 minutes.
        dispatch_a = create_dispatch_for_report(reports[0]["id"], courier["id"],
                                                pickup_at="2026-08-02T10:00:00Z",
                                                travel_minutes=120)
        assert dispatch_a["status"] == "DISPATCHED"

        # B starts exactly buffer (60m) after A's end: allowed.
        resp_b = api.create_dispatch(
            create_dispatch_payload(reports[1]["id"], courier["id"],
                                    pickup_at="2026-08-02T13:00:00Z",
                                    travel_minutes=120), AGENT)
        dispatch_b = validate_success(resp_b, 201)
        assert dispatch_b["status"] == "DISPATCHED"

        # C starts 30 minutes before that boundary: conflicts with A.
        resp_c = api.create_dispatch(
            create_dispatch_payload(reports[2]["id"], courier["id"],
                                    pickup_at="2026-08-02T12:30:00Z",
                                    travel_minutes=120), AGENT)
        validate_error(resp_c, ApiErrorId.ERR_DISPATCH_WINDOW_CONFLICT, 409)
        report_c = get_success_data(api.get_report(reports[2]["id"], AGENT))
        assert report_c["status"] == "FOUND_PENDING_DELIVERY"

    def test_exact_buffer_separation_on_both_sides(self, api):
        """PRD §3.5: "two windows separated by exactly the buffer do not conflict."

        Design: Difficulty/resource_temporal_overlap/courier_dispatch_buffer_expanded_conflict
        """
        _, _, courier, _, reports = self._setup_three_reports(api)
        # Window A: [10:00, 12:00].
        create_dispatch_for_report(reports[0]["id"], courier["id"],
                                   pickup_at="2026-08-02T10:00:00Z",
                                   travel_minutes=120)
        # B ends exactly buffer before A's start: [07:00, 09:00] with 60m buffer.
        resp_b = api.create_dispatch(
            create_dispatch_payload(reports[1]["id"], courier["id"],
                                    pickup_at="2026-08-02T07:00:00Z",
                                    travel_minutes=120), AGENT)
        dispatch_b = validate_success(resp_b, 201)
        assert dispatch_b["status"] == "DISPATCHED"
        # C overlaps A's window directly: [11:00, 13:00].
        resp_c = api.create_dispatch(
            create_dispatch_payload(reports[2]["id"], courier["id"],
                                    pickup_at="2026-08-02T11:00:00Z",
                                    travel_minutes=120), AGENT)
        validate_error(resp_c, ApiErrorId.ERR_DISPATCH_WINDOW_CONFLICT, 409)


class TestDeliveryCascade:

    def test_mark_delivered_two_hop_cascade(self, api):
        """PRD §3.5: "confirmation moves the dispatch to `DELIVERED` and cascades
        broadly: the report moves from `DELIVERY_IN_PROGRESS` to `DELIVERED`, the
        bag moves from `IN_RECOVERY` to `DELIVERED`, the report's `delivered_on` is
        stamped with the current logical clock date (closing the expense eligibility
        window for future adjudications), and the courier's `active_dispatch_count`
        is decremented."

        Design: Difficulty/transitive_cascade/delivery_mark_delivered_two_hop_cascade
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        resp = api.mark_dispatch_delivered(dispatch["id"], AGENT)
        delivered = validate_success(resp, 200)
        assert delivered["status"] == "DELIVERED"

        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "DELIVERED"
        assert report_now["delivered_on"] == "2026-08-01"
        bag_now = get_success_data(api.get_bag_tag(ctx["bag"]["id"], AGENT))
        assert bag_now["status"] == "DELIVERED"
        courier_now = get_success_data(api.get_courier_service(ctx["courier"]["id"],
                                                               AGENT))
        assert courier_now["active_dispatch_count"] == 0

    def test_mark_delivered_stamps_delivered_on_closing_window(self, api):
        """PRD §3.5: "the report's `delivered_on` is stamped with the current
        logical clock date (closing the expense eligibility window for future
        adjudications)"
        PRD §3.3: "Until the bag is delivered, `delivered_on` remains null."

        Design: Difficulty/transitive_cascade/delivery_mark_delivered_two_hop_cascade
        """
        ctx = setup_found_pending_delivery()
        # Before delivery: delivered_on is null.
        report_before = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_before["delivered_on"] is None

        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        get_success_data(api.mark_dispatch_delivered(dispatch["id"], AGENT))
        report_after = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_after["delivered_on"] == "2026-08-01"
        assert report_after["status"] == "DELIVERED"


class TestFailureAndReschedule:

    def test_failure_reschedule_cycle(self, api):
        """PRD §3.5: "A successful reschedule returns the dispatch to `DISPATCHED`,
        increments `attempt_count` by one, and replaces `pickup_at` with
        `new_pickup_at`."

        Design: Difficulty/non_linear_state_machine/dispatch_failure_reschedule_cycle
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        get_success_data(api.mark_dispatch_failed(dispatch["id"], AGENT))
        resp = api.reschedule_dispatch(dispatch["id"],
                                       {"new_pickup_at": "2026-08-03T10:00:00Z"}, AGENT)
        updated = validate_success(resp, 200)
        assert updated["status"] == "DISPATCHED"
        assert updated["attempt_count"] == 2
        assert_same_instant(updated["pickup_at"], "2026-08-03T10:00:00Z")
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "DELIVERY_IN_PROGRESS"

    def test_failed_attempt_keeps_courier_count(self, api):
        """PRD §3.5: "While the dispatch's `attempt_count` is still below three, the
        failure moves the dispatch from `DISPATCHED` to `FAILED_ATTEMPT` and nothing
        else changes — the dispatch remains active and the courier's count is
        untouched."

        Design: Difficulty/non_linear_state_machine/dispatch_failure_reschedule_cycle
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        resp = api.mark_dispatch_failed(dispatch["id"], AGENT)
        failed = validate_success(resp, 200)
        assert failed["status"] == "FAILED_ATTEMPT"
        assert failed["attempt_count"] == 1
        courier_now = get_success_data(api.get_courier_service(ctx["courier"]["id"],
                                                               AGENT))
        assert courier_now["active_dispatch_count"] == 1
        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "DELIVERY_IN_PROGRESS"

    def test_third_failure_is_permanent(self, api):
        """PRD §3.5: "A failure recorded when `attempt_count` has reached three or
        more is permanent: the dispatch moves from `DISPATCHED` to
        `FAILED_PERMANENT`, the report falls back from `DELIVERY_IN_PROGRESS` to
        `FOUND_PENDING_DELIVERY` so it can accept a fresh dispatch, the bag remains
        `IN_RECOVERY`, and the courier's `active_dispatch_count` is decremented."

        Design: Corner/state_machines/failed_permanent_returns_report_to_found_pending
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        # attempt 1 -> fail, reschedule -> attempt 2 -> fail, reschedule -> attempt 3
        get_success_data(api.mark_dispatch_failed(dispatch["id"], AGENT))
        get_success_data(api.reschedule_dispatch(
            dispatch["id"], {"new_pickup_at": "2026-08-03T10:00:00Z"}, AGENT))
        get_success_data(api.mark_dispatch_failed(dispatch["id"], AGENT))
        get_success_data(api.reschedule_dispatch(
            dispatch["id"], {"new_pickup_at": "2026-08-04T10:00:00Z"}, AGENT))
        resp = api.mark_dispatch_failed(dispatch["id"], AGENT)
        final = validate_success(resp, 200)
        assert final["status"] == "FAILED_PERMANENT"
        assert final["attempt_count"] == 3

        report_now = get_success_data(api.get_report(ctx["report"]["id"], AGENT))
        assert report_now["status"] == "FOUND_PENDING_DELIVERY"
        courier_now = get_success_data(api.get_courier_service(ctx["courier"]["id"],
                                                               AGENT))
        assert courier_now["active_dispatch_count"] == 0
        bag_now = get_success_data(api.get_bag_tag(ctx["bag"]["id"], AGENT))
        assert bag_now["status"] == "IN_RECOVERY"

    def test_reschedule_on_dispatched_rejected(self, api):
        """PRD §3.5: "Only a dispatch in `FAILED_ATTEMPT` may be rescheduled —
        otherwise the request is rejected with `ERR_DISPATCH_NOT_RESCHEDULABLE`."

        Design: Corner/errors/reschedule_on_dispatched_rejected
        """
        ctx = setup_found_pending_delivery()
        dispatch = create_dispatch_for_report(ctx["report"]["id"],
                                              ctx["courier"]["id"], pickup_at=PICKUP)
        resp = api.reschedule_dispatch(dispatch["id"],
                                       {"new_pickup_at": "2026-08-03T10:00:00Z"}, AGENT)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_RESCHEDULABLE, 409)
        current = get_success_data(api.get_dispatch(dispatch["id"], AGENT))
        assert_same_instant(current["pickup_at"], "2026-08-02T10:00:00Z")
        assert current["attempt_count"] == 1
