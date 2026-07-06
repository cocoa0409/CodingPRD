"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ELECTION_ADMIN = "ElectionAdmin"
    PRECINCT_CAPTAIN = "PrecinctCaptain"
    POLL_WORKER = "PollWorker"
    CUSTODY_OFFICER = "CustodyOfficer"
    SUPPORT_AGENT = "SupportAgent"


class ElectionStatus(str, Enum):
    PLANNING = "PLANNING"
    VOTING_OPEN = "VOTING_OPEN"
    VOTING_CLOSED = "VOTING_CLOSED"


class ReadinessPosture(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    BALANCED = "BALANCED"
    MISMATCH = "MISMATCH"


class EquipmentType(str, Enum):
    SCANNER = "SCANNER"
    BMD = "BMD"
    EPOLLBOOK = "EPOLLBOOK"
    PRINTER = "PRINTER"


class EquipmentStatus(str, Enum):
    IN_WAREHOUSE = "IN_WAREHOUSE"
    OPERATIONAL = "OPERATIONAL"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TrainingStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class CustodyState(str, Enum):
    PREPARED = "PREPARED"
    ISSUED = "ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_PLACE = "AT_PLACE"
    RETURN_PENDING = "RETURN_PENDING"
    RECONCILED = "RECONCILED"
    COMPROMISED = "COMPROMISED"


class CustodyEventType(str, Enum):
    ISSUE = "ISSUE"
    DISPATCH = "DISPATCH"
    RECEIVE = "RECEIVE"
    RETURN = "RETURN"
    RECONCILE = "RECONCILE"
    SEAL_BREAK = "SEAL_BREAK"
    VOID_ISSUE = "VOID_ISSUE"


class ProvisionalStatus(str, Enum):
    CAST = "CAST"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class IncidentCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    STAFFING = "STAFFING"
    SECURITY = "SECURITY"
    ACCESSIBILITY = "ACCESSIBILITY"
    OTHER = "OTHER"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


# ---- Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version) ----

class Election(TypedDict):
    id: str
    name: str
    jurisdiction: str
    election_date: str
    status: str
    initial_ballot_stock: int
    unallocated_ballot_stock: int
    created_at: str
    updated_at: str
    version: int


class PollingPlace(TypedDict):
    id: str
    election_id: str
    name: str
    address: str
    min_workers_required: int
    staffing_capacity: int
    station_capacity: int
    wheelchair_accessible: bool
    accessible_parking: bool
    ada_voting_stations: int
    readiness_posture: str
    slots_filled: int
    slots_open: int
    provisional_cast_count: int
    provisional_accepted_count: int
    scanner_tally: Optional[int]
    epollbook_checkins: Optional[int]
    spoiled_count: int
    reconciliation_status: str
    reconciliation_discrepancy: Optional[int]
    total_payroll_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    equipment_type: str
    serial_number: str
    status: str
    polling_place_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PollWorker(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    training_status: str
    accrued_payroll_cents: int
    stipend_paid: bool
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    poll_worker_id: str
    polling_place_id: str
    is_lead: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    assignment_id: str
    poll_worker_id: str
    polling_place_id: str
    scheduled_start: str
    scheduled_end: str
    check_in_time: Optional[str]
    check_out_time: Optional[str]
    status: str
    is_lead: bool
    scheduled_hours: float
    scheduled_pay_cents: int
    actual_hours: Optional[float]
    gross_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SupplyKit(TypedDict):
    id: str
    election_id: str
    polling_place_id: Optional[str]
    ballot_count: int
    seal_number: str
    custody_state: str
    returned_ballot_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProvisionalBallot(TypedDict):
    id: str
    polling_place_id: str
    voter_name: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    polling_place_id: str
    equipment_unit_id: Optional[str]
    category: str
    description: str
    severity: str
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---- Append-only audit record (common_fields: false -> only id + created_at) ----

class CustodyEvent(TypedDict):
    id: str
    supply_kit_id: str
    event_type: str
    from_state: str
    to_state: str
    actor_role: str
    note: Optional[str]
    created_at: str
