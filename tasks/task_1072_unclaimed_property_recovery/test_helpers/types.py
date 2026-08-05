"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    STATE_ADMIN = "StateAdmin"
    HOLDER = "Holder"
    OWNER = "Owner"
    RECOVERY_AGENT = "RecoveryAgent"
    STATE_EXAMINER = "StateExaminer"
    STATE_APPROVER = "StateApprover"


class HolderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HolderType(str, Enum):
    BANK = "BANK"
    INSURER = "INSURER"
    UTILITY = "UTILITY"
    BROKER = "BROKER"
    OTHER = "OTHER"


class DormancyBasis(str, Enum):
    LAST_ACTIVITY = "LAST_ACTIVITY"
    ISSUANCE = "ISSUANCE"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    REPORTED = "REPORTED"
    ESCHEATED = "ESCHEATED"
    CLAIMED = "CLAIMED"


class NoticeMethod(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"


class HolderReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FiledBy(str, Enum):
    OWNER = "OWNER"
    FIRM = "FIRM"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class DocType(str, Enum):
    GOV_ID = "GOV_ID"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"
    DEATH_CERTIFICATE = "DEATH_CERTIFICATE"
    OWNERSHIP_PROOF = "OWNERSHIP_PROOF"


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    INFO_REQUESTED = "INFO_REQUESTED"
    CLOSED_NO_FINDING = "CLOSED_NO_FINDING"
    CLOSED_ASSESSED = "CLOSED_ASSESSED"


class LedgerEntryType(str, Enum):
    REMIT_IN = "REMIT_IN"
    PAYOUT_OUT = "PAYOUT_OUT"
    FEE_OUT = "FEE_OUT"
    CLAWBACK_IN = "CLAWBACK_IN"


# --- Entity TypedDicts ---
# Full-field entities carry id + created_at + updated_at + version.

class Holder(TypedDict):
    id: str
    legal_name: str
    incorporation_state: str
    holder_type: str
    status: str
    audit_hold: bool
    assessed_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


# PropertyType: lightweight config record — only id + created_at.
class PropertyType(TypedDict):
    id: str
    code: str
    name: str
    dormancy_period_years: int
    dormancy_basis: str
    interest_bearing: bool
    due_diligence_required: bool
    due_diligence_min_days: int
    created_at: str


class StateAccount(TypedDict):
    id: str
    state_code: str
    custody_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    full_name: str
    ssn_last4: str
    address_state: str
    email: str
    id_verified: bool
    created_at: str
    updated_at: str
    version: int


class RecoveryFirm(TypedDict):
    id: str
    legal_name: str
    registered_state: str
    license_number: str
    max_fee_pct: float
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    holder_id: str
    property_type_id: str
    owner_name: str
    owner_last_known_state: Optional[str]
    amount_cents: int
    last_activity_date: str
    issue_date: Optional[str]
    escheat_state: str
    dormancy_date: str
    remitted_amount_cents: int
    report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DueDiligenceNotice(TypedDict):
    id: str
    property_id: str
    method: str
    sent_at: str
    responded: bool
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HolderReport(TypedDict):
    id: str
    holder_id: str
    report_state: str
    report_period_year: int
    property_count: int
    total_remitted_cents: int
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    property_id: str
    claimant_owner_id: str
    recovery_firm_id: Optional[str]
    filed_by: str
    contract_fee_pct: float
    claim_amount_cents: int
    provisional_fee_cents: int
    fee_cents: int
    admin_deduction_cents: int
    net_payout_cents: int
    examiner_user_id: Optional[str]
    approver_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict):
    id: str
    holder_id: str
    examiner_user_id: str
    assessed_penalty_cents: int
    findings: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# LedgerEntry: immutable append-only accounting record — only id + created_at.
class LedgerEntry(TypedDict):
    id: str
    state_account_id: str
    property_id: Optional[str]
    ref_claim_id: Optional[str]
    ref_report_id: Optional[str]
    entry_type: str
    amount_cents: int
    created_at: str
