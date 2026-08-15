"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITER = "Underwriter"
    POLICYHOLDER = "Policyholder"
    ADJUSTER = "Adjuster"
    CLAIMS_APPROVER = "ClaimsApprover"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEBARRED = "DEBARRED"


class FederalCropPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RatingKind(str, Enum):
    CROP_HAIL = "CROP_HAIL"
    LIVESTOCK_MORTALITY = "LIVESTOCK_MORTALITY"


class RateTableStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class Species(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    POULTRY = "POULTRY"
    EQUINE = "EQUINE"
    SHEEP = "SHEEP"


class PolicyKind(str, Enum):
    CROP_HAIL = "CROP_HAIL"
    LIVESTOCK_MORTALITY = "LIVESTOCK_MORTALITY"


class PolicyLifecycle(str, Enum):
    APPLICATION = "APPLICATION"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    NON_RENEWED = "NON_RENEWED"


class BillingState(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    DELINQUENT = "DELINQUENT"


class ClaimsPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class CoverageUnitStatus(str, Enum):
    PENDING_REPORT = "PENDING_REPORT"
    REPORTED = "REPORTED"
    LAPSED_REPORT = "LAPSED_REPORT"
    UNDER_CLAIM = "UNDER_CLAIM"
    SETTLED = "SETTLED"


class AcreageReportKind(str, Enum):
    PLANTING = "PLANTING"
    HARVEST = "HARVEST"


class HeadReportKind(str, Enum):
    INITIAL = "INITIAL"
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class ClaimKind(str, Enum):
    HAIL_DAMAGE = "HAIL_DAMAGE"
    LIVESTOCK_MORTALITY = "LIVESTOCK_MORTALITY"


class ClaimState(str, Enum):
    REPORTED = "REPORTED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTED = "INSPECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"
    CLOSED_UNTIMELY = "CLOSED_UNTIMELY"


class DocPosture(str, Enum):
    DOCS_PENDING = "DOCS_PENDING"
    DOCS_COMPLETE = "DOCS_COMPLETE"
    DOCS_WAIVED = "DOCS_WAIVED"


class AdjusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VetReportKind(str, Enum):
    VETERINARY_CERTIFICATE = "VETERINARY_CERTIFICATE"
    NECROPSY_REPORT = "NECROPSY_REPORT"
    THIRD_PARTY_AFFIDAVIT = "THIRD_PARTY_AFFIDAVIT"


class DeterminationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    PARTIAL = "PARTIAL"


class DenialReasonCode(str, Enum):
    FRAUD = "FRAUD"
    NOT_COVERED_PERIL = "NOT_COVERED_PERIL"
    LATE_NOTICE_OVER_30D = "LATE_NOTICE_OVER_30D"
    MISSING_DOCS = "MISSING_DOCS"
    POLICY_INACTIVE = "POLICY_INACTIVE"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"


class PaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    VOID = "VOID"


class RenewalDecision(str, Enum):
    RENEW = "RENEW"
    NON_RENEW = "NON_RENEW"


class Carrier(TypedDict, total=False):
    id: str
    carrier_code: str
    legal_name: str
    current_utc: str
    reinsurance_treaty_attachment_cents: int
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict, total=False):
    id: str
    carrier_id: str
    full_name: str
    tax_id_last4: str
    email: str
    county_code: str
    state_code: str
    continuous_coverage_since: Optional[str]
    prior_claims_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FederalCropPolicy(TypedDict, total=False):
    id: str
    carrier_id: str
    grower_id: str
    fci_policy_number: str
    coverage_level_pct: float
    crop_code: str
    county_code: str
    effective_date: str
    expiration_date: str
    liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateTable(TypedDict, total=False):
    id: str
    carrier_id: str
    rating_kind: str
    county_code: Optional[str]
    crop_code: Optional[str]
    species: Optional[str]
    value_band_floor_cents: Optional[int]
    value_band_ceiling_cents: Optional[int]
    rate_per_100_cents_of_liability: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    carrier_id: str
    grower_id: str
    policy_kind: str
    policy_number: str
    effective_date: str
    expiration_date: str
    acreage_report_deadline: Optional[str]
    harvest_report_deadline: Optional[str]
    head_report_deadline: Optional[str]
    premium_cents: int
    premium_paid_cents: int
    premium_reserve_cents: int
    continuous_coverage_carryover_credit_cents: int
    high_risk_surcharge_pct: int
    lifecycle_state: str
    billing_state: str
    claims_posture: str
    prior_policy_id: Optional[str]
    dual_coverage_link_id: Optional[str]
    version_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageUnit(TypedDict, total=False):
    id: str
    policy_id: str
    unit_kind: str
    county_code: Optional[str]
    crop_code: Optional[str]
    declared_acres: Optional[int]
    species: Optional[str]
    declared_head_count: Optional[int]
    per_head_value_cents: Optional[int]
    liability_cents: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AcreageReport(TypedDict, total=False):
    id: str
    coverage_unit_id: str
    report_kind: str
    reported_acres: int
    submitted_at: str
    is_timely: bool
    lateness_days: int
    coverage_reduction_pct: int
    created_at: str
    updated_at: str
    version: int


class HeadReport(TypedDict, total=False):
    id: str
    coverage_unit_id: str
    report_kind: str
    reported_head_count: int
    submitted_at: str
    is_timely: bool
    lateness_days: int
    coverage_reduction_pct: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    coverage_unit_id: str
    claim_kind: str
    loss_date: str
    reported_at: str
    reported_within_window: bool
    late_notification_penalty_pct: int
    percent_damage_estimate_pct: Optional[int]
    appraisal_value_cents: Optional[int]
    deceased_head_count: Optional[int]
    adjuster_id: Optional[str]
    provisional_indemnity_cents: int
    final_indemnity_cents: int
    claim_state: str
    doc_posture: str
    created_at: str
    updated_at: str
    version: int


class Adjuster(TypedDict, total=False):
    id: str
    carrier_id: str
    full_name: str
    license_number: str
    county_codes: List[str]
    species_qualified: List[str]
    capacity_max_open_claims: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldInspection(TypedDict, total=False):
    id: str
    claim_id: str
    adjuster_id: str
    scheduled_for: str
    inspected_at: str
    within_inspection_window: bool
    observed_percent_damage_pct: Optional[int]
    observed_appraisal_cents: Optional[int]
    observed_deceased_count: Optional[int]
    provisional_indemnity_cents: int
    notes: str
    created_at: str
    updated_at: str
    version: int


class VeterinaryReport(TypedDict, total=False):
    id: str
    claim_id: str
    veterinarian_license: str
    report_kind: str
    cause_of_death: str
    necropsy_performed: bool
    death_date: str
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class LossDetermination(TypedDict, total=False):
    id: str
    claim_id: str
    reviewer_id: str
    decision: str
    approved_indemnity_cents: int
    applied_coverage_reduction_pct: int
    applied_late_notification_penalty_pct: int
    applied_dual_coverage_offset_cents: int
    final_indemnity_cents: int
    denial_reason_code: Optional[str]
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class IndemnityPayment(TypedDict, total=False):
    id: str
    claim_id: str
    amount_cents: int
    issued_at: str
    payment_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DualCoverageLink(TypedDict, total=False):
    id: str
    policy_id: str
    federal_crop_policy_id: str
    offset_pct_of_federal_liability: int
    established_at: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict, total=False):
    id: str
    policy_id: str
    prior_policy_id: str
    continuity_gap_days: int
    carryover_credit_cents: int
    decision: str
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class PremiumPayment(TypedDict, total=False):
    id: str
    policy_id: str
    amount_cents: int
    posted_at: str
    created_at: str
    updated_at: str
    version: int
