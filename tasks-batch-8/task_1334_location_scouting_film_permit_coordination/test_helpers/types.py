"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system carries the full common field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ProductionStatus(str, Enum):
    PREP = "PREP"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class JurisdictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LocationStatus(str, Enum):
    SCOUTING = "SCOUTING"
    AGREEMENT_EXECUTED = "AGREEMENT_EXECUTED"
    RETIRED = "RETIRED"


class LocationBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ScoutPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OwnerAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    COLLAPSED = "COLLAPSED"


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class StreetClosureStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NotificationRecordStatus(str, Enum):
    POSTED = "POSTED"
    ACKED = "ACKED"
    DEFICIENT = "DEFICIENT"


class InsuranceCertificateStatus(str, Enum):
    PRESENTED = "PRESENTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    LAPSED = "LAPSED"


class DepositAccountStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class WalkthroughReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    DISPUTED = "DISPUTED"
    FINAL = "FINAL"


class MonitorAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class ShootDayStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SHUT_DOWN = "SHUT_DOWN"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEGRADED = "DEGRADED"
    VIOLATION = "VIOLATION"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class MonitorType(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    FILM_OFFICER = "FILM_OFFICER"


class ComplaintCategory(str, Enum):
    NOISE = "NOISE"
    PARKING = "PARKING"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    HOURS_VIOLATION = "HOURS_VIOLATION"
    OTHER = "OTHER"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WalkthroughKind(str, Enum):
    PRE = "PRE"
    POST = "POST"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class PermitDecision(str, Enum):
    ISSUE = "ISSUE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    DENY = "DENY"


class UserRole(str, Enum):
    LOCATION_MANAGER = "LocationManager"
    FILM_OFFICE = "FilmOffice"
    OWNER_REP = "OwnerRep"


class Production(TypedDict):
    id: str
    title: str
    production_company: str
    cast_size: int
    umbrella_liability_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    lead_time_business_days: int
    notification_lead_calendar_days: int
    notification_radius_ft: int
    base_fee_cents: int
    per_day_fee_cents: int
    per_lane_fee_cents: int
    large_cast_threshold: int
    large_cast_multiplier_bps: int
    min_liability_limit_cents: int
    police_monitor_lane_threshold: int
    holidays: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    name: str
    address: str
    jurisdiction_id: str
    owner_id: str
    deposit_floor_cents: int
    buffer_days: int
    max_shoot_hours_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LocationOwner(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    default_day_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class LocationBooking(TypedDict):
    id: str
    production_id: str
    location_id: str
    booking_start_date: str
    booking_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoutPackage(TypedDict):
    id: str
    production_id: str
    location_id: str
    photo_count: int
    coverage_score_pct: int
    scout_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerAgreement(TypedDict):
    id: str
    production_id: str
    location_id: str
    shoot_start_date: str
    shoot_end_date: str
    proposed_day_rate_cents: int
    round_count: int
    max_rounds: int
    agreed_day_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    production_id: str
    location_id: str
    jurisdiction_id: str
    shoot_start_date: str
    shoot_end_date: str
    closed_lanes: int
    shoot_hours_per_day: int
    submitted_at: Optional[str]
    business_days_available: Optional[int]
    lead_time_satisfied: Optional[bool]
    fee_cents: Optional[int]
    amendment_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StreetClosure(TypedDict):
    id: str
    production_id: str
    permit_application_id: str
    street_segment: str
    closure_start: str
    closure_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NotificationRecord(TypedDict):
    id: str
    production_id: str
    permit_application_id: str
    posted_at: str
    households_reached: int
    radius_ft_used: int
    calendar_days_before_shoot: int
    notification_adequate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    production_id: str
    jurisdiction_id: str
    insurer_name: str
    umbrella_limit_cents: int
    indemnity_clause_ref: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict):
    id: str
    production_id: str
    location_id: str
    required_amount_cents: int
    held_amount_cents: int
    claimed_amount_cents: int
    released_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WalkthroughReport(TypedDict):
    id: str
    production_id: str
    location_id: str
    kind: str
    damage_item_count: int
    damage_claim_cents: int
    signed_by_owner: bool
    signed_by_manager: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitorAssignment(TypedDict):
    id: str
    production_id: str
    shoot_day_id: str
    monitor_type: str
    officer_badge: str
    hours_booked: int
    checked_in: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ShootDay(TypedDict):
    id: str
    production_id: str
    permit_application_id: str
    location_id: str
    shoot_date: str
    planned_hours: int
    actual_hours: Optional[int]
    overtime_minutes: int
    monitors_required: int
    monitors_confirmed: int
    compliance_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    production_id: str
    shoot_day_id: str
    category: str
    severity: str
    filed_at: str
    response_due_at: str
    resolution_note: str
    status: str
    created_at: str
    updated_at: str
    version: int
