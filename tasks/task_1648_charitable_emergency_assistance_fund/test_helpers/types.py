"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. Entities described in PRD §2.5 as
append-only ledgers (ApplicationDocument, CaseNote, ReplenishmentRun) carry
only id + created_at — no updated_at, no version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CASEWORKER = "Caseworker"
    PROGRAM_MANAGER = "ProgramManager"
    FINANCE_OFFICER = "FinanceOfficer"
    AUDITOR = "Auditor"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorType(str, Enum):
    LANDLORD = "LANDLORD"
    UTILITY = "UTILITY"


class ApplicationStatus(str, Enum):
    INTAKE = "INTAKE"
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PENDING_DECISION = "PENDING_DECISION"
    WAITLISTED = "WAITLISTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class ApplicationCategory(str, Enum):
    RENT = "RENT"
    UTILITY = "UTILITY"


class DenialReason(str, Enum):
    INELIGIBLE_INCOME = "INELIGIBLE_INCOME"
    CAP_EXHAUSTED = "CAP_EXHAUSTED"
    DUPLICATE_BENEFIT = "DUPLICATE_BENEFIT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ELIGIBILITY_LAPSED = "ELIGIBILITY_LAPSED"
    PROGRAM_DIRECTED = "PROGRAM_DIRECTED"


class DocumentType(str, Enum):
    EVICTION_NOTICE = "EVICTION_NOTICE"
    LEASE_LEDGER = "LEASE_LEDGER"
    UTILITY_BILL = "UTILITY_BILL"
    ID_VERIFICATION = "ID_VERIFICATION"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class DuplicationCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class FundingSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class FundingSourceType(str, Enum):
    DONOR_UNRESTRICTED = "DONOR_UNRESTRICTED"
    GRANT_RESTRICTED = "GRANT_RESTRICTED"
    GOVERNMENT = "GOVERNMENT"


class PaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class CaseNoteType(str, Enum):
    GENERAL = "GENERAL"
    FOLLOW_UP = "FOLLOW_UP"
    DUPLICATION_CHECK = "DUPLICATION_CHECK"
    COMMUNICATION = "COMMUNICATION"


class CaseNoteOutcome(str, Enum):
    CRISIS_RESOLVED = "CRISIS_RESOLVED"
    PARTIAL_RELIEF = "PARTIAL_RELIEF"
    NO_CHANGE = "NO_CHANGE"
    LOST_CONTACT = "LOST_CONTACT"


class Household(TypedDict, total=False):
    id: str
    head_of_household_name: str
    address: str
    phone: str
    household_size: int
    annual_income_cents: int
    created_at: str
    updated_at: str
    version: int


class EligibilityPolicy(TypedDict, total=False):
    id: str
    name: str
    max_annual_benefit_cents: int
    rent_cap_cents: int
    utility_cap_cents: int
    income_limit_cents: int
    appeal_window_days: int
    require_eviction_notice: bool
    require_lease_ledger: bool
    require_utility_bill: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    vendor_type: str
    contact_name: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssistanceApplication(TypedDict, total=False):
    id: str
    household_id: str
    vendor_id: str
    policy_id: str
    category: str
    requested_amount_cents: int
    service_month: str
    intake_caseworker_id: str
    status: str
    active_award_id: str
    submitted_at: str
    waitlisted_at: str
    denied_at: str
    denial_reason: str
    closed_at: str
    created_at: str
    updated_at: str
    version: int


class ApplicationDocument(TypedDict, total=False):
    # Append-only ledger (PRD §2.5): id + created_at only.
    id: str
    application_id: str
    doc_type: str
    file_reference: str
    uploaded_by: str
    created_at: str


class VendorVerification(TypedDict, total=False):
    id: str
    application_id: str
    vendor_id: str
    verifier_id: str
    status: str
    confirmed_amount_cents: int
    outcome_notes: str
    completed_at: str
    created_at: str
    updated_at: str
    version: int


class DuplicationCheck(TypedDict, total=False):
    id: str
    application_id: str
    agency_name: str
    recorded_by: str
    status: str
    resolution_notes: str
    override_justification: str
    created_at: str
    updated_at: str
    version: int


class AssistanceAward(TypedDict, total=False):
    id: str
    application_id: str
    policy_id: str
    awarded_amount_cents: int
    benefit_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict, total=False):
    id: str
    award_id: str
    funding_source_id: str
    allocated_cents: int
    consumed_cents: int
    rank_order: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict, total=False):
    id: str
    name: str
    funder_name: str
    source_type: str
    allowed_categories: List[str]
    period_start: str
    period_end: str
    total_budget_cents: int
    max_per_household_cents: int
    reserved_cents: int
    committed_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    award_id: str
    vendor_id: str
    funding_source_id: str
    amount_cents: int
    payment_date: str
    status: str
    issued_by: str
    cleared_at: str
    created_at: str
    updated_at: str
    version: int


class CaseNote(TypedDict, total=False):
    # Append-only ledger (PRD §2.5): id + created_at only.
    id: str
    application_id: str
    author_id: str
    note_type: str
    body: str
    outcome: str
    occurred_at: str
    created_at: str


class ReplenishmentRun(TypedDict, total=False):
    # Append-only ledger (PRD §2.5): id + created_at only.
    id: str
    run_by: str
    promoted_count: int
    denied_count: int
    remaining_waitlisted_count: int
    promoted_application_ids: List[str]
    denied_application_ids: List[str]
    created_at: str
