"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    TAX_ANALYST = "TaxAnalyst"
    TAX_REVIEWER = "TaxReviewer"
    JURISDICTION_AUDITOR = "JurisdictionAuditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class RegistrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProductClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TaxRateStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RateChangeNoticeStatus(str, Enum):
    DETECTED = "DETECTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BOND_DEFICIENT = "BOND_DEFICIENT"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BondStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ExemptionCertificateStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BondedMovementStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DISCHARGED = "DISCHARGED"
    PARTIAL_DEFAULT = "PARTIAL_DEFAULT"
    DEFAULTED = "DEFAULTED"


class TaxableEventStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    RATED = "RATED"
    RETURNED = "RETURNED"
    ADJUSTED = "ADJUSTED"
    VOIDED = "VOIDED"


class EventDetermination(str, Enum):
    STANDARD = "STANDARD"
    DEFAULT_ASSESSMENT = "DEFAULT_ASSESSMENT"


class ReturnFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class ReturnSettlementStatus(str, Enum):
    UNFILED = "UNFILED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    SETTLED = "SETTLED"
    OVERPAID = "OVERPAID"


class DepositStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LATE = "LATE"
    PAID = "PAID"
    APPLIED = "APPLIED"
    WAIVED = "WAIVED"


class CreditClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"
    WITHDRAWN = "WITHDRAWN"


class AuditCaseStatus(str, Enum):
    OPENED = "OPENED"
    DOCUMENTS_REQUESTED = "DOCUMENTS_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED_NO_CHANGE = "CLOSED_NO_CHANGE"
    CLOSED_ASSESSMENT = "CLOSED_ASSESSMENT"


# ---------------------------------------------------------------------------
# Misc enums used by inputs
# ---------------------------------------------------------------------------
class JurisdictionLevel(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    LOCAL = "LOCAL"


class ReturnFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class DepositFrequency(str, Enum):
    SEMI_MONTHLY = "SEMI_MONTHLY"
    MONTHLY = "MONTHLY"


class BaseUnit(str, Enum):
    GALLON = "GALLON"
    PROOF_GALLON = "PROOF_GALLON"
    PACK = "PACK"
    UNIT = "UNIT"


class DepositMethod(str, Enum):
    SAFE_HARBOR = "SAFE_HARBOR"
    ACTUAL = "ACTUAL"


class CertificateType(str, Enum):
    RESALE = "RESALE"
    GOVERNMENT = "GOVERNMENT"
    EXPORT = "EXPORT"


class ClaimType(str, Enum):
    BAD_DEBT = "BAD_DEBT"
    EXPORT = "EXPORT"


class DepositWindow(str, Enum):
    A = "A"
    B = "B"
    M = "M"


class RequirementVariant(str, Enum):
    STANDARD = "STANDARD"
    AGGRAVATED = "AGGRAVATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries the standard system-managed fields
# id / created_at / updated_at / version (PRD §2.5).
# ---------------------------------------------------------------------------
class Registrant(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    status: str
    aggregate_open_liability_cents: int
    overpayment_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    level: str
    return_frequency: str
    deposit_frequency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductClass(TypedDict, total=False):
    id: str
    code: str
    description: str
    base_unit: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxRate(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    product_class_id: str
    rate_millicents_per_unit: int
    effective_from: str
    effective_to: Optional[str]
    source_notice_id: Optional[str]
    supersedes_rate_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RateChangeNotice(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    product_class_id: str
    new_rate_millicents_per_unit: int
    announced_effective_from: str
    source_reference: str
    detected_at: str
    applied_rate_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    registrant_id: str
    jurisdiction_id: str
    registration_number: Optional[str]
    deposit_method: str
    status: str
    bond_required_cents: int
    bond_coverage_cents: int
    requirement_variant: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict, total=False):
    id: str
    registration_id: str
    surety_name: str
    principal_amount_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict, total=False):
    id: str
    registration_id: str
    product_class_id: Optional[str]
    customer_reference: str
    certificate_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BondedMovement(TypedDict, total=False):
    id: str
    registration_id: str
    bond_id: str
    product_class_id: str
    quantity_units: int
    origin_facility: str
    destination_facility: str
    transit_deadline_days: int
    dispatched_at: Optional[str]
    received_at: Optional[str]
    quantity_received_units: Optional[int]
    defaulted_quantity_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxableEvent(TypedDict, total=False):
    id: str
    registration_id: str
    jurisdiction_id: str
    product_class_id: str
    event_date: str
    quantity_units: int
    customer_reference: Optional[str]
    is_export: bool
    period: str
    determination: str
    exemption_certificate_id: Optional[str]
    bonded_movement_id: Optional[str]
    gross_tax_cents: int
    tax_cents: int
    return_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    registration_id: str
    jurisdiction_id: str
    period: str
    amendment_of_id: Optional[str]
    amendment_sequence: int
    prepared_by_user_id: Optional[str]
    filed_by_user_id: Optional[str]
    due_date: str
    filed_at: Optional[str]
    event_count: int
    gross_tax_cents: int
    exempted_cents: int
    taxable_tax_cents: int
    credits_cents: int
    deposits_applied_cents: int
    penalty_cents: int
    net_due_cents: int
    pinned_rate_snapshot: List[Dict[str, Any]]
    filing_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    registration_id: str
    jurisdiction_id: str
    period: str
    window: str
    scheduled_amount_cents: int
    due_date: str
    paid_amount_cents: Optional[int]
    paid_at: Optional[str]
    penalty_cents: int
    applied_amount_cents: int
    applied_return_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict, total=False):
    id: str
    registration_id: str
    return_id: str
    claim_type: str
    claimed_cents: int
    event_ids: List[str]
    justification: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    eligible_cents: int
    approved_cents: Optional[int]
    applied_cents: int
    reversed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    registration_id: str
    jurisdiction_id: str
    period_start: str
    period_end: str
    records_hold: bool
    assessment_cents: Optional[int]
    opened_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
