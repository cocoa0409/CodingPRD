"""TypedDict shapes for every resource exposed by the consumer-health compliance API."""

from __future__ import annotations

from typing import Any, TypedDict


class AppProduct(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    product_name: str
    company_legal_name: str
    primary_state_code: str
    consumer_count: int
    annual_revenue_cents: int
    hipaa_covered_transaction_ratio: float
    small_business_flag: bool
    applicability_status: str
    regulated_scope: str
    active_element_count: int
    regulated_element_count: int
    compliance_deadline_date: str | None
    active_share_consent_count: int
    exposure_cents: int
    policy_compliance_state: str
    security_program_state: str


class ApplicabilityAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    entity_status_claim: str
    analyst_note: str | None
    determination: str | None
    regulated_element_count_snapshot: int
    active_element_count_snapshot: int
    regulated_scope: str | None
    compliance_deadline_date: str | None
    state: str
    revision_count: int
    submitted_by_user_id: str | None
    approved_by_user_id: str | None
    return_reason: str | None


class DataElement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    element_key: str
    display_name: str
    source_kind: str
    health_signal_kind: str
    derived_from_element_id: str | None
    hipaa_flow_only: bool
    inference_depth: int
    chd_classification: str
    status: str
    retired_reason: str | None


class ProcessingPurpose(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    purpose_key: str
    description_text: str
    purpose_kind: str
    activity_kind: str
    consent_axis: str
    requires_separate_consent: bool
    third_party_disclosure_required: bool


class ElementPurposeMapping(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    data_element_id: str
    processing_purpose_id: str
    vendor_id: str | None
    disclosure_specificity: str
    status: str
    suspension_reason: str | None
    regulated_flag: bool


class Consumer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    external_ref: str
    residency_state_code: str
    age_band: str
    verification_token: str
    deletion_completed_count: int


class ConsentRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    consumer_id: str
    collection_state: str
    sharing_state: str
    sale_state: str
    record_state: str
    collection_granted_at: str | None
    sharing_granted_at: str | None
    sale_authorized_at: str | None
    last_withdrawn_axis: str | None
    last_withdrawn_at: str | None
    processing_halt_deadline_at: str | None


class PrivacyPolicyVersion(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    applicability_assessment_id: str
    version_label: str
    specificity_mode: str
    disclosed_category_count: int
    disclosed_purpose_count: int
    disclosed_third_party_count: int
    named_third_party_count: int
    effective_from: str
    effective_to: str | None
    completeness_score: float
    gap_count: int
    state: str
    authored_by_user_id: str | None
    published_by_user_id: str | None


class ConsumerRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    consumer_id: str
    request_kind: str
    submitted_channel: str
    received_at: str
    state: str
    verification_rounds_used: int
    verification_window_ends_at: str | None
    verified_at: str | None
    extension_granted: bool
    response_deadline_at: str | None
    outstanding_task_count: int
    denial_reason: str | None


class DeletionTask(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    consumer_request_id: str
    vendor_id: str
    hop_distance: int
    state: str
    attempt_count: int
    due_at: str | None
    confirmed_at: str | None
    failure_reason: str | None


class Vendor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    vendor_name: str
    vendor_kind: str
    subprocessor_of_id: str | None
    flow_down_clause: bool
    audit_rights_clause: bool
    sale_authorization_clause: bool
    deletion_sla_days: int
    agreement_state: str
    agreement_compliance: str
    executed_at: str | None
    terminated_at: str | None


class GeofenceZone(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    zone_name: str
    state_code: str
    facility_kind: str
    center_label: str
    radius_meters: int
    prohibition_rule: str
    min_standoff_meters: int
    last_campaign_activated_at: str | None


class GeofenceCampaign(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    geofence_zone_id: str
    processing_purpose_id: str
    campaign_name: str
    target_radius_meters: int
    distance_to_zone_center_meters: int
    window_start_at: str
    window_end_at: str
    standoff_meters: int
    state: str
    pause_reason: str | None


class BreachIncident(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    incident_label: str
    discovered_at: str
    breach_scope: str
    protection_state: str
    affected_consumer_count: int
    affected_state_max_count: int
    media_notice_sent: bool
    state: str
    health_rule_deadline_at: str | None
    general_rule_deadline_at: str | None
    governing_deadline_at: str | None
    media_notice_required: bool
    notified_at: str | None
    exposure_contribution_cents: int


class SecurityRiskAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    app_product_id: str
    assessment_label: str
    admin_control_score: int
    technical_control_score: int
    physical_control_score: int
    vendor_oversight_score: int
    documented_gap_count: int
    remediation_plan_present: bool
    residual_risk_score: float
    risk_tier: str
    state: str
    finalized_at: str | None


class ComplianceSummary(TypedDict, total=False):
    """Computed read returned by the product compliance-summary endpoint."""

    app_product_id: str
    applicability_status: str
    regulated_scope: str
    active_element_count: int
    regulated_element_count: int
    active_share_consent_count: int
    policy_compliance_state: str
    security_program_state: str
    exposure_cents: int
    open_request_count: int
    outstanding_deletion_task_count: int


Payload = dict[str, Any]
