"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the full set of common fields (id, created_at,
updated_at, version), so every TypedDict below lists updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    SCHEDULER = "Scheduler"
    NEPHROLOGIST = "Nephrologist"
    BILLING_CLERK = "BillingClerk"


# ─── Status enums ─────────────────────────────────────────────────────────
class ClinicStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ShiftStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class StationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PatientKind(str, Enum):
    RESIDENT = "RESIDENT"
    TRANSIENT = "TRANSIENT"


class PayerClass(str, Enum):
    CONTRACTED = "CONTRACTED"
    STANDARD = "STANDARD"


class AdherenceStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    AT_RISK = "AT_RISK"
    SUSPENDED = "SUSPENDED"


class Modality(str, Enum):
    HEMODIALYSIS = "HEMODIALYSIS"
    HEMODIAFILTRATION = "HEMODIAFILTRATION"
    PERITONEAL = "PERITONEAL"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    REVOKED = "REVOKED"


class StandingSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class ClinicalStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class DayPattern(str, Enum):
    MWF = "MWF"
    TTHS = "TTHS"


class TransportDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class TransportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LabPanel(str, Enum):
    MONTHLY_CHEM = "MONTHLY_CHEM"
    CBC = "CBC"
    IRON_STUDIES = "IRON_STUDIES"


class LabStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    CANCELLED = "CANCELLED"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (all carry the full common-field set) ───────────────
class Clinic(TypedDict):
    id: str
    name: str
    time_zone: str
    dialyzer_reuse_limit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    clinic_id: str
    code: str
    day_pattern: str
    start_minute: int
    end_minute: int
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    clinic_id: str
    asset_tag: str
    model: str
    supports_hdf: bool
    dialyzer_reuse_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    clinic_id: str
    chair_label: str
    machine_id: str
    isolation_capable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    clinic_id: str
    mrn: str
    full_name: str
    patient_kind: str
    payer_class: str
    requires_isolation: bool
    coinsurance_pct: float
    no_show_count_window: int
    adherence_status: str
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class NephrologistOrder(TypedDict):
    id: str
    patient_id: str
    clinic_id: str
    modality: str
    sessions_per_week: int
    epo_units: int
    iron_ordered: bool
    effective_from_date: str
    revision_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingSlot(TypedDict):
    id: str
    patient_id: str
    clinic_id: str
    shift_id: str
    station_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentSession(TypedDict):
    id: str
    patient_id: str
    clinic_id: str
    order_id: str
    station_id: str
    shift_id: str
    standing_slot_id: Optional[str]
    rescheduled_from_id: Optional[str]
    service_date: str
    billed_amount_cents: int
    missed_fee_cents: int
    clinical_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    patient_id: str
    clinic_id: str
    panel: str
    scheduled_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportTrip(TypedDict):
    id: str
    session_id: str
    patient_id: str
    direction: str
    miles: float
    cross_county: bool
    wheelchair: bool
    shared_ride: bool
    fare_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict):
    id: str
    patient_id: str
    clinic_id: str
    period_month: str
    session_count: int
    coinsurance_due_cents: int
    missed_fee_total_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
