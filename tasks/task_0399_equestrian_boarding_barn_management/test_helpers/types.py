"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the full common-field set (id, created_at,
updated_at, version) per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class StallKind(str, Enum):
    STALL = "STALL"
    PASTURE = "PASTURE"


class BoardingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ServiceVisitType(str, Enum):
    FARRIER = "FARRIER"
    VET = "VET"
    DENTIST = "DENTIST"


class ServiceVisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShowEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    SCRATCHED = "SCRATCHED"
    WITHDRAWN = "WITHDRAWN"


class TurnoutStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class UserRole(str, Enum):
    BARN_MANAGER = "BarnManager"
    OWNER = "Owner"
    INSTRUCTOR = "Instructor"
    SERVICE_PROVIDER = "ServiceProvider"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: true)
# ---------------------------------------------------------------------------
class Owner(TypedDict):
    id: str
    full_name: str
    email: str
    deposit_held_cents: int
    account_balance_cents: int
    standing_score: int
    provisional_standing_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityWaiver(TypedDict):
    id: str
    owner_id: str
    signed_at: Optional[str]
    expires_at: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict):
    id: str
    label: str
    kind: str
    capacity: int
    daily_rate_cents: int
    occupied_count: int
    created_at: str
    updated_at: str
    version: int


class Horse(TypedDict):
    id: str
    owner_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class BoardingAgreement(TypedDict):
    id: str
    horse_id: str
    stall_id: str
    start_date: str
    end_date: Optional[str]
    suspended_days: int
    provisional_charge_cents: int
    final_charge_cents: int
    suspended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    horse_id: str
    instructor_name: str
    lesson_fee_cents: int
    starts_at: str
    ends_at: str
    billed_fee_cents: int
    invoiced: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    horse_id: str
    visit_type: str
    scheduled_at: str
    duration_minutes: int
    fee_cents: int
    invoiced: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowEntry(TypedDict):
    id: str
    horse_id: str
    event_name: str
    event_date: str
    entry_fee_cents: int
    invoiced: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TurnoutAssignment(TypedDict):
    id: str
    horse_id: str
    pasture_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    owner_id: str
    period_label: str
    gross_amount_cents: int
    multi_horse_discount_cents: int
    deposit_applied_cents: int
    amount_due_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
