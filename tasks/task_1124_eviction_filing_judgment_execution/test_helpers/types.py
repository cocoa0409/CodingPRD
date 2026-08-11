"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model. Entities with the standard common
fields carry id + created_at + updated_at + version. The two immutable
ledger-style records (ServiceAttempt, CollectionEntry) carry ONLY
id + created_at (PRD: "no updated_at, no version").
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LANDLORD = "Landlord"
    COURT_CLERK = "CourtClerk"
    PROCESS_SERVER = "ProcessServer"
    SHERIFF_DEPUTY = "SheriffDeputy"
    MEDIATOR = "Mediator"


class JurisdictionCode(str, Enum):
    CA = "CA"
    TX = "TX"
    OH = "OH"


class UnitStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


class TenancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class CaseReason(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    LEASE_VIOLATION = "LEASE_VIOLATION"
    SEVERE = "SEVERE"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICE_ACTIVE = "NOTICE_ACTIVE"
    NOTICE_EXPIRED = "NOTICE_EXPIRED"
    FILING_REJECTED = "FILING_REJECTED"
    FILED = "FILED"
    SERVICE_COMPLETE = "SERVICE_COMPLETE"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    ANSWERED = "ANSWERED"
    MEDIATION_PENDING = "MEDIATION_PENDING"
    HEARING_CONCLUDED = "HEARING_CONCLUDED"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    WRIT_ISSUED = "WRIT_ISSUED"
    LOCKOUT_SCHEDULED = "LOCKOUT_SCHEDULED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"
    CURED = "CURED"


class NoticeType(str, Enum):
    PAY_OR_QUIT = "PAY_OR_QUIT"
    CURE_OR_QUIT = "CURE_OR_QUIT"
    UNCONDITIONAL_QUIT = "UNCONDITIONAL_QUIT"


class NoticeStatus(str, Enum):
    PENDING = "PENDING"
    CURED = "CURED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class FeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ServiceMethod(str, Enum):
    PERSONAL = "PERSONAL"
    SUBSTITUTED = "SUBSTITUTED"
    POST_AND_MAIL = "POST_AND_MAIL"


class ServiceResult(str, Enum):
    SERVED = "SERVED"
    FAILED = "FAILED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONTINUED = "CONTINUED"
    STAYED = "STAYED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


class DefenseCode(str, Enum):
    PAYMENT_TENDERED = "PAYMENT_TENDERED"
    HABITABILITY = "HABITABILITY"
    RETALIATION = "RETALIATION"
    PROCEDURAL = "PROCEDURAL"


class AnswerStatus(str, Enum):
    FILED = "FILED"
    REFERRED = "REFERRED"
    RETURNED = "RETURNED"
    RESOLVED = "RESOLVED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class JudgmentStatus(str, Enum):
    ENTERED = "ENTERED"
    FINAL = "FINAL"
    SATISFIED = "SATISFIED"


class WritStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class StorageStatus(str, Enum):
    STORED = "STORED"
    DISPOSABLE = "DISPOSABLE"
    RECLAIMED = "RECLAIMED"
    DISPOSED = "DISPOSED"


class BillingMode(str, Enum):
    CALENDAR_INCLUSIVE = "CALENDAR_INCLUSIVE"
    ELAPSED_24H = "ELAPSED_24H"


class EntryType(str, Enum):
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"
    WRITE_OFF = "WRITE_OFF"


class ReportType(str, Enum):
    FILING = "FILING"
    JUDGMENT = "JUDGMENT"
    SATISFACTION = "SATISFACTION"
    CORRECTION = "CORRECTION"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---

class Landlord(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class RentalUnit(TypedDict, total=False):
    id: str
    landlord_id: str
    jurisdiction_code: str
    street_address: str
    unit_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict, total=False):
    id: str
    unit_id: str
    tenant_full_name: str
    monthly_rent_cents: int
    lease_start_date: str
    lease_end_date: Optional[str]
    status: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict, total=False):
    id: str
    tenancy_id: str
    landlord_id: str
    case_reason: str
    status: str
    case_number: str
    served_defendant_names: List[str]
    service_completed_at: Optional[str]
    dismiss_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict, total=False):
    id: str
    case_id: str
    notice_type: str
    served_on: str
    claimed_rent_owed_cents: Optional[int]
    violation_description: Optional[str]
    statutory_cure_days: int
    cure_deadline: str
    status: str
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingPackage(TypedDict, total=False):
    id: str
    case_id: str
    claimed_amount_cents: int
    defendant_names: List[str]
    jury_demanded: bool
    efiled: bool
    filing_fee_cents: int
    fee_paid_cents: int
    fee_status: str
    status: str
    accepted_by_clerk_id: Optional[str]
    accepted_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceAttempt(TypedDict, total=False):
    # Immutable ledger record: ONLY id + created_at among common fields.
    id: str
    case_id: str
    defendant_name: str
    method: str
    result: str
    served_at: str
    server_user_id: str
    server_role: str
    created_at: str


class Hearing(TypedDict, total=False):
    id: str
    case_id: str
    courtroom: str
    start_at: str
    end_at: str
    status: str
    clerk_user_id: str
    created_at: str
    updated_at: str
    version: int


class TenantAnswer(TypedDict, total=False):
    id: str
    case_id: str
    defense_codes: List[str]
    mediation_requested: bool
    status: str
    filed_by_clerk_id: str
    created_at: str
    updated_at: str
    version: int


class MediationReferral(TypedDict, total=False):
    id: str
    answer_id: str
    mediator_id: str
    session_date: str
    status: str
    outcome_notes: Optional[str]
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Judgment(TypedDict, total=False):
    id: str
    case_id: str
    possession_granted: bool
    rent_awarded_cents: int
    damages_cents: int
    late_fee_cents: int
    court_costs_cents: int
    oldest_unpaid_due_date: str
    interest_cents: int
    total_awarded_cents: int
    outstanding_balance_cents: int
    status: str
    entered_by_clerk_id: str
    entered_at: str
    appeal_deadline: str
    satisfied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Writ(TypedDict, total=False):
    id: str
    judgment_id: str
    case_id: str
    unit_id: str
    status: str
    writ_fee_paid_cents: int
    issued_at: Optional[str]
    expires_on: Optional[str]
    deputy_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PropertyStorageRecord(TypedDict, total=False):
    id: str
    writ_id: str
    case_id: str
    items_summary: str
    status: str
    stored_at: str
    daily_fee_cents: int
    billing_mode: str
    disposal_eligible_on: str
    accrued_charge_cents: int
    final_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CollectionEntry(TypedDict, total=False):
    # Immutable ledger record: ONLY id + created_at among common fields.
    id: str
    judgment_id: str
    entry_type: str
    amount_cents: int
    reversal_of_id: Optional[str]
    allocation: Dict[str, Any]
    resulting_outstanding_cents: int
    reversed_by_id: Optional[str]
    recorded_by: str
    created_at: str


class RentalHistoryReport(TypedDict, total=False):
    id: str
    tenancy_id: str
    landlord_id: str
    report_type: str
    reference_report_id: Optional[str]
    event_at: str
    superseded: bool
    bureau_reference: str
    created_at: str
    updated_at: str
    version: int
