"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DOCKETING_CLERK = "DocketingClerk"
    DOCKETING_MANAGER = "DocketingManager"
    RECORDS_SPECIALIST = "RecordsSpecialist"
    FINANCE_OFFICER = "FinanceOfficer"
    CLIENT_APPROVER = "ClientApprover"
    OUTSIDE_COUNSEL = "OutsideCounsel"


class Jurisdiction(str, Enum):
    US = "US"
    EP = "EP"
    JP = "JP"
    CN = "CN"
    KR = "KR"
    PCT = "PCT"


class ApplicationType(str, Enum):
    ORIGINAL = "ORIGINAL"
    PARIS_CONVENTION = "PARIS_CONVENTION"
    PCT_INTERNATIONAL = "PCT_INTERNATIONAL"
    PCT_NATIONAL_PHASE = "PCT_NATIONAL_PHASE"
    CONTINUATION = "CONTINUATION"
    DIVISIONAL = "DIVISIONAL"


class EntitySize(str, Enum):
    LARGE = "LARGE"
    SMALL = "SMALL"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PRUNING_REVIEW = "PRUNING_REVIEW"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    ABANDONED = "ABANDONED"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class DocketEntryType(str, Enum):
    OFFICE_ACTION_RESPONSE = "OFFICE_ACTION_RESPONSE"
    STATUTORY = "STATUTORY"
    PARIS_PRIORITY = "PARIS_PRIORITY"
    PCT_PHASE = "PCT_PHASE"
    ANNUITY = "ANNUITY"
    RECORDATION = "RECORDATION"


class DocketEntryStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESPONSE_FILED = "RESPONSE_FILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class OfficeActionType(str, Enum):
    NON_FINAL_REJECTION = "NON_FINAL_REJECTION"
    FINAL_REJECTION = "FINAL_REJECTION"
    NOTICE_OF_ALLOWANCE = "NOTICE_OF_ALLOWANCE"
    INFORMATIONAL = "INFORMATIONAL"


class OfficeActionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_RESPONSE = "UNDER_RESPONSE"
    CLOSED = "CLOSED"


class AnnuityObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    PAYMENT_INSTRUCTED = "PAYMENT_INSTRUCTED"
    CONFIRMATION_QUERY = "CONFIRMATION_QUERY"
    PAID_CONFIRMED = "PAID_CONFIRMED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class PaymentAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class InstructionType(str, Enum):
    FILING = "FILING"
    OA_RESPONSE = "OA_RESPONSE"
    ANNUITY_PAYMENT = "ANNUITY_PAYMENT"
    RECORDATION = "RECORDATION"


class InstructionStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class AbandonmentReviewStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class AssignmentRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    RECORDATION_REJECTED = "RECORDATION_REJECTED"
    RECORDED = "RECORDED"


class DocketAuditStatus(str, Enum):
    OPEN = "OPEN"
    VARIANCE_FOUND = "VARIANCE_FOUND"
    RESOLVED = "RESOLVED"
    CLOSED_CLEAN = "CLOSED_CLEAN"


# --- Entity TypedDicts (all entities carry the common system fields of PRD §2.6) ---

class JurisdictionRule(TypedDict, total=False):
    id: str
    jurisdiction: str
    oa_response_months: int
    max_extensions: int
    extension_months: int
    extension_fee_cents: int
    annuity_start_year: int
    term_years: int
    surcharge_window_months: int
    surcharge_bps_month_1: int
    surcharge_bps_late: int
    small_entity_multiplier_bps: int
    fee_tier_bounds: str
    fee_tier_1_cents: int
    fee_tier_2_cents: int
    fee_tier_3_cents: int
    fee_tier_4_cents: int
    paris_window_months: int
    pct_window_months: int
    fx_to_usd_cents_bps: int
    requires_recorded_assignment_for_grant: bool
    requires_recorded_assignment_for_payment: bool
    requires_confirmed_instruction_for_payment: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    display_name: str
    default_currency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClientContact(TypedDict, total=False):
    id: str
    client_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class CounselFirm(TypedDict, total=False):
    id: str
    display_name: str
    accredited_jurisdictions: List[str]
    created_at: str
    updated_at: str
    version: int


class Inventor(TypedDict, total=False):
    id: str
    client_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class PatentFamily(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    first_priority_date: str
    budget_cap_cents: int
    status: str
    committed_forecast_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    family_id: str
    jurisdiction: str
    application_type: str
    filing_date: str
    application_number: str
    entity_size: str
    parent_application_id: Optional[str]
    grant_date: Optional[str]
    status: str
    open_docket_count: int
    created_at: str
    updated_at: str
    version: int


class DocketEntry(TypedDict, total=False):
    id: str
    application_id: str
    entry_type: str
    title: str
    base_due_date: str
    extension_count: int
    extension_fees_total_cents: int
    current_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficeAction(TypedDict, total=False):
    id: str
    application_id: str
    action_type: str
    mail_date: str
    docket_entry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnuityObligation(TypedDict, total=False):
    id: str
    application_id: str
    period_year: int
    due_date: str
    surcharge_window_end: str
    base_fee_local_cents: int
    estimated_amount_usd_cents: int
    authorized_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentAuthorization(TypedDict, total=False):
    id: str
    annuity_obligation_id: str
    amount_cents: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutsideCounselInstruction(TypedDict, total=False):
    id: str
    application_id: str
    counsel_firm_id: str
    docket_entry_id: Optional[str]
    instruction_type: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AbandonmentReview(TypedDict, total=False):
    id: str
    application_id: str
    rationale: str
    estimated_savings_usd_cents: int
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssignmentRecord(TypedDict, total=False):
    id: str
    application_id: str
    assignee_name: str
    inventor_ids: List[str]
    execution_date: str
    executed_by_user_id: Optional[str]
    register_recordation_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DocketAudit(TypedDict, total=False):
    id: str
    application_id: str
    window_start: str
    window_end: str
    register_entries: List[Any]
    variances: List[Any]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
