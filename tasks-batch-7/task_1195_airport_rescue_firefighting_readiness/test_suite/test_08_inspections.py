"""FAA inspections and determination gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_aircraft,
    create_certified_drill,
    create_faa_inspection_payload,
    create_profile,
    create_vehicle,
    get_success_data,
    open_oos_event,
    record_readiness_check,
    record_training,
    set_clock,
    setup_compliant_index_c_airport,
    validate_error,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]
FAA = TEST_USERS["faa_inspector_headers"]


class TestInspectionBlockedByNotification:
    def test_conclude_pass_blocked_by_pending_notification(self, api):
        """PRD §3.12: "First, no `IndexDowngradeNotification` may sit in
        `PENDING`, `ACKNOWLEDGED`, or `OVERDUE` — a blocking notification
        yields `ERR_INSPECTION_BLOCKING_NOTIFICATIONS`."

        Design: Difficulty/cross_entity_state_dependency/ce_inspection_blocked_by_open_notification
        """
        ctx = setup_compliant_index_c_airport()
        # Certify a drill (valid for 12 months)
        create_certified_drill(
            runway="09L",
            window_start="2026-05-02T10:00:00Z",
            window_end="2026-05-02T11:00:00Z",
            execute_clock="2026-05-02T10:30:00Z",
            first_vehicle_arrival_seconds=120,
            all_vehicles_arrival_seconds=200,
        )
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.begin_faa_inspection(insp["id"], FAA)
        api.issue_findings_faa_inspection(insp["id"], {"findings_count": 1}, FAA)
        # Open OOS on veh2 to trigger a notification
        oos = open_oos_event(ctx["veh2"]["id"], "Turret inoperative")
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "PASS"}, FAA)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_BLOCKING_NOTIFICATIONS)

    def test_conclude_pass_blocked_even_after_acknowledge(self, api):
        """PRD §3.12: "First, no `IndexDowngradeNotification` may sit in
        `PENDING`, `ACKNOWLEDGED`, or `OVERDUE` — a blocking notification
        yields `ERR_INSPECTION_BLOCKING_NOTIFICATIONS`."

        Design: Difficulty/cross_entity_state_dependency/ce_inspection_blocked_by_open_notification
        """
        ctx = setup_compliant_index_c_airport()
        create_certified_drill(
            runway="09L",
            window_start="2026-05-02T10:00:00Z",
            window_end="2026-05-02T11:00:00Z",
            execute_clock="2026-05-02T10:30:00Z",
            first_vehicle_arrival_seconds=120,
            all_vehicles_arrival_seconds=200,
        )
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.begin_faa_inspection(insp["id"], FAA)
        api.issue_findings_faa_inspection(insp["id"], {"findings_count": 1}, FAA)
        oos = open_oos_event(ctx["veh2"]["id"], "Turret inoperative")
        notif_resp = api.list_index_downgrade_notifications(FAA)
        notif_data = notif_resp.json()["data"]
        n_id = notif_data[0]["id"]
        # Acknowledge does not clear the gate
        api.acknowledge_index_downgrade_notification(n_id, FAA)
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "PASS"}, FAA)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_BLOCKING_NOTIFICATIONS)
        # Only restore cascade -> RESOLVED clears the gate
        record_readiness_check(ctx["veh2"]["id"], 2000, 500, True)
        from test_helpers import restore_oos_event
        restore_oos_event(oos["id"])
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "PASS"}, FAA)
        concluded = validate_success(resp)
        assert concluded["status"] == "CLOSED_PASS"


class TestInspectionErrorBattery:
    def test_duplicate_inspection_year_rejected(self, api):
        """PRD §3.12: "An `AirportManager` schedules one by naming the
        `inspection_year` (unique across inspections — a duplicate year is
        rejected with `ERR_DUPLICATE_INSPECTION_YEAR`) and a `scheduled_on`
        ISO date."

        Design: Corner/errors/err_inspection_flow_error_battery
        """
        setup_compliant_index_c_airport()
        api.create_faa_inspection(
            create_faa_inspection_payload(
                inspection_year=2026, scheduled_on="2026-05-03",
            ),
            AM,
        )
        resp = api.create_faa_inspection(
            create_faa_inspection_payload(
                inspection_year=2026, scheduled_on="2026-06-01",
            ),
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INSPECTION_YEAR)

    def test_out_of_order_transitions_rejected(self, api):
        """PRD §3.12: "Begin moves `SCHEDULED` to `IN_PROGRESS` (begin on a
        non-`SCHEDULED` inspection is rejected with
        `ERR_INSPECTION_NOT_BEGINNABLE`). Issue-findings moves `IN_PROGRESS`
        to `FINDINGS_ISSUED` and records `findings_count` from the caller's
        input (issue-findings on a non-`IN_PROGRESS` inspection is rejected
        with `ERR_INSPECTION_NOT_IN_PROGRESS`). Conclude moves
        `FINDINGS_ISSUED` to either `CLOSED_PASS` or `CLOSED_FAIL` based on
        the supplied `outcome`. A conclude on a non-`FINDINGS_ISSUED`
        inspection is rejected with `ERR_INSPECTION_NOT_CONCLUDABLE`."

        Design: Corner/errors/err_inspection_flow_error_battery
        """
        setup_compliant_index_c_airport()
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        # issue-findings before begin
        r1 = api.issue_findings_faa_inspection(
            insp["id"], {"findings_count": 0}, FAA,
        )
        validate_error(r1, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS)
        # conclude before findings
        r2 = api.conclude_faa_inspection(insp["id"], {"outcome": "FAIL"}, FAA)
        validate_error(r2, ApiErrorId.ERR_INSPECTION_NOT_CONCLUDABLE)
        # begin twice
        api.begin_faa_inspection(insp["id"], FAA)
        r3 = api.begin_faa_inspection(insp["id"], FAA)
        validate_error(r3, ApiErrorId.ERR_INSPECTION_NOT_BEGINNABLE)

    def test_conclude_pass_without_certified_drill_rejected(self, api):
        """PRD §3.12: "Second, at least one `ResponseDrill` must sit in
        `CERTIFIED` whose `executed_at` falls within the preceding twelve
        calendar months, measured by the same `month_index` arithmetic as
        training currency — `month_index` of today minus `month_index` of the
        drill's `executed_at` must be at most twelve; without one,
        `ERR_NO_VALID_CERTIFIED_DRILL`."

        Design: Corner/errors/err_inspection_flow_error_battery
        """
        setup_compliant_index_c_airport()
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.begin_faa_inspection(insp["id"], FAA)
        api.issue_findings_faa_inspection(insp["id"], {"findings_count": 0}, FAA)
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "PASS"}, FAA)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_CERTIFIED_DRILL)

    def test_conclude_pass_on_noncompliant_profile_rejected(self, api):
        """PRD §3.12: "Third, the profile's `index_compliance_status` must
        currently be `COMPLIANT`; otherwise `ERR_PROFILE_NOT_COMPLIANT`."

        Design: Corner/errors/err_inspection_flow_error_battery
        """
        setup_compliant_index_c_airport()
        create_certified_drill(
            runway="09L",
            window_start="2026-05-03T10:00:00Z",
            window_end="2026-05-03T11:00:00Z",
            execute_clock="2026-05-03T10:30:00Z",
            first_vehicle_arrival_seconds=100,
            all_vehicles_arrival_seconds=200,
        )
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.begin_faa_inspection(insp["id"], FAA)
        api.issue_findings_faa_inspection(insp["id"], {"findings_count": 0}, FAA)
        # Register an E-band aircraft (drives required_index to E > effective C)
        create_aircraft(model_name="A380", length_ft=238.6,
                        avg_daily_departures=6.0, in_scheduled_service=True)
        # No notification was created because effective_index never dropped
        # below certificated C; required_index rose.
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "PASS"}, FAA)
        validate_error(resp, ApiErrorId.ERR_PROFILE_NOT_COMPLIANT)

    def test_conclude_fail_closes_inspection(self, api):
        """PRD §3.12: "On a `PASS` conclusion the server records
        `concluded_outcome` `PASS`; on a `FAIL` conclusion it records
        `concluded_outcome` `FAIL` and no additional gates apply."

        Design: Corner/errors/err_inspection_flow_error_battery
        """
        setup_compliant_index_c_airport()
        insp = validate_success(
            api.create_faa_inspection(
                create_faa_inspection_payload(
                    inspection_year=2026, scheduled_on="2026-05-03",
                ),
                AM,
            ),
            expected_status=201,
        )
        api.begin_faa_inspection(insp["id"], FAA)
        api.issue_findings_faa_inspection(insp["id"], {"findings_count": 0}, FAA)
        resp = api.conclude_faa_inspection(insp["id"], {"outcome": "FAIL"}, FAA)
        concluded = validate_success(resp)
        assert concluded["status"] == "CLOSED_FAIL"
