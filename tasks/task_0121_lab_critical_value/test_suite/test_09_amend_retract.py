"""Amendment + retraction lifecycle and branching state machine.

PRD §3.4 fixes amendment and retraction; amendment that changes the
critical set auto-issues a RetestRequest(RESULT_AMENDED) AND opens a
fresh CriticalNotification scoped only to newly-critical analytes.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    acknowledge_with_recipient,
    amend_result_payload,
    analyte_spec,
    anchor_clock,
    create_catalog_bundle,
    list_audit_for_order,
    list_notifications_for_result,
    list_retests_for_order,
    make_lab_director_headers,
    measurement,
    release,
    reget_notification,
    reget_result,
    resultate,
    setup_released_critical,
    validate_error,
    validate_success,
    walk_order_to_received,
)


# ===========================================================================
# §3.4 Amendment basics
# ===========================================================================
class TestAmendBasics:

    def test_amend_released_transitions_to_amended_and_writes_event(
        self, api,
    ):
        """PRD §3.4: "A `LabDirector` may amend a `RELEASED` result
        by supplying new `measurements` (and optionally `version`).
        The result must be in `RELEASED`."

        PRD §3.4: "The result's `status` transitions from `RELEASED`
        to `AMENDED`."

        PRD §3.4: "A `ComplianceAuditEvent` with `event_type` of
        `AMENDMENT_RECORDED` is appended."

        Claim: amend transitions status -> AMENDED and writes an
        AMENDMENT_RECORDED audit event.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, order, result = (
            ctx["bundle"], ctx["order"], ctx["result"],
        )
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        res = api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        amended = validate_success(res, 200)
        assert amended["status"] == "AMENDED"
        ev = list_audit_for_order(
            bundle, order["id"], event_type="AMENDMENT_RECORDED",
        )
        assert len(ev) >= 1

    def test_amend_recomputes_critical_flags(self, api):
        """PRD §3.4: "Amendment recomputes `critical_flags` and
        recomputes the final severity score over the new
        measurements, replacing the prior value."

        Claim: amending with values inside the bounds clears the
        critical_flags array.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, result = ctx["bundle"], ctx["result"]
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        amended = reget_result(bundle, result["id"])
        assert amended["critical_flags"] == []


# ===========================================================================
# §3.4 Amendment changing critical set -> new notification + retest
# difficulty: non_linear_state_machine /
#             critical_notification_cyclic_via_amendment_reopening
# difficulty: compensating_invariant /
#             amend_then_retract_invariant_total_critical_notifications_per_result
# ===========================================================================
class TestAmendCriticalSetChange:

    def _setup_panel_a1_only_critical(self):
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
        order = walked["order"]
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        result = resultate(
            bundle, order,
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        notif = list_notifications_for_result(bundle, released["id"])[0]
        return bundle, order, released, notif

    def test_amend_introducing_new_critical_opens_new_notification(
        self, api,
    ):
        """PRD §3.4: "When the recomputed `critical_flags` differ
        from the prior `critical_flags` — whether by introduction of
        new critical analytes, removal of previous ones, or a change
        in side — the system auto-creates a `RetestRequest` with
        `reason` set to `RESULT_AMENDED`, and additionally opens a
        fresh `CriticalNotification` scoped only to the newly-critical
        analytes (those flagged by the amendment that were not
        flagged before), inheriting the same priority-driven deadline
        rules."

        Claim: after an amendment that makes A2 newly critical, a
        NEW CriticalNotification exists for the same lab_result_id
        in PENDING state and the original ACKNOWLEDGED notification
        is left untouched.

        # difficulty: non_linear_state_machine/critical_notification_cyclic_via_amendment_reopening
        """
        bundle, order, result, original_notif = (
            self._setup_panel_a1_only_critical()
        )
        acknowledge_with_recipient(
            bundle, original_notif, read_back_text="A1 acknowledged",
        )
        original_after = reget_notification(bundle, original_notif["id"])
        assert original_after["status"] == "ACKNOWLEDGED"

        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        notifications = list_notifications_for_result(bundle, result["id"])
        pending_new = [
            n for n in notifications
            if n["status"] == "PENDING"
            and n["id"] != original_notif["id"]
        ]
        assert len(pending_new) >= 1
        original_check = reget_notification(
            bundle, original_notif["id"],
        )
        assert original_check["status"] == "ACKNOWLEDGED"

    def test_amend_changing_critical_set_auto_issues_retest(self, api):
        """PRD §3.4: "When the recomputed `critical_flags` differ
        from the prior `critical_flags` — whether by introduction of
        new critical analytes, removal of previous ones, or a change
        in side — the system auto-creates a `RetestRequest` with
        `reason` set to `RESULT_AMENDED`, and additionally opens a
        fresh `CriticalNotification` scoped only to the newly-critical
        analytes (those flagged by the amendment that were not
        flagged before), inheriting the same priority-driven deadline
        rules."

        Claim: amendment that changes the critical set produces a
        RetestRequest(reason=RESULT_AMENDED) for the order.
        """
        bundle, order, result, _ = (
            self._setup_panel_a1_only_critical()
        )
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        retests = list_retests_for_order(bundle, order["id"])
        assert any(
            r["reason"] == "RESULT_AMENDED" for r in retests
        )


# ===========================================================================
# §3.4 Retraction
# difficulty: non_linear_state_machine /
#             lab_result_branching_with_amend_then_retract
# difficulty: compensating_invariant /
#             amend_then_retract_invariant_total_critical_notifications_per_result
# ===========================================================================
class TestRetraction:

    def test_retract_amended_transitions_to_retracted(self, api):
        """PRD §3.4: "A `LabDirector` may retract an `AMENDED`
        result. The result must currently be in `AMENDED`; retraction
        transitions its `status` from `AMENDED` to `RETRACTED`."

        Claim: POST /results/{id}/retract on AMENDED -> 200 status
        RETRACTED.

        # difficulty: non_linear_state_machine/lab_result_branching_with_amend_then_retract
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, result = ctx["bundle"], ctx["result"]
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        api.amend_result(
            result["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        res = api.retract_result(
            result["id"],
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        retracted = validate_success(res, 200)
        assert retracted["status"] == "RETRACTED"

    def test_retract_on_released_rejected(self, api):
        """PRD §3.4: "A `LabDirector` may retract an `AMENDED`
        result. The result must currently be in `AMENDED`; retraction
        transitions its `status` from `AMENDED` to `RETRACTED`."

        Claim: retract on a RELEASED (never-amended) result ->
        ERR_INVALID_STATE.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, result = ctx["bundle"], ctx["result"]
        res = api.retract_result(
            result["id"],
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_amend_then_retract_preserves_acked_count(self, api):
        """PRD §3.4: "The parent order's `status` is not changed by
        retraction — it remains in `RELEASED` — but the audit log
        records the retraction via a `ComplianceAuditEvent` row."

        Together with PRD §3.4 ("opens a fresh `CriticalNotification`
        scoped only to the newly-critical analytes") and PRD §3.5
        ("On a successful acknowledgement, the system creates an
        `AcknowledgementReceipt`"), the count of ACKNOWLEDGED
        notifications on a result is preserved after amend+retract.

        Claim: amend then retract leave the count of ACKNOWLEDGED
        notifications for the result at exactly the same value as
        immediately after the original ack.

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
        meas = [
            measurement(analyte_code="A1", value=400, unit="mg/dL"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(bundle, result)
        notif = list_notifications_for_result(bundle, released["id"])[0]
        acknowledge_with_recipient(
            bundle, notif, read_back_text="A1 acked",
        )
        acked_before = sum(
            1 for n in list_notifications_for_result(bundle, released["id"])
            if n["status"] == "ACKNOWLEDGED"
        )
        assert acked_before == 1
        new_meas = [
            measurement(analyte_code="A1", value=250, unit="mg/dL"),
            measurement(analyte_code="A2", value=400, unit="mg/dL"),
        ]
        api.amend_result(
            released["id"],
            amend_result_payload(measurements=new_meas),
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        api.retract_result(
            released["id"],
            make_lab_director_headers(bundle["director2"]["id"]),
        )
        acked_after = sum(
            1 for n in list_notifications_for_result(bundle, released["id"])
            if n["status"] == "ACKNOWLEDGED"
        )
        assert acked_after == 1
