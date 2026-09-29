"""TypedDict shapes for every entity the biometric privacy consent API returns.

Every entity in this system carries the four common fields ``id``,
``created_at``, ``updated_at`` and ``version``; no entity is exempt.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ComplianceProgram(CommonFields):
    org_name: str
    org_type: str
    exposure_ceiling_cents: int
    posture: str
    consent_gap_count: int
    gated_asset_count: int
    open_deletion_obligation_count: int
    pra_exposure_cents: int
    inventory_completeness_pct: float


class Jurisdiction(CommonFields):
    program_id: str
    state_code: str
    statute_name: str
    private_right_of_action: str
    damages_model: str
    requires_written_release: bool
    translation_required: bool
    required_locales: List[str]
    retention_max_days: int
    notice_lead_days: int
    per_violation_negligent_cents: int
    per_violation_reckless_cents: int
    cure_period_days: int
    statutory_cap_cents: Optional[int]


class Vendor(CommonFields):
    program_id: str
    name: str
    sells_biometric_data: bool
    subprocessor_count: int
    subprocessor_disclosure_complete: bool
    deletion_sla_days: int
    attestation_status: str
    risk_score: float


class VendorContract(CommonFields):
    vendor_id: str
    prohibits_sale: bool
    restricts_disclosure: bool
    requires_deletion_on_termination: bool
    deletion_deadline_days: int
    indemnity_cap_cents: int
    effective_from: str
    compliance_score: float
    status: str
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    terminated_at: Optional[str]
    deletion_deadline_at: Optional[str]
    deletion_certificate_ref: Optional[str]


class BiometricPolicy(CommonFields):
    program_id: str
    version_label: str
    retention_days: int
    destruction_trigger: str
    release_language_included: bool
    jurisdiction_scope: List[str]
    status: str
    published_at: Optional[str]
    submitted_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    revision_count: int


class NoticePacket(CommonFields):
    program_id: str
    jurisdiction_id: str
    policy_id: str
    audience: str
    locales: List[str]
    accommodation_channel: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    published_at: Optional[str]
    consent_eligible_from: Optional[str]


class BiometricAsset(CommonFields):
    program_id: str
    jurisdiction_id: str
    vendor_id: Optional[str]
    pinned_policy_id: Optional[str]
    system_category: str
    modality: str
    subject_class: str
    template_storage_location: str
    declared_retention_days: int
    retention_basis: str
    status: str
    collection_started_at: Optional[str]
    purpose_satisfied_at: Optional[str]
    destruction_due_at: Optional[str]
    templates_destroyed_at: Optional[str]
    enrolled_subject_count: int
    consent_gap_count: int


class DataSubject(CommonFields):
    program_id: str
    jurisdiction_id: str
    subject_type: str
    external_ref: str
    preferred_locale: str
    accommodation_needed: bool
    enrollment_status: str
    active_accommodation_count: int


class ConsentRecord(CommonFields):
    data_subject_id: str
    asset_id: str
    pinned_policy_id: Optional[str]
    locale: str
    status: str
    written_release_acknowledged: bool
    signature_ref: Optional[str]
    signed_at: Optional[str]
    pinned_retention_days: Optional[int]
    record_retention_until: Optional[str]
    decline_reason: Optional[str]
    revocation_reason: Optional[str]
    solicitation_round: int


class AlternativeAccommodation(CommonFields):
    data_subject_id: str
    asset_id: str
    created_from_consent_id: Optional[str]
    method: str
    starts_at: str
    ends_at: str
    status: str
    sla_due_at: str
    sla_breached: bool
    origin: str


class IncidentCase(CommonFields):
    program_id: str
    affected_asset_ids: List[str]
    exposure_vector: str
    description: str
    discovered_at: str
    exposed_subject_count: int
    heightened_tier: str
    notification_due_at: str
    containment_status: str
    notification_status: str
    translation_locale_count: int
    gross_notice_cents: int
    regulator_surcharge_cents: int
    vendor_indemnity_credit_cents: int
    net_incident_cost_cents: int
    notified_subject_count: int
    notified_at: Optional[str]
    late_notification: bool
    exemption_basis: Optional[str]
    containment_note: Optional[str]


class ExposureAssessment(CommonFields):
    program_id: str
    jurisdiction_id: str
    incident_id: Optional[str]
    variant: str
    status: str
    negligent_unit_count: int
    reckless_unit_count: int
    base_cents: int
    notice_gap_multiplier: float
    cure_credit_pct: float
    exposure_cents: int
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    void_reason: Optional[str]


class DestructionSweepReport(TypedDict):
    swept_asset_count: int
    destroyed_template_count: int
    expired_consent_count: int
    sla_breached_accommodation_count: int
    program_posture: str
