"""Domain types: entity TypedDicts, status enums, role/input enums.

All entities in this API carry the four common properties id, created_at,
updated_at, and version (PRD §2.4), so every TypedDict lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RIGHTS_HOLDER = "RightsHolder"
    EXAMINER = "Examiner"
    COMPLAINANT = "Complainant"
    ADMIN = "Admin"


# --------------------------------------------------------------------------
# Input enums
# --------------------------------------------------------------------------
class WorkType(str, Enum):
    LITERARY = "LITERARY"
    MUSICAL = "MUSICAL"
    SOUND_RECORDING = "SOUND_RECORDING"
    VISUAL_ARTS = "VISUAL_ARTS"
    DRAMATIC = "DRAMATIC"
    ARCHITECTURAL = "ARCHITECTURAL"
    MOTION_PICTURE = "MOTION_PICTURE"


class FilingBasis(str, Enum):
    SINGLE_AUTHOR_SINGLE_WORK = "SINGLE_AUTHOR_SINGLE_WORK"
    STANDARD = "STANDARD"


class DepositType(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    PHYSICAL = "PHYSICAL"


class LicenseType(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class RightType(str, Enum):
    REPRODUCTION = "REPRODUCTION"
    DISTRIBUTION = "DISTRIBUTION"
    PERFORMANCE = "PERFORMANCE"
    DERIVATIVE = "DERIVATIVE"
    PUBLIC_DISPLAY = "PUBLIC_DISPLAY"


class Territory(str, Enum):
    US = "US"
    EU = "EU"
    WORLD = "WORLD"


class RoyaltyBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class WorkRegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    CORRESPONDENCE = "CORRESPONDENCE"
    REGISTERED = "REGISTERED"
    REFUSED = "REFUSED"
    WITHDRAWN = "WITHDRAWN"


class DepositStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    RENEWED = "RENEWED"


class RecordationStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    TERMINATED = "TERMINATED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    DISTRIBUTED = "DISTRIBUTED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class DmcaTakedownStatus(str, Enum):
    FILED = "FILED"
    EFFECTIVE = "EFFECTIVE"
    COUNTERED = "COUNTERED"
    RESTORED = "RESTORED"
    WITHDRAWN = "WITHDRAWN"


class CounterNoticeStatus(str, Enum):
    FORWARDED = "FORWARDED"
    COMPLETE = "COMPLETE"


class TerminationStatus(str, Enum):
    NOTICE_SERVED = "NOTICE_SERVED"
    EFFECTIVE = "EFFECTIVE"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Work(TypedDict, total=False):
    id: str
    title: str
    work_type: str
    year_of_creation: int
    author_name: str
    is_published: bool
    publication_date: Optional[str]
    owner_shares: List[dict]
    owner_user_id: str
    registration_status: str
    current_owner_name: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    work_id: str
    applicant_user_id: str
    filing_basis: str
    claimant_count: int
    is_expedited: bool
    status: str
    fee_due_cents: int
    fee_paid_cents: int
    fee_refunded_cents: int
    net_fee_cents: int
    correspondence_open: bool
    correspondence_deadline: Optional[str]
    correspondence_rounds: int
    submitted_at: Optional[str]
    fee_paid_at: Optional[str]
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    application_id: str
    deposit_type: str
    copy_count: int
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    application_id: str
    registration_number: str
    effective_date: str
    decision_date: str
    status: str
    renewal_window_start: str
    renewal_deadline: str
    renewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recordation(TypedDict, total=False):
    id: str
    work_id: str
    transferor_name: str
    transferee_name: str
    execution_date: str
    status: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    work_id: str
    licensor_user_id: str
    licensee_name: str
    license_type: str
    right_type: str
    territory: str
    start_date: str
    end_date: str
    grant_date: str
    royalty_rate_bps: int
    royalty_basis: str
    status: str
    escrow_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    license_id: str
    period_start: str
    period_end: str
    gross_revenue_cents: int
    deduction_cents: int
    accrued_cents: int
    distributed_cents: int
    distribution: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class DmcaTakedown(TypedDict, total=False):
    id: str
    work_id: str
    complainant_user_id: str
    complainant_name: str
    infringing_url: str
    status: str
    effective_at: Optional[str]
    countered_at: Optional[str]
    restoration_earliest_date: Optional[str]
    restoration_latest_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CounterNotice(TypedDict, total=False):
    id: str
    takedown_id: str
    subscriber_user_id: str
    subscriber_name: str
    statement: str
    status: str
    forwarded_at: str
    created_at: str
    updated_at: str
    version: int


class Termination(TypedDict, total=False):
    id: str
    license_id: str
    terminating_party_name: str
    notice_served_date: str
    effective_date: str
    window_earliest_date: str
    window_latest_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
