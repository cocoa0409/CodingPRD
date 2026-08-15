"""Leak events: confirmation cascade, the 100 lb reportable-quantity boundary,
and the regulatory notification clock."""
from test_helpers import (
    CO,
    ApiErrorId,
    api_client,
    assert_leak_event,
    assert_timestamp_instant,
    get_facility,
    set_clock,
    setup_suspected_leak,
    validate_error,
    validate_success,
)


class TestLeakConfirmCascade:

    def test_leak_confirm_cascade_leak_fields(self):
        """PRD section 3.8: "The event moves to `CONFIRMED`, `confirmed_at` is
        stamped from the logical clock, and the notification obligation is
        computed: a confirmed quantity of at least 100 pounds — the CERCLA
        reportable quantity for ammonia, where exactly 100.0 qualifies — sets
        `notification_required` true, fixes `notification_deadline_at` at
        fifteen minutes after confirmation, and moves `notification_status` to
        `PENDING`; anything below the reportable quantity leaves the deadline
        null and the status `NOT_REQUIRED`."

        Design: Difficulty/transitive_cascade/leak_confirm_cascade
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=130.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 120.0}, CO),
            expected_status=200)
        assert_leak_event(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert_timestamp_instant(confirmed["confirmed_at"], "2026-08-10T09:00:00Z")
        assert confirmed["notification_required"] is True
        # confirmed at 09:00 -> deadline fifteen minutes later
        assert_timestamp_instant(confirmed["notification_deadline_at"],
                                 "2026-08-10T09:15:00Z")
        assert confirmed["notification_status"] == "PENDING"

    def test_leak_confirm_cascade_incident_and_posture(self):
        """PRD section 3.8: "Confirmation also auto-creates an incident for the
        system's facility: `severity` `REPORTABLE` when the release reaches the
        reportable quantity, otherwise `RECORDABLE`; `reported_by_employee_id`
        left null as the one exception to the reporting rule of §3.6;
        `source_leak_event_id` pointing back at the leak; and the leak's
        `auto_incident_id` set to the new incident. The facility's
        `open_incident_count` increments and its posture recomputes, just as
        for a hand-filed report."
        PRD section 2.7: "From these counts the platform computes the
        `posture_score`: five points for every overdue inspection, three for
        every open incident, and two for every expired training record, summed
        as integers with no rounding. The `compliance_posture` then bands the
        score — `COMPLIANT` when the score is zero, `DEGRADED` when it sits
        between one and nine inclusive, and `NONCOMPLIANT` once it reaches
        ten."

        Design: Difficulty/transitive_cascade/leak_confirm_cascade
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=130.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 120.0}, CO),
            expected_status=200)
        incident_id = confirmed["auto_incident_id"]
        assert incident_id is not None

        incident = validate_success(api_client.get_incident(incident_id, CO),
                                    expected_status=200)
        # 120.0 lbs reaches the reportable quantity
        assert incident["severity"] == "REPORTABLE"
        assert incident["status"] == "REPORTED"
        assert incident.get("reported_by_employee_id") is None
        assert incident["source_leak_event_id"] == leak["id"]
        assert incident["facility_id"] == facility["id"]

        facility_after = get_facility(facility["id"], headers=CO)
        assert facility_after["open_incident_count"] == 1
        # 3 points for the single open incident: COMPLIANT -> DEGRADED
        assert facility_after["posture_score"] == 3
        assert facility_after["compliance_posture"] == "DEGRADED"


class TestReportableQuantityBoundary:

    def test_leak_release_exactly_at_rq_notification(self):
        """PRD section 3.8: "a confirmed quantity of at least 100 pounds — the
        CERCLA reportable quantity for ammonia, where exactly 100.0 qualifies —
        sets `notification_required` true, fixes `notification_deadline_at` at
        fifteen minutes after confirmation, and moves `notification_status` to
        `PENDING`; anything below the reportable quantity leaves the deadline
        null and the status `NOT_REQUIRED`."

        Design: Difficulty/boundary_precision_check/leak_release_exactly_at_rq
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=110.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 100.0}, CO),
            expected_status=200)
        # exactly 100.0 qualifies (>= RQ)
        assert confirmed["notification_required"] is True
        assert confirmed["notification_status"] == "PENDING"
        assert_timestamp_instant(confirmed["notification_deadline_at"],
                                 "2026-08-10T09:15:00Z")

    def test_leak_release_exactly_at_rq_incident_reportable(self):
        """PRD section 3.8: "Confirmation also auto-creates an incident for the
        system's facility: `severity` `REPORTABLE` when the release reaches the
        reportable quantity, otherwise `RECORDABLE`; `reported_by_employee_id`
        left null as the one exception to the reporting rule of §3.6;
        `source_leak_event_id` pointing back at the leak; and the leak's
        `auto_incident_id` set to the new incident."

        Design: Difficulty/boundary_precision_check/leak_release_exactly_at_rq
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=110.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 100.0}, CO),
            expected_status=200)
        incident = validate_success(
            api_client.get_incident(confirmed["auto_incident_id"], CO),
            expected_status=200)
        assert incident["severity"] == "REPORTABLE"
        assert incident["source_leak_event_id"] == leak["id"]

    def test_leak_below_rq_no_notification(self):
        """PRD section 3.8: "a confirmed quantity of at least 100 pounds — the
        CERCLA reportable quantity for ammonia, where exactly 100.0 qualifies —
        sets `notification_required` true, fixes `notification_deadline_at` at
        fifteen minutes after confirmation, and moves `notification_status` to
        `PENDING`; anything below the reportable quantity leaves the deadline
        null and the status `NOT_REQUIRED`."
        PRD section 3.8: "Confirmation also auto-creates an incident for the
        system's facility: `severity` `REPORTABLE` when the release reaches the
        reportable quantity, otherwise `RECORDABLE`; `reported_by_employee_id`
        left null as the one exception to the reporting rule of §3.6;
        `source_leak_event_id` pointing back at the leak; and the leak's
        `auto_incident_id` set to the new incident."

        Design: Corner/errors/leak_below_rq_no_notification
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=95.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 99.9}, CO),
            expected_status=200)
        assert confirmed["notification_required"] is False
        assert confirmed["notification_status"] == "NOT_REQUIRED"
        assert confirmed.get("notification_deadline_at") is None
        incident = validate_success(
            api_client.get_incident(confirmed["auto_incident_id"], CO),
            expected_status=200)
        # 99.9 < 100: one step below the reportable quantity
        assert incident["severity"] == "RECORDABLE"


class TestNotifyRegulator:

    def test_notify_when_not_required_rejected(self):
        """PRD section 3.8: "The call is accepted only while
        `notification_status` stands `PENDING` or `OVERDUE` — a notification
        that was never required, or one already recorded, is rejected with
        `ERR_NOTIFICATION_NOT_REQUIRED` (409)."

        Design: Corner/validations/notify_when_not_required_rejected
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=60.0, clock="2026-08-10T09:00:00Z")
        confirmed = validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 50.0}, CO),
            expected_status=200)
        assert confirmed["notification_required"] is False
        assert confirmed["notification_status"] == "NOT_REQUIRED"

        resp = api_client.notify_regulator(leak["id"], CO)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_REQUIRED,
                       expected_status=409)

    def test_notify_exactly_at_deadline_is_on_time(self):
        """PRD section 3.8: "When accepted, `notified_at` is stamped from the
        logical clock, the status moves to `NOTIFIED`, and `late_notification`
        is computed: true only when the notification landed strictly after the
        deadline, since landing exactly at the deadline counts as on time."

        Design: Corner/errors/notify_exactly_at_deadline_is_on_time
        """
        facility, system, employee, op_headers, leak = setup_suspected_leak(
            estimated_release_lbs=120.0, clock="2026-08-10T09:00:00Z")
        validate_success(
            api_client.confirm_leak(leak["id"], {"final_release_lbs": 120.0}, CO),
            expected_status=200)
        # advance the clock to exactly the 09:15 deadline
        set_clock("2026-08-10T09:15:00Z", CO)
        notified = validate_success(api_client.notify_regulator(leak["id"], CO),
                                    expected_status=200)
        assert notified["notification_status"] == "NOTIFIED"
        assert_timestamp_instant(notified["notified_at"], "2026-08-10T09:15:00Z")
        # strict > rule: exact equality is on time
        assert notified["late_notification"] is False
