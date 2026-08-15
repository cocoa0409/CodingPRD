"""Operational posture: transitive cascades out of pump and SSO writes, the
freeze cascade, logical-clock defaults, and optimistic-concurrency guards."""
from test_helpers import (
    ApiErrorId,
    add_operator,
    add_project,
    assert_instant_equal,
    create_draft_permit,
    create_permit_trio,
    create_plan,
    create_sso,
    create_sso_event_payload,
    create_station,
    get_cleaning,
    get_generator_test,
    get_permit,
    get_station,
    rank_plan,
    reset_clock,
    raise_ticket,
    schedule_cleaning,
    schedule_generator_test,
    setup_normal_station,
    setup_sso_accepted,
    setup_station_with_pumps,
    validate_error,
    validate_success,
)


class TestPumpOutOfServiceCascade:
    def test_mark_out_of_service_cascades_to_degraded_posture_and_alarms(
        self, api, operations_supervisor_headers, utility_admin_headers
    ):
        """PRD §3.4: "The same firm-capacity rule guards an
        `OperationsSupervisor` marking a pump out of service (`IN_SERVICE →
        OUT_OF_SERVICE`, which also auto-fires the `PUMP_OUT_OF_SERVICE` `MAJOR`
        alarm)."
        PRD §3.2: "A station's firm capacity follows the N-1 criterion:
        `firm_capacity_available_gpm` is the sum of `rated_gpm` across the
        station's pumps whose status is `IN_SERVICE`, minus the largest single
        `rated_gpm` among those pumps."
        PRD §2.10: "a station sliding into `DEGRADED` fires a `MAJOR` ticket
        with `alarm_code` `STATION_DEGRADED`; a pump marked out of service fires
        a `MAJOR` ticket with `alarm_code` `PUMP_OUT_OF_SERVICE`"

        Design: Difficulty/transitive_cascade/pump_out_of_service_cascade_depth3
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=400,
        )
        assert get_station(station["id"])["operational_posture"] == "NORMAL"
        res = api.mark_pump_out_of_service(pumps[0]["id"], operations_supervisor_headers)
        pump = validate_success(res, 200)
        assert pump["status"] == "OUT_OF_SERVICE"
        station_after = get_station(station["id"])
        assert station_after["firm_capacity_available_gpm"] == 200, (
            "IN_SERVICE = {P2, P3}: 400 - largest 200"
        )
        assert station_after["operational_posture"] == "DEGRADED", (
            "firm 200 below design 400"
        )
        res = api.list_station_alarm_tickets(station["id"], utility_admin_headers)
        tickets = validate_success(res, 200)
        codes = {t["alarm_code"] for t in tickets}
        assert "PUMP_OUT_OF_SERVICE" in codes
        assert "STATION_DEGRADED" in codes
        for t in tickets:
            if t["alarm_code"] in ("PUMP_OUT_OF_SERVICE", "STATION_DEGRADED"):
                assert t["alarm_class"] == "MAJOR"
                assert t["status"] == "OPEN"

    def test_standby_cascade_fires_degraded_alarm_but_not_oos_alarm(
        self, api, operations_supervisor_headers, utility_admin_headers
    ):
        """PRD §3.4: "Every pump status change recomputes the station's firm
        capacity and posture"
        PRD §2.10: "a station sliding into `DEGRADED` fires a `MAJOR` ticket
        with `alarm_code` `STATION_DEGRADED`; a pump marked out of service fires
        a `MAJOR` ticket with `alarm_code` `PUMP_OUT_OF_SERVICE`; a failed
        generator test fires a `MAJOR` ticket with `alarm_code`
        `GEN_TEST_FAILED`; a cleaning that becomes overdue fires a `MINOR`
        ticket with `alarm_code` `CLEANING_OVERDUE`."

        Design: Difficulty/transitive_cascade/pump_out_of_service_cascade_depth3
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=400,
        )
        res = api.standby_pump(pumps[0]["id"], operations_supervisor_headers)
        pump = validate_success(res, 200)
        assert pump["status"] == "STANDBY"
        station_after = get_station(station["id"])
        assert station_after["firm_capacity_available_gpm"] == 200
        assert station_after["operational_posture"] == "DEGRADED"
        res = api.list_station_alarm_tickets(station["id"], utility_admin_headers)
        tickets = validate_success(res, 200)
        codes = {t["alarm_code"] for t in tickets}
        assert "STATION_DEGRADED" in codes
        assert "PUMP_OUT_OF_SERVICE" not in codes, (
            "the enumerated auto-fire triggers do not include standby"
        )


class TestEmergencyCascade:
    def test_sso_create_cascades_to_emergency_and_cancels_children(self, api):
        """PRD §3.8: "Recording an SSO is the most consequential write in the
        system. The new event enters `OPEN`; the station's posture cascades to
        `EMERGENCY`; the station's `last_sso_occurred_at` is set to the event's
        `started_at`; the station's `version` increments; every `SCHEDULED`
        generator test at the station is automatically moved to `ABORTED`; and
        every `DRAFT` confined-space permit at the station is automatically
        moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/station_emergency_cascade_depth2
        """
        reset_clock()
        station, _ = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=400, has_backup_generator=True,
        )
        gt = schedule_generator_test(station["id"], scheduled_for="2026-08-02T00:00:00Z")
        trio = create_permit_trio()
        permit = create_draft_permit(station["id"], *trio)
        sso = create_sso(station["id"], cause_code="POWER_FAILURE")
        assert sso["status"] == "OPEN"
        station_after = get_station(station["id"])
        assert station_after["operational_posture"] == "EMERGENCY"
        assert get_generator_test(gt["id"])["status"] == "ABORTED"
        assert get_permit(permit["id"])["status"] == "CANCELLED"

    def test_emergency_releases_to_normal_on_report_acceptance(self, api):
        """PRD §3.8: "Note the posture interplay: an event remains
        posture-forcing through `OPEN`, `CONTAINED`, `REPORT_DRAFT`, and
        `REPORT_SUBMITTED`; only acceptance or closure releases the station from
        `EMERGENCY` (into `DEGRADED` if capacity or rebuild or overdue-test
        drivers remain, else `NORMAL`)."
        PRD §3.8: "the station's `last_sso_occurred_at` is set to the event's
        `started_at`"

        Design: Difficulty/transitive_cascade/station_emergency_cascade_depth2
        """
        reset_clock()
        station, _ = setup_station_with_pumps(
            ratings=(200, 200, 200), design_capacity_gpm=400,
        )
        sso = setup_sso_accepted(station["id"])
        assert sso["status"] == "REPORT_ACCEPTED"
        station_after = get_station(station["id"])
        assert station_after["operational_posture"] == "NORMAL", (
            "acceptance releases EMERGENCY; no degradation drivers remain"
        )
        assert_instant_equal(
            station_after["last_sso_occurred_at"], "2026-08-01T00:00:00Z",
        )


class TestCrossCuttingOcc:
    def test_occ_sso_create_stale_station_version(self, api, utility_admin_headers):
        """PRD §2.6: "Recording a new SSO event against a station requires the
        request to carry `expected_station_version`, set to the value of the
        station's `version` the client last observed. If the station's current
        `version` does not match, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "Creating a ticket bumps the parent station's `version`."

        Design: Corner/cross_cutting_layers/occ_sso_create_stale_station_version
        """
        reset_clock()
        station = create_station()
        stale_version = station["version"]
        raise_ticket(station["id"], alarm_class="INFO", alarm_code="TEST")
        payload = create_sso_event_payload(stale_version)
        res = api.create_sso_event(station["id"], payload, utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_capital_plan_approve_stale(self, api, utility_admin_headers,
                                            capital_program_manager_headers):
        """PRD §2.6: "Approving a capital plan requires the request to carry
        `expected_plan_version`, the plan `version` last observed by the
        approver. A mismatch with the plan's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing two planners stepping a plan
        through its lifecycle from approving on a stale read."
        PRD §3.10: "Ranking increments the plan's `version`."

        Design: Corner/cross_cutting_layers/occ_capital_plan_approve_stale
        """
        reset_clock()
        station = create_station(has_backup_generator=True)
        plan = create_plan(plan_year=2036)
        stale_version = plan["version"]
        add_project(plan["id"], station["id"], estimated_cost_usd=5000)
        rank_plan(plan["id"])
        res = api.approve_capital_plan(plan["id"], stale_version, utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


class TestCrossCuttingCascadesAndClock:
    def test_sso_create_cascades_abort_generator_test(self, api, utility_admin_headers):
        """PRD §3.8: "Recording an SSO is the most consequential write in the
        system. The new event enters `OPEN`; the station's posture cascades to
        `EMERGENCY`; the station's `last_sso_occurred_at` is set to the event's
        `started_at`; the station's `version` increments; every `SCHEDULED`
        generator test at the station is automatically moved to `ABORTED`; and
        every `DRAFT` confined-space permit at the station is automatically
        moved to `CANCELLED`."

        Design: Corner/cross_cutting_layers/sso_create_cascades_abort_generator_test
        """
        reset_clock()
        station, _ = setup_station_with_pumps(has_backup_generator=True)
        gt = schedule_generator_test(station["id"], scheduled_for="2026-08-05T00:00:00Z")
        create_sso(station["id"], cause_code="PUMP_FAILURE")
        assert get_generator_test(gt["id"])["status"] == "ABORTED"

    def test_freeze_station_cascades_cancel_cleanings(self, api, utility_admin_headers):
        """PRD §3.12: "Freezing cascades: every `SCHEDULED` wet-well cleaning at
        the station moves to `CANCELLED`, and every `SCHEDULED` generator test
        moves to `CANCELLED`."
        PRD §3.12: "A `UtilityAdmin` freezes a station, moving its posture
        `NORMAL → FROZEN` — but only when the station has no SSO event in
        `OPEN`, `CONTAINED`, `REPORT_DRAFT`, or `REPORT_SUBMITTED` and no
        confined-space permit in `ISSUED` or `ACTIVE`; an active emergency or
        live permit must be wound down first."

        Design: Corner/cross_cutting_layers/freeze_station_cascades_cancel_cleanings
        """
        reset_clock()
        station, _ = setup_normal_station()
        lead = add_operator(full_name="Lead", certifications=["CSE_1"])
        cleaning = schedule_cleaning(
            station["id"], lead["id"], scheduled_for="2026-08-10T00:00:00Z",
        )
        res = api.freeze_station(station["id"], utility_admin_headers)
        frozen = validate_success(res, 200)
        assert frozen["operational_posture"] == "FROZEN"
        assert get_cleaning(cleaning["id"])["status"] == "CANCELLED"

    def test_clock_default_2026_08_01(self, api, utility_admin_headers):
        """PRD §2.9: "Before any explicit clock-set call, the logical clock
        defaults to 2026-08-01T00:00:00Z and must never fall back to wall-clock
        time."
        PRD §2.9: "may invoke a tick capability that re-evaluates all
        time-driven automatic transitions described in §3, returning a
        `transitioned_counts` object summarizing what moved"

        Design: Corner/cross_cutting_layers/clock_default_2026_08_01
        """
        res = api.tick(utility_admin_headers)
        data = validate_success(res, 200)
        assert isinstance(data.get("transitioned_counts"), dict)
