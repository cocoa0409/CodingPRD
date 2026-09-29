"""TypedDict shapes for every resource the PRD declares.

Twelve resource types carry the full common property set of §2.4 — `id`,
`created_at`, `updated_at` and `version`. Three — checklist items, inspection
results and certification documents — are configuration or append-only evidence
rows and carry only `id` and `created_at`; `updated_at` and `version` are absent
from them, which is why those three shapes inherit `AppendOnlyRow` instead of
`CommonFields`.
"""

from typing import List, NotRequired, Optional, TypedDict


class CommonFields(TypedDict):
    """§2.4: the four system-managed properties of a mutable resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRow(TypedDict):
    """§2.4: an append-only evidence row exposes neither updated_at nor version."""

    id: str
    created_at: str


class VolumeDiscountTier(TypedDict):
    min_count: int
    pct: float


class ProgramConfig(CommonFields):
    max_age_days: int
    max_odometer_miles: int
    ineligible_title_brands: List[str]
    ineligible_prior_uses: List[str]
    base_fee_cents: int
    age_surcharge_free_years: int
    age_surcharge_cents_per_year: int
    mileage_surcharge_free_miles: int
    mileage_surcharge_cents_per_10k: int
    surcharge_cap_pct: float
    volume_discount_tiers: List[VolumeDiscountTier]
    recon_reimbursement_share: float
    recon_reimbursement_cap_cents: int
    factory_basic_months: int
    factory_basic_miles: int
    warranty_extension_months: int
    warranty_extension_miles: int
    warranty_total_cap_months: int
    warranty_total_cap_miles: int
    claim_per_claim_cap_cents: int
    claim_window_days: int
    claim_variant_volume_floor: int
    claim_ratio_probation_threshold: float
    claim_ratio_suspension_threshold: float
    probation_claim_share: float
    audit_sample_pct: float
    audit_sample_min_per_run: int
    audit_fail_suspension_count: int
    doc_retention_years: int
    required_doc_types: List[str]
    listing_required_disclosure_fields: List[str]
    listing_removal_sla_hours: int
    inspection_slot_minutes: int
    technician_buffer_minutes: int


class Dealer(CommonFields):
    name: str
    franchise_code: str
    region_code: str
    privilege_status: str
    privilege_reason: Optional[str]
    lifetime_submitted_count: int
    lifetime_activated_count: int
    window_activated_count: int
    active_certification_count: int
    approved_claim_count_lifetime: int
    approved_claim_count_window: int
    claim_ratio_variant: str
    claim_ratio_effective: float
    audit_sample_count: int
    audit_fail_count: int
    audit_fail_rate: float
    risk_score: int
    fee_billed_cents_total: int
    fee_credited_cents_total: int
    fee_balance_cents: int


class Technician(CommonFields):
    dealer_id: str
    name: str
    credential_id: str
    credential_expires_at: str
    credential_status: str
    completed_inspection_count: int


class Vehicle(CommonFields):
    vin: str
    model_year: int
    in_service_date: str
    odometer_miles: int
    title_brand: str
    prior_use: str
    owner_count: int
    cpo_state: str
    inventory_state: str
    active_certification_count: int
    certified_certification_id: Optional[str]
    decertified_at: Optional[str]
    last_history_event_type: Optional[str]
    last_history_event_at: Optional[str]


class ChecklistTemplate(CommonFields):
    code: str
    effective_from: str
    status: str
    published_at: Optional[str]
    point_count: int
    critical_item_count: int


class ChecklistItem(AppendOnlyRow):
    template_id: str
    item_code: str
    category: str
    severity: str
    pass_criteria: str
    min_measure: Optional[float]
    max_measure: Optional[float]
    reconditioning_allowed: bool
    max_reconditioning_cost_cents: int


class Inspection(CommonFields):
    dealer_id: str
    vehicle_id: str
    technician_id: str
    template_id: str
    parent_inspection_id: Optional[str]
    complaint_id: Optional[str]
    purpose: str
    status: str
    started_at: str
    slot_end_at: str
    odometer_at_inspection: int
    vehicle_age_days_at_inspection: int
    attempt_count: int
    recorded_item_count: int
    failed_critical_count: int
    failed_recon_count: int
    total_recon_cost_cents: int
    total_reimbursable_cents: int
    submitted_at: Optional[str]
    failure_reason: Optional[str]


class InspectionResult(AppendOnlyRow):
    inspection_id: str
    attempt_index: int
    item_code: str
    outcome: str
    measured_value: Optional[float]
    recorded_by_technician_id: str
    recorded_at: str


class ReconditioningItem(CommonFields):
    inspection_id: str
    item_code: str
    severity: str
    status: str
    actual_cost_cents: Optional[int]
    reimbursable_cents: int
    waiver_reason: Optional[str]
    completed_at: Optional[str]
    closed_by_user_id: Optional[str]


class Certification(CommonFields):
    dealer_id: str
    vehicle_id: str
    inspection_id: str
    certification_number: str
    status: str
    submitted_at: str
    activated_at: Optional[str]
    decertified_at: Optional[str]
    rejection_reason: Optional[str]
    decertification_reason: Optional[str]
    program_config_version: Optional[int]
    fee_surcharge_cents: int
    fee_discount_cents: int
    fee_charged_cents: int
    fee_credited_cents: int
    warranty_anchor_variant: Optional[str]
    warranty_start_date: Optional[str]
    warranty_end_date: Optional[str]
    warranty_end_miles: Optional[int]
    retention_expires_at: Optional[str]
    listing_syndicated_at: Optional[str]
    audit_sampled: bool
    audit_sample_count: int
    document_count: int
    approved_claim_count: int
    approved_claim_amount_cents: int


class CertificationDocument(AppendOnlyRow):
    certification_id: str
    doc_type: str
    reference: str
    uploaded_at: str
    retained_until: Optional[str]


class AuditSample(CommonFields):
    certification_id: str
    audit_run_id: str
    selection_rank: int
    status: str
    finding_code: Optional[str]
    reviewed_at: Optional[str]
    reviewer_user_id: Optional[str]


class AuditRunSummary(TypedDict):
    """§3.10: the audit run returns a summary object, not a persisted entity."""

    audit_run_id: str
    pool_size: int
    selected_count: int
    selected_certification_ids: List[str]


class WarrantyClaim(CommonFields):
    certification_id: str
    component_category: str
    repair_date: str
    repair_odometer_miles: int
    claimed_amount_cents: int
    approved_amount_cents: int
    dealer_ratio_snapshot_before: Optional[float]
    status: str
    denial_reason: Optional[str]
    adjudicated_at: Optional[str]


class Listing(CommonFields):
    certification_id: str
    channel: str
    price_cents: int
    disclosure_fields: List[str]
    status: str
    syndicated_at: Optional[str]
    syndicated_snapshot_version: Optional[int]
    withdrawn_at: Optional[str]
    withdrawal_reason: Optional[str]
    removal_due_at: Optional[str]


class Complaint(CommonFields):
    certification_id: str
    customer_reference: str
    category: str
    description: str
    status: str
    filed_at: str
    reinspection_deadline_at: str
    reinspection_ordered_at: Optional[str]
    resolved_at: Optional[str]


class ClockEcho(TypedDict):
    current_utc: str


class PaginationMeta(TypedDict):
    limit: int
    offset: int
    total_count: int
    has_more: bool
    api_request_id: NotRequired[str]
    api_request_timestamp: NotRequired[str]
