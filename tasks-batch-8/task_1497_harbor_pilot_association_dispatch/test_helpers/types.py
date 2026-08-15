"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    DISPATCHER = "Dispatcher"
    PILOT = "Pilot"
    VESSEL_AGENT = "VesselAgent"
    FINANCE_OFFICER = "FinanceOfficer"
    INVESTIGATOR = "Investigator"


class PilotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EndorsementClass(str, Enum):
    HARBOR = "HARBOR"
    COASTAL = "COASTAL"
    UNLIMITED = "UNLIMITED"


class EndorsementStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class RotationEntryStatus(str, Enum):
    IN_ROTATION = "IN_ROTATION"
    OFF_BOARD = "OFF_BOARD"


class OrderType(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"
    SHIFT = "SHIFT"


class VesselOrderStatus(str, Enum):
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PilotBoatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_RUN = "ON_RUN"


class ServiceStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ABOARD = "ABOARD"
    COMPLETED = "COMPLETED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    FINALIZED = "FINALIZED"
    DISTRIBUTED = "DISTRIBUTED"


class IncidentType(str, Enum):
    GROUNDING = "GROUNDING"
    COLLISION = "COLLISION"
    NEAR_MISS = "NEAR_MISS"
    EQUIPMENT = "EQUIPMENT"
    CONDUCT = "CONDUCT"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISMISSED = "DISMISSED"
    SUBSTANTIATED = "SUBSTANTIATED"
    CLOSED = "CLOSED"


class ApprenticeTrack(str, Enum):
    STANDARD = "STANDARD"
    ACCELERATED = "ACCELERATED"


class ApprenticeStatus(str, Enum):
    ENROLLED = "ENROLLED"
    QUALIFIED = "QUALIFIED"
    CERTIFIED = "CERTIFIED"


class TariffScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DistributionRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class Pilot(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    share_units: int
    status: str
    rest_until: Optional[str]
    duty_minutes_rolling_7d: int
    created_at: str
    updated_at: str
    version: int


class LicenseEndorsement(TypedDict, total=False):
    id: str
    pilot_id: str
    endorsement_class: str
    tonnage_cap_gt: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RotationEntry(TypedDict, total=False):
    id: str
    pilot_id: str
    position: int
    previous_position: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class VesselOrder(TypedDict, total=False):
    id: str
    agent_id: str
    vessel_name: str
    gt: int
    draft_dm: int
    order_type: str
    eta: str
    tariff_schedule_id: str
    provisional_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PilotBoat(TypedDict, total=False):
    id: str
    name: str
    capacity_persons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    order_id: str
    pilot_id: str
    boat_id: str
    apprentice_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    detention_minutes: int
    delay_minutes: int
    service_status: str
    billing_status: str
    recall_count: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    assignment_id: str
    base_fee_cents: int
    detention_fee_cents: int
    delay_fee_cents: int
    total_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    assignment_id: str
    pilot_id: str
    incident_type: str
    description: str
    corrective_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Apprentice(TypedDict, total=False):
    id: str
    full_name: str
    track: str
    trips_completed: int
    evaluations_count: int
    evaluation_avg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffTier(TypedDict, total=False):
    min_gt_exclusive: int
    max_gt_inclusive: Optional[int]
    rate_cents_per_gt: int


class TariffSchedule(TypedDict, total=False):
    id: str
    effective_from: str
    tiers: List[dict]
    draft_surcharge_threshold_dm: int
    draft_surcharge_pct: float
    detention_free_minutes: int
    detention_rate_cents_per_minute: int
    delay_rate_cents_per_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionShare(TypedDict, total=False):
    pilot_id: str
    share_units: int
    share_cents: int


class DistributionRun(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    gross_pool_cents: int
    levy_cents: int
    net_pool_cents: int
    shares: List[dict]
    invoice_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
