"""Critical notification windows, sweep escalation, acknowledgement.

PRD §3.5 fixes the window (30 ROUTINE / 10 STAT), the sweep's
escalation rules; PRD §3.8 fixes the audit events; PRD §2.12
specifies post-ACKNOWLEDGED double-fire response.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ACK_WINDOW_ROUTINE_MIN,
    ACK_WINDOW_STAT_MIN,
    ESCALATION_EXTENSION_MIN,
    acknowledge_payload,
    acknowledge_with_recipient,
    advance_clock_to,
    anchor_clock,
    assert_acknowledgement_receipt,
    attempt_acknowledge,
    create_catalog_bundle,
    critical_measurements_high,
    iso_anchor_offset,
    list_audit_for_order,
    list_notifications_for_result,
    list_retests_for_order,
    make_lab_director_headers,
    make_ordering_provider_headers,
    parse_anchor,
    parse_iso,
    patch_clinician_payload,
    reget_lab_order,
    reget_notification,
    release,
    resultate,
    run_sweep,
    setup_released_critical,
    setup_two_orders_for_ordered_escalation,
    setup_two_priorities_at_anchor,
    validate_error,
    walk_order_to_received,
)


def _minutes_from_anchor(iso_ts: str) -> float:
    delta = parse_iso(iso_ts) - parse_anchor()
    return delta.total_seconds() / 60.0


# ===========================================================================
# §3.5 ack_deadline_at by priority
# difficulty: combinatorial_formula /
#             ack_window_tiered_by_priority_and_escalation_extension
# ===========================================================================
class TestAckWindowByPriority:

    def test_routine_window_is_30_minutes(self, api):
        """PRD §3.5: "Its acknowledgement deadline `ack_deadline_at`
        is the `first_sent_at` plus a window that depends on the
        parent order's `priority`: 30 minutes when `priority` is
        `ROUTINE`, 10 minutes when `priority` is `STAT`."

        Claim: a ROUTINE notification has ack_deadline_at =
        first_sent_at + 30 minutes.

        # difficulty: combinatorial_formula/ack_window_tiered_by_priority_and_escalation_extension
        """
        ctx = setup_two_priorities_at_anchor()
        routine = ctx["routine"]["notification"]
        first_sent = parse_iso(routine["first_sent_at"])
        deadline = parse_iso(routine["ack_deadline_at"])
        delta_min = (deadline - first_sent).total_seconds() / 60.0
        assert delta_min == pytest.approx(
            ACK_WINDOW_ROUTINE_MIN, abs=1e-6,
        )

    def test_stat_window_is_10_minutes(self, api):
        """PRD §3.5: "Its acknowledgement deadline `ack_deadline_at`
        is the `first_sent_at` plus a window that depends on the
        parent order's `priority`: 30 minutes when `priority` is
        `ROUTINE`, 10 minutes when `priority` is `STAT`."

        Claim: a STAT notification has ack_deadline_at = first_sent_at
        + 10 minutes.

        # difficulty: combinatorial_formula/ack_window_tiered_by_priority_and_escalation_extension
        """
        ctx = setup_two_priorities_at_anchor()
        stat = ctx["stat"]["notification"]
        first_sent = parse_iso(stat["first_sent_at"])
        deadline = parse_iso(stat["ack_deadline_at"])
        delta_min = (deadline - first_sent).total_seconds() / 60.0
        assert delta_min == pytest.approx(
            ACK_WINDOW_STAT_MIN, abs=1e-6,
        )


# ===========================================================================
# §3.5 Sweep escalation rules
# difficulty: resource_temporal_overlap /
#             notification_ack_window_half_open_interval
# ===========================================================================
class TestSweepEscalation:

    def test_sweep_inside_window_does_not_escalate(self, api):
        """PRD §3.5: "If the server clock is earlier than the
        notification's `ack_deadline_at`, the notification is
        skipped."

        Claim: a sweep at T0+29:59 leaves a ROUTINE PENDING
        notification at PENDING with channel SMS.

        # difficulty: resource_temporal_overlap/notification_ack_window_half_open_interval
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, notif = ctx["bundle"], ctx["notification"]
        advance_clock_to(
            bundle["director"],
            iso_anchor_offset(minutes=29, seconds=59),
        )
        run_sweep(bundle["director"])
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["status"] == "PENDING"
        assert n_after["channel"] == "SMS"

    def test_sweep_at_deadline_escalates_to_voice(self, api):
        """PRD §3.5: "If the notification is `PENDING` on the `SMS`
        channel and the deadline has elapsed, the sweep transitions
        it to `ESCALATED`, flips `channel` to `VOICE`, increments
        `attempt_count` by one (without resetting `first_sent_at`),
        extends `ack_deadline_at` by 10 minutes regardless of the
        original priority, and appends a `ComplianceAuditEvent` with
        `event_type` of `CRITICAL_ESCALATED`."

        Claim: at clock T0+30 (the right edge of the 30-min ROUTINE
        window) the sweep transitions notification -> ESCALATED with
        channel VOICE, attempt_count 1, first_sent_at unchanged, and
        ack_deadline_at extended by 10 minutes; a CRITICAL_ESCALATED
        audit event is written.

        # difficulty: combinatorial_formula/ack_window_tiered_by_priority_and_escalation_extension
        # difficulty: resource_temporal_overlap/notification_ack_window_half_open_interval
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, notif = ctx["bundle"], ctx["notification"]
        first_sent_at = notif["first_sent_at"]
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=30),
        )
        run_sweep(bundle["director"])
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["status"] == "ESCALATED"
        assert n_after["channel"] == "VOICE"
        assert n_after["attempt_count"] == 1
        assert n_after["first_sent_at"] == first_sent_at
        new_dl_min = _minutes_from_anchor(n_after["ack_deadline_at"])
        first_min = _minutes_from_anchor(first_sent_at)
        assert new_dl_min == pytest.approx(
            first_min + ACK_WINDOW_ROUTINE_MIN
            + ESCALATION_EXTENSION_MIN, abs=1e-6,
        )
        audit = list_audit_for_order(
            bundle, ctx["order"]["id"],
            event_type="CRITICAL_ESCALATED",
        )
        assert len(audit) >= 1


# ===========================================================================
# §3.5 Failure cascade
# difficulty: transitive_cascade / notification_failed_cascade_chain_depth_2
# ===========================================================================
class TestSweepFailureCascade:

    def test_second_sweep_after_extension_transitions_to_failed(
        self, api,
    ):
        """PRD §3.5: "If the notification is `ESCALATED` on the
        `VOICE` channel and the extended deadline has elapsed, the
        sweep transitions it to `FAILED`, increments `attempt_count`
        by one, auto-creates a `RetestRequest` with `reason` set to
        `CRITICAL_UNACKNOWLEDGED` whose `new_lab_order_id` references
        a freshly minted replacement `LabOrder` cloning patient and
        panel with `parent_order_id` set to the original order and
        `retest_count` incremented, and appends a
        `ComplianceAuditEvent` with `event_type` of
        `CRITICAL_ESCALATED` whose `payload` carries a failure flag."

        Claim: STAT-priority notification escalated at T0+11 then
        failed at T0+22 yields FAILED notification, a new
        RetestRequest(CRITICAL_UNACKNOWLEDGED) linking to a new
        LabOrder whose parent_order_id == original.id and
        retest_count == +1.

        # difficulty: transitive_cascade/notification_failed_cascade_chain_depth_2
        """
        ctx = setup_released_critical(priority="STAT")
        bundle, order, notif = (
            ctx["bundle"], ctx["order"], ctx["notification"],
        )
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=11),
        )
        run_sweep(bundle["director"])
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["status"] == "ESCALATED"
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=22),
        )
        run_sweep(bundle["director"])
        n_failed = reget_notification(bundle, notif["id"])
        assert n_failed["status"] == "FAILED"
        assert n_failed["attempt_count"] >= 2
        retests = list_retests_for_order(bundle, order["id"])
        rr = next(
            (r for r in retests
             if r["reason"] == "CRITICAL_UNACKNOWLEDGED"),
            None,
        )
        assert rr is not None
        new_order = reget_lab_order(bundle, rr["new_lab_order_id"])
        assert new_order["parent_order_id"] == order["id"]
        assert new_order["retest_count"] == order["retest_count"] + 1


# ===========================================================================
# §3.5 Acknowledgement happy path / receipt fields
# difficulty: dual_variant_calc /
#             ack_latency_minutes_recorded_vs_attempt_escalation_count_on_notification
# ===========================================================================
class TestAcknowledgement:

    def test_ack_within_window_succeeds_and_records_latency(self, api):
        """PRD §3.5: "On a successful acknowledgement, the system
        creates an `AcknowledgementReceipt` whose
        `critical_notification_id` references the notification, whose
        `acknowledged_by_id` records the acknowledging clinician,
        whose `acknowledged_at` is the server clock, whose
        `read_back_text` is persisted as supplied, and whose
        `ack_latency_minutes` is computed as the difference between
        `acknowledged_at` and the notification's `first_sent_at`
        expressed in minutes to 2 decimal places. The notification
        transitions to `ACKNOWLEDGED`."

        Claim: ack at T0+15 for a ROUTINE notification yields a
        receipt with ack_latency_minutes == 15.00 and the notification
        transitions to ACKNOWLEDGED.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, notif = ctx["bundle"], ctx["notification"]
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=15),
        )
        receipt = acknowledge_with_recipient(
            bundle, notif, read_back_text="A1 A2 acknowledged",
        )
        assert_acknowledgement_receipt(receipt)
        assert receipt["ack_latency_minutes"] == pytest.approx(
            15.00, abs=1e-2,
        )
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["status"] == "ACKNOWLEDGED"

    def test_ack_after_escalation_records_post_escalation_latency(
        self, api,
    ):
        """PRD §3.5: "the sweep transitions it to `ESCALATED`, flips
        `channel` to `VOICE`, increments `attempt_count` by one
        (without resetting `first_sent_at`), extends
        `ack_deadline_at` by 10 minutes regardless of the original
        priority, and appends a `ComplianceAuditEvent` with
        `event_type` of `CRITICAL_ESCALATED`."

        PRD §3.5: "`ack_latency_minutes` is computed as the
        difference between `acknowledged_at` and the notification's
        `first_sent_at` expressed in minutes to 2 decimal places."

        Claim: ROUTINE notification escalated at T0+45 and then acked
        at T0+50 yields receipt.ack_latency_minutes == 50.00 while
        notification.attempt_count == 1 — same physical row produces
        two divergent observable numbers from the same setup.

        # difficulty: dual_variant_calc/ack_latency_minutes_recorded_vs_attempt_escalation_count_on_notification
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, notif = ctx["bundle"], ctx["notification"]
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=45),
        )
        run_sweep(bundle["director"])
        n_esc = reget_notification(bundle, notif["id"])
        assert n_esc["status"] == "ESCALATED"
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=50),
        )
        receipt = acknowledge_with_recipient(
            bundle, notif, read_back_text="A1 A2 acknowledged",
        )
        assert receipt["ack_latency_minutes"] == pytest.approx(
            50.00, abs=1e-2,
        )
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["status"] == "ACKNOWLEDGED"
        assert n_after["attempt_count"] == 1


# ===========================================================================
# §3.5 Ack identity / state / read-back rules
# ===========================================================================
class TestAckRules:

    def test_ack_by_wrong_recipient_rejected(self, api):
        """PRD §3.5: "The supplied `acknowledged_by_id` must equal
        the notification's `recipient_clinician_id` — any other
        clinician is rejected with `ERR_ACK_BY_WRONG_RECIPIENT`."

        Claim: acknowledging with a different OrderingProvider id ->
        ERR_ACK_BY_WRONG_RECIPIENT.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
            include_second_ordering_provider=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = critical_measurements_high(
            bundle["panel"]["analytes"], value=400.0,
        )
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        release(bundle, result)
        notifications = list_notifications_for_result(
            bundle, result["id"],
        )
        notif = notifications[0]
        op2 = bundle["ordering_provider2"]
        res = attempt_acknowledge(
            bundle, notif,
            acknowledger_id=op2["id"], actor_id=op2["id"],
            read_back_text="A1 A2",
        )
        validate_error(res, "ERR_ACK_BY_WRONG_RECIPIENT")

    def test_ack_high_complexity_requires_each_analyte_in_readback(
        self, api,
    ):
        """PRD §3.5: "When the panel's `clia_complexity` is `HIGH`,
        the `read_back_text` must contain, as a case-insensitive
        substring, every `analyte_code` present in the result's
        `critical_flags`; missing any of them is rejected with
        `ERR_READBACK_INCOMPLETE`."

        Claim: ack on HIGH with read_back_text missing one analyte ->
        ERR_READBACK_INCOMPLETE.
        """
        ctx = setup_released_critical(
            priority="ROUTINE", panel_complexity="HIGH",
        )
        bundle, notif = ctx["bundle"], ctx["notification"]
        op = bundle["ordering_provider"]
        payload = acknowledge_payload(
            acknowledged_by_id=op["id"], read_back_text="A1 only",
        )
        res = api.acknowledge_notification(
            notif["id"], payload,
            make_ordering_provider_headers(op["id"]),
        )
        validate_error(res, "ERR_READBACK_INCOMPLETE")

    def test_ack_high_complexity_readback_case_insensitive(self, api):
        """PRD §3.5: "When the panel's `clia_complexity` is `HIGH`,
        the `read_back_text` must contain, as a case-insensitive
        substring, every `analyte_code` present in the result's
        `critical_flags`; missing any of them is rejected with
        `ERR_READBACK_INCOMPLETE`."

        Claim: ack on HIGH with all analyte codes lowercased in the
        read-back succeeds.
        """
        ctx = setup_released_critical(
            priority="ROUTINE", panel_complexity="HIGH",
        )
        bundle, notif = ctx["bundle"], ctx["notification"]
        receipt = acknowledge_with_recipient(
            bundle, notif, read_back_text="patient values a1 and a2",
        )
        assert_acknowledgement_receipt(receipt)

    def test_second_ack_after_acknowledged_returns_already_acked(
        self, api,
    ):
        """PRD §3.5: "a second acknowledgement after the row has
        already reached `ACKNOWLEDGED` is rejected with
        `ERR_ALREADY_ACKNOWLEDGED`, which is distinct from the
        generic state error."

        Claim: a second POST /notifications/{id}/acknowledge after
        the first succeeded returns ERR_ALREADY_ACKNOWLEDGED.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, notif = ctx["bundle"], ctx["notification"]
        acknowledge_with_recipient(
            bundle, notif, read_back_text="A1 A2",
        )
        op = bundle["ordering_provider"]
        payload = acknowledge_payload(
            acknowledged_by_id=op["id"], read_back_text="A1 A2",
        )
        res = api.acknowledge_notification(
            notif["id"], payload,
            make_ordering_provider_headers(op["id"]),
        )
        validate_error(res, "ERR_ALREADY_ACKNOWLEDGED")

# ===========================================================================
# §2.13 Validation priority on ack endpoint
# difficulty: priority_pair_validation_conflict /
#             business_safety_vs_business_referential_conflict_on_ack
# ===========================================================================
class TestAckValidationPriority:

    def test_wrong_recipient_beats_incomplete_readback(self, api):
        """PRD §2.13: "then the business-referential rules in this
        order — acknowledger-recipient identity
        (`ERR_ACK_BY_WRONG_RECIPIENT`), read-back completeness
        (`ERR_READBACK_INCOMPLETE`)"

        Claim: HIGH-complexity ack with BOTH wrong recipient AND
        empty read_back_text returns ERR_ACK_BY_WRONG_RECIPIENT —
        priority 9 wins over priority 10.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_conflict_on_ack
        """
        bundle = create_catalog_bundle(
            panel_complexity="HIGH",
            include_second_director=True,
            include_second_ordering_provider=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = critical_measurements_high(
            bundle["panel"]["analytes"], value=400.0,
        )
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["director"],
        )
        release(bundle, result, released_by=bundle["director2"])
        notif = list_notifications_for_result(
            bundle, result["id"],
        )[0]
        op2 = bundle["ordering_provider2"]
        res = attempt_acknowledge(
            bundle, notif,
            acknowledger_id=op2["id"], actor_id=op2["id"],
            read_back_text="",
        )
        validate_error(res, "ERR_ACK_BY_WRONG_RECIPIENT")
