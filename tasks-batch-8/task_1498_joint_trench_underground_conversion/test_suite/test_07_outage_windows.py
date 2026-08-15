"""Outage windows: duration and crew-capacity bounds, the 72h notification
lead, execution coverage, missed windows, and the reschedule cycle.

PRD §3.6 (outage coordination), §2.5 (logical clock).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_instant_equal,
    create_outage_window_payload,
    create_service_conversion,
    temp_transition,
    setup_mobilized_project,
    create_parcel,
    make_coordinator_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


def _two_party_project(api, name):
    return setup_mobilized_project(
        [
            {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
            {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
        ],
        name=name, rule20_credit_cents=0, estimated_total_cost_cents=1000000,
        target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
    )


class TestExecutionCoverage:
    def _setup(self, api):
        """Mobilized project; conversion PLANNED/NONE; outage on F1
        2026-09-05T10:00..16:00 APPROVED; clock set so notify lead is exactly
        72h."""
        project, parts = _two_party_project(api, "Outage Project")
        p1, _p2 = parts
        parcel = create_parcel(project["id"], address="10 Poplar St", owner_name="Owner Ten",
                               existing_panel_amps=200, load_calc_amps=100)
        conv = create_service_conversion(parcel["id"], project["id"])
        ow = validate_success(api.create_outage_window(
            create_outage_window_payload(
                project["id"], feeder_id="F1",
                start_at="2026-09-05T10:00:00Z", end_at="2026-09-05T16:00:00Z",
                conversion_ids=[conv["id"]]),
            make_coordinator_headers(p1["id"])), 201)
        validate_success(api.transition_outage_window(ow["id"], {"to": "APPROVED"}, PM), 200)
        validate_success(api.set_clock("2026-09-02T10:00:00Z", PM), 200)
        return project, p1, conv, ow

    def test_notify_at_exactly_72h_then_execution_blocked_without_power(self, api):
        """PRD §3.6: "Customer notification (`APPROVED → NOTIFIED`) is performed
        by a `UtilityCoordinator` and is bound by a hard lead time: the gap
        between `start_at` and the logical clock must be at least seventy-two
        hours; exactly seventy-two hours to the second passes, one second less
        is rejected with `ERR_NOTIFICATION_LEAD_TIME`."
        PRD §3.6: "every conversion named in `conversion_ids` must either have
        `work_status` of `ENERGIZED`, `INSPECTED`, or `COMPLETE`, or be riding
        active temporary service with `temp_service_status` of `TEMP_ACTIVE`
        (`ERR_TEMP_SERVICE_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/outage_execution_requires_temp_or_energized
        """
        _project, p1, _conv, ow = self._setup(api)
        notif = validate_success(api.transition_outage_window(
            ow["id"], {"to": "NOTIFIED"}, make_coordinator_headers(p1["id"])), 200)
        assert notif["status"] == "NOTIFIED", "lead of exactly 72h passes"
        assert_instant_equal(notif["notified_at"], "2026-09-02T10:00:00Z",
                             "notified_at stamps the clock")

        validate_success(api.set_clock("2026-09-05T11:00:00Z", PM), 200)
        resp = api.transition_outage_window(
            ow["id"], {"to": "EXECUTED"}, make_coordinator_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_TEMP_SERVICE_REQUIRED)

    def test_execution_succeeds_with_temp_active(self, api):
        """PRD §3.6: "Execution (`NOTIFIED → EXECUTED`, again the
        `UtilityCoordinator`) must fall inside the window — starting before
        `start_at` is `ERR_INVALID_STATE`, and attempting after `end_at` is
        `ERR_OUTAGE_WINDOW_MISSED` — and every conversion named in
        `conversion_ids` must either have `work_status` of `ENERGIZED`,
        `INSPECTED`, or `COMPLETE`, or be riding active temporary service with
        `temp_service_status` of `TEMP_ACTIVE` (`ERR_TEMP_SERVICE_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/outage_execution_requires_temp_or_energized
        """
        _project, p1, conv, ow = self._setup(api)
        validate_success(api.transition_outage_window(
            ow["id"], {"to": "NOTIFIED"}, make_coordinator_headers(p1["id"])), 200)
        validate_success(api.set_clock("2026-09-05T11:00:00Z", PM), 200)
        temp_transition(conv["id"], "TEMP_INSTALLED")
        temp_transition(conv["id"], "TEMP_ACTIVE")
        resp = api.transition_outage_window(
            ow["id"], {"to": "EXECUTED"}, make_coordinator_headers(p1["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "EXECUTED"


class TestCrewAggregateCapacity:
    def _setup(self, api):
        """Four PROPOSED outages on feeder F1: A 10:00-14:00, B 14:00-18:00
        (back-to-back), C 13:00-15:00, D 13:30-14:30."""
        project, _parts = _two_party_project(api, "Crew Project")

        def _propose(start, end):
            ow = validate_success(api.create_outage_window(
                create_outage_window_payload(project["id"], feeder_id="F1",
                                             start_at=start, end_at=end), PM), 201)
            return ow["id"]

        return project, {
            "A": _propose("2026-09-05T10:00:00Z", "2026-09-05T14:00:00Z"),
            "B": _propose("2026-09-05T14:00:00Z", "2026-09-05T18:00:00Z"),
            "C": _propose("2026-09-05T13:00:00Z", "2026-09-05T15:00:00Z"),
            "D": _propose("2026-09-05T13:30:00Z", "2026-09-05T14:30:00Z"),
        }

    def test_back_to_back_and_two_concurrent_approved(self, api):
        """PRD §3.6: "Crew capacity is evaluated with half-open semantics, so
        back-to-back windows where one ends exactly when the next begins do not
        overlap: at every instant inside the candidate window, the number of
        windows on the same feeder in `APPROVED`, `NOTIFIED`, or `EXECUTED`
        status — counting the candidate — must stay at or below two, else
        `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/outage_crew_aggregate_capacity
        """
        _project, ow = self._setup(api)
        a = validate_success(api.transition_outage_window(ow["A"], {"to": "APPROVED"}, PM), 200)
        b = validate_success(api.transition_outage_window(ow["B"], {"to": "APPROVED"}, PM), 200)
        assert a["status"] == "APPROVED" and b["status"] == "APPROVED", (
            "back-to-back at 14:00 does not overlap (half-open intervals)"
        )
        c = validate_success(api.transition_outage_window(ow["C"], {"to": "APPROVED"}, PM), 200)
        assert c["status"] == "APPROVED", (
            "A and C overlap 13:00-14:00: exactly two concurrent is at the limit"
        )

    def test_third_simultaneous_outage_rejected(self, api):
        """PRD §3.6: "Crew capacity is evaluated with half-open semantics, so
        back-to-back windows where one ends exactly when the next begins do not
        overlap: at every instant inside the candidate window, the number of
        windows on the same feeder in `APPROVED`, `NOTIFIED`, or `EXECUTED`
        status — counting the candidate — must stay at or below two, else
        `ERR_CREW_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/outage_crew_aggregate_capacity
        """
        _project, ow = self._setup(api)
        for key in ("A", "B", "C"):
            validate_success(api.transition_outage_window(ow[key], {"to": "APPROVED"}, PM), 200)
        resp = api.transition_outage_window(ow["D"], {"to": "APPROVED"}, PM)
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)


class TestNotificationLeadBoundary:
    def test_notification_lead_one_second_short(self, api):
        """PRD §3.6: "Customer notification (`APPROVED → NOTIFIED`) is
        performed by a `UtilityCoordinator` and is bound by a hard lead time:
        the gap between `start_at` and the logical clock must be at least
        seventy-two hours; exactly seventy-two hours to the second passes, one
        second less is rejected with `ERR_NOTIFICATION_LEAD_TIME`."

        Design: Corner/calculations/notification_lead_one_second_short
        """
        project, parts = _two_party_project(api, "C3")
        p1, _p2 = parts
        ow = validate_success(api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="F1",
                                         start_at="2026-09-05T10:00:00Z",
                                         end_at="2026-09-05T14:00:00Z"), PM), 201)
        validate_success(api.transition_outage_window(ow["id"], {"to": "APPROVED"}, PM), 200)
        validate_success(api.set_clock("2026-09-02T10:00:01Z", PM), 200)
        resp = api.transition_outage_window(
            ow["id"], {"to": "NOTIFIED"}, make_coordinator_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_LEAD_TIME)


class TestDurationBoundary:
    def test_outage_duration_exactly_8h_allowed(self, api):
        """PRD §3.6: "The duration must not exceed eight hours — exactly eight
        hours passes, anything longer is `ERR_OUTAGE_DURATION_EXCEEDED`."

        Design: Corner/calculations/outage_duration_exactly_8h_allowed
        """
        project, _parts = _two_party_project(api, "C4")
        ow8 = validate_success(api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="FA",
                                         start_at="2026-09-05T08:00:00Z",
                                         end_at="2026-09-05T16:00:00Z"), PM), 201)
        ow9 = validate_success(api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="FB",
                                         start_at="2026-09-05T08:00:00Z",
                                         end_at="2026-09-05T16:00:01Z"), PM), 201)
        ok = validate_success(api.transition_outage_window(ow8["id"], {"to": "APPROVED"}, PM), 200)
        assert ok["status"] == "APPROVED", "exactly 8h passes"
        resp = api.transition_outage_window(ow9["id"], {"to": "APPROVED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_DURATION_EXCEEDED)


class TestMissedWindow:
    def test_outage_executed_after_window_missed(self, api):
        """PRD §3.6: "Execution (`NOTIFIED → EXECUTED`, again the
        `UtilityCoordinator`) must fall inside the window — starting before
        `start_at` is `ERR_INVALID_STATE`, and attempting after `end_at` is
        `ERR_OUTAGE_WINDOW_MISSED` — and every conversion named in
        `conversion_ids` must either have `work_status` of `ENERGIZED`,
        `INSPECTED`, or `COMPLETE`, or be riding active temporary service with
        `temp_service_status` of `TEMP_ACTIVE` (`ERR_TEMP_SERVICE_REQUIRED`)."

        Design: Corner/validations/outage_executed_after_window_missed
        """
        project, parts = _two_party_project(api, "V15")
        p1, _p2 = parts
        parcel = create_parcel(project["id"], address="10 B St", owner_name="O",
                               existing_panel_amps=200, load_calc_amps=100)
        conv = create_service_conversion(parcel["id"], project["id"])
        temp_transition(conv["id"], "TEMP_INSTALLED")
        temp_transition(conv["id"], "TEMP_ACTIVE")
        ow = validate_success(api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="F1",
                                         start_at="2026-09-05T10:00:00Z",
                                         end_at="2026-09-05T12:00:00Z",
                                         conversion_ids=[conv["id"]]), PM), 201)
        validate_success(api.transition_outage_window(ow["id"], {"to": "APPROVED"}, PM), 200)
        validate_success(api.set_clock("2026-09-02T09:00:00Z", PM), 200)
        validate_success(api.transition_outage_window(
            ow["id"], {"to": "NOTIFIED"}, make_coordinator_headers(p1["id"])), 200)

        validate_success(api.set_clock("2026-09-05T12:00:01Z", PM), 200)
        resp = api.transition_outage_window(
            ow["id"], {"to": "EXECUTED"}, make_coordinator_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTAGE_WINDOW_MISSED)


class TestRescheduleCycle:
    def test_outage_reschedule_cycle_resets_notification(self, api):
        """PRD §3.6: "A notified window may be rescheduled — `NOTIFIED →
        PROPOSED` by the `ProgramManager`, supplying `new_start_at` and
        `new_end_at` (the new start strictly before the new end, else
        `ERR_VALIDATION`) — which replaces `start_at` and `end_at` and resets
        `notified_at` to null, forcing the notification lead time to be earned
        again."

        Design: Corner/state_machines/outage_reschedule_cycle_resets_notification
        """
        project, parts = _two_party_project(api, "SM5")
        p1, _p2 = parts
        ow = validate_success(api.create_outage_window(
            create_outage_window_payload(project["id"], feeder_id="F9",
                                         start_at="2026-09-05T10:00:00Z",
                                         end_at="2026-09-05T14:00:00Z"), PM), 201)
        validate_success(api.transition_outage_window(ow["id"], {"to": "APPROVED"}, PM), 200)
        validate_success(api.set_clock("2026-09-01T09:00:00Z", PM), 200)
        validate_success(api.transition_outage_window(
            ow["id"], {"to": "NOTIFIED"}, make_coordinator_headers(p1["id"])), 200)

        resp = api.transition_outage_window(
            ow["id"],
            {"to": "PROPOSED", "new_start_at": "2026-09-20T10:00:00Z",
             "new_end_at": "2026-09-20T14:00:00Z"},
            PM,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "PROPOSED"
        assert data["notified_at"] is None, "reschedule voids the notification"
        assert_instant_equal(data["start_at"], "2026-09-20T10:00:00Z",
                             "start_at replaced by the reschedule")
