"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    RECOVERY_SPECIALIST = "RecoverySpecialist"
    RECOVERY_SUPERVISOR = "RecoverySupervisor"
    RECOVERY_ACCOUNTANT = "RecoveryAccountant"
    ESTATE_RECOVERY_OFFICER = "EstateRecoveryOfficer"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"


class RecoveryApproach(str, Enum):
    SUBROGATION = "SUBROGATION"
    REIMBURSEMENT = "REIMBURSEMENT"


class TplCaseStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ATTORNEY_NOTIFIED = "ATTORNEY_NOTIFIED"
    LIEN_FILED = "LIEN_FILED"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    RESOLVED = "RESOLVED"
    CLOSED_NO_RECOVERY = "CLOSED_NO_RECOVERY"
    SOL_EXPIRED = "SOL_EXPIRED"


class LitigationStatus(str, Enum):
    NO_SUIT = "NO_SUIT"
    SUIT_FILED = "SUIT_FILED"
    JUDGMENT = "JUDGMENT"
    SUIT_DISMISSED = "SUIT_DISMISSED"


class LitigationEvent(str, Enum):
    FILE_SUIT = "FILE_SUIT"
    RECORD_JUDGMENT = "RECORD_JUDGMENT"
    RECORD_DISMISSAL = "RECORD_DISMISSAL"


class LienStatus(str, Enum):
    FILED = "FILED"
    AMENDED = "AMENDED"
    SATISFIED = "SATISFIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"


class OfferedBy(str, Enum):
    INSURER = "INSURER"
    STATE = "STATE"


class PostingStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class EstateCaseStatus(str, Enum):
    OPENED = "OPENED"
    CLAIM_FILED = "CLAIM_FILED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    TIME_BARRED = "TIME_BARRED"


class WaiverType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class NoticeType(str, Enum):
    LIEN_FILED_NOTICE = "LIEN_FILED_NOTICE"
    SETTLEMENT_NOTICE = "SETTLEMENT_NOTICE"
    CASE_RESOLUTION_NOTICE = "CASE_RESOLUTION_NOTICE"
    ESTATE_CLAIM_NOTICE = "ESTATE_CLAIM_NOTICE"
    ESTATE_DECISION_NOTICE = "ESTATE_DECISION_NOTICE"


class NoticeStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class Member(TypedDict):
    id: str
    medicaid_id: str
    full_name: str
    state_code: str
    recovery_approach: str
    date_of_death: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TplCase(TypedDict):
    id: str
    member_id: str
    attorney_name: str
    attorney_email: str
    injury_date: str
    third_party_insurer: str
    status: str
    litigation_status: str
    sol_date: str
    attorney_notified_at: Optional[str]
    total_paid_claims_cents: int
    total_recovered_cents: int
    created_at: str
    updated_at: str
    version: int


class ExpenseClaim(TypedDict):
    id: str
    case_id: str
    service_date: str
    paid_amount_cents: int
    claim_reference: str
    included_in_lien_basis: bool
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    case_id: str
    lien_amount_cents: int
    statutory_cap_cents: int
    outstanding_cents: int
    status: str
    filed_at: str
    amended_count: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    case_id: str
    round_number: int
    status: str
    gross_amount_cents: int
    attorney_fee_pct: float
    litigation_costs_cents: int
    offered_by: str
    created_by_user_id: str
    fee_amount_cents: int
    cost_share_cents: int
    state_recovery_cents: int
    member_net_cents: int
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryPosting(TypedDict):
    id: str
    settlement_id: str
    lien_id: str
    contractor_code: str
    gross_recovery_cents: int
    commission_cents: Optional[int]
    net_to_state_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EstateCase(TypedDict):
    id: str
    member_id: str
    date_of_death: str
    lifetime_paid_cents: int
    probate_case_number: Optional[str]
    exempt_services_cents: Optional[int]
    provisional_claim_cents: int
    claim_amount_cents: Optional[int]
    claim_outstanding_cents: int
    total_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HardshipWaiver(TypedDict):
    id: str
    estate_case_id: str
    waiver_type: str
    household_income_annual_cents: int
    homestead_value_cents: int
    requested_reduction_cents: Optional[int]
    decided_reduction_cents: Optional[int]
    appeal_count: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunicationNotice(TypedDict):
    id: str
    member_id: str
    case_id: Optional[str]
    estate_case_id: Optional[str]
    notice_type: str
    status: str
    due_date: str
    sent_at: Optional[str]
    is_late: Optional[bool]
    created_at: str
    updated_at: str
    version: int
