"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AffectedSubjectStatus,
    CreditMonitoringSubjectStatus,
    DeadlineKind,
    EvidenceItemStatus,
    EvidenceType,
    ForensicScopeStatus,
    InvestigationStatus,
    JurisdictionEvaluationStatus,
    MailingBatchStatus,
    CreditMonitoringOfferStatus,
    CallCenterPlanStatus,
    NoticeStatus,
    NotificationStatus,
    RegulatorSubmissionStatus,
    RemediationActionCategory,
    RemediationActionStatus,
    RemediationStatus,
    Severity,
    SourceChannel,
    SubmissionChannel,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be int >= 1"
    )


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["source_channel"] in [c.value for c in SourceChannel]
    assert data["severity"] in [s.value for s in Severity]
    assert data["investigation_status"] in [s.value for s in InvestigationStatus]
    assert data["notification_status"] in [s.value for s in NotificationStatus]
    assert data["remediation_status"] in [s.value for s in RemediationStatus]
    assert 0 <= data["risk_score_conservative"] <= 100
    assert 0 <= data["risk_score_likelihood_adjusted"] <= 100
    assert data["total_affected_subjects"] >= 0
    assert data["total_notified_subjects"] >= 0
    assert data["total_pending_subjects"] >= 0
    assert data["credit_monitoring_offered"] >= 0
    assert data["credit_monitoring_enrolled"] >= 0
    assert data["credit_monitoring_declined"] >= 0


def assert_incident_invariants(data: dict):
    """Cross-field derived counters stay internally consistent (PRD §2.9)."""
    tas = data["total_affected_subjects"]
    tns = data["total_notified_subjects"]
    tps = data["total_pending_subjects"]
    assert tas >= 0 and tns >= 0 and tps >= 0
    # pending counts IDENTIFIED|VERIFIED|NOTICE_QUEUED; notified counts NOTIFIED.
    # Both come from the same non-EXCLUDED universe so neither can exceed
    # tas + tns (worst case: pending=tas when nothing notified yet).
    assert tps <= tas, "pending subjects cannot exceed affected subjects"
    assert data["credit_monitoring_enrolled"] <= data["credit_monitoring_offered"]
    assert data["credit_monitoring_declined"] <= data["credit_monitoring_offered"]


def assert_forensic_scope(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ForensicScopeStatus]
    assert isinstance(data["systems_in_scope"], list)
    assert isinstance(data["data_elements_at_risk"], list)
    assert isinstance(data["exfiltration_likelihood_pct"], int)
    assert 0 <= data["exfiltration_likelihood_pct"] <= 100


def assert_evidence_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in EvidenceItemStatus]
    assert data["evidence_type"] in [t.value for t in EvidenceType]
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["collected_by_user_id"], str)


def assert_custody_log(data: dict):
    # common_fields=false: only id + created_at; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "custody log must omit updated_at"
    assert "version" not in data, "custody log must omit version"
    assert isinstance(data["evidence_item_id"], str)
    assert isinstance(data["custodian_user_id"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))


def assert_affected_subject(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AffectedSubjectStatus]
    assert data["credit_monitoring_status"] in [
        s.value for s in CreditMonitoringSubjectStatus
    ]
    assert isinstance(data["external_subject_ref"], str)
    assert isinstance(data["residence_state_code"], str)
    assert isinstance(data["data_elements_exposed"], list)
    assert isinstance(data["record_count"], int)


def assert_jurisdiction_evaluation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in JurisdictionEvaluationStatus]
    assert data["deadline_kind"] in [d.value for d in DeadlineKind]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["statute_reference"], str)
    assert isinstance(data["record_count_threshold"], int)
    assert isinstance(data["deadline_days"], int)
    assert isinstance(data["requires_ag_notification"], bool)
    assert isinstance(data["requires_credit_agencies"], bool)
    assert isinstance(data["subjects_in_jurisdiction"], int)
    assert isinstance(data["notification_required"], bool)


def assert_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert isinstance(data["body_text"], str)
    assert isinstance(data["version_label"], int) and data["version_label"] >= 1
    assert isinstance(data["jurisdiction_evaluation_id"], str)


def assert_mailing_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in MailingBatchStatus]
    assert isinstance(data["vendor_code"], str)
    assert isinstance(data["recipient_count"], int)


def assert_credit_monitoring_offer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CreditMonitoringOfferStatus]
    assert data["term_months"] in (12, 24)
    assert data["unit_cost_cents"] > 0
    assert isinstance(data["offer_code"], str) and data["offer_code"]


def assert_call_center_staffing_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CallCenterPlanStatus]
    assert isinstance(data["seats_required"], int)
    assert data["seats_required"] >= 2
    assert isinstance(data["languages_supported"], list)


def assert_regulator_submission(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RegulatorSubmissionStatus]
    assert data["submission_channel"] in [c.value for c in SubmissionChannel]


def assert_remediation_action(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RemediationActionStatus]
    assert data["category"] in [c.value for c in RemediationActionCategory]
    assert isinstance(data["owner_user_id"], str)


def assert_cost_summary(data: dict):
    assert isinstance(data["credit_monitoring_cost_cents"], int)
    assert isinstance(data["offer_count"], int)
    assert data["credit_monitoring_cost_cents"] >= 0
    assert data["offer_count"] >= 0
