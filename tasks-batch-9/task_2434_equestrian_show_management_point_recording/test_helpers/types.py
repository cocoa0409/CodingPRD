"""Domain types for the Equestrian Show Management API.

Status enums, role enum and entity TypedDicts. Every one of the fourteen
resource types exposes `id`, `created_at`, `updated_at` and `version`
(PRD §2.5), so every TypedDict below carries all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    SHOW_SECRETARY = "ShowSecretary"
    FEDERATION_OFFICER = "FederationOfficer"
    RING_MASTER = "RingMaster"
    JUDGE = "Judge"
    STEWARD = "Steward"
    EXHIBITOR = "Exhibitor"
    GROUNDS_MANAGER = "GroundsManager"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CompetitionLevel(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"
    PREMIER = "PREMIER"


class RingStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"


class SurfaceType(str, Enum):
    SAND_FIBER = "SAND_FIBER"
    GRASS = "GRASS"
    CLAY = "CLAY"


class DivisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Discipline(str, Enum):
    HUNTER = "HUNTER"
    JUMPER = "JUMPER"
    EQUITATION = "EQUITATION"
    DRESSAGE = "DRESSAGE"


class AgeGroup(str, Enum):
    JUNIOR = "JUNIOR"
    AMATEUR = "AMATEUR"
    OPEN = "OPEN"
    PONY = "PONY"


class ClassStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    JUDGED = "JUDGED"
    RESULTS_POSTED = "RESULTS_POSTED"
    POINTS_SUBMITTED = "POINTS_SUBMITTED"
    VOIDED = "VOIDED"


class SlotType(str, Enum):
    CLASS = "CLASS"
    MAINTENANCE = "MAINTENANCE"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OfficialRole(str, Enum):
    JUDGE = "JUDGE"
    STEWARD = "STEWARD"
    TECHNICAL_DELEGATE = "TECHNICAL_DELEGATE"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class VerificationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ClassEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    DISQUALIFIED = "DISQUALIFIED"
    SCRATCHED = "SCRATCHED"


class SubmissionStatus(str, Enum):
    PREPARED = "PREPARED"
    NATIONAL_ACCEPTED = "NATIONAL_ACCEPTED"
    REGIONAL_ACCEPTED = "REGIONAL_ACCEPTED"
    RECORDED = "RECORDED"
    REJECTED = "REJECTED"
    RETRACTED = "RETRACTED"


class StandingsBody(str, Enum):
    NATIONAL = "NATIONAL"
    REGIONAL = "REGIONAL"


class AcknowledgementOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CaseType(str, Enum):
    DRUG_TEST = "DRUG_TEST"
    WELFARE_CITATION = "WELFARE_CITATION"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class Finding(str, Enum):
    NEGATIVE = "NEGATIVE"
    WARNING = "WARNING"
    POSITIVE = "POSITIVE"


class CoverageType(str, Enum):
    VETERINARIAN = "VETERINARIAN"
    FARRIER = "FARRIER"


class CoverageStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"


class LicenseDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    DENY = "DENY"


# --------------------------------------------------------------------------
# Entity TypedDicts — all fourteen carry the four common properties
# --------------------------------------------------------------------------

class Show(TypedDict):
    id: str
    name: str
    federation_show_id: str
    venue: str
    competition_level: str
    start_utc: str
    end_utc: str
    entry_close_utc: str
    prize_money_pool_cents: int
    stall_capacity: int
    stall_fee_cents: int
    license_status: str
    revision_count: int
    correction_note: Optional[str]
    allocated_prize_cents: int
    unallocated_prize_cents: int
    reserved_stall_count: int
    available_stall_count: int
    division_share_bp_total: int
    welfare_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Ring(TypedDict):
    id: str
    show_id: str
    name: str
    surface_type: str
    footing_condition_score: int
    turnover_buffer_minutes: int
    warmup_capacity_horses: int
    status: str
    scheduled_minutes_total: int
    slot_count: int
    created_at: str
    updated_at: str
    version: int


class CompetitionDivision(TypedDict):
    id: str
    show_id: str
    name: str
    discipline: str
    age_group: str
    min_jump_height_cm: int
    max_jump_height_cm: int
    division_share_bp: int
    jumpoff_enabled: bool
    status: str
    division_allotment_cents: int
    created_at: str
    updated_at: str
    version: int


class ShowClass(TypedDict):
    id: str
    division_id: str
    class_number: int
    name: str
    jump_height_cm: int
    entry_fee_cents: int
    class_share_bp: int
    max_entries: int
    qualifier_for_class_id: Optional[str]
    status: str
    entry_count: int
    confirmed_entry_count: int
    class_purse_cents: int
    awarded_prize_cents: int
    placed_count: int
    point_eligible: bool
    estimated_minutes: Optional[int]
    actual_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RingSlot(TypedDict):
    id: str
    ring_id: str
    class_id: Optional[str]
    slot_type: str
    start_utc: str
    end_utc: str
    warmup_start_utc: str
    duration_minutes: int
    order_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict):
    id: str
    federation_official_id: str
    full_name: str
    license_roles: List[str]
    license_level: int
    licensed_disciplines: List[str]
    license_expires_on: str
    affiliated_trainer_name: Optional[str]
    assigned_minutes: int
    created_at: str
    updated_at: str
    version: int


class OfficialAssignment(TypedDict):
    id: str
    official_id: str
    slot_id: str
    official_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    federation_member_number: str
    full_name: str
    membership_expires_on: str
    trainer_name: str
    membership_status: str
    national_points_total: float
    regional_points_total: int
    created_at: str
    updated_at: str
    version: int


class Horse(TypedDict):
    id: str
    federation_registration_number: str
    name: str
    owner_name: str
    coggins_drawn_on: str
    coggins_expires_on: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict):
    id: str
    show_id: str
    rider_id: str
    horse_id: str
    requested_stall_count: int
    assigned_stall_count: int
    verification_status: str
    settlement_status: str
    class_fee_cents_total: int
    stall_fee_cents: int
    preliminary_subtotal_cents: int
    office_fee_cents: int
    total_due_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class ClassEntry(TypedDict):
    id: str
    entry_id: str
    class_id: str
    status: str
    placing: Optional[int]
    round_seconds: Optional[float]
    prize_cents: int
    points_national: float
    points_regional: int
    created_at: str
    updated_at: str
    version: int


class PointSubmission(TypedDict):
    id: str
    class_id: str
    status: str
    submitted_by_user_id: str
    national_body_reference: Optional[str]
    regional_body_reference: Optional[str]
    national_points_total: float
    regional_points_total: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    entry_id: str
    opened_by_official_id: str
    case_type: str
    sample_code: Optional[str]
    welfare_rule_code: Optional[str]
    status: str
    finding: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageShift(TypedDict):
    id: str
    show_id: str
    coverage_type: str
    provider_name: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int
