"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Vacant & Abandoned Property Registry PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    REGISTRANT = "Registrant"
    CODE_OFFICER = "CodeOfficer"
    PROGRAM_ADMIN = "ProgramAdmin"


class PartyType(str, Enum):
    LENDER = "LENDER"
    OWNER = "OWNER"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    ABANDONED = "ABANDONED"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEMOLISHED = "DEMOLISHED"


class ForeclosureStatus(str, Enum):
    NONE = "NONE"
    NOTICE_OF_DEFAULT = "NOTICE_OF_DEFAULT"
    LIS_PENDENS = "LIS_PENDENS"
    AUCTION_SCHEDULED = "AUCTION_SCHEDULED"
    REO = "REO"


class MaintenanceCategory(str, Enum):
    SECURING = "SECURING"
    LANDSCAPING = "LANDSCAPING"
    STRUCTURAL = "STRUCTURAL"
    SANITATION = "SANITATION"
    POOL_SAFETY = "POOL_SAFETY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    FINED = "FINED"
    VOIDED = "VOIDED"


class FineStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    LIENED = "LIENED"


class LienStatus(str, Enum):
    RECORDED = "RECORDED"
    SATISFIED = "SATISFIED"
    FORECLOSED = "FORECLOSED"


class AbatementStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"


class ReceivershipStatus(str, Enum):
    REFERRED = "REFERRED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"


class DemolitionStatus(str, Enum):
    LISTED = "LISTED"
    SCHEDULED = "SCHEDULED"
    DEMOLISHED = "DEMOLISHED"
    REMOVED = "REMOVED"


class ReceivershipGround(str, Enum):
    CHRONIC_NUISANCE = "CHRONIC_NUISANCE"
    STRUCTURAL_HAZARD = "STRUCTURAL_HAZARD"
    TAX_DELINQUENCY = "TAX_DELINQUENCY"


class LedgerEntryType(str, Enum):
    REGISTRATION_FEE = "REGISTRATION_FEE"
    FINE_ASSESSED = "FINE_ASSESSED"
    FINE_ACCRUAL = "FINE_ACCRUAL"
    FINE_PAYMENT = "FINE_PAYMENT"
    FINE_WAIVED = "FINE_WAIVED"
    FINE_LIENED = "FINE_LIENED"
    ABATEMENT_RECOVERY = "ABATEMENT_RECOVERY"


# --- Entity TypedDicts ---------------------------------------------------
# common_fields: true -> id, created_at, updated_at, version
# common_fields: false -> id, created_at ONLY (MaintenanceStandard, LedgerEntry)


class Registrant(TypedDict):
    id: str
    legal_name: str
    party_type: str
    email: str
    contact_phone: str
    mailing_address: str
    license_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    registrant_id: str
    parcel_id: str
    street_address: str
    occupancy_status: str
    registration_type: str
    registration_status: str
    foreclosure_status: str
    registration_fee_cents: int
    registered_at: str
    registration_expires_at: str
    outstanding_balance_cents: int
    lien_balance_cents: int
    open_violation_count: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceStandard(TypedDict):
    id: str
    code: str
    category: str
    description: str
    severity_weight: int
    cure_period_days: int
    base_fine_cents: int
    created_at: str


class Inspection(TypedDict):
    id: str
    property_id: str
    inspector_badge: str
    scheduled_start: str
    scheduled_end: str
    status: str
    result: Optional[str]
    failed_standard_codes: List[str]
    performed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    property_id: str
    inspection_id: str
    standard_code: str
    severity_weight: int
    status: str
    cited_at: str
    cure_deadline_at: str
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    violation_id: str
    property_id: str
    base_amount_cents: int
    assessed_at: str
    daily_penalty_cents: int
    accrued_amount_cents: int
    finalized_amount_cents: Optional[int]
    status: str
    dispute_reason: Optional[str]
    disputed_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    property_id: str
    source_fine_id: str
    principal_cents: int
    interest_rate_bps: int
    recorded_at: str
    payoff_amount_cents: int
    payoff_quoted_cents: int
    status: str
    satisfied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementOrder(TypedDict):
    id: str
    property_id: str
    ordered_at: str
    scheduled_start: str
    scheduled_end: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    admin_fee_cents: Optional[int]
    recovered_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReceivershipReferral(TypedDict):
    id: str
    property_id: str
    referred_at: str
    ground: str
    receiver_name: str
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemolitionListing(TypedDict):
    id: str
    property_id: str
    listed_at: str
    priority_score: float
    status: str
    demolition_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    id: str
    property_id: str
    entry_type: str
    amount_cents: int
    source_type: str
    source_id: str
    occurred_at: str
    memo: str
    created_at: str
