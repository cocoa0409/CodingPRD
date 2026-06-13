"""Domain types: entity TypedDicts, status enums, role enum (Private Adoption Agency API)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    SUPERVISOR = "Supervisor"
    CASEWORKER = "Caseworker"
    FINANCE_OFFICER = "FinanceOfficer"
    COMPACT_ADMINISTRATOR = "CompactAdministrator"


# ─── Status enums ───────────────────────────────────────────────────────────
class CasePhase(str, Enum):
    INTAKE = "INTAKE"
    HOME_STUDY = "HOME_STUDY"
    MATCHED = "MATCHED"
    CONSENTED = "CONSENTED"
    ICPC_CLEARED = "ICPC_CLEARED"
    PLACED = "PLACED"
    FINALIZED = "FINALIZED"
    DISRUPTED = "DISRUPTED"


class HomeStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESUBMITTED = "RESUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"


class CounselingSessionStatus(str, Enum):
    BOOKED = "BOOKED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    DISSOLVED = "DISSOLVED"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"
    IRREVOCABLE = "IRREVOCABLE"


class IcpcStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SENDING_APPROVED = "SENDING_APPROVED"
    RECEIVING_APPROVED = "RECEIVING_APPROVED"
    REJECTED = "REJECTED"


class PlacementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FINALIZED = "FINALIZED"
    DISRUPTED = "DISRUPTED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class ExpenseStatus(str, Enum):
    LOGGED = "LOGGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class BirthParentRole(str, Enum):
    BIRTH_MOTHER = "BIRTH_MOTHER"
    BIRTH_FATHER = "BIRTH_FATHER"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN"


class ExpenseCategory(str, Enum):
    MEDICAL = "MEDICAL"
    LEGAL = "LEGAL"
    LIVING = "LIVING"
    COUNSELING = "COUNSELING"
    TRAVEL = "TRAVEL"
    OTHER = "OTHER"


class RevocationBasis(str, Enum):
    CALENDAR_DAYS = "CALENDAR_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class TxnType(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"
    REFUND = "REFUND"


# ─── Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ──
class Agency(TypedDict):
    id: str
    name: str
    licensed_state: str
    fee_schedule_cents: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class AdoptionCase(TypedDict):
    id: str
    agency_id: str
    case_label: str
    child_state: str
    family_state: str
    phase: str
    escrow_balance_cents: int
    reimbursable_expense_cents: int
    interstate: bool
    created_at: str
    updated_at: str
    version: int


class AdoptiveFamily(TypedDict):
    id: str
    case_id: str
    primary_applicant_name: str
    residence_state: str
    household_size: int
    annual_income_cents: int
    created_at: str
    updated_at: str
    version: int


class HomeStudy(TypedDict):
    id: str
    case_id: str
    family_id: str
    authoring_caseworker_id: str
    approving_supervisor_id: Optional[str]
    completed_at: Optional[str]
    expires_at: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BirthParent(TypedDict):
    id: str
    agency_id: str
    legal_name: str
    birth_state: str
    parent_role: str
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    birth_parent_id: str
    case_id: str
    counselor_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    case_id: str
    family_id: str
    birth_parent_id: str
    proposed_by_caseworker_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    case_id: str
    birth_parent_id: str
    supersedes_consent_id: Optional[str]
    child_dob: str
    signed_at: Optional[str]
    revocation_deadline: Optional[str]
    revocation_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IcpcClearance(TypedDict):
    id: str
    case_id: str
    sending_state: str
    receiving_state: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    case_id: str
    family_id: str
    required_visits: int
    completed_visit_count: int
    placed_at: Optional[str]
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PostPlacementVisit(TypedDict):
    id: str
    case_id: str
    placement_id: str
    visiting_caseworker_id: str
    window_start: str
    window_end: str
    conducted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseEntry(TypedDict):
    id: str
    case_id: str
    logged_by_caseworker_id: str
    approved_by_finance_id: Optional[str]
    category: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyFeeInvoice(TypedDict):
    id: str
    case_id: str
    base_fee_cents: int
    sliding_scale_pct: float
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false -> id + created_at only) ──────
class EscrowTransaction(TypedDict):
    id: str
    case_id: str
    expense_id: Optional[str]
    txn_type: str
    amount_cents: int
    recorded_by_finance_id: str
    created_at: str
