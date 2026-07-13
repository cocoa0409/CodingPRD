"""Domain types for the Medical Courier & Specimen Logistics API.

Entity TypedDicts, status enums, and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    LAB_CLIENT = "LabClient"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------
class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class CustodyStatus(str, Enum):
    AWAITING_PICKUP = "AWAITING_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


class IntegrityStatus(str, Enum):
    INTACT = "INTACT"
    COMPROMISED = "COMPROMISED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"


class BillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ExceptionType(str, Enum):
    MISSED_STOP = "MISSED_STOP"
    TEMP_EXCURSION = "TEMP_EXCURSION"
    CREDENTIAL_LAPSE = "CREDENTIAL_LAPSE"


class CredentialType(str, Enum):
    STANDARD = "STANDARD"
    BLOODBORNE = "BLOODBORNE"
    HAZMAT = "HAZMAT"


class CredentialAction(str, Enum):
    RENEW = "RENEW"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class RunType(str, Enum):
    STAT = "STAT"
    SCHEDULED = "SCHEDULED"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    TISSUE = "TISSUE"
    URINE = "URINE"
    SWAB = "SWAB"
    CULTURE = "CULTURE"


class TempRequirement(str, Enum):
    AMBIENT = "AMBIENT"
    REFRIGERATED = "REFRIGERATED"
    FROZEN = "FROZEN"


class StopKind(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"
    BOTH = "BOTH"


class Cadence(str, Enum):
    DAILY = "DAILY"
    WEEKDAYS = "WEEKDAYS"
    WEEKLY = "WEEKLY"


class ScanType(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"


# ---------------------------------------------------------------------------
# Entities (PRD §2.4 + §3)
# ---------------------------------------------------------------------------
class RateCard(TypedDict):
    id: str
    name: str
    per_stop_fee_cents: int
    per_mile_rate_cents: int
    stat_surcharge_pct: float
    stat_surcharge_cap_cents: int
    temp_handling_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class LabClient(TypedDict):
    id: str
    name: str
    budget_cents: int
    contact: Optional[str]
    billed_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    credential_type: str
    credential_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    plate: str
    has_refrigeration: bool
    sanitation_buffer_minutes: int
    status: str
    last_released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteTemplate(TypedDict):
    id: str
    lab_client_id: str
    rate_card_id: str
    cadence: str
    default_run_type: str
    stop_specs: List[Any]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    lab_client_id: str
    rate_card_id: str
    template_id: Optional[str]
    driver_id: Optional[str]
    vehicle_id: Optional[str]
    run_type: str
    scheduled_start: str
    scheduled_end: str
    planned_total_miles: float
    sla_deadline: str
    provisional_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict):
    id: str
    route_id: str
    sequence: int
    address: str
    stop_kind: str
    planned_leg_miles: float
    actual_leg_miles: Optional[float]
    leg_charge_cents: Optional[int]
    arrived_at: Optional[str]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    specimen_type: str
    temp_requirement: str
    required_temp_min_c: float
    required_temp_max_c: float
    custody_status: str
    integrity_status: str
    excursion_count: int
    picked_up_at: Optional[str]
    delivered_at: Optional[str]
    estimated_risk_score: Optional[int]
    final_risk_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ScanEvent(TypedDict):
    """Append-only chain-of-custody record (PRD §2.4): carries only id and
    created_at — never an updated_at or a version."""
    id: str
    specimen_id: str
    driver_id: str
    stop_id: str
    scan_type: str
    temp_reading_c: float
    leg_miles: float
    scanned_at: str
    is_excursion: bool
    created_at: str


class RouteException(TypedDict):
    id: str
    route_id: str
    stop_id: Optional[str]
    specimen_id: Optional[str]
    exception_type: str
    detail: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RunBilling(TypedDict):
    id: str
    route_id: str
    lab_client_id: str
    gross_charge_cents: int
    surcharge_cents: int
    net_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
