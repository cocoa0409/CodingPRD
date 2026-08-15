"""Exceedances: detection boundary, MDL substitution, governing-limit coverage,
the 24h/120h notification clock, closure gates and the detection cascade
(PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_custody_to_analyzed,
    assert_exceedance,
    assert_instant_equals,
    collect_sample,
    create_active_permit,
    create_effluent_limit,
    create_exceedance_scenario,
    create_outfall,
    create_permit,
    drive_corrective_action_to_verified,
    get_permit_state,
    issue_permit,
    make_lab_validator_headers,
    record_lab_result,
    schedule_sample,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)
CO = TEST_USERS["compliance_officer_headers"]

class TestExceedanceDetection:
    def test_exceedance_detection_strictly_greater_boundary(self, api):
        """PRD §3.3: "If one exists and the comparison value is strictly greater
        than its `limit_value` — equality is not an exceedance — `exceeds_limit` is
        set to true and the detection cascade of §3.4 fires"
        PRD §3.4: "`percent_over` expresses the magnitude of the breach: the
        comparison value minus the limit value, divided by the limit value,
        multiplied by one hundred, rounded half-up to two decimal places."

        Design: Corner/calculations/exceedance_detection_strictly_greater_boundary
        """
        env = create_active_permit(
            permit_number="NPDES-CALC1", parameter_code="TSS", limit_value=2.0
        )
        sample_a = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-05T08:00:00Z")
        sample_b = schedule_sample(env["outfall"]["id"], "TSS", "2026-08-05T08:30:00Z")
        set_clock("2026-08-05T09:00:00Z")
        for sample in (sample_a, sample_b):
            collect_sample(sample["id"])
            advance_custody_to_analyzed(sample["id"], "2026-08-05T09:00:00Z")
        result_a = record_lab_result(
            sample_a["id"], "TSS", 2.0, "2026-08-05T09:45:00Z"  # exactly the limit
        )
        result_b = record_lab_result(
            sample_b["id"], "TSS", 2.5, "2026-08-05T09:45:00Z"  # strictly above
        )
        set_clock("2026-08-05T10:00:00Z")

        validated_a = validate_success(
            api.validate_lab_result(result_a["id"], make_lab_validator_headers("validator-1"))
        )
        validated_b = validate_success(
            api.validate_lab_result(result_b["id"], make_lab_validator_headers("validator-1"))
        )
        assert validated_a["exceeds_limit"] is False, "equality is NOT an exceedance"
        assert validated_a["exceedance_id"] is None
        assert validated_b["exceeds_limit"] is True
        assert validated_b["exceedance_id"] is not None

        exceedance = validate_success(
            api.get_exceedance(validated_b["exceedance_id"], ANY_HEADERS)
        )
        assert_exceedance(exceedance)
        assert exceedance["percent_over"] == pytest.approx(25.0, abs=0.001), (
            "(2.5 - 2.0) / 2.0 * 100 = 25.0"
        )

        rows, meta = validate_paginated(
            api.list_exceedances(ANY_HEADERS, params={"outfall_id": env["outfall"]["id"]})
        )
        assert len(rows) == 1 and meta["total_count"] == 1
        assert rows[0]["id"] == validated_b["exceedance_id"]

    def test_exceedance_detection_uses_mdl_when_below_mdl_qualifier(self, api):
        """PRD §3.3: "The comparison value is the result's `reported_value`, except
        that a result carrying the `BELOW_MDL` qualifier compares at its
        `method_detection_limit` instead."
        PRD §3.4: "`reported_value` snapshots the comparison value used at detection
        (the detection limit itself when the result was `BELOW_MDL`)".

        Design: Corner/calculations/exceedance_detection_uses_mdl_when_below_mdl_qualifier
        """
        scenario = create_exceedance_scenario(
            permit_number="NPDES-CALC2",
            limit_value=0.5,
            reported_value=0.4,
            method_detection_limit=0.6,
            qualifier="BELOW_MDL",
            flow_mgd=1.0,
        )
        exceedance = scenario["exceedance"]
        assert scenario["result"]["exceeds_limit"] is True, (
            "MDL 0.6 (not reported 0.4) is the comparison value"
        )
        assert exceedance["reported_value"] == pytest.approx(0.6), (
            "the exceedance snapshots the comparison value used at detection"
        )
        assert exceedance["percent_over"] == pytest.approx(20.0, abs=0.001), (
            "(0.6 - 0.5) / 0.5 * 100 = 20.0"
        )

    def test_exceedance_not_detected_without_governing_limit(self, api):
        """PRD §3.3: "The governing limit is the `ACTIVE` `DAILY_MAX` effluent limit
        for the sample's outfall and the result's parameter whose half-open effective
        range covers the sample's `collected_at`. If no such governing limit exists,
        `exceeds_limit` is set to false and nothing further happens."

        Design: Corner/calculations/exceedance_not_detected_without_governing_limit
        """
        # The limit's half-open range ends exactly at the collection instant, so it
        # covers scheduled_for (scheduling gate passes) but NOT collected_at.
        permit = create_permit(permit_number="NPDES-CALC3")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(
            outfall["id"], parameter_code="TSS", limit_value=2.0,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-08-05T09:00:00Z",
        )
        issue_permit(permit["id"])
        sample = schedule_sample(outfall["id"], "TSS", "2026-08-05T08:00:00Z")
        collect_sample(sample["id"], clock_iso="2026-08-05T09:00:00Z")
        advance_custody_to_analyzed(sample["id"], "2026-08-05T09:00:00Z")
        result = record_lab_result(
            sample["id"], "TSS", 99.0, "2026-08-05T09:45:00Z"
        )
        validated = validate_success(
            api.validate_lab_result(result["id"], make_lab_validator_headers("validator-1"))
        )
        assert validated["exceeds_limit"] is False
        assert validated["exceedance_id"] is None

        rows, meta = validate_paginated(
            api.list_exceedances(ANY_HEADERS, params={"outfall_id": outfall["id"]})
        )
        assert rows == [] and meta["total_count"] == 0

class TestNotificationClock:
    def test_notification_deadlines_overdue_boundary_strictly_greater(self, api):
        """PRD §3.4: "Two statutory deadlines are computed from it:
        `oral_notification_due_at` exactly 24 hours after detection, and
        `written_report_due_at` exactly 120 hours (five days) after detection."
        PRD §3.4: "Both deadlines share one boundary rule: an act performed at
        exactly the due instant is timely — only a clock strictly later than the
        due instant triggers the overdue transition."

        Design: Corner/calculations/notification_deadlines_overdue_boundary_strictly_greater
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-CALC4")
        exceedance = scenario["exceedance"]
        assert_instant_equals(exceedance["detected_at"], "2026-08-05T10:00:00Z", "detected_at")
        assert_instant_equals(
            exceedance["oral_notification_due_at"], "2026-08-06T10:00:00Z",
            "oral_notification_due_at == detected_at + 24h",
        )
        assert_instant_equals(
            exceedance["written_report_due_at"], "2026-08-10T10:00:00Z",
            "written_report_due_at == detected_at + 120h",
        )

        set_clock("2026-08-06T10:00:00Z")  # exactly at the due instant
        at_due = validate_success(api.get_exceedance(exceedance["id"], ANY_HEADERS))
        assert at_due["notification_status"] == "PENDING_ORAL", (
            "exactly at the due instant is still timely"
        )

        set_clock("2026-08-06T10:00:01Z")  # one second past
        past_due = validate_success(api.get_exceedance(exceedance["id"], ANY_HEADERS))
        assert past_due["notification_status"] == "ORAL_OVERDUE"

    def test_exceedance_notification_happy_path_to_closed(self, api):
        """PRD §3.4: "A `ComplianceOfficer` records the oral notification while the
        exceedance is in `PENDING_ORAL` or `ORAL_OVERDUE` ... moving it to
        `ORAL_NOTIFIED` and stamping `oral_notified_at` with the logical clock".
        PRD §3.4: "A `ComplianceOfficer` closes an exceedance only from
        `WRITTEN_FILED` ... and only when the corrective action linked through
        `corrective_action_id` stands in `VERIFIED` or `CLOSED`".

        Design: Corner/state_machines/exceedance_notification_happy_path_to_closed
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM19")
        exceedance = scenario["exceedance"]
        drive_corrective_action_to_verified(
            scenario["corrective_action"]["id"], actual_cost_cents=5000
        )

        notified = validate_success(api.notify_exceedance(exceedance["id"], CO))
        assert notified["notification_status"] == "ORAL_NOTIFIED"
        assert_instant_equals(
            notified["oral_notified_at"], "2026-08-05T10:00:00Z", "oral_notified_at"
        )

        filed = validate_success(api.file_exceedance_report(
            exceedance["id"], {"report_summary": "5-day written report"}, CO
        ))
        assert filed["notification_status"] == "WRITTEN_FILED"
        assert filed["written_filed_at"] is not None

        closed = validate_success(api.close_exceedance(exceedance["id"], CO))
        assert closed["notification_status"] == "CLOSED"
        permit = get_permit_state(scenario["permit"]["id"])
        assert permit["open_exceedance_count"] == 0, (
            "closed exceedances leave the open-exceedance count (PRD §2.9)"
        )

    def test_exceedance_notify_from_oral_notified_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` records the oral notification while the
        exceedance is in `PENDING_ORAL` or `ORAL_OVERDUE` — from any other status
        the call is rejected with `ERR_INVALID_NOTIFICATION_STATE`"

        Design: Corner/state_machines/exceedance_notify_from_oral_notified_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM20")
        exceedance = scenario["exceedance"]
        validate_success(api.notify_exceedance(exceedance["id"], CO))

        resp = api.notify_exceedance(exceedance["id"], CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTIFICATION_STATE)

    def test_exceedance_file_report_before_notify_rejected(self, api):
        """PRD §3.4: "filing by a `ComplianceOfficer` — which carries a
        `report_summary` — is accepted from `ORAL_NOTIFIED` or `WRITTEN_OVERDUE`
        (`ERR_INVALID_NOTIFICATION_STATE` otherwise)"

        Design: Corner/state_machines/exceedance_file_report_before_notify_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM21")
        resp = api.file_exceedance_report(
            scenario["exceedance"]["id"], {"report_summary": "premature"}, CO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_NOTIFICATION_STATE)

    def test_error_exceedance_not_closable_while_action_open(self, api):
        """PRD §3.4: "A `ComplianceOfficer` closes an exceedance only from
        `WRITTEN_FILED` (`ERR_INVALID_NOTIFICATION_STATE` otherwise), and only when
        the corrective action linked through `corrective_action_id` stands in
        `VERIFIED` or `CLOSED` (`ERR_EXCEEDANCE_NOT_CLOSABLE`)."

        Design: Corner/errors/error_exceedance_not_closable_while_action_open
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-ERR4")
        exceedance = scenario["exceedance"]
        validate_success(api.notify_exceedance(exceedance["id"], CO))
        validate_success(api.file_exceedance_report(
            exceedance["id"], {"report_summary": "written"}, CO
        ))
        # Corrective action is still OPEN.
        resp = api.close_exceedance(exceedance["id"], CO)
        validate_error(resp, ApiErrorId.ERR_EXCEEDANCE_NOT_CLOSABLE)

    def test_threshold_oral_overdue_then_late_notify_allowed(self, api):
        """PRD §3.4: "If the clock sweeps strictly past `oral_notification_due_at`
        while the exceedance still waits in `PENDING_ORAL`, the sweep moves it to
        `ORAL_OVERDUE` (`EXCEEDANCE_ORAL_OVERDUE`, recorded against `system`); a late
        oral notification is still permitted from `ORAL_OVERDUE`, and the overdue
        sojourn remains visible in the audit chain."

        Design: Corner/cross_cutting_layers/threshold_oral_overdue_then_late_notify_allowed
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-LAY6")
        exceedance = scenario["exceedance"]

        set_clock("2026-08-07T12:00:00Z")  # strictly past the 24h oral deadline
        overdue = validate_success(api.get_exceedance(exceedance["id"], ANY_HEADERS))
        assert overdue["notification_status"] == "ORAL_OVERDUE"

        notified = validate_success(api.notify_exceedance(exceedance["id"], CO))
        assert notified["notification_status"] == "ORAL_NOTIFIED"
        assert_instant_equals(
            notified["oral_notified_at"], "2026-08-07T12:00:00Z", "late oral_notified_at"
        )

    def test_error_exceedance_not_found_on_notify(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_EXCEEDANCE_NOT_FOUND` ..."

        Design: Corner/errors/error_exceedance_not_found_on_notify
        """
        resp = api.notify_exceedance(NON_EXISTENT_UUID, CO)
        validate_error(resp, ApiErrorId.ERR_EXCEEDANCE_NOT_FOUND)

class TestExceedanceCascadeAndQueries:
    def test_cascade_lab_validation_exceedance_to_corrective_action_to_permit_posture(self, api):
        """PRD §3.4: "every exceedance auto-creates a CorrectiveAction with
        `source_type` `EXCEEDANCE`, `exceedance_id` set, severity always `MAJOR`,
        status `OPEN` and an auto-generated narrative `description`" and "the
        corrective action's creation increments the parent permit's
        `open_corrective_action_count` by one and recomputes its `compliance_posture`
        — a permit in `GOOD_STANDING` drops to `UNDER_CORRECTIVE_ACTION` — while the
        permit's `open_exceedance_count` is also recomputed."
        PRD §3.4: "The new exceedance stands with `notification_status` at
        `PENDING_ORAL` and `enforcement_status` at `NONE`".

        Design: Corner/cross_cutting_layers/cascade_lab_validation_exceedance_to_corrective_action_to_permit_posture
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-LAY2")
        ca = scenario["corrective_action"]
        assert ca["source_type"] == "EXCEEDANCE"
        assert ca["exceedance_id"] == scenario["exceedance"]["id"]
        assert ca["severity"] == "MAJOR"
        assert ca["status"] == "OPEN"
        assert scenario["exceedance"]["corrective_action_id"] == ca["id"]

        permit = get_permit_state(scenario["permit"]["id"])
        assert permit["open_corrective_action_count"] == 1
        assert permit["compliance_posture"] == "UNDER_CORRECTIVE_ACTION"
        assert permit["open_exceedance_count"] == 1

        exceedance = scenario["exceedance"]
        assert exceedance["notification_status"] == "PENDING_ORAL"
        assert exceedance["enforcement_status"] == "NONE"

    def test_exceedance_list_filtered_by_lab_result(self, api):
        """PRD §3.4: "Exceedances can be listed filtered by `outfall_id`,
        `lab_result_id`, `effluent_limit_id`, `corrective_action_id` or
        `notification_status`."

        Design: Corner/endpoints/exceedance_list_filtered_by_lab_result
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-EP2")
        exceedance = scenario["exceedance"]

        rows, meta = validate_paginated(
            api.list_exceedances(
                ANY_HEADERS, params={"lab_result_id": scenario["result"]["id"]}
            )
        )
        assert len(rows) == 1 and meta["total_count"] == 1
        assert rows[0]["id"] == exceedance["id"]

        closed_rows, closed_meta = validate_paginated(
            api.list_exceedances(
                ANY_HEADERS,
                params={
                    "outfall_id": scenario["outfall"]["id"],
                    "notification_status": "CLOSED",
                },
            )
        )
        assert closed_rows == [] and closed_meta["total_count"] == 0
