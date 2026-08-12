"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class CoveragePosture(str, Enum):
    UNBOUND = "UNBOUND"
    BOUND_PARTIAL = "BOUND_PARTIAL"
    BOUND_FULL = "BOUND_FULL"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ProductionType(str, Enum):
    FEATURE = "FEATURE"
    EPISODIC = "EPISODIC"
    DOCUMENTARY = "DOCUMENTARY"
    COMMERCIAL = "COMMERCIAL"
    MUSIC_VIDEO = "MUSIC_VIDEO"


class CoverageLine(str, Enum):
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    EQUIPMENT = "EQUIPMENT"
    CAST = "CAST"
    ERRORS_OMISSIONS = "ERRORS_OMISSIONS"
    FOREIGN_TRAVEL = "FOREIGN_TRAVEL"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ENDORSED_PENDING = "ENDORSED_PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RoleTier(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    SUPPORTING = "SUPPORTING"
    DAY_PLAYER = "DAY_PLAYER"
    STUNT = "STUNT"


class PhysicalExamStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class EndorsementType(str, Enum):
    PHYSICAL_CLEARANCE = "PHYSICAL_CLEARANCE"
    ESSENTIAL_ELEMENT = "ESSENTIAL_ELEMENT"
    STUNT_RIDER = "STUNT_RIDER"


class EndorsementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class CertificateType(str, Enum):
    LOCATION = "LOCATION"
    VENDOR = "VENDOR"
    EQUIPMENT_RENTAL = "EQUIPMENT_RENTAL"
    PERMIT = "PERMIT"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    INJURY = "INJURY"
    WEATHER_DELAY = "WEATHER_DELAY"
    THEFT = "THEFT"
    THIRD_PARTY = "THIRD_PARTY"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUSTED = "ADJUSTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class ClaimEventType(str, Enum):
    SUBMIT = "SUBMIT"
    ADJUST_RESERVE = "ADJUST_RESERVE"
    DENY = "DENY"
    SETTLE = "SETTLE"
    REOPEN = "REOPEN"
    CLOSE = "CLOSE"


class ClearanceKind(str, Enum):
    SCRIPT = "SCRIPT"
    TITLE = "TITLE"
    MUSIC = "MUSIC"
    PERSONAL_RIGHTS = "PERSONAL_RIGHTS"
    TRADEMARK = "TRADEMARK"
    LOCATION_RIGHTS = "LOCATION_RIGHTS"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    WAIVED = "WAIVED"


class BondStatus(str, Enum):
    APPLIED = "APPLIED"
    UNDERWRITTEN = "UNDERWRITTEN"
    ISSUED = "ISSUED"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    LAPSED = "LAPSED"


class TravelExtensionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"


class PayrollAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"


class RenewalOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    BROKER_AGENT = "BrokerAgent"
    PRODUCTION_MANAGER = "ProductionManager"
    UNDERWRITER_AGENT = "UnderwriterAgent"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CLEARANCE_COUNSEL = "ClearanceCounsel"
    SURETY_UNDERWRITER = "SuretyUnderwriter"
    EXTERNAL_AUDITOR = "ExternalAuditor"
    PLATFORM_OPERATOR = "PlatformOperator"


# --- Entity bodies (common_fields entities: id + created_at + updated_at + version) ---

class Production(TypedDict, total=False):
    id: str
    production_code: str
    title: str
    production_type: str
    principal_photography_start: str
    principal_photography_end: str
    budget_cents: int
    requires_completion_bond: bool
    coverage_posture: str
    posture_reasons: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    production_id: str
    coverage_line: str
    carrier_code: str
    policy_number: str
    limit_cents: int
    aggregate_limit_cents: int
    deductible_cents: int
    effective_date: str
    expiry_date: str
    provisional_premium_cents: Optional[int]
    final_premium_cents: Optional[int]
    payroll_basis_cents: int
    audited_payroll_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CastMember(TypedDict, total=False):
    id: str
    production_id: str
    full_name: str
    role_tier: str
    weekly_salary_cents: int
    essential_element: bool
    physical_exam_status: str
    physical_exam_expires_at: Optional[str]
    endorsement_required: bool
    created_at: str
    updated_at: str
    version: int


class CastEndorsement(TypedDict, total=False):
    id: str
    cast_member_id: str
    policy_id: str
    endorsement_type: str
    underwriter_notes: Optional[str]
    issued_at: Optional[str]
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    production_id: str
    certificate_type: str
    holder_name: str
    holder_address: str
    additional_insured_name: Optional[str]
    coverage_lines: List[str]
    location_start: str
    location_end: str
    certificate_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    production_id: str
    policy_id: str
    claim_type: str
    occurrence_date: str
    reported_date: str
    loss_amount_cents: int
    deductible_applied_cents: int
    carrier_payable_cents: int
    reserve_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log (PRD §2.4): carries ONLY id + created_at — no updated_at, no version.
class ClaimEvent(TypedDict, total=False):
    id: str
    claim_id: str
    event_type: str
    payload: dict
    recorded_at: str
    actor_role: str
    created_at: str


class ClearanceItem(TypedDict, total=False):
    id: str
    production_id: str
    clearance_kind: str
    item_reference: str
    legal_reviewer: str
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompletionBond(TypedDict, total=False):
    id: str
    production_id: str
    surety_company: str
    bond_amount_cents: int
    bond_premium_cents: Optional[int]
    strike_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeignTravelExtension(TypedDict, total=False):
    id: str
    production_id: str
    territory_code: str
    travel_window_start: str
    travel_window_end: str
    travelers_count: int
    repatriation_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollAudit(TypedDict, total=False):
    id: str
    policy_id: str
    audit_period_start: str
    audit_period_end: str
    auditor_name: str
    reported_payroll_cents: int
    premium_delta_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict, total=False):
    id: str
    policy_id: str
    offered_premium_cents: int
    loss_ratio_pct: int
    renewal_term_months: int
    offer_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
