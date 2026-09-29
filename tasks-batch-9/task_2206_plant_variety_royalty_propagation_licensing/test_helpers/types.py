"""Domain types for the Plant Variety Royalty & Propagation Licensing API.

Entity TypedDicts, state enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BREEDER_ADMIN = "BreederAdmin"
    LICENSING_OFFICER = "LicensingOfficer"
    PROPAGATOR = "Propagator"
    TRIAL_COORDINATOR = "TrialCoordinator"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# ---------------------------------------------------------------------------
# State enums
# ---------------------------------------------------------------------------
class VarietyLifecycleState(str, Enum):
    CANDIDATE = "CANDIDATE"
    IN_TRIAL = "IN_TRIAL"
    TRIAL_COMPLETE = "TRIAL_COMPLETE"
    RELEASED = "RELEASED"
    RETIRED = "RETIRED"


class VarietyBrandStatus(str, Enum):
    BRAND_NONE = "BRAND_NONE"
    BRAND_REGISTERED = "BRAND_REGISTERED"
    BRAND_RENEWAL_DUE = "BRAND_RENEWAL_DUE"
    BRAND_ABANDONED = "BRAND_ABANDONED"


class ProtectionPosture(str, Enum):
    UNPROTECTED = "UNPROTECTED"
    PENDING = "PENDING"
    PROTECTED = "PROTECTED"
    LAPSED_PROTECTION = "LAPSED_PROTECTION"


class RoyaltyBasis(str, Enum):
    PER_PLANT = "PER_PLANT"
    PER_ACRE = "PER_ACRE"


class InstrumentType(str, Enum):
    PLANT_PATENT = "PLANT_PATENT"
    PLANT_VARIETY_CERTIFICATE = "PLANT_VARIETY_CERTIFICATE"


class ProtectionFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    GRANTED = "GRANTED"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    LAPSED = "LAPSED"
    ABANDONED = "ABANDONED"


class LapseReason(str, Enum):
    GRACE_EXPIRED = "GRACE_EXPIRED"
    VOLUNTARY_LAPSE = "VOLUNTARY_LAPSE"


class VarietyTrialStatus(str, Enum):
    PLANNED = "PLANNED"
    PLANTED = "PLANTED"
    EVALUATED = "EVALUATED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AgreementStatus(str, Enum):
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class QualityTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class SuspensionReason(str, Enum):
    COMPLIANCE_SCORE_BREACH = "COMPLIANCE_SCORE_BREACH"
    AUDIT_FINDING = "AUDIT_FINDING"
    MANUAL = "MANUAL"


class QuotaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class TerritoryClass(str, Enum):
    DOMESTIC = "DOMESTIC"
    EXPORT = "EXPORT"


class TagOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class SublicenseStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Exclusivity(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class RevocationReason(str, Enum):
    PROTECTION_LAPSED = "PROTECTION_LAPSED"
    AGREEMENT_TERMINATED = "AGREEMENT_TERMINATED"
    MANUAL = "MANUAL"


class SurveillanceCaseStatus(str, Enum):
    OPENED = "OPENED"
    SAMPLED = "SAMPLED"
    TESTING = "TESTING"
    MATCH_CONFIRMED = "MATCH_CONFIRMED"
    NO_MATCH = "NO_MATCH"
    RESOLVED = "RESOLVED"


class GeneticTestResult(str, Enum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"


class AuditEngagementStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_NO_FINDING = "CLOSED_NO_FINDING"


class FindingSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class Variety(TypedDict):
    id: str
    denomination: str
    species: str
    breeder_code: str
    lifecycle_state: str
    brand_status: str
    brand_mark_text: Optional[str]
    brand_registry_class: Optional[int]
    brand_registered_on: Optional[str]
    brand_renewal_due_at: Optional[str]
    brand_renewal_count: int
    protection_posture: str
    protected_jurisdictions: List[str]
    royalty_basis_default: str
    base_royalty_cents_per_plant: int
    base_royalty_cents_per_acre: int
    regional_performance_index: float
    passed_trial_region_count: int
    active_sublicense_count: int
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtectionFiling(TypedDict):
    id: str
    variety_id: str
    instrument_type: str
    jurisdiction_code: str
    status: str
    filed_on: Optional[str]
    granted_on: Optional[str]
    term_years: int
    annuity_base_cents: int
    annuity_sequence_no: int
    annuity_due_date: Optional[str]
    annuity_grace_days: int
    annuity_days_late: int
    annuity_surcharge_cents: int
    annuity_volume_credit_cents: int
    annuity_total_due_cents: int
    installments_paid_count: int
    lapse_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrialSite(TypedDict):
    id: str
    site_name: str
    region_code: str
    plot_capacity: int
    occupied_plot_count: int
    created_at: str
    updated_at: str
    version: int


class VarietyTrial(TypedDict):
    id: str
    variety_id: str
    trial_site_id: str
    plot_count: int
    plant_date: str
    harvest_date: str
    status: str
    yield_index: Optional[float]
    vigor_score: Optional[float]
    uniformity_score: Optional[float]
    disease_resistance_score: Optional[float]
    propagation_pass_rate: Optional[float]
    performance_index: float
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Propagator(TypedDict):
    id: str
    legal_name: str
    home_territory_code: str
    compliance_score: int
    lifetime_compliance_score: int
    royalty_payable_cents: int
    royalty_settled_cents: int
    damages_credit_cents: int
    material_audit_finding_count: int
    created_at: str
    updated_at: str
    version: int


class PropagatorAgreement(TypedDict):
    id: str
    propagator_id: str
    status: str
    quality_tier: str
    territory_codes: List[str]
    term_start: str
    term_end: str
    countersigned_by_user_id: Optional[str]
    countersigned_at: Optional[str]
    suspension_reason: Optional[str]
    reinstatement_count: int
    created_at: str
    updated_at: str
    version: int


class ProductionQuota(TypedDict):
    id: str
    agreement_id: str
    variety_id: str
    season_code: str
    basis: str
    territory_code: str
    territory_class: str
    allocated_units: int
    status: str
    tags_committed_units: int
    units_available: int
    tags_activated_units: int
    created_at: str
    updated_at: str
    version: int


class TagOrder(TypedDict):
    id: str
    quota_id: str
    requested_units: int
    serial_prefix: Optional[str]
    status: str
    activated_units: int
    voided_units: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyReport(TypedDict):
    id: str
    agreement_id: str
    period_code: str
    period_start: str
    period_end: str
    due_at: str
    review_status: str
    settlement_status: str
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    is_late: bool
    provisional_total_cents: int
    final_total_cents: int
    late_fee_cents: int
    booked_amount_cents: int
    revision_no: int
    accepted_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyLineItem(TypedDict):
    id: str
    report_id: str
    quota_id: str
    reported_units: int
    effective_rate_cents: float
    billable_units: int
    provisional_amount_cents: int
    final_amount_cents: int
    overrun_flagged: bool
    created_at: str
    updated_at: str
    version: int


class SublicenseGrant(TypedDict):
    id: str
    agreement_id: str
    variety_id: str
    sublicensee_name: str
    territory_code: str
    jurisdiction_code: str
    exclusivity: str
    effective_date: str
    expiry_date: str
    status: str
    activated_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveillanceCase(TypedDict):
    id: str
    variety_id: str
    suspected_propagator_id: Optional[str]
    market_survey_ref: str
    status: str
    sampled_unit_count: int
    max_match_confidence: float
    concluded_at: Optional[str]
    recovered_damages_cents: int
    enforcement_cost_cents: int
    enforcement_recovery_cents: int
    breeder_pool_cents: int
    propagator_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class GeneticTest(TypedDict):
    """A genetic test is an immutable laboratory record: it carries id and
    created_at only -- no updated_at and no version."""

    id: str
    case_id: str
    lab_code: str
    marker_panel: str
    match_confidence: float
    result: str
    created_at: str


class AuditEngagement(TypedDict):
    id: str
    agreement_id: str
    royalty_report_id: str
    status: str
    finding_severity: Optional[str]
    underreported_units: int
    finalized_at: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
