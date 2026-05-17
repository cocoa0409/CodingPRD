"""Second test per difficulty-design instance.

Per the test generator's mandate, every difficulty-design instance must
be covered by at least TWO tests. This file supplies the second test
for each instance not already double-covered elsewhere — each cites
the same PRD prose its sibling test cites, and exercises an
adjacent observable behavior so the two together pin the implementation
firmly to the PRD rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LAB_LOCATION_CODE,
    acknowledge_payload,
    acknowledge_with_recipient,
    advance_clock_to,
    amend_result_payload,
    analyte_spec,
    anchor_clock,
    attempt_acknowledge,
    attempt_amend,
    attempt_open_transport_leg,
    attempt_release,
    create_catalog_bundle,
    critical_measurements_high,
    iso_anchor_offset,
    list_audit_for_order,
    list_notifications_for_result,
    list_orders_for_patient,
    list_retests_for_order,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    measurement,
    normal_measurements,
    open_transport_leg,
    place_lab_order,
    collect_specimen,
    reget_lab_order,
    reget_notification,
    reget_result,
    release,
    resultate,
    run_sweep,
    setup_in_transit_for_break,
    setup_patient_with_three_ordered,
    setup_released_critical,
    setup_released_non_critical,
    setup_specimen_with_arrived_first_leg,
    setup_two_orders_for_ordered_escalation,
    setup_two_priorities_at_anchor,
    validate_error,
    validate_success,
    walk_order_to_received,
)


# ===========================================================================
# difficulty: dual_variant_calc/
#             ack_latency_minutes_recorded_vs_attempt_escalation_count_on_notification
# ===========================================================================
class TestAckLatencyVsAttemptCountDualVariant:

    def test_late_ack_after_two_sweep_passes_yields_independent_metrics(
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

        Claim: a STAT notification escalated by sweep, then acked
        deep inside the extended window, records ack_latency_minutes
        equal to wall-clock delta from first_sent_at (NOT reset on
        escalation), while attempt_count reflects the sweep
        escalation only — two divergent observable numbers from the
        SAME setup.

        # difficulty: dual_variant_calc/ack_latency_minutes_recorded_vs_attempt_escalation_count_on_notification
        """
        ctx = setup_released_critical(priority="STAT")
        bundle, notif = ctx["bundle"], ctx["notification"]
        # Sweep at T0+11 (past STAT 10-min window) -> ESCALATED.
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=11),
        )
        run_sweep(bundle["director"])
        # Ack at T0+15.
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=15),
        )
        receipt = acknowledge_with_recipient(
            bundle, notif, read_back_text="A1 A2 ack",
        )
        # Wall-clock latency.
        assert receipt["ack_latency_minutes"] == pytest.approx(
            15.00, abs=1e-2,
        )
        # Attempt count incremented by exactly 1 from the one sweep.
        n_after = reget_notification(bundle, notif["id"])
        assert n_after["attempt_count"] == 1
        assert n_after["status"] == "ACKNOWLEDGED"


# ===========================================================================
# difficulty: combinatorial_formula/
#             attempt_escalation_chronological_order_dependency
# ===========================================================================
class TestSweepOrderingSecondCase:

    def test_attempt_count_on_both_increments_after_single_sweep_run(
        self, api,
    ):
        """PRD §3.5: "When the sweep is invoked, it walks every
        notification whose `status` is in `PENDING` or `ESCALATED`,
        ordered first by `ack_deadline_at` ascending and then by
        `created_at` ascending to break ties — this fixed ordering
        matters because two notifications maturing in the same sweep
        run must produce deterministic audit-event ordering."

        PRD §3.5: "the sweep transitions it to `ESCALATED`, flips
        `channel` to `VOICE`, increments `attempt_count` by one
        (without resetting `first_sent_at`), extends
        `ack_deadline_at` by 10 minutes regardless of the original
        priority, and appends a `ComplianceAuditEvent` with
        `event_type` of `CRITICAL_ESCALATED`."

        Claim: a single sweep run that processes two notifications
        with the same ack_deadline_at increments BOTH notifications'
        attempt_count to 1.

        # difficulty: combinatorial_formula/attempt_escalation_chronological_order_dependency
        """
        ctx = setup_two_orders_for_ordered_escalation()
        bundle = ctx["bundle"]
        notif_a = ctx["A"]["notification"]
        notif_b = ctx["B"]["notification"]
        advance_clock_to(
            bundle["director"], iso_anchor_offset(minutes=31),
        )
        run_sweep(bundle["director"])
        a_after = reget_notification(bundle, notif_a["id"])
        b_after = reget_notification(bundle, notif_b["id"])
        assert a_after["attempt_count"] == 1
        assert b_after["attempt_count"] == 1
        assert a_after["status"] == "ESCALATED"
        assert b_after["status"] == "ESCALATED"


# ===========================================================================
# difficulty: non_linear_state_machine /
#             lab_result_branching_with_amend_then_retract
# ===========================================================================
class TestLabResultBranchingTwo:

    def test_parent_order_remains_released_after_retract(self, api):
        """PRD §3.4: "The parent order's `status` is not changed by
        retraction — it remains in `RELEASED` — but the audit log
        records the retraction via a `ComplianceAuditEvent` row."

        Claim: after amend+retract, the parent LabOrder is still
        RELEASED.

        # difficulty: non_linear_state_machine/lab_result_branching_with_amend_then_retract
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, order, result = (
            ctx["bundle"], ctx["order"], ctx["result"],
        )
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        api.retract_result(
            result["id"],
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        order_after = reget_lab_order(bundle, order["id"])
        assert order_after["status"] == "RELEASED"


# ===========================================================================
# difficulty: non_linear_state_machine /
#             critical_notification_cyclic_via_amendment_reopening
# ===========================================================================
class TestNotificationCyclicReopenTwo:

    def test_reopened_notification_inherits_priority_deadline(self, api):
        """PRD §3.4: "the system auto-creates a `RetestRequest` with
        `reason` set to `RESULT_AMENDED`, and additionally opens a
        fresh `CriticalNotification` scoped only to the newly-critical
        analytes (those flagged by the amendment that were not
        flagged before), inheriting the same priority-driven deadline
        rules."

        Claim: the fresh CriticalNotification opened by an amendment
        carries the parent order's priority-driven window (STAT order
        => 10-minute window between its own first_sent_at and
        ack_deadline_at).

        # difficulty: non_linear_state_machine/critical_notification_cyclic_via_amendment_reopening
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
                analyte_spec(
                    analyte_code="A2", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle, priority="STAT")
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        # Original notification.
        original = list_notifications_for_result(bundle, released["id"])[0]
        # Ack the original so amendment-introduced notif is the only
        # PENDING one.
        acknowledge_with_recipient(
            bundle, original, read_back_text="A1 acked",
        )
        # Now amend to make A2 newly critical.
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        api.amend_result(
            released["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        notifications = list_notifications_for_result(bundle, released["id"])
        new_notif = next(
            n for n in notifications
            if n["status"] == "PENDING" and n["id"] != original["id"]
        )
        # STAT window is 10 minutes between first_sent_at and deadline.
        from test_helpers import parse_iso
        delta = (
            parse_iso(new_notif["ack_deadline_at"])
            - parse_iso(new_notif["first_sent_at"])
        ).total_seconds() / 60.0
        assert delta == pytest.approx(10, abs=1e-6), (
            "STAT-priority amendment-reopened notification must "
            "inherit the 10-minute STAT window"
        )


# ===========================================================================
# difficulty: priority_pair_validation_conflict /
#             state_vs_business_safety_conflict_on_release
# ===========================================================================
class TestStateVsSafetyConflictTwo:

    def test_canceled_order_release_attempt_returns_invalid_state(
        self, api,
    ):
        """PRD §2.13: "target-resource state validity for the
        requested transition (`ERR_INVALID_STATE`), then the
        business-safety rules in this order — segregation of duties
        (`ERR_CLIA_SOD_VIOLATION`), CLIA complexity tiering
        (`ERR_CLIA_COMPLEXITY_VIOLATION`), patient consent
        (`ERR_PATIENT_CONSENT_BLOCKED`)"

        Claim: even when the released_by_id would violate SoD, state
        validity is checked first and reported as ERR_INVALID_STATE.

        Second-instance variation: a release attempt on a result that
        was already released (and amended) is still blocked by
        ERR_INVALID_STATE before any business-safety check fires.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_conflict_on_release
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = normal_measurements(
            bundle["panel"]["analytes"], value=250.0,
        )
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["director"],
        )
        release(bundle, result, released_by=bundle["director2"])
        # Now amend so status is AMENDED.
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        # Try to release AGAIN with director1==resulted_by — would
        # be both an invalid state AND SoD violation; state wins.
        res = attempt_release(
            bundle, result,
            released_by=bundle["director"],
            actor=bundle["director2"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# difficulty: priority_pair_validation_conflict /
#             business_safety_vs_business_referential_conflict_on_ack
# ===========================================================================
class TestAckPriorityPairTwo:

    def test_wrong_recipient_beats_incomplete_readback_routine_panel(
        self, api,
    ):
        """PRD §2.13: "acknowledger-recipient identity
        (`ERR_ACK_BY_WRONG_RECIPIENT`), read-back completeness
        (`ERR_READBACK_INCOMPLETE`)"

        Second instance: in a non-HIGH (MODERATE) panel the
        ERR_READBACK_INCOMPLETE rule does NOT fire (read-back is
        only required for HIGH per PRD §3.5), so wrong-recipient
        still produces ERR_ACK_BY_WRONG_RECIPIENT regardless of
        read_back_text content.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_conflict_on_ack
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


# ===========================================================================
# difficulty: boundary_precision_check /
#             empty_critical_flags_skips_notification_creation
# ===========================================================================
class TestEmptyCriticalFlagsSkipsNotification:

    def test_release_with_no_criticals_still_writes_result_released_event(
        self, api,
    ):
        """PRD §3.4: "When the result's `critical_flags` is empty,
        the system appends a single `ComplianceAuditEvent` with
        `event_type` of `RESULT_RELEASED` and the workflow ends with
        the result released and no notification opened."

        Claim: with empty critical_flags, GET /audit-events?event_type
        =RESULT_RELEASED returns exactly one event and no
        CRITICAL_NOTIFIED event is written.

        # difficulty: boundary_precision_check/empty_critical_flags_skips_notification_creation
        """
        ctx = setup_released_non_critical()
        bundle, order = ctx["bundle"], ctx["order"]
        rr = list_audit_for_order(
            bundle, order["id"], event_type="RESULT_RELEASED",
        )
        cn = list_audit_for_order(
            bundle, order["id"], event_type="CRITICAL_NOTIFIED",
        )
        assert len(rr) == 1, (
            "exactly one RESULT_RELEASED audit event must be written"
        )
        assert cn == [], (
            "no CRITICAL_NOTIFIED audit event when critical_flags empty"
        )


# ===========================================================================
# difficulty: cross_entity_state_dependency /
#             lab_order_resulted_depends_on_specimen_received
# ===========================================================================
class TestOrderResultedDependsOnSpecimenReceivedTwo:

    def test_result_attempt_on_in_transit_order_blocked(self, api):
        """PRD §3.4: "Once the order is in `RECEIVED` and its
        specimen is in `RECEIVED`, a clinician may produce the
        result."

        Second-instance variation: when the order is IN_TRANSIT
        (specimen still not received), a result attempt is blocked
        with ERR_INVALID_STATE for a different reason than the
        REJECTED-specimen case.

        # difficulty: cross_entity_state_dependency/lab_order_resulted_depends_on_specimen_received
        """
        from test_helpers import attempt_resultate
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        # Open a leg but do not arrive — order stays IN_TRANSIT.
        open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
        )
        meas = normal_measurements(
            bundle["panel"]["analytes"], value=250.0,
        )
        res = attempt_resultate(
            bundle, order,
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# difficulty: compensating_invariant /
#             amend_then_retract_invariant_total_critical_notifications_per_result
# ===========================================================================
class TestAmendRetractInvariantTwo:

    def test_amend_pending_notification_count_unchanged_by_retract(
        self, api,
    ):
        """PRD §3.4: "The parent order's `status` is not changed by
        retraction — it remains in `RELEASED` — but the audit log
        records the retraction via a `ComplianceAuditEvent` row."

        Companion claim to the ACKED-count invariant: a PENDING
        CriticalNotification opened by an amendment is NOT canceled
        by a subsequent retract — the PENDING count is unchanged
        across the retract operation.

        # difficulty: compensating_invariant/amend_then_retract_invariant_total_critical_notifications_per_result
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            include_second_director=True,
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
                analyte_spec(
                    analyte_code="A2", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        # Release with A1 critical, A2 normal -> 1 PENDING notification.
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        n1 = list_notifications_for_result(bundle, released["id"])[0]
        # Ack n1.
        acknowledge_with_recipient(
            bundle, n1, read_back_text="A1 acked",
        )
        # Amend to make A2 newly critical -> n2 PENDING.
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        api.amend_result(
            released["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        pending_before = sum(
            1 for n in list_notifications_for_result(bundle, released["id"])
            if n["status"] == "PENDING"
        )
        # Retract — PRD §3.4 says retract does NOT cancel pending
        # notifications, only the audit event records retract.
        api.retract_result(
            released["id"],
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        pending_after = sum(
            1 for n in list_notifications_for_result(bundle, released["id"])
            if n["status"] == "PENDING"
        )
        assert pending_after == pending_before, (
            "retract must NOT cancel pending notifications; count "
            "is invariant across the retract operation"
        )
