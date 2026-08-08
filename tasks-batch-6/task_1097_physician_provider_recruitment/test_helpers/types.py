"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the common lifecycle fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Header role (X-User-Role values, spelled exactly per PRD §2.1) ---
class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    ACCOUNT_MANAGER = "AccountManager"
    CREDENTIALING_COORDINATOR = "CredentialingCoordinator"
    CLIENT_CONTACT = "ClientContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- StaffUser.role field values (distinct from the header role strings) ---
class StaffRole(str, Enum):
    RECRUITER = "RECRUITER"
    ACCOUNT_MANAGER = "ACCOUNT_MANAGER"
    CREDENTIALING_COORDINATOR = "CREDENTIALING_COORDINATOR"


class ActiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Specialty(str, Enum):
    FAMILY_MEDICINE = "FAMILY_MEDICINE"
    CARDIOLOGY = "CARDIOLOGY"
    PSYCHIATRY = "PSYCHIATRY"
    ORTHOPEDIC_SURGERY = "ORTHOPEDIC_SURGERY"
    EMERGENCY_MEDICINE = "EMERGENCY_MEDICINE"


class JobOpeningStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PLACED = "PLACED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


class ApplicationStage(str, Enum):
    SOURCED = "SOURCED"
    SCREENED = "SCREENED"
    SUBMITTED = "SUBMITTED"
    INTERVIEWING = "INTERVIEWING"
    OFFER_STAGE = "OFFER_STAGE"
    PLACED = "PLACED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RejectReason(str, Enum):
    CLIENT_PASS = "CLIENT_PASS"
    OPENING_FILLED = "OPENING_FILLED"
    WITHDRAWN_BY_CANDIDATE = "WITHDRAWN_BY_CANDIDATE"


class SiteVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OfferStatus(str, Enum):
    EXTENDED = "EXTENDED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"
    EXPIRED = "EXPIRED"


class PlacementStatus(str, Enum):
    PRE_START = "PRE_START"
    ACTIVE = "ACTIVE"
    GUARANTEE_MET = "GUARANTEE_MET"
    FELL_OUT = "FELL_OUT"
    CANCELLED = "CANCELLED"


class FeeStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"
    WAIVED = "WAIVED"


class RelocationStatus(str, Enum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    REIMBURSED = "REIMBURSED"


class CredentialingFileStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class CredentialItemType(str, Enum):
    STATE_LICENSE = "STATE_LICENSE"
    DEA_REGISTRATION = "DEA_REGISTRATION"
    BOARD_CERTIFICATION = "BOARD_CERTIFICATION"
    MALPRACTICE_HISTORY = "MALPRACTICE_HISTORY"
    REFERENCE = "REFERENCE"


class CredentialItemStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class RelocationCategory(str, Enum):
    MOVERS = "MOVERS"
    TEMP_HOUSING = "TEMP_HOUSING"
    FLIGHTS = "FLIGHTS"
    LICENSING_FEES = "LICENSING_FEES"
    OTHER = "OTHER"


class RelocationExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GuaranteeClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_REPLACEMENT = "RESOLVED_REPLACEMENT"


class StaffUser(TypedDict):
    id: str
    role: str
    full_name: str
    email: str
    covered_specialties: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    name: str
    region: str
    account_manager_id: str
    contingency_pct: float
    min_fee_cents: int
    guarantee_days: int
    status: str
    net_placement_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class JobOpening(TypedDict):
    id: str
    client_id: str
    specialty: str
    region: str
    region_state: str
    comp_min_cents: int
    comp_max_cents: int
    is_hard_to_fill: bool
    positions_total: int
    positions_filled: int
    recruiter_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    recruiter_id: str
    full_name: str
    specialty: str
    home_region: str
    license_states: List[str]
    desired_comp_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    candidate_id: str
    opening_id: str
    recruiter_id: str
    match_score: int
    stage: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteVisit(TypedDict):
    id: str
    application_id: str
    interviewer_user_id: str
    scheduled_start: str
    scheduled_end: str
    location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    application_id: str
    base_salary_cents: int
    sign_on_bonus_cents: int
    start_date: str
    relocation_cap_cents: int
    expires_at: str
    round_number: int
    extended_by_user_id: str
    offered_first_year_comp_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    offer_id: str
    application_id: str
    client_id: str
    candidate_id: str
    opening_id: str
    start_date: str
    fee_estimate_cents: int
    final_first_year_comp_cents: Optional[int]
    placement_fee_cents: int
    relocation_cap_cents: int
    relocation_reimbursed_cents: int
    relocation_status: str
    guarantee_end_date: Optional[str]
    placement_status: str
    fee_status: str
    created_at: str
    updated_at: str
    version: int


class CredentialingFile(TypedDict):
    id: str
    placement_id: str
    candidate_id: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class CredentialItem(TypedDict):
    id: str
    credentialing_file_id: str
    item_type: str
    is_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RelocationExpense(TypedDict):
    id: str
    placement_id: str
    category: str
    amount_cents: int
    is_taxable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict):
    id: str
    placement_id: str
    client_id: str
    fell_out_date: str
    reason: str
    replacement_placement_id: Optional[str]
    days_worked: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
