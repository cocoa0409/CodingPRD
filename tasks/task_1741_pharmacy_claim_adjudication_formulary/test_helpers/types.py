"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PBM_ADMIN = "PbmAdmin"
    PHARMACIST = "Pharmacist"
    MEMBER = "Member"
    CLINICAL_REVIEWER = "ClinicalReviewer"
    AUDITOR = "Auditor"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssistanceModel(str, Enum):
    ACCUMULATOR = "ACCUMULATOR"
    MAXIMIZER = "MAXIMIZER"


class FormularyEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CopayType(str, Enum):
    FLAT = "FLAT"
    PERCENTAGE = "PERCENTAGE"


class PharmacyChannel(str, Enum):
    RETAIL = "RETAIL"
    SPECIALTY = "SPECIALTY"
    MAIL_ORDER = "MAIL_ORDER"


class PharmacyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PriorAuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    PAID = "PAID"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class AuditStatus(str, Enum):
    UNAUDITED = "UNAUDITED"
    FLAGGED = "FLAGGED"
    CLAWED_BACK = "CLAWED_BACK"


class RebateTag(str, Enum):
    REBATE_ELIGIBLE = "REBATE_ELIGIBLE"
    REBATE_INELIGIBLE = "REBATE_INELIGIBLE"
    REBATE_VOID = "REBATE_VOID"


class DurAlertType(str, Enum):
    EARLY_REFILL = "EARLY_REFILL"
    THERAPEUTIC_DUPLICATION = "THERAPEUTIC_DUPLICATION"
    HIGH_DAILY_DOSE = "HIGH_DAILY_DOSE"


class DurAlertSeverity(str, Enum):
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DurAlertStatus(str, Enum):
    OPEN = "OPEN"
    OVERRIDDEN = "OVERRIDDEN"
    SUPERSEDED = "SUPERSEDED"


class OverrideCode(str, Enum):
    PROFESSIONAL_CONSULT = "PROFESSIONAL_CONSULT"
    PRESCRIBER_CONFIRMED = "PRESCRIBER_CONFIRMED"
    PATIENT_EDUCATED = "PATIENT_EDUCATED"


class PharmacyAuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    DISPUTED = "DISPUTED"
    CLOSED_WITH_FINDINGS = "CLOSED_WITH_FINDINGS"
    CLOSED_NO_FINDINGS = "CLOSED_NO_FINDINGS"


class ExtrapolationMethod(str, Enum):
    CLAIM_LEVEL = "CLAIM_LEVEL"
    EXTRAPOLATED = "EXTRAPOLATED"


class Plan(TypedDict, total=False):
    id: str
    name: str
    deductible_cents: int
    oop_max_cents: int
    assistance_model: str
    member_min_pay_cents: int
    card_fill_cap_cents: int
    dispensing_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict, total=False):
    id: str
    ndc: str
    name: str
    therapeutic_class: str
    unit_cost_cents: int
    max_daily_dose_units: int
    is_specialty: bool
    created_at: str
    updated_at: str
    version: int


class FormularyEntry(TypedDict, total=False):
    id: str
    plan_id: str
    drug_id: str
    tier: int
    pa_required: bool
    step_therapy_required: bool
    step_drug_id: Optional[str]
    step_therapy_lookback_days: int
    quantity_limit_per_fill: int
    max_days_supply: int
    copay_type: str
    copay_flat_cents: Optional[int]
    copay_percentage: Optional[float]
    rebate_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Pharmacy(TypedDict, total=False):
    id: str
    ncpdp_id: str
    name: str
    channel: str
    auto_suspend_threshold_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    plan_id: str
    external_ref: str
    full_name: str
    eligibility_start_date: str
    eligibility_end_date: str
    status: str
    deductible_paid_cents: int
    oop_paid_cents: int
    oop_max_reached: bool
    card_drug_id: Optional[str]
    card_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    member_id: str
    drug_id: str
    requested_quantity: int
    note: Optional[str]
    status: str
    approved_quantity: Optional[int]
    quantity_consumed: int
    expires_at: Optional[str]
    denial_reason: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    pharmacy_id: str
    drug_id: str
    prescription_number: str
    fill_date: str
    quantity: int
    days_supply: int
    status: str
    reject_reasons: List[str]
    allowed_cents: int
    copay_base_cents: int
    deductible_applied_cents: int
    card_applied_cents: int
    member_pays_cents: int
    plan_paid_cents: int
    pa_id: Optional[str]
    resubmit_count: int
    audit_status: str
    rebate_tag: str
    created_at: str
    updated_at: str
    version: int


class DurAlert(TypedDict, total=False):
    # Append-only screening record: carries ONLY id + created_at (no updated_at, no version).
    id: str
    created_at: str
    claim_id: str
    alert_type: str
    severity: str
    status: str
    override_code: Optional[str]


class Finding(TypedDict, total=False):
    claim_id: str
    clawback_cents: int


class PharmacyAudit(TypedDict, total=False):
    id: str
    pharmacy_id: str
    window_start_date: str
    window_end_date: str
    extrapolation_method: str
    status: str
    findings: List[Finding]
    sample_size: int
    universe_paid_claims: int
    total_clawback_cents: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
