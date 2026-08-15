"""Boil-order notification, sampling windows, and lift/escalation cascades."""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_boil_order,
    assert_compliance_sample,
    collect_sample,
    create_active_member,
    create_area,
    create_district,
    get_district_version,
    get_success_data,
    issue_boil_order,
    notify_member,
    setup_member_with_installed_tap,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_ORDER_ISSUED,
    SAMPLE_AT_WINDOW_EDGE,
    SAMPLE_IN_WINDOW,
    SAMPLE_IN_WINDOW_2,
    SAMPLE_IN_WINDOW_3,
    SAMPLE_PAST_WINDOW,
)
from test_helpers.fixtures import ADMIN, CLERK, FIELD, create_member, approve_member


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestLogicalClockDefault:
    def test_boil_order_stamps_default_logical_clock(self, api):
        """PRD section 2.4: "Before any clock call has been made, the logical clock
        reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock
        time." PRD section 3.11: issuance "computes `notification_deadline_utc` as
        24 hours after issuance".

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_epoch
        """
        district = create_district(district_name="LA")
        order = issue_boil_order(district["id"], reason="Default clock check")
        assert_boil_order(order)
        assert _parse(order["issued_utc"]) == datetime(2026, 8, 1, tzinfo=timezone.utc)
        assert _parse(order["notification_deadline_utc"]) == _parse(order["issued_utc"]) + timedelta(hours=24)
        assert order["status"] == "IN_EFFECT"
        district_after = get_success_data(api.get_district(district["id"], ADMIN))
        assert district_after["boil_order_active"] is True


class TestNotificationRules:
    def test_duplicate_notification_rejected(self, api):
        """PRD section 3.11: "Notifying the same member twice for the same order is
        rejected with `ERR_DUPLICATE_NOTIFICATION` (HTTP 409), and the order's
        `notified_member_count` tracks the distinct members notified."

        Design: Corner/errors/error_duplicate_notification_trigger
        """
        district = create_district(district_name="RB")
        area = create_area(district["id"])
        member = create_active_member(district["id"], area["id"])
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Break")
        notify_member(district["id"], order["id"], member["id"], channel="PHONE_TREE")

        resp = api.create_notification(
            district["id"], order["id"],
            {"member_id": member["id"], "channel": "CERTIFIED_MAIL"}, FIELD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NOTIFICATION, expected_status=409)
        after = [o for o in get_success_data(api.list_boil_orders(district["id"], FIELD))
                 if o["id"] == order["id"]][0]
        assert after["notified_member_count"] == 1


class TestSamplingGate:
    def _setup_late_member_scenario(self, api):
        """One ACTIVE member notified; a second member approved after issuance."""
        district = create_district(district_name="D14")
        area = create_area(district["id"])
        member_a = create_active_member(district["id"], area["id"], legal_name="M One")
        member_b = create_member(district["id"], area["id"], legal_name="M Two",
                                 member_class="COMMERCIAL")
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Pressure loss")
        notify_member(district["id"], order["id"], member_a["id"], channel="PHONE_TREE")
        approve_member(district["id"], member_b["id"])
        return district, member_a, member_b, order

    def test_late_approved_member_reblocks_begin_sampling(self, api):
        """PRD section 3.11: "Sampling may begin — `IN_EFFECT → SAMPLING`, a
        `FieldOperator` action — only when that count equals the number of district
        members with `membership_status` `ACTIVE`; otherwise
        `ERR_NOTIFICATION_INCOMPLETE` (HTTP 409)." One notified of two ACTIVE
        members is incomplete.

        Design: Difficulty/cross_entity_state_dependency/boil_sampling_gated_by_member_notification_state
        """
        district, _, _, order = self._setup_late_member_scenario(api)
        resp = api.begin_sampling(district["id"], order["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_INCOMPLETE, expected_status=409)
        after = [o for o in get_success_data(api.list_boil_orders(district["id"], FIELD))
                 if o["id"] == order["id"]][0]
        assert after["status"] == "IN_EFFECT"

    def test_begin_sampling_succeeds_once_all_active_members_notified(self, api):
        """PRD section 3.11: "Sampling may begin — `IN_EFFECT → SAMPLING`, a
        `FieldOperator` action — only when that count equals the number of district
        members with `membership_status` `ACTIVE`; otherwise
        `ERR_NOTIFICATION_INCOMPLETE` (HTTP 409)." and "the order's
        `notified_member_count` tracks the distinct members notified."

        Design: Difficulty/cross_entity_state_dependency/boil_sampling_gated_by_member_notification_state
        """
        district, _, member_b, order = self._setup_late_member_scenario(api)
        validate_error(
            api.begin_sampling(district["id"], order["id"], FIELD),
            ApiErrorId.ERR_NOTIFICATION_INCOMPLETE,
            expected_status=409,
        )
        notify_member(district["id"], order["id"], member_b["id"], channel="CERTIFIED_MAIL")
        sampling = get_success_data(api.begin_sampling(district["id"], order["id"], FIELD))
        assert sampling["status"] == "SAMPLING"
        assert sampling["notified_member_count"] == 2


class TestSamplingWindow:
    def _setup_sampling_order(self, api):
        district = create_district(district_name="D16")
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Turbidity")
        # No ACTIVE members exist, so the notification gate is trivially satisfied.
        get_success_data(api.begin_sampling(district["id"], order["id"], FIELD))
        return district, order

    def test_sample_one_second_past_window_rejected(self, api):
        """PRD section 3.11: "The collection time must not precede the order's
        `issued_utc` and must fall within 72 hours of it; a violation is
        `ERR_SAMPLE_WINDOW_VIOLATION` (HTTP 422)." issued+72h+1s is outside.

        Design: Difficulty/resource_temporal_overlap/compliance_sample_window_closed_interval
        """
        district, order = self._setup_sampling_order(api)
        resp = api.create_compliance_sample(
            district["id"],
            {"boil_order_id": order["id"], "sample_point": "SP-LATE",
             "collected_utc": SAMPLE_PAST_WINDOW},
            FIELD,
        )
        validate_error(resp, ApiErrorId.ERR_SAMPLE_WINDOW_VIOLATION, expected_status=422)

    def test_sample_at_exact_window_end_accepted(self, api):
        """PRD section 3.11: "The collection time must not precede the order's
        `issued_utc` and must fall within 72 hours of it; a violation is
        `ERR_SAMPLE_WINDOW_VIOLATION` (HTTP 422). A new sample's `result` is
        `PENDING`." A collection exactly at issued+72h is still within the window.

        Design: Difficulty/resource_temporal_overlap/compliance_sample_window_closed_interval
        """
        district, order = self._setup_sampling_order(api)
        sample = collect_sample(district["id"], order["id"], SAMPLE_AT_WINDOW_EDGE, "SP-EDGE")
        assert_compliance_sample(sample)
        assert sample["result"] == "PENDING"


class TestLiftAndEscalation:
    def test_two_absent_samples_lift_order(self, api):
        """PRD section 3.11: "when two samples, consecutive in `created_at` order,
        have each reached `ABSENT` with no `PRESENT` result anywhere on the order,
        the order lifts — `SAMPLING → LIFTED` — clearing `boil_order_active` and
        incrementing the district's `version`."

        Design: Corner/state_machines/boil_order_two_absent_samples_lift_cascade
        """
        district = create_district(district_name="DK")
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Main break")
        get_success_data(api.begin_sampling(district["id"], order["id"], FIELD))
        s1 = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW, "SP-1")
        s2 = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW_2, "SP-2")

        get_success_data(api.record_sample_result(district["id"], s1["id"], {"result": "ABSENT"}, FIELD))
        mid = [o for o in get_success_data(api.list_boil_orders(district["id"], FIELD))
               if o["id"] == order["id"]][0]
        assert mid["status"] == "SAMPLING", "One clear sample must not lift the order"

        version_before = get_district_version(district["id"])
        get_success_data(api.record_sample_result(district["id"], s2["id"], {"result": "ABSENT"}, FIELD))
        end = [o for o in get_success_data(api.list_boil_orders(district["id"], FIELD))
               if o["id"] == order["id"]][0]
        assert end["status"] == "LIFTED"
        district_after = get_success_data(api.get_district(district["id"], FIELD))
        assert district_after["boil_order_active"] is False
        assert district_after["version"] > version_before

    def test_record_result_on_lifted_order_rejected(self, api):
        """PRD section 3.11: "Recording the result is only legal while the parent
        order is `SAMPLING` — otherwise `ERR_ORDER_NOT_SAMPLING` (HTTP 409)."

        Design: Corner/state_machines/record_result_on_lifted_order_rejected
        """
        district = create_district(district_name="DL")
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED, reason="Main break")
        get_success_data(api.begin_sampling(district["id"], order["id"], FIELD))
        s1 = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW, "SP-1")
        s2 = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW_2, "SP-2")
        s3 = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW_3, "SP-3")
        get_success_data(api.record_sample_result(district["id"], s1["id"], {"result": "ABSENT"}, FIELD))
        get_success_data(api.record_sample_result(district["id"], s2["id"], {"result": "ABSENT"}, FIELD))

        resp = api.record_sample_result(district["id"], s3["id"], {"result": "ABSENT"}, FIELD)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SAMPLING, expected_status=409)
        samples = get_success_data(api.list_compliance_samples(district["id"], FIELD))
        s3_after = [s for s in samples if s["id"] == s3["id"]][0]
        assert s3_after["result"] == "PENDING"

    def _setup_present_scenario(self, api):
        ctx = setup_member_with_installed_tap()
        district = ctx["district"]
        order = issue_boil_order(district["id"], at_iso=CLOCK_ORDER_ISSUED,
                                 reason="Main break loss of pressure")
        notify_member(district["id"], order["id"], ctx["member"]["id"])
        get_success_data(api.begin_sampling(district["id"], order["id"], FIELD))
        sample = collect_sample(district["id"], order["id"], SAMPLE_IN_WINDOW, "SP-1")
        return ctx, order, sample

    def test_present_sample_escalates_order(self, api):
        """PRD section 3.11: "Any single `PRESENT` result escalates instead:
        `SAMPLING → VIOLATION_ESCALATED`, the district's `version` increments, and
        a new boil order must be issued before lifting is possible."

        Design: Difficulty/transitive_cascade/sample_present_cascade_depth3
        """
        ctx, order, sample = self._setup_present_scenario(api)
        district = ctx["district"]
        result = get_success_data(
            api.record_sample_result(district["id"], sample["id"], {"result": "PRESENT"}, FIELD)
        )
        assert result["result"] == "PRESENT"
        order_after = [o for o in get_success_data(api.list_boil_orders(district["id"], FIELD))
                       if o["id"] == order["id"]][0]
        assert order_after["status"] == "VIOLATION_ESCALATED"

    def test_present_sample_increments_district_version(self, api):
        """PRD section 3.11: "Any single `PRESENT` result escalates instead:
        `SAMPLING → VIOLATION_ESCALATED`, the district's `version` increments, and
        a new boil order must be issued before lifting is possible."

        Design: Difficulty/transitive_cascade/sample_present_cascade_depth3
        """
        ctx, order, sample = self._setup_present_scenario(api)
        district = ctx["district"]
        version_before = get_district_version(district["id"])
        get_success_data(
            api.record_sample_result(district["id"], sample["id"], {"result": "PRESENT"}, FIELD)
        )
        version_after = get_district_version(district["id"])
        assert version_after > version_before, (
            f"Escalation must increment the district version ({version_before} -> {version_after})"
        )
