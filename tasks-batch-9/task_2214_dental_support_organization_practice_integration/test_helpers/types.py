"""Domain types for the DSO Practice Integration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    DSO_DEAL_COUNSEL = "DsoDealCounsel"
    DSO_INTEGRATION_LEAD = "DsoIntegrationLead"
    DSO_FINANCE_CONTROLLER = "DsoFinanceController"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    DENTIST = "Dentist"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class AffiliationStatus(str, Enum):
    DRAFT = "DRAFT"
    DILIGENCE = "DILIGENCE"
    SIGNED = "SIGNED"
    CLOSED = "CLOSED"


class EarnoutMeasurementState(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class PracticeAffiliationStatus(str, Enum):
    PENDING = "PENDING"
    AFFILIATED = "AFFILIATED"


class IntegrationPosture(str, Enum):
    PRE_CLOSE = "PRE_CLOSE"
    FROZEN = "FROZEN"
    RESTRICTED = "RESTRICTED"
    STABILIZING = "STABILIZING"
    INTEGRATED = "INTEGRATED"


class StaffingModelState(str, Enum):
    LEGACY = "LEGACY"
    STANDARDIZED = "STANDARDIZED"


class DoctorSpecialty(str, Enum):
    GENERAL = "GENERAL"
    ENDODONTICS = "ENDODONTICS"
    ORTHODONTICS = "ORTHODONTICS"
    ORAL_SURGERY = "ORAL_SURGERY"
    PERIODONTICS = "PERIODONTICS"


class EmploymentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SEPARATED = "SEPARATED"


class CredentialingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RecordsCustodyState(str, Enum):
    HELD_BY_PRACTICE = "HELD_BY_PRACTICE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TRANSFERRED = "TRANSFERRED"


class NonCompeteEnforcementState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    ENFORCED = "ENFORCED"


class CompModel(str, Enum):
    MONTHLY_MIN_GUARANTEE = "MONTHLY_MIN_GUARANTEE"
    ANNUAL_TRUE_UP = "ANNUAL_TRUE_UP"


class SeparationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    TERMINATED_FOR_CAUSE = "TERMINATED_FOR_CAUSE"
    NON_RENEWAL = "NON_RENEWAL"


class ServiceAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    EFFECTIVE = "EFFECTIVE"


class FeeModel(str, Enum):
    PCT_OF_COLLECTIONS = "PCT_OF_COLLECTIONS"
    FIXED_MONTHLY = "FIXED_MONTHLY"


class ServiceDomain(str, Enum):
    BILLING = "BILLING"
    HR = "HR"
    PROCUREMENT = "PROCUREMENT"
    IT = "IT"
    MARKETING = "MARKETING"
    FACILITIES = "FACILITIES"
    CREDENTIALING = "CREDENTIALING"
    TREATMENT_PLANNING = "TREATMENT_PLANNING"
    CLINICAL_SUPERVISION = "CLINICAL_SUPERVISION"
    DIAGNOSIS = "DIAGNOSIS"


class MigrationBatchStatus(str, Enum):
    STAGED = "STAGED"
    SCHEDULED = "SCHEDULED"
    VALIDATED = "VALIDATED"
    QUARANTINED = "QUARANTINED"
    RECONCILED = "RECONCILED"
    HELD = "HELD"
    SUPERSEDED = "SUPERSEDED"


class PayerContractTransitionState(str, Enum):
    LEGACY = "LEGACY"
    PENDING_CREDENTIALING = "PENDING_CREDENTIALING"
    DSO_SCHEDULE_ACTIVE = "DSO_SCHEDULE_ACTIVE"


class PayerEnrollmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"


class EnrollmentDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class EarnoutTrancheStatus(str, Enum):
    PROJECTED = "PROJECTED"
    RESERVED = "RESERVED"
    SETTLED = "SETTLED"
    CLAWED_BACK = "CLAWED_BACK"


class EarnoutVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class VendorCategory(str, Enum):
    SUPPLY = "SUPPLY"
    LAB = "LAB"


class SupplyPreferenceExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class VendorConsolidationStatus(str, Enum):
    PLANNED = "PLANNED"
    FINALIZED = "FINALIZED"


class ClinicalQualityReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_NO_FINDINGS = "CLOSED_NO_FINDINGS"
    CLOSED_WITH_PLAN = "CLOSED_WITH_PLAN"
    ESCALATED = "ESCALATED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------


class Affiliation(TypedDict):
    id: str
    seller_group_name: str
    purchase_price_cents: int
    earnout_pool_cents: int
    baseline_ebitda_cents: int
    baseline_net_collections_cents: int
    post_close_doctor_term_months: int
    status: str
    repricing_round: int
    practice_count: int
    earnout_reserved_cents: int
    earnout_settled_cents: int
    earnout_unallocated_cents: int
    earnout_measurement_state: str
    diligence_opened_at: Optional[str]
    signed_date: Optional[str]
    close_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionVendor(TypedDict):
    id: str
    name: str
    max_concurrent_windows: int
    active_window_count: int
    created_at: str
    updated_at: str
    version: int


class Practice(TypedDict):
    id: str
    affiliation_id: str
    conversion_vendor_id: str
    name: str
    state_code: str
    charts_total_expected: int
    affiliation_status: str
    integration_posture: str
    staffing_model_state: str
    fte_hygiene_ratio_bps: Optional[int]
    active_doctor_count: int
    charts_migrated_count: int
    pending_credentialing_count: int
    denied_enrollment_count: int
    quarantined_batch_count: int
    clinical_coverage_gap: bool
    created_at: str
    updated_at: str
    version: int


class Doctor(TypedDict):
    id: str
    full_name: str
    npi: str
    license_number: str
    license_state: str
    specialty: str
    is_seller_owner: bool
    created_at: str
    updated_at: str
    version: int


class DoctorEmployment(TypedDict):
    id: str
    practice_id: str
    doctor_id: str
    base_salary_monthly_cents: int
    collections_pct_bps: int
    comp_model: str
    legacy_annual_comp_cents: int
    post_close_term_months: int
    non_compete_months: int
    non_compete_radius_miles: int
    employment_status: str
    offer_accepted: bool
    credentialing_status: str
    records_custody_state: str
    non_compete_enforcement_state: str
    is_harmonized: bool
    harmonized_annual_comp_cents: Optional[int]
    harmonization_delta_cents: Optional[int]
    comp_effective_date: Optional[str]
    non_compete_end_date: Optional[str]
    separation_date: Optional[str]
    separation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict):
    id: str
    practice_id: str
    fee_model: str
    mgmt_fee_bps: int
    status: str
    review_round: int
    scope_findings_count: int
    line_item_count: int
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MigrationBatch(TypedDict):
    id: str
    practice_id: str
    batch_label: str
    records_total: int
    records_validated: int
    records_quarantined: int
    records_pending: int
    remediation_round: int
    status: str
    cutover_start_at: Optional[str]
    cutover_end_at: Optional[str]
    validation_error_rate_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict):
    id: str
    practice_id: str
    payer_name: str
    transition_state: str
    fee_schedule_item_count: int
    enrollment_open_count: int
    erosion_override_ack: bool
    blended_impact_cents: Optional[int]
    dso_schedule_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayerEnrollment(TypedDict):
    id: str
    payer_contract_id: str
    doctor_employment_id: str
    effective_date: str
    term_date: Optional[str]
    status: str
    submission_round: int
    lead_days: Optional[int]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarnoutTranche(TypedDict):
    id: str
    affiliation_id: str
    period_label: str
    measurement_start: str
    measurement_end: str
    status: str
    variant_applied: Optional[str]
    reported_net_collections_cents: Optional[int]
    reported_expenses_cents: Optional[int]
    annualized_net_collections_cents: Optional[int]
    annualized_expenses_cents: Optional[int]
    final_net_collections_cents: Optional[int]
    final_expenses_cents: Optional[int]
    lag_holdback_cents: Optional[int]
    management_fee_cents: Optional[int]
    adjusted_ebitda_cents: Optional[int]
    growth_bps: Optional[int]
    multiple_bps: Optional[int]
    reserved_cents: int
    awarded_cents: int
    clawed_back_cents: int
    reserved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyPreferenceException(TypedDict):
    id: str
    doctor_employment_id: str
    vendor_category: str
    item_code: str
    annual_qty: int
    formulary_unit_cents: int
    preferred_unit_cents: int
    clinical_rationale: str
    status: str
    incremental_cost_cents: Optional[int]
    decided_by_doctor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorConsolidation(TypedDict):
    id: str
    practice_id: str
    vendor_category: str
    baseline_annual_spend_cents: int
    formulary_annual_spend_cents: int
    status: str
    gross_savings_cents: Optional[int]
    exception_leakage_cents: Optional[int]
    projected_savings_cents: Optional[int]
    exception_count_applied: int
    created_at: str
    updated_at: str
    version: int


class ClinicalQualityReview(TypedDict):
    id: str
    doctor_employment_id: str
    period_label: str
    charts_sampled: int
    charts_with_findings: int
    treatment_plan_overrides: int
    finding_rate_bps: int
    override_rate_bps: int
    score_bps: int
    status: str
    closed_by_doctor_id: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Write-once resources: only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------


class ServiceLineItem(TypedDict):
    id: str
    service_agreement_id: str
    service_code: str
    service_domain: str
    monthly_fee_cents: int
    is_clinical: bool
    created_at: str


class FeeScheduleItem(TypedDict):
    id: str
    payer_contract_id: str
    procedure_code: str
    legacy_allowed_cents: int
    dso_allowed_cents: int
    annual_volume: int
    line_impact_cents: int
    created_at: str


__all__ = [
    "UserRole",
    "AffiliationStatus",
    "EarnoutMeasurementState",
    "PracticeAffiliationStatus",
    "IntegrationPosture",
    "StaffingModelState",
    "DoctorSpecialty",
    "EmploymentStatus",
    "CredentialingStatus",
    "RecordsCustodyState",
    "NonCompeteEnforcementState",
    "CompModel",
    "SeparationReason",
    "ServiceAgreementStatus",
    "FeeModel",
    "ServiceDomain",
    "MigrationBatchStatus",
    "PayerContractTransitionState",
    "PayerEnrollmentStatus",
    "EnrollmentDecision",
    "EarnoutTrancheStatus",
    "EarnoutVariant",
    "VendorCategory",
    "SupplyPreferenceExceptionStatus",
    "VendorConsolidationStatus",
    "ClinicalQualityReviewStatus",
    "Affiliation",
    "ConversionVendor",
    "Practice",
    "Doctor",
    "DoctorEmployment",
    "ServiceAgreement",
    "MigrationBatch",
    "PayerContract",
    "PayerEnrollment",
    "EarnoutTranche",
    "SupplyPreferenceException",
    "VendorConsolidation",
    "ClinicalQualityReview",
    "ServiceLineItem",
    "FeeScheduleItem",
]
