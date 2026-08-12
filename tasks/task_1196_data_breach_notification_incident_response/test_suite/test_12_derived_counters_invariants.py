"""Derived counters and compensating invariants (difficulty rule
compensating_invariant; corner cross-cutting-complexity-layers)."""
from test_helpers import (
    TEST_USERS,
    create_affected_subject_payload,
    create_incident,
    create_incident_confirmed,
    create_issued_offer,
    get_success_data,
    make_affected_subject_headers,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
DA = TEST_USERS["data_analyst_headers"]


class TestNotifiedPlusPendingEqualsAffected:
    def test_counters_reconcile_after_verify_and_exclude(self, api):
        """PRD §2.9: "`total_affected_subjects` is the count of
        `AffectedSubject` rows whose status is `IDENTIFIED` or `VERIFIED`";
        "`total_pending_subjects` is the count of `AffectedSubject` rows
        whose status is `IDENTIFIED`, `VERIFIED`, or `NOTICE_QUEUED`";
        "`total_notified_subjects` is the count of `AffectedSubject` rows
        whose status is `NOTIFIED`." EXCLUDED rows count toward none.

        With 2 VERIFIED + 1 EXCLUDED the counters must satisfy
        notified + pending == affected (here 0 + 2 == 2).

        Design: Difficulty/compensating_invariant/notified_plus_pending_equals_affected
        """
        inc = create_incident()
        s1 = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S1"),
                DA,
            ),
            expected_status=201,
        )
        s2 = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S2"),
                DA,
            ),
            expected_status=201,
        )
        s3 = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S3"),
                DA,
            ),
            expected_status=201,
        )
        api.verify_affected_subject(inc["id"], s1["id"], DA)
        api.verify_affected_subject(inc["id"], s2["id"], DA)
        api.exclude_affected_subject(inc["id"], s3["id"], DA)

        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["total_affected_subjects"] == 2
        assert after["total_pending_subjects"] == 2
        assert after["total_notified_subjects"] == 0
        assert (
            after["total_notified_subjects"] + after["total_pending_subjects"]
            == after["total_affected_subjects"]
        )


class TestCreditMonitoringCounters:
    def test_enrolled_plus_declined_reconciles_with_offered(self, api):
        """PRD §2.9: "`credit_monitoring_offered` is the count of
        `AffectedSubject` rows whose `credit_monitoring_status` is anything
        other than `NOT_OFFERED`"; `credit_monitoring_enrolled` counts
        `ENROLLED`; `credit_monitoring_declined` counts `DECLINED`.

        PRD §3.9: cancel "moves the offer to `CANCELLED`, returns the
        subject's `credit_monitoring_status` to `NOT_OFFERED`, and recomputes
        `credit_monitoring_offered`."

        After 3 issues, 1 redeem, 1 decline, 1 cancel: enrolled=1,
        declined=1, offered=2 (the cancelled subject returns to NOT_OFFERED).

        Design: Difficulty/compensating_invariant/credit_monitoring_enrolled_plus_declined_plus_pending_equals_offered
        """
        ctx = create_incident_confirmed(subject_count=3)
        inc = ctx["incident"]
        s1, s2, s3 = ctx["subjects"]

        off1 = create_issued_offer(inc, s1)
        off2 = create_issued_offer(inc, s2)
        off3 = create_issued_offer(inc, s3)

        api.redeem_credit_monitoring_offer(
            inc["id"], off1["id"], make_affected_subject_headers(s1["id"])
        )
        api.decline_credit_monitoring_offer(
            inc["id"], off2["id"], make_affected_subject_headers(s2["id"])
        )
        api.cancel_credit_monitoring_offer(inc["id"], off3["id"], PC)

        after = get_success_data(api.get_incident(inc["id"], IC))
        assert after["credit_monitoring_enrolled"] == 1
        assert after["credit_monitoring_declined"] == 1
        assert after["credit_monitoring_offered"] == 2


class TestDerivedFieldReconciliationOnExclude:
    def test_exclude_decrements_total_affected_subjects(self, api):
        """PRD §3.4: "Exclusion recomputes `total_affected_subjects`,
        `total_pending_subjects`, and `subjects_in_jurisdiction` on every
        linked `JurisdictionEvaluation`, and increments the incident's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_subject_exclude
        """
        inc = create_incident()
        s = validate_success(
            api.create_affected_subject(
                inc["id"],
                create_affected_subject_payload(external_subject_ref="S1"),
                DA,
            ),
            expected_status=201,
        )
        pre = get_success_data(api.get_incident(inc["id"], IC))
        assert pre["total_affected_subjects"] == 1
        api.exclude_affected_subject(inc["id"], s["id"], DA)
        post = get_success_data(api.get_incident(inc["id"], IC))
        assert post["total_affected_subjects"] == 0
