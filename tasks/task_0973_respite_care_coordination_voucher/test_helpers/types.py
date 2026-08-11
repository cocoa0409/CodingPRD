"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CAREGIVER = "Caregiver"
    PROVIDER = "Provider"
    COORDINATOR = "Coordinator"
    FUNDER_ADMIN = "FunderAdmin"


class ProgramPosture(str, Enum):
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    ENROLLMENT_PAUSED = "ENROLLMENT_PAUSED"
    PROGRAM_SUSPENDED = "PROGRAM_SUSPENDED"
    CLOSED = "CLOSED"


class CaregiverStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REDETERMINATION_PENDING = "REDETERMINATION_PENDING"
    DISENROLLED = "DISENROLLED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    WITHDRAWN = "WITHDRAWN"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    COMMITTED = "COMMITTED"
    REDEEMED = "REDEEMED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CredentialStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_BOOKED = "FULLY_BOOKED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class BookingStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class VisitStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"


class EmergencyStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SnapshotStatus(str, Enum):
    GENERATED = "GENERATED"
    FINALIZED = "FINALIZED"
    SUBMITTED_TO_FUNDER = "SUBMITTED_TO_FUNDER"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    RESUBMITTED = "RESUBMITTED"


class LedgerEntryType(str, Enum):
    ENCUMBER = "ENCUMBER"
    RELEASE = "RELEASE"
    SETTLE = "SETTLE"
    ADJUSTMENT = "ADJUSTMENT"


# --- Entity shapes (PRD §2.4: id/created_at/updated_at/version on most resources) ---

class Program(TypedDict, total=False):
    id: str
    name: str
    fiscal_year_start: str
    posture: str
    total_budget_cents: int
    encumbered_cents: int
    settled_cents: int
    unencumbered_cents: int
    emergency_reserve_hours: int
    emergency_hours_used: float
    quarterly_cap_hours: float
    annual_cap_hours: float
    standard_rate_cents_per_hour: int
    weekend_multiplier: float
    evening_multiplier: float
    evening_start_hour: int
    emergency_multiplier: float
    credential_premium_multiplier: float
    max_overage_pct: float
    voucher_expiry_days: int
    carryover_cap_pct: float
    no_show_grace_minutes: int
    auto_close_grace_hours: int
    appeal_window_days: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Caregiver(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    care_recipient_name: str
    care_recipient_condition: str
    status: str
    redetermination_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityApplication(TypedDict, total=False):
    id: str
    caregiver_id: str
    need_score: int
    notes: str
    status: str
    revision_count: int
    review_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    caregiver_id: str
    program_id: str
    period_start: str
    period_end: str
    granted_hours: float
    available_hours: float
    reserved_hours: float
    consumed_hours: float
    expired_hours: float
    revoked_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    allocation_id: Optional[str]
    program_id: str
    caregiver_id: str
    is_emergency: bool
    authorized_hours: float
    committed_hours: float
    consumed_hours: float
    released_hours: float
    forfeited_hours: float
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    name: str
    credential_level: str
    service_zip: str
    accepts_emergency: bool
    credential_status: str
    credential_expires_at: Optional[str]
    quality_score_simple: Optional[float]
    quality_score_weighted: Optional[float]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict, total=False):
    id: str
    provider_id: str
    start_at: str
    end_at: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    voucher_id: str
    caregiver_id: str
    provider_id: str
    window_id: Optional[str]
    emergency_request_id: Optional[str]
    is_emergency: bool
    auto_matched: bool
    start_at: str
    end_at: str
    committed_minutes: int
    status: str
    provisional_amount_cents: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VisitRecord(TypedDict, total=False):
    id: str
    booking_id: str
    check_in_at: str
    check_in_location: str
    check_out_at: Optional[str]
    tasks_completed: List[str]
    auto_closed: bool
    verified_minutes: Optional[int]
    payable_minutes: Optional[int]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    visit_record_id: str
    voucher_id: str
    provider_id: str
    provisional_amount_cents: int
    amount_cents: int
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only fact table (PRD §2.4): carries ONLY id + created_at.
class BudgetLedgerEntry(TypedDict, total=False):
    id: str
    program_id: str
    entry_type: str
    amount_cents: int
    ref_type: str
    ref_id: str
    note: str
    created_at: str


class EmergencyRequest(TypedDict, total=False):
    id: str
    caregiver_id: str
    needed_start_at: str
    needed_end_at: str
    reason: str
    requested_hours: float
    approved_hours: Optional[float]
    status: str
    dispatched_booking_id: Optional[str]
    selected_provider_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SatisfactionSurvey(TypedDict, total=False):
    id: str
    booking_id: str
    caregiver_id: str
    provider_id: str
    rating: int
    would_rebook: bool
    comments: str
    created_at: str
    updated_at: str
    version: int


class ReportSnapshot(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    status: str
    utilization_projected_pct: float
    utilization_settled_pct: float
    total_granted_hours: float
    consumed_hours: float
    reserved_hours: float
    claims_paid_count: int
    total_paid_amount_cents: int
    emergency_hours_used: float
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int
