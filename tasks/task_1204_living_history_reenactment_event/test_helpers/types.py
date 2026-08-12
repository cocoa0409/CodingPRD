"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system-managed properties (id, created_at,
updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    EVENT_ORGANIZER = "EventOrganizer"
    AUTHENTICITY_OFFICER = "AuthenticityOfficer"
    SAFETY_OFFICER = "SafetyOfficer"
    UNIT_COMMANDER = "UnitCommander"
    PARTICIPANT = "Participant"
    VENDOR = "Vendor"
    SPECTATOR = "Spectator"


class EventPosture(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    PUBLISHED = "PUBLISHED"
    EVENT_OPEN = "EVENT_OPEN"
    RESTRICTED = "RESTRICTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RestrictionLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class AgreementType(str, Enum):
    LANDOWNER_USE = "LANDOWNER_USE"
    INSURANCE_LIABILITY = "INSURANCE_LIABILITY"


class AgreementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"


class UnitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class UnitType(str, Enum):
    MILITARY = "MILITARY"
    CIVILIAN = "CIVILIAN"
    ARTILLERY = "ARTILLERY"


class ParticipantStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    VETTED = "VETTED"
    CHECKED_IN = "CHECKED_IN"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ImpressionClass(str, Enum):
    COMBATANT = "COMBATANT"
    CIVILIAN = "CIVILIAN"
    ARTILLERY_CREW = "ARTILLERY_CREW"


class EquipmentItemStatus(str, Enum):
    DECLARED = "DECLARED"
    INSPECTION_DUE = "INSPECTION_DUE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"
    BANNED = "BANNED"
    WITHDRAWN = "WITHDRAWN"


class ItemType(str, Enum):
    FIREARM = "FIREARM"
    EDGED = "EDGED"
    CANNON = "CANNON"
    CAMP_FLAME = "CAMP_FLAME"
    TENTAGE = "TENTAGE"
    OTHER = "OTHER"


class InspectionKind(str, Enum):
    SAFETY = "SAFETY"
    AUTHENTICITY = "AUTHENTICITY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED_PASS = "RECORDED_PASS"
    RECORDED_FAIL = "RECORDED_FAIL"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class AreaKind(str, Enum):
    CAMP = "CAMP"
    DEMO = "DEMO"
    PARKING = "PARKING"
    SUTLER = "SUTLER"
    SPECTATOR = "SPECTATOR"


class SiteAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ProgramSlotStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TicketOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    PAID = "PAID"
    CHECKED_IN = "CHECKED_IN"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class LineType(str, Enum):
    ADULT_DAY = "ADULT_DAY"
    CHILD_DAY = "CHILD_DAY"
    ADULT_WEEKEND = "ADULT_WEEKEND"
    CHILD_WEEKEND = "CHILD_WEEKEND"


class RefundReason(str, Enum):
    PATRON_CHOICE = "PATRON_CHOICE"
    EVENT_CONTINGENCY = "EVENT_CONTINGENCY"


class VehicleClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"


class ParkingPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class VendorStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    CONTRACTED = "CONTRACTED"
    SETTLED = "SETTLED"
    REVOKED = "REVOKED"


class AlertKind(str, Enum):
    WEATHER = "WEATHER"
    FIRE = "FIRE"
    SECURITY = "SECURITY"


class AlertSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    WATCH = "WATCH"
    RED_FLAG = "RED_FLAG"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class VetDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Event(TypedDict, total=False):
    id: str
    name: str
    site_name: str
    event_starts_at: str
    event_ends_at: str
    adult_day_price_cents: int
    child_day_price_cents: int
    adult_weekend_price_cents: int
    child_weekend_price_cents: int
    early_bird_pct: float
    early_bird_cutoff_at: str
    service_fee_cents: int
    refund_retain_pct: float
    required_liability_cents: int
    max_minor_per_adult: int
    vendor_frontage_rate_cents: int
    vendor_multi_day_discount_pct: float
    vendor_min_fee_cents: int
    vendor_late_insurance_surcharge_cents: int
    vendor_insurance_deadline_at: str
    event_posture: str
    restriction_level: str
    approved_combatant_count: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    event_id: str
    agreement_type: str
    document_ref: str
    coverage_amount_cents: Optional[int]
    effective_from: str
    effective_until: str
    status: str
    signed_at: Optional[str]
    signer_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    unit_type: str
    portrayal_name: str
    headcount_estimate: int
    status: str
    vet_notes: Optional[str]
    approved_combatant_count: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    event_id: str
    unit_id: Optional[str]
    supervisor_participant_id: Optional[str]
    full_name: str
    age_at_event: int
    impression_class: str
    persona_description: str
    is_minor: bool
    status: str
    vet_notes: Optional[str]
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict, total=False):
    id: str
    participant_id: str
    item_type: str
    description: str
    status: str
    failure_count: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    equipment_item_id: str
    inspection_kind: str
    scheduled_for: str
    status: str
    recorded_by_user_id: Optional[str]
    failure_reason: Optional[str]
    waived_by_user_id: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteArea(TypedDict, total=False):
    id: str
    event_id: str
    area_name: str
    area_kind: str
    capacity_units: int
    status: str
    allocated_units: int
    created_at: str
    updated_at: str
    version: int


class AreaAllocation(TypedDict, total=False):
    id: str
    site_area_id: str
    unit_id: Optional[str]
    vendor_id: Optional[str]
    starts_at: str
    ends_at: str
    units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramSlot(TypedDict, total=False):
    id: str
    event_id: str
    site_area_id: str
    title: str
    starts_at: str
    ends_at: str
    open_flame: bool
    required_combatants: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict, total=False):
    id: str
    event_id: str
    buyer_user_id: str
    buyer_name: str
    lines: List[Dict[str, Any]]
    status: str
    quoted_total_cents: int
    final_total_cents: Optional[int]
    refund_amount_cents: Optional[int]
    retained_fee_cents: Optional[int]
    refund_reason: Optional[str]
    paid_at: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParkingPass(TypedDict, total=False):
    id: str
    ticket_order_id: str
    site_area_id: str
    vehicle_plate: str
    vehicle_class: str
    units_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    event_id: str
    owner_user_id: str
    business_name: str
    wares_description: str
    frontage_feet: int
    requested_days: int
    status: str
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    fee_paid_cents: int
    insurance_cert_ref: Optional[str]
    insurance_uploaded_at: Optional[str]
    balance_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ContingencyAlert(TypedDict, total=False):
    id: str
    event_id: str
    alert_kind: str
    severity: str
    message: str
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
