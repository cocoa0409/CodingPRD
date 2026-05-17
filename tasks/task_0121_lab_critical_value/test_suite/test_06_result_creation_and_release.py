"""Result creation (DRAFT) and release (CLIA SoD, consent, criticals).

PRD §3.4 fixes result creation, the critical-flag computation, the
release transition; PRD §2.6 fixes CLIA segregation of duties and
complexity tiering; PRD §2.7 fixes patient consent gating; PRD §3.8
fixes the audit events written on release.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    analyte_spec,
    anchor_clock,
    assert_critical_notification,
    assert_lab_result,
    attempt_release,
    attempt_resultate,
    create_catalog_bundle,
    critical_measurements_high,
    list_audit_for_order,
    list_notifications_for_result,
    make_lab_director_headers,
    measurement,
    normal_measurements,
    release,
    reget_lab_order,
    resultate,
    setup_released_critical,
    setup_released_non_critical,
    validate_error,
    walk_order_to_received,
)


# ===========================================================================
# §3.4 Resulting basics
# ===========================================================================
class TestResultCreation:

    def test_resultate_creates_draft_result_and_advances_order(self, api):
        """PRD §3.4: "A successful resulting creates a `LabResult`
        whose `lab_order_id` references the order, whose
        `resulted_by_id` reflects the input, whose `released_by_id` is
        initially absent, whose `measurements` are persisted as
        supplied, and whose `status` is set to `DRAFT` (the initial
        result state)."

        PRD §3.4: "The parent order transitions from `RECEIVED` to
        `RESULTED`."

        Claim: POST /lab-orders/{id}/results returns 201 with status
        DRAFT and the order transitions to RESULTED.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        order = walked["order"]
        meas = normal_measurements(
            bundle["panel"]["analytes"], value=250.0,
        )
        result = resultate(
            bundle, order,
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        assert_lab_result(result)
        assert result["status"] == "DRAFT"
        order_after = reget_lab_order(bundle, order["id"])
        assert order_after["status"] == "RESULTED"

    def test_critical_flag_only_when_strictly_outside_range(self, api):
        """PRD §3.4: "A measurement whose value sits at exactly
        `critical_low` or exactly `critical_high` is not critical
        because the comparison is strict outside the range."

        Claim: a measurement equal to critical_high produces NO
        critical flag.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        result = resultate(
            bundle, walked["order"],
            measurements=[measurement(
                analyte_code="A1", value=300, unit="mg/dL",
            )],
            resulted_by=bundle["lab_tech"],
        )
        assert result["critical_flags"] == []

    def test_value_above_critical_high_flags_as_high(self, api):
        """PRD §3.4: "otherwise if the spec's `critical_high` is
        present and the measurement's `value` is strictly greater than
        `critical_high`, the system appends an entry with `side` of
        `HIGH` and `bound` of `critical_high`."

        Claim: value = critical_high + 1 yields exactly one entry with
        side HIGH, bound = critical_high.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        result = resultate(
            bundle, walked["order"],
            measurements=[measurement(
                analyte_code="A1", value=301, unit="mg/dL",
            )],
            resulted_by=bundle["lab_tech"],
        )
        flags = result["critical_flags"]
        assert len(flags) == 1
        assert flags[0]["analyte_code"] == "A1"
        assert flags[0]["side"] == "HIGH"
        assert flags[0]["bound"] == 300

    def test_value_below_critical_low_flags_as_low(self, api):
        """PRD §3.4: "if the spec's `critical_low` is present and
        the measurement's `value` is strictly less than
        `critical_low`, the system appends a critical-flag entry
        whose `analyte_code` is the measurement's analyte, whose
        `side` is `LOW`, whose `value` is the measurement's value,
        and whose `bound` is `critical_low`; otherwise if the spec's
        `critical_high` is present and the measurement's `value` is
        strictly greater than `critical_high`, the system appends an
        entry with `side` of `HIGH` and `bound` of `critical_high`."

        Claim: value = critical_low - 1 yields one entry with side
        LOW, bound = critical_low.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            analytes=[
                analyte_spec(
                    analyte_code="K", unit="mmol/L",
                    critical_low=3.0, critical_high=None,
                ),
            ],
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        result = resultate(
            bundle, walked["order"],
            measurements=[measurement(
                analyte_code="K", value=2, unit="mmol/L",
            )],
            resulted_by=bundle["lab_tech"],
        )
        flags = result["critical_flags"]
        assert len(flags) == 1
        assert flags[0]["side"] == "LOW"
        assert flags[0]["bound"] == 3.0


# ===========================================================================
# §3.4 Measurement completeness
# ===========================================================================
class TestMeasurementCompleteness:

    def test_measurements_must_cover_every_analyte_exactly_once(self, api):
        """PRD §3.4: "The submitted set must cover every analyte in
        the panel exactly once — no analyte missing, no analyte
        repeated, no analyte not on the panel — and each entry's
        `unit` must match the panel's declared unit for that analyte.
        A coverage or unit mismatch is rejected with
        `ERR_MEASUREMENTS_INCOMPLETE`."

        Claim: omitting an analyte -> ERR_MEASUREMENTS_INCOMPLETE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        res = attempt_resultate(
            bundle, walked["order"],
            measurements=[measurement(
                analyte_code="A1", value=250, unit="mg/dL",
            )],
            resulted_by=bundle["lab_tech"],
        )
        validate_error(res, "ERR_MEASUREMENTS_INCOMPLETE")

    def test_unit_mismatch_rejected(self, api):
        """PRD §3.4: "The submitted set must cover every analyte in
        the panel exactly once — no analyte missing, no analyte
        repeated, no analyte not on the panel — and each entry's
        `unit` must match the panel's declared unit for that analyte.
        A coverage or unit mismatch is rejected with
        `ERR_MEASUREMENTS_INCOMPLETE`."

        Claim: supplying a wrong unit -> ERR_MEASUREMENTS_INCOMPLETE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        bad = [
            measurement(analyte_code="A1", value=250, unit="mmol/L"),
            measurement(analyte_code="A2", value=250, unit="mg/dL"),
        ]
        res = attempt_resultate(
            bundle, walked["order"],
            measurements=bad, resulted_by=bundle["lab_tech"],
        )
        validate_error(res, "ERR_MEASUREMENTS_INCOMPLETE")


# ===========================================================================
# §2.6 CLIA complexity tiering on resulting
# ===========================================================================
class TestCliaComplexityTiering:

    def test_high_complexity_requires_lab_director(self, api):
        """PRD §2.6: "the clinician who produces the result (named in
        `resulted_by_id`) must have a `role_kind` of `LAB_TECH` or
        `LAB_DIRECTOR` for `WAIVED` and `MODERATE` panels, and must
        have a `role_kind` of `LAB_DIRECTOR` for `HIGH` panels. A
        violation of this rule is rejected with
        `ERR_CLIA_COMPLEXITY_VIOLATION`."

        Claim: LabTech results on a HIGH-complexity panel ->
        ERR_CLIA_COMPLEXITY_VIOLATION.
        """
        bundle = create_catalog_bundle(
            panel_complexity="HIGH",
            include_second_director=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = normal_measurements(
            bundle["panel"]["analytes"], value=250.0,
        )
        res = attempt_resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        validate_error(res, "ERR_CLIA_COMPLEXITY_VIOLATION")

    def test_high_complexity_with_lab_director_accepted(self, api):
        """PRD §2.6: "the clinician who produces the result (named in
        `resulted_by_id`) must have a `role_kind` of `LAB_TECH` or
        `LAB_DIRECTOR` for `WAIVED` and `MODERATE` panels, and must
        have a `role_kind` of `LAB_DIRECTOR` for `HIGH` panels."

        Claim: LabDirector results on a HIGH panel succeeds.
        """
        bundle = create_catalog_bundle(
            panel_complexity="HIGH",
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
        assert result["status"] == "DRAFT"


# ===========================================================================
# §2.6 CLIA SoD on release
# ===========================================================================
class TestCliaSegregationOfDuties:

    def test_release_with_same_clinician_as_resulted_rejected(self, api):
        """PRD §2.6: "if `released_by_id` equals `resulted_by_id` the
        release is rejected with `ERR_CLIA_SOD_VIOLATION`."

        Claim: POST /results/{id}/release with released_by_id ==
        resulted_by_id -> ERR_CLIA_SOD_VIOLATION.
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
        res = attempt_release(
            bundle, result,
            released_by=bundle["director"], actor=bundle["director"],
        )
        validate_error(res, "ERR_CLIA_SOD_VIOLATION")

    def test_release_with_distinct_directors_succeeds(self, api):
        """PRD §3.4: "On release, the result's `status` transitions
        from `DRAFT` to `RELEASED`, the `released_at` field is set
        to the server clock, the parent order transitions from
        `RESULTED` to `RELEASED`, and the system recomputes the
        severity score using the final variant described in §3.6,
        replacing the provisional value."

        Claim: release with a different LabDirector succeeds and the
        result's status becomes RELEASED.
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
        released = release(
            bundle, result, released_by=bundle["director2"],
        )
        assert released["status"] == "RELEASED"


# ===========================================================================
# §2.7 Patient consent gating
# ===========================================================================
class TestPatientConsentBlocking:

    def test_consent_none_blocks_release_with_critical_flags(self, api):
        """PRD §2.7: "When releasing a result that would, by virtue of
        containing critical flags, require the system to open a
        `CriticalNotification`, the patient's `notification_consent`
        must permit some form of contact: a value of `NONE` blocks the
        release, which is rejected with
        `ERR_PATIENT_CONSENT_BLOCKED`."

        Claim: notification_consent=NONE with critical flags ->
        ERR_PATIENT_CONSENT_BLOCKED on release.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            notification_consent="NONE",
            include_second_director=True,
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
        res = attempt_release(
            bundle, result, released_by=bundle["director2"],
        )
        validate_error(res, "ERR_PATIENT_CONSENT_BLOCKED")

    def test_consent_none_allows_release_with_empty_critical_flags(
        self, api,
    ):
        """PRD §2.7: "Releases for a result with no critical flags are
        unaffected by the consent setting because no notification is
        opened."

        Claim: notification_consent=NONE with empty critical_flags ->
        release succeeds.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            notification_consent="NONE",
            include_second_director=True,
        )
        anchor_clock(bundle["director"])
        walked = walk_order_to_received(bundle)
        meas = normal_measurements(
            bundle["panel"]["analytes"], value=250.0,
        )
        result = resultate(
            bundle, walked["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        released = release(
            bundle, result, released_by=bundle["director2"],
        )
        assert released["status"] == "RELEASED"


# ===========================================================================
# §3.4 Side effects of release
# ===========================================================================
class TestReleaseSideEffects:

    def test_release_with_criticals_opens_pending_sms_notification(
        self, api,
    ):
        """PRD §3.4: "the system additionally creates a
        `CriticalNotification` whose `lab_result_id` references the
        result, whose `recipient_clinician_id` is cloned from the
        order's `ordering_provider_id` at this moment, whose
        `channel` is set to `SMS` (the initial channel for any new
        notification), whose `attempt_count` is 0, whose
        `first_sent_at` is set to the server clock, whose
        `ack_deadline_at` is computed as described in §3.5, and whose
        `status` is `PENDING` (the initial notification state)."

        Claim: after release with non-empty critical_flags, exactly
        one CriticalNotification exists with channel=SMS,
        status=PENDING, attempt_count=0, and recipient_clinician_id
        == order.ordering_provider_id.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, result = ctx["bundle"], ctx["result"]
        notifications = list_notifications_for_result(bundle, result["id"])
        assert len(notifications) >= 1
        n = notifications[0]
        assert_critical_notification(n)
        assert n["channel"] == "SMS"
        assert n["status"] == "PENDING"
        assert n["attempt_count"] == 0
        assert n["recipient_clinician_id"] == (
            bundle["ordering_provider"]["id"]
        )

    def test_release_with_criticals_writes_released_and_notified_events(
        self, api,
    ):
        """PRD §3.4: "Two audit events are written for this case, in
        this order: first an event with `event_type` of
        `RESULT_RELEASED`, then an event with `event_type` of
        `CRITICAL_NOTIFIED`."

        Claim: after such a release, RESULT_RELEASED precedes
        CRITICAL_NOTIFIED in the audit log.
        """
        ctx = setup_released_critical(priority="ROUTINE")
        bundle, order = ctx["bundle"], ctx["order"]
        events = list_audit_for_order(bundle, order["id"])
        rr = [e for e in events
              if e["event_type"] == "RESULT_RELEASED"]
        cn = [e for e in events
              if e["event_type"] == "CRITICAL_NOTIFIED"]
        assert rr
        assert cn
        first_rr = min(e["created_at"] for e in rr)
        first_cn = min(e["created_at"] for e in cn)
        assert first_rr <= first_cn

    def test_release_with_no_criticals_does_not_open_notification(
        self, api,
    ):
        """PRD §3.4: "When the result's `critical_flags` is empty,
        the system appends a single `ComplianceAuditEvent` with
        `event_type` of `RESULT_RELEASED` and the workflow ends with
        the result released and no notification opened."

        Claim: no CriticalNotification and no CRITICAL_NOTIFIED audit
        event are produced when critical_flags is empty.

        # difficulty: boundary_precision_check/empty_critical_flags_skips_notification_creation
        """
        ctx = setup_released_non_critical()
        bundle, order, result = (
            ctx["bundle"], ctx["order"], ctx["result"],
        )
        notifications = list_notifications_for_result(bundle, result["id"])
        assert notifications == []
        events = list_audit_for_order(
            bundle, order["id"], event_type="CRITICAL_NOTIFIED",
        )
        assert events == []
        rr = list_audit_for_order(
            bundle, order["id"], event_type="RESULT_RELEASED",
        )
        assert len(rr) >= 1


# ===========================================================================
# §2.13 Validation priority — STATE vs SoD
# difficulty: priority_pair_validation_conflict /
#             state_vs_business_safety_conflict_on_release
# ===========================================================================
class TestReleaseValidationPriority:

    def test_already_released_takes_precedence_over_sod_violation(
        self, api,
    ):
        """PRD §2.13: "The order, from highest priority to lowest, is:
        authentication header presence (`ERR_AUTH_REQUIRED`), role
        permission for the endpoint (`ERR_FORBIDDEN`), path-segment
        existence (`ERR_NOT_FOUND`), body-referenced foreign-key
        existence (`ERR_NOT_FOUND`), target-resource state validity
        for the requested transition (`ERR_INVALID_STATE`), then the
        business-safety rules in this order — segregation of duties
        (`ERR_CLIA_SOD_VIOLATION`), CLIA complexity tiering
        (`ERR_CLIA_COMPLEXITY_VIOLATION`), patient consent
        (`ERR_PATIENT_CONSENT_BLOCKED`)."

        Claim: a second release attempt on a RELEASED result with
        released_by == resulted_by triggers BOTH ERR_INVALID_STATE
        and ERR_CLIA_SOD_VIOLATION conditions; state wins.

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
        res = attempt_release(
            bundle, result,
            released_by=bundle["director"],
            actor=bundle["director2"],
        )
        validate_error(res, "ERR_INVALID_STATE")
