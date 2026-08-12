"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class BuildingStatus(str, Enum):
    ACADEMIC_USE = "ACADEMIC_USE"
    RELEASE_REVIEW = "RELEASE_REVIEW"
    RELEASED = "RELEASED"
    TURN_ACTIVE = "TURN_ACTIVE"
    FALL_PREP = "FALL_PREP"
    READY_FOR_FALL = "READY_FOR_FALL"


class RoomStatus(str, Enum):
    ACADEMIC_OCCUPIED = "ACADEMIC_OCCUPIED"
    RELEASED = "RELEASED"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    NEEDS_TURN = "NEEDS_TURN"
    IN_TURN = "IN_TURN"
    READY = "READY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class GroupStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    CONFIRMED = "CONFIRMED"
    IN_HOUSE = "IN_HOUSE"
    DEPARTED = "DEPARTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ParticipantRole(str, Enum):
    ATTENDEE = "ATTENDEE"
    CHAPERONE = "CHAPERONE"
    STAFF = "STAFF"


class RevisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    APPEALED = "APPEALED"
    DENIED = "DENIED"


class TurnTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_INSPECTION = "READY_FOR_INSPECTION"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LinenIssueStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RECONCILED = "RECONCILED"


class KeyCredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVATED = "ACTIVATED"
    RETURNED = "RETURNED"
    LOST = "LOST"


class DamageAssessmentStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class MaintenanceWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AllocationRunStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class LinenTier(str, Enum):
    STANDARD = "STANDARD"
    DELUXE = "DELUXE"


class UserRole(str, Enum):
    CONFERENCE_SERVICES_ADMIN = "ConferenceServicesAdmin"
    FACILITIES_MANAGER = "FacilitiesManager"
    HOUSEKEEPING_SUPERVISOR = "HousekeepingSupervisor"
    FINANCE_OFFICER = "FinanceOfficer"
    SCREENING_REVIEWER = "ScreeningReviewer"
    CLIENT_COORDINATOR = "ClientCoordinator"


class Building(TypedDict, total=False):
    id: str
    name: str
    fall_opening_date: str
    key_pool_size: int
    status: str
    released_bed_count: int
    reserved_bed_count: int
    available_bed_count: int
    scheduled_turn_count: int
    out_of_service_room_count: int
    available_key_count: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    building_id: str
    room_number: str
    bed_count: int
    status: str
    active_turn_task_id: Optional[str]
    out_of_service_window_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConferenceGroup(TypedDict, total=False):
    id: str
    building_id: str
    client_name: str
    contact_email: str
    arrival_date: str
    departure_date: str
    has_minor_participants: bool
    linen_tier: str
    contracted_bed_count: int
    deposit_paid_cents: int
    status: str
    provisional_invoice_id: Optional[str]
    cancellation_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    group_id: str
    full_name: str
    date_of_birth: str
    role_in_group: str
    is_minor: bool
    created_at: str
    updated_at: str
    version: int


# RoomingListRevision is immutable once written (PRD section on common resource
# properties): it carries only id and created_at — no updated_at, no version.
class RoomingListRevision(TypedDict, total=False):
    id: str
    group_id: str
    revision_number: int
    status: str
    assignment_ids: List[str]
    superseded_at: Optional[str]
    created_at: str


class StayAssignment(TypedDict, total=False):
    id: str
    revision_id: str
    group_id: str
    room_id: str
    participant_id: str
    checkin_at: str
    checkout_at: str
    actual_checkin_at: Optional[str]
    actual_checkout_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundScreening(TypedDict, total=False):
    id: str
    participant_id: str
    consent_reference: str
    status: str
    decided_at: Optional[str]
    cleared_on: Optional[str]
    is_expired: bool
    appeal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TurnTask(TypedDict, total=False):
    id: str
    room_id: str
    window_start: str
    window_end: str
    linen_tier: str
    status: str
    rework_count: int
    inspector_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LinenIssue(TypedDict, total=False):
    id: str
    group_id: str
    packs_issued: int
    packs_returned: int
    packs_damaged: int
    status: str
    loss_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class KeyCredential(TypedDict, total=False):
    id: str
    group_id: str
    participant_id: str
    credential_code: str
    status: str
    returned_at: Optional[str]
    late_fee_cents: Optional[int]
    lost_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DamageLineItem(TypedDict):
    description: str
    quantity: int
    unit_replacement_cost_cents: int
    fixture_age_months: int


class DamageAssessment(TypedDict, total=False):
    id: str
    room_id: str
    group_id: str
    line_items: List[Dict[str, Any]]
    estimate_total_cents: int
    assessed_total_cents: Optional[int]
    assessed_at: Optional[str]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    group_id: str
    status: str
    provisional_bed_night_subtotal_cents: int
    provisional_total_cents: int
    final_bed_night_subtotal_cents: Optional[int]
    linen_charge_cents: Optional[int]
    key_charge_cents: Optional[int]
    damage_charge_cents: Optional[int]
    total_cents: Optional[int]
    balance_due_cents: Optional[int]
    finalized_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    building_id: str
    start_date: str
    end_date: str
    buffer_days: int
    blocked_start_date: str
    blocked_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    building_id: str
    period_start: str
    period_end: str
    gross_cents: int
    overhead_cents: int
    reserve_cents: int
    ops_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
