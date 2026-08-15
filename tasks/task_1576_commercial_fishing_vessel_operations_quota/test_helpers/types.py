"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    VESSEL_OWNER = "VesselOwner"
    CAPTAIN = "Captain"
    CREW_MEMBER = "CrewMember"
    OBSERVER = "Observer"
    OBSERVER_COORDINATOR = "ObserverCoordinator"
    FISHERIES_REGULATOR = "FisheriesRegulator"
    SETTLEMENT_CLERK = "SettlementClerk"


class VesselStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class HoldingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class OpeningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CLOSED_EARLY = "CLOSED_EARLY"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    DEPARTED = "DEPARTED"
    RETURNED = "RETURNED"
    LANDING_FINALIZED = "LANDING_FINALIZED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"
    VERIFIED = "VERIFIED"
    FINALIZED = "FINALIZED"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ObserverStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"


class AssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    DEPLOYED = "DEPLOYED"
    DEBRIEFED = "DEBRIEFED"
    RELEASED = "RELEASED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class CrewContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ExpenseStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    REVERSED = "REVERSED"
    UPHELD = "UPHELD"


class FisheryCode(str, Enum):
    HALIBUT = "HALIBUT"
    SABLEFISH = "SABLEFISH"
    POLLOCK = "POLLOCK"
    PACIFIC_COD = "PACIFIC_COD"


class GearType(str, Enum):
    TRAWL_NET = "TRAWL_NET"
    LONGLINE = "LONGLINE"
    POT = "POT"
    GILLNET = "GILLNET"


class CoverageClass(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    EXEMPT = "EXEMPT"


class ReportType(str, Enum):
    HARVEST = "HARVEST"
    DISCARD = "DISCARD"


class GearEventType(str, Enum):
    LOSS = "LOSS"
    REPAIR = "REPAIR"
    MAINTENANCE_START = "MAINTENANCE_START"
    MAINTENANCE_END = "MAINTENANCE_END"


class ViolationType(str, Enum):
    OVER_QUOTA = "OVER_QUOTA"
    OUT_OF_SEASON = "OUT_OF_SEASON"
    OBSERVER_BREACH = "OBSERVER_BREACH"
    VMS_GAP = "VMS_GAP"
    GEAR_MISMATCH = "GEAR_MISMATCH"
    MANUAL_CITATION = "MANUAL_CITATION"


# --- Entity TypedDicts -------------------------------------------------------
# Entities with full bookkeeping carry id + created_at + updated_at + version.
# Append-only event records (catch reports, gear events, VMS pings) carry only
# id + created_at per PRD §2.4.


class Vessel(TypedDict, total=False):
    id: str
    vessel_name: str
    license_number: str
    home_port: str
    length_ft: int
    observer_coverage_class: str
    vms_unit_id: Optional[str]
    compliance_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    vessel_id: str
    fishery_code: str
    gear_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QuotaShareHolding(TypedDict, total=False):
    id: str
    vessel_id: str
    fishery_code: str
    season_year: int
    initial_pounds: int
    landed_pounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonOpening(TypedDict, total=False):
    id: str
    fishery_code: str
    area_code: str
    opens_at: str
    closes_at: str
    tac_pounds: int
    landed_against_tac_pounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FishingTrip(TypedDict, total=False):
    id: str
    vessel_id: str
    season_opening_id: str
    planned_departure_utc: str
    planned_return_utc: str
    gear_requirements: List[Dict[str, Any]]
    observer_required: bool
    observer_waived: bool
    actual_departure_utc: Optional[str]
    actual_return_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CatchReport(TypedDict, total=False):
    # Append-only: id + created_at only (no updated_at, no version) — PRD §2.4
    id: str
    trip_id: str
    haul_seq: int
    fishery_code: str
    report_type: str
    reported_lbs: int
    reported_at: str
    created_at: str


class LandingDeclaration(TypedDict, total=False):
    id: str
    trip_id: str
    port_code: str
    lines: List[Dict[str, Any]]
    discrepancy_details: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuotaTransfer(TypedDict, total=False):
    id: str
    from_vessel_id: str
    to_vessel_id: str
    fishery_code: str
    season_year: int
    pounds: int
    price_per_lb_cents: int
    round_number: int
    last_offered_by: str
    transfer_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Observer(TypedDict, total=False):
    id: str
    observer_name: str
    certification_level: str
    home_base: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ObserverAssignment(TypedDict, total=False):
    id: str
    trip_id: str
    observer_id: Optional[str]
    coverage_from: Optional[str]
    coverage_to: Optional[str]
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewShareContract(TypedDict, total=False):
    id: str
    vessel_id: str
    crew_name: str
    share_points: float
    joined_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseRecord(TypedDict, total=False):
    id: str
    trip_id: str
    category: str
    amount_cents: int
    incurred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TripSettlement(TypedDict, total=False):
    id: str
    trip_id: str
    gross_revenue_cents: int
    provisional_total_expenses_cents: int
    provisional_processing_fee_cents: int
    provisional_vessel_share_cents: int
    provisional_crew_pool_cents: int
    total_expenses_cents: Optional[int]
    observer_fee_cents: Optional[int]
    gear_loss_charge_cents: Optional[int]
    processing_fee_cents: Optional[int]
    net_cents: Optional[int]
    vessel_share_cents: Optional[int]
    crew_pool_cents: Optional[int]
    crew_payouts: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class GearAsset(TypedDict, total=False):
    id: str
    vessel_id: str
    gear_type: str
    units_total: int
    units_lost: int
    units_in_maintenance: int
    units_operational: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GearEvent(TypedDict, total=False):
    # Append-only: id + created_at only (no updated_at, no version) — PRD §2.4
    id: str
    gear_asset_id: str
    trip_id: Optional[str]
    event_type: str
    units: int
    occurred_at: str
    created_at: str


class VMSPing(TypedDict, total=False):
    # Append-only: id + created_at only (no updated_at, no version) — PRD §2.4
    id: str
    vessel_id: str
    recorded_at: str
    latitude: float
    longitude: float
    created_at: str


class ComplianceViolation(TypedDict, total=False):
    id: str
    vessel_id: str
    trip_id: Optional[str]
    violation_type: str
    details: str
    season_year: int
    severity_points: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
