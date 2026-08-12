"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    ZONE_OPERATOR = "ZoneOperator"
    RESIDENT = "Resident"
    DRIVER = "Driver"
    PARTNER_MANAGER = "PartnerManager"
    INSPECTOR = "Inspector"
    SPONSOR_MANAGER = "SponsorManager"
    CHARITY_ADMIN = "CharityAdmin"
    SENSOR_GATEWAY = "SensorGateway"


class ResidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BagKitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETIRED = "RETIRED"


class KitType(str, Enum):
    BAG = "BAG"
    BIN = "BIN"


class PickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ROUTED = "ROUTED"
    COLLECTED = "COLLECTED"
    WEIGHED = "WEIGHED"
    SETTLED = "SETTLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PartnerStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    QUARANTINED = "QUARANTINED"


class PartnerType(str, Enum):
    BRAND = "BRAND"
    THRIFT = "THRIFT"


class Grade(str, Enum):
    RESALE = "RESALE"
    RECYCLE = "RECYCLE"
    FIBER = "FIBER"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"


class DropBoxPosture(str, Enum):
    OK = "OK"
    FILLING = "FILLING"
    FULL_PENDING_COLLECTION = "FULL_PENDING_COLLECTION"


class TicketStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    QUARANTINED = "QUARANTINED"
    VOIDED = "VOIDED"


class SourceType(str, Enum):
    PICKUP_REQUEST = "PICKUP_REQUEST"
    DROPBOX = "DROPBOX"


class CreditStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class FundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"


class ReportOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class Severity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --- Entity payloads (common_fields entities carry id/created_at/updated_at/version) ---

class ServiceZone(TypedDict, total=False):
    id: str
    name: str
    charity_splits: List[dict]
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    zone_id: str
    full_name: str
    email: str
    address: str
    status: str
    strikes: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class BagKit(TypedDict, total=False):
    id: str
    resident_id: str
    kit_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupRequest(TypedDict, total=False):
    id: str
    resident_id: str
    window_start: str
    window_end: str
    bags_claimed: int
    est_weight_kg: float
    status: str
    reschedule_count: int
    rebook_count: int
    driver_id: Optional[str]
    service_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict, total=False):
    id: str
    name: str
    partner_type: str
    accepted_grades: List[str]
    capacity_kg: int
    committed_kg: float
    completed_kg: float
    remaining_kg: float
    routing_score: float
    report_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RoutingAssignment(TypedDict, total=False):
    id: str
    ticket_id: str
    partner_id: str
    assigned_weight_kg: float
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DropBox(TypedDict, total=False):
    id: str
    zone_id: str
    label: str
    location: str
    fill_pct: float
    posture: str
    last_collected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event (PRD §2.4): carries ONLY id + created_at — never updated_at/version.
class FillReading(TypedDict, total=False):
    id: str
    dropbox_id: str
    fill_pct: float
    recorded_at: str
    created_at: str


class WeightTicket(TypedDict, total=False):
    id: str
    source_type: str
    source_id: str
    provisional_weight_kg: float
    certified_weight_kg: Optional[float]
    grade: Optional[str]
    status: str
    projected_credit_cents: int
    highest_upheld_severity: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionCredit(TypedDict, total=False):
    id: str
    ticket_id: str
    fund_id: Optional[str]
    beneficiary_resident_id: Optional[str]
    projected_cents: int
    gross_cents: Optional[int]
    applied_severity: str
    has_hold: bool
    status: str
    charity_allocations: List[dict]
    resident_share_cents: Optional[int]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorFund(TypedDict, total=False):
    id: str
    zone_id: str
    sponsor_name: str
    initial_cents: int
    funded_total_cents: int
    held_cents: int
    paid_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Charity(TypedDict, total=False):
    id: str
    name: str
    total_received_cents: int
    created_at: str
    updated_at: str
    version: int


class ContaminationReport(TypedDict, total=False):
    id: str
    ticket_id: str
    severity: str
    notes: str
    status: str
    outcome: Optional[str]
    reported_by: str
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict, total=False):
    id: str
    zone_id: str
    period_start: str
    period_end: str
    status: str
    closed_at: Optional[str]
    aggregates: Optional[dict]
    created_at: str
    updated_at: str
    version: int
