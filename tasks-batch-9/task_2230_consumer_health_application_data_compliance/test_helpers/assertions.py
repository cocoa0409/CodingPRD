"""Shape assertions: every resource read must carry its full documented field set."""

from __future__ import annotations

from typing import Any, Iterable

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AGE_BANDS,
    AGREEMENT_COMPLIANCES,
    AGREEMENT_STATES,
    APPLICABILITY_STATUSES,
    ACTIVITY_KINDS,
    ASSESSMENT_STATES,
    BREACH_SCOPES,
    BREACH_STATES,
    CAMPAIGN_STATES,
    CHD_CLASSIFICATIONS,
    CONSENT_AXIS_STATES,
    DISCLOSURE_SPECIFICITIES,
    ELEMENT_STATUSES,
    ENTITY_STATUS_CLAIMS,
    FACILITY_KINDS,
    HEALTH_SIGNAL_KINDS,
    MAPPING_STATUSES,
    POLICY_COMPLIANCE_STATES,
    POLICY_STATES,
    PROHIBITION_RULES,
    PROTECTION_STATES,
    PURPOSE_KINDS,
    RECORD_STATES,
    REGULATED_SCOPES,
    REQUEST_KINDS,
    REQUEST_STATES,
    RISK_TIERS,
    SALE_AXIS_STATES,
    SECURITY_PROGRAM_STATES,
    SOURCE_KINDS,
    SPECIFICITY_MODES,
    SRA_STATES,
    STATE_CODES,
    SUBMITTED_CHANNELS,
    TASK_STATES,
    VENDOR_KINDS,
)


def _assert_fields_present(data: dict[str, Any], fields: Iterable[str], label: str) -> None:
    missing = [field for field in fields if field not in data]
    assert not missing, f"{label} is missing documented field(s): {missing}"


def _assert_common_fields(data: dict[str, Any], label: str) -> None:
    """Every resource in this system carries id, created_at, updated_at and version."""
    _assert_fields_present(data, ("id", "created_at", "updated_at", "version"), label)
    assert is_valid_uuid(data["id"]), f"{label}.id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"{label}.created_at is not ISO 8601: {data['created_at']!r}"
    assert is_iso8601_timestamp(
        data["updated_at"]
    ), f"{label}.updated_at is not ISO 8601: {data['updated_at']!r}"
    assert isinstance(data["version"], int), f"{label}.version is not an integer"
    assert data["version"] >= 1, f"{label}.version must start at or above 1"


def _assert_enum(data: dict[str, Any], field: str, allowed: Iterable[str], label: str) -> None:
    value = data.get(field)
    if value is None:
        return
    assert value in tuple(allowed), f"{label}.{field} has undocumented value {value!r}"


def assert_app_product(data: dict[str, Any]) -> None:
    """Assert an app product read carries its inputs and derived compliance counters."""
    _assert_common_fields(data, "AppProduct")
    _assert_fields_present(
        data,
        (
            "product_name",
            "company_legal_name",
            "primary_state_code",
            "consumer_count",
            "annual_revenue_cents",
            "hipaa_covered_transaction_ratio",
            "small_business_flag",
            "applicability_status",
            "regulated_scope",
            "active_element_count",
            "regulated_element_count",
            "compliance_deadline_date",
            "active_share_consent_count",
            "exposure_cents",
            "policy_compliance_state",
            "security_program_state",
        ),
        "AppProduct",
    )
    _assert_enum(data, "primary_state_code", STATE_CODES, "AppProduct")
    _assert_enum(data, "applicability_status", APPLICABILITY_STATUSES, "AppProduct")
    _assert_enum(data, "regulated_scope", REGULATED_SCOPES, "AppProduct")
    _assert_enum(data, "policy_compliance_state", POLICY_COMPLIANCE_STATES, "AppProduct")
    _assert_enum(data, "security_program_state", SECURITY_PROGRAM_STATES, "AppProduct")
    assert isinstance(data["small_business_flag"], bool)
    assert isinstance(data["exposure_cents"], int)


def assert_applicability_assessment(data: dict[str, Any]) -> None:
    """Assert an applicability assessment read carries its determination fields."""
    _assert_common_fields(data, "ApplicabilityAssessment")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "entity_status_claim",
            "analyst_note",
            "determination",
            "regulated_element_count_snapshot",
            "active_element_count_snapshot",
            "regulated_scope",
            "compliance_deadline_date",
            "state",
            "revision_count",
            "submitted_by_user_id",
            "approved_by_user_id",
            "return_reason",
        ),
        "ApplicabilityAssessment",
    )
    _assert_enum(data, "entity_status_claim", ENTITY_STATUS_CLAIMS, "ApplicabilityAssessment")
    _assert_enum(data, "state", ASSESSMENT_STATES, "ApplicabilityAssessment")
    _assert_enum(data, "regulated_scope", REGULATED_SCOPES, "ApplicabilityAssessment")


def assert_data_element(data: dict[str, Any]) -> None:
    """Assert a data element read carries its stored inputs and its classification."""
    _assert_common_fields(data, "DataElement")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "element_key",
            "display_name",
            "source_kind",
            "health_signal_kind",
            "derived_from_element_id",
            "hipaa_flow_only",
            "inference_depth",
            "chd_classification",
            "status",
            "retired_reason",
        ),
        "DataElement",
    )
    _assert_enum(data, "source_kind", SOURCE_KINDS, "DataElement")
    _assert_enum(data, "health_signal_kind", HEALTH_SIGNAL_KINDS, "DataElement")
    _assert_enum(data, "chd_classification", CHD_CLASSIFICATIONS, "DataElement")
    _assert_enum(data, "status", ELEMENT_STATUSES, "DataElement")
    assert isinstance(data["inference_depth"], int)
    assert isinstance(data["hipaa_flow_only"], bool)


def assert_processing_purpose(data: dict[str, Any]) -> None:
    """Assert a processing purpose read carries its consent-axis derivations."""
    _assert_common_fields(data, "ProcessingPurpose")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "purpose_key",
            "description_text",
            "purpose_kind",
            "activity_kind",
            "consent_axis",
            "requires_separate_consent",
            "third_party_disclosure_required",
        ),
        "ProcessingPurpose",
    )
    _assert_enum(data, "purpose_kind", PURPOSE_KINDS, "ProcessingPurpose")
    _assert_enum(data, "activity_kind", ACTIVITY_KINDS, "ProcessingPurpose")
    _assert_enum(data, "consent_axis", ACTIVITY_KINDS, "ProcessingPurpose")
    assert isinstance(data["requires_separate_consent"], bool)
    assert isinstance(data["third_party_disclosure_required"], bool)


def assert_element_purpose_mapping(data: dict[str, Any]) -> None:
    """Assert a mapping read carries both legs, its status and its regulated flag."""
    _assert_common_fields(data, "ElementPurposeMapping")
    _assert_fields_present(
        data,
        (
            "data_element_id",
            "processing_purpose_id",
            "vendor_id",
            "disclosure_specificity",
            "status",
            "suspension_reason",
            "regulated_flag",
        ),
        "ElementPurposeMapping",
    )
    _assert_enum(
        data, "disclosure_specificity", DISCLOSURE_SPECIFICITIES, "ElementPurposeMapping"
    )
    _assert_enum(data, "status", MAPPING_STATUSES, "ElementPurposeMapping")
    assert isinstance(data["regulated_flag"], bool)


def assert_consumer(data: dict[str, Any]) -> None:
    """Assert a consumer read carries its registration inputs and issued token."""
    _assert_common_fields(data, "Consumer")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "external_ref",
            "residency_state_code",
            "age_band",
            "verification_token",
            "deletion_completed_count",
        ),
        "Consumer",
    )
    _assert_enum(data, "residency_state_code", STATE_CODES, "Consumer")
    _assert_enum(data, "age_band", AGE_BANDS, "Consumer")
    assert isinstance(data["deletion_completed_count"], int)


def assert_consent_record(data: dict[str, Any]) -> None:
    """Assert a consent record read carries all three axes and their instants."""
    _assert_common_fields(data, "ConsentRecord")
    _assert_fields_present(
        data,
        (
            "consumer_id",
            "collection_state",
            "sharing_state",
            "sale_state",
            "record_state",
            "collection_granted_at",
            "sharing_granted_at",
            "sale_authorized_at",
            "last_withdrawn_axis",
            "last_withdrawn_at",
            "processing_halt_deadline_at",
        ),
        "ConsentRecord",
    )
    _assert_enum(data, "collection_state", CONSENT_AXIS_STATES, "ConsentRecord")
    _assert_enum(data, "sharing_state", CONSENT_AXIS_STATES, "ConsentRecord")
    _assert_enum(data, "sale_state", SALE_AXIS_STATES, "ConsentRecord")
    _assert_enum(data, "record_state", RECORD_STATES, "ConsentRecord")
    _assert_enum(data, "last_withdrawn_axis", ACTIVITY_KINDS, "ConsentRecord")


def assert_privacy_policy_version(data: dict[str, Any]) -> None:
    """Assert a policy version read carries its counts, score and lifecycle stamps."""
    _assert_common_fields(data, "PrivacyPolicyVersion")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "applicability_assessment_id",
            "version_label",
            "specificity_mode",
            "disclosed_category_count",
            "disclosed_purpose_count",
            "disclosed_third_party_count",
            "named_third_party_count",
            "effective_from",
            "effective_to",
            "completeness_score",
            "gap_count",
            "state",
            "authored_by_user_id",
            "published_by_user_id",
        ),
        "PrivacyPolicyVersion",
    )
    _assert_enum(data, "specificity_mode", SPECIFICITY_MODES, "PrivacyPolicyVersion")
    _assert_enum(data, "state", POLICY_STATES, "PrivacyPolicyVersion")
    assert isinstance(data["gap_count"], int)
    assert isinstance(data["completeness_score"], (int, float))


def assert_consumer_request(data: dict[str, Any]) -> None:
    """Assert a rights request read carries its verification and deadline fields."""
    _assert_common_fields(data, "ConsumerRequest")
    _assert_fields_present(
        data,
        (
            "consumer_id",
            "request_kind",
            "submitted_channel",
            "received_at",
            "state",
            "verification_rounds_used",
            "verification_window_ends_at",
            "verified_at",
            "extension_granted",
            "response_deadline_at",
            "outstanding_task_count",
            "denial_reason",
        ),
        "ConsumerRequest",
    )
    _assert_enum(data, "request_kind", REQUEST_KINDS, "ConsumerRequest")
    _assert_enum(data, "submitted_channel", SUBMITTED_CHANNELS, "ConsumerRequest")
    _assert_enum(data, "state", REQUEST_STATES, "ConsumerRequest")
    assert isinstance(data["extension_granted"], bool)
    assert isinstance(data["verification_rounds_used"], int)
    assert isinstance(data["outstanding_task_count"], int)


def assert_deletion_task(data: dict[str, Any]) -> None:
    """Assert a deletion task read carries its hop distance and attempt bookkeeping."""
    _assert_common_fields(data, "DeletionTask")
    _assert_fields_present(
        data,
        (
            "consumer_request_id",
            "vendor_id",
            "hop_distance",
            "state",
            "attempt_count",
            "due_at",
            "confirmed_at",
            "failure_reason",
        ),
        "DeletionTask",
    )
    _assert_enum(data, "state", TASK_STATES, "DeletionTask")
    assert isinstance(data["hop_distance"], int)
    assert isinstance(data["attempt_count"], int)


def assert_vendor(data: dict[str, Any]) -> None:
    """Assert a vendor read carries its contract clauses and agreement posture."""
    _assert_common_fields(data, "Vendor")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "vendor_name",
            "vendor_kind",
            "subprocessor_of_id",
            "flow_down_clause",
            "audit_rights_clause",
            "sale_authorization_clause",
            "deletion_sla_days",
            "agreement_state",
            "agreement_compliance",
            "executed_at",
            "terminated_at",
        ),
        "Vendor",
    )
    _assert_enum(data, "vendor_kind", VENDOR_KINDS, "Vendor")
    _assert_enum(data, "agreement_state", AGREEMENT_STATES, "Vendor")
    _assert_enum(data, "agreement_compliance", AGREEMENT_COMPLIANCES, "Vendor")
    assert isinstance(data["flow_down_clause"], bool)
    assert isinstance(data["audit_rights_clause"], bool)
    assert isinstance(data["sale_authorization_clause"], bool)
    assert isinstance(data["deletion_sla_days"], int)


def assert_geofence_zone(data: dict[str, Any]) -> None:
    """Assert a zone read carries its derived prohibition rule and standoff minimum."""
    _assert_common_fields(data, "GeofenceZone")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "zone_name",
            "state_code",
            "facility_kind",
            "center_label",
            "radius_meters",
            "prohibition_rule",
            "min_standoff_meters",
            "last_campaign_activated_at",
        ),
        "GeofenceZone",
    )
    _assert_enum(data, "state_code", STATE_CODES, "GeofenceZone")
    _assert_enum(data, "facility_kind", FACILITY_KINDS, "GeofenceZone")
    _assert_enum(data, "prohibition_rule", PROHIBITION_RULES, "GeofenceZone")
    assert isinstance(data["radius_meters"], int)


def assert_geofence_campaign(data: dict[str, Any]) -> None:
    """Assert a campaign read carries its window, computed standoff and state."""
    _assert_common_fields(data, "GeofenceCampaign")
    _assert_fields_present(
        data,
        (
            "geofence_zone_id",
            "processing_purpose_id",
            "campaign_name",
            "target_radius_meters",
            "distance_to_zone_center_meters",
            "window_start_at",
            "window_end_at",
            "standoff_meters",
            "state",
            "pause_reason",
        ),
        "GeofenceCampaign",
    )
    _assert_enum(data, "state", CAMPAIGN_STATES, "GeofenceCampaign")
    assert isinstance(data["standoff_meters"], int)


def assert_breach_incident(data: dict[str, Any]) -> None:
    """Assert a breach read carries both rule deadlines and its exposure figure."""
    _assert_common_fields(data, "BreachIncident")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "incident_label",
            "discovered_at",
            "breach_scope",
            "protection_state",
            "affected_consumer_count",
            "affected_state_max_count",
            "media_notice_sent",
            "state",
            "health_rule_deadline_at",
            "general_rule_deadline_at",
            "governing_deadline_at",
            "media_notice_required",
            "notified_at",
            "exposure_contribution_cents",
        ),
        "BreachIncident",
    )
    _assert_enum(data, "breach_scope", BREACH_SCOPES, "BreachIncident")
    _assert_enum(data, "protection_state", PROTECTION_STATES, "BreachIncident")
    _assert_enum(data, "state", BREACH_STATES, "BreachIncident")
    assert isinstance(data["media_notice_required"], bool)
    assert isinstance(data["media_notice_sent"], bool)
    assert isinstance(data["exposure_contribution_cents"], int)


def assert_security_risk_assessment(data: dict[str, Any]) -> None:
    """Assert a security risk assessment read carries its score and banded tier."""
    _assert_common_fields(data, "SecurityRiskAssessment")
    _assert_fields_present(
        data,
        (
            "app_product_id",
            "assessment_label",
            "admin_control_score",
            "technical_control_score",
            "physical_control_score",
            "vendor_oversight_score",
            "documented_gap_count",
            "remediation_plan_present",
            "residual_risk_score",
            "risk_tier",
            "state",
            "finalized_at",
        ),
        "SecurityRiskAssessment",
    )
    _assert_enum(data, "risk_tier", RISK_TIERS, "SecurityRiskAssessment")
    _assert_enum(data, "state", SRA_STATES, "SecurityRiskAssessment")
    assert isinstance(data["remediation_plan_present"], bool)
    assert isinstance(data["residual_risk_score"], (int, float))


def assert_compliance_summary(data: dict[str, Any]) -> None:
    """Assert the computed compliance summary carries every documented counter."""
    _assert_fields_present(
        data,
        (
            "applicability_status",
            "regulated_scope",
            "active_element_count",
            "regulated_element_count",
            "active_share_consent_count",
            "policy_compliance_state",
            "security_program_state",
            "exposure_cents",
            "open_request_count",
            "outstanding_deletion_task_count",
        ),
        "ComplianceSummary",
    )
    _assert_enum(data, "applicability_status", APPLICABILITY_STATUSES, "ComplianceSummary")
    _assert_enum(data, "regulated_scope", REGULATED_SCOPES, "ComplianceSummary")
    _assert_enum(data, "policy_compliance_state", POLICY_COMPLIANCE_STATES, "ComplianceSummary")
    _assert_enum(data, "security_program_state", SECURITY_PROGRAM_STATES, "ComplianceSummary")
