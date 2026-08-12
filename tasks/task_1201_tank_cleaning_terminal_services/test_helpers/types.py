"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TERMINAL_ADMIN = "TerminalAdmin"
    TERMINAL_OPERATOR = "TerminalOperator"
    CONTRACTOR_SUPERVISOR = "ContractorSupervisor"
    MARINE_CHEMIST = "MarineChemist"
    EHS_OFFICER = "EHSOfficer"
    API653_INSPECTOR = "API653Inspector"
    LAB_TECHNICIAN = "LabTechnician"


class TankStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ContractorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    BARRED = "BARRED"


class CleaningJobStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    TANK_OOS = "TANK_OOS"
    HEEL_REMOVED = "HEEL_REMOVED"
    SLUDGE_REMOVED = "SLUDGE_REMOVED"
    GAS_FREE_PENDING = "GAS_FREE_PENDING"
    GAS_FREE_CERTIFIED = "GAS_FREE_CERTIFIED"
    ENTRY_IN_PROGRESS = "ENTRY_IN_PROGRESS"
    ENTRY_COMPLETE = "ENTRY_COMPLETE"
    INSPECTION_IN_PROGRESS = "INSPECTION_IN_PROGRESS"
    INSPECTION_ACCEPTED = "INSPECTION_ACCEPTED"
    REWORK_CLEANING = "REWORK_CLEANING"
    FLUSH_IN_PROGRESS = "FLUSH_IN_PROGRESS"
    FLUSH_VERIFIED = "FLUSH_VERIFIED"
    RTS_PENDING = "RTS_PENDING"
    RETURNED_TO_SERVICE = "RETURNED_TO_SERVICE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ServiceWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    OVERRUN = "OVERRUN"


class WasteProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class WasteShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"


class GasFreeCertificateStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class EntryPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class PermitAtmosphere(str, Enum):
    CLEAR = "CLEAR"
    ALARM = "ALARM"
    RETEST_REQUIRED = "RETEST_REQUIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REPAIR_ORDERED = "REPAIR_ORDERED"
    RESOLVED = "RESOLVED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class WastewaterBatchStatus(str, Enum):
    COLLECTED = "COLLECTED"
    LAB_TESTED = "LAB_TESTED"
    AUTHORIZED = "AUTHORIZED"
    DISCHARGED = "DISCHARGED"
    REJECTED = "REJECTED"


class ChangeoverClass(str, Enum):
    COMPATIBLE_DIRECT = "COMPATIBLE_DIRECT"
    REQUIRES_FLUSH = "REQUIRES_FLUSH"
    REQUIRES_FULL_STRIP = "REQUIRES_FULL_STRIP"
    FORBIDDEN = "FORBIDDEN"


class ProductFamily(str, Enum):
    GASOLINE = "GASOLINE"
    DISTILLATE = "DISTILLATE"
    JET = "JET"
    CRUDE = "CRUDE"
    CHEMICAL = "CHEMICAL"
    VEGOIL = "VEGOIL"


class ViscosityClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Terminal(TypedDict, total=False):
    id: str
    name: str
    wastewater_daily_capacity_liters: int
    safety_score_threshold: float
    score_variant: str
    mass_balance_tolerance_pct: float
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    code: str
    family: str
    viscosity_class: str
    compatibility_group: str
    flash_point_c: float
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict, total=False):
    id: str
    terminal_id: str
    tank_number: str
    capacity_m3: int
    current_product_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    status: str
    safety_score: float
    created_at: str
    updated_at: str
    version: int


class SafetyEvent(TypedDict, total=False):
    # Append-only: carries only id + created_at (PRD §2.4); no updated_at, no version.
    id: str
    contractor_id: str
    kind: str
    severity_weight: int
    occurred_at: str
    created_at: str


class CleaningJob(TypedDict, total=False):
    id: str
    terminal_id: str
    tank_id: str
    contractor_id: str
    from_product_id: str
    to_product_id: str
    lines_included: bool
    heel_volume_liters_sounding: int
    heel_volume_liters_metered: Optional[int]
    residual_sludge_kg: int
    base_service_fee_cents: int
    changeover_class: Optional[str]
    sludge_estimate_provisional_kg: Optional[int]
    expected_solids_kg: Optional[int]
    shipped_solids_kg: Optional[int]
    flush_volume_liters: Optional[int]
    waste_cost_cents: Optional[int]
    invoice_total_cents: Optional[int]
    window_id: Optional[str]
    status: str
    paused_from: Optional[str]
    pause_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceWindow(TypedDict, total=False):
    id: str
    tank_id: str
    job_id: Optional[str]
    planned_start: str
    planned_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteProfile(TypedDict, total=False):
    id: str
    job_id: str
    waste_code: str
    hazard_class: str
    lab_flash_point_c: float
    lab_tph_mg_l: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteShipment(TypedDict, total=False):
    id: str
    job_id: str
    profile_id: str
    lines: List[dict]
    manifested_kg: int
    disposal_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GasFreeCertificate(TypedDict, total=False):
    id: str
    job_id: str
    lel_pct: float
    o2_pct: float
    h2s_ppm: float
    benzene_ppm: float
    issued_at: str
    expires_at: str
    revalidated: bool
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EntryPermit(TypedDict, total=False):
    id: str
    job_id: str
    cert_id: str
    max_entrants: int
    issued_by_user_id: Optional[str]
    status: str
    atmosphere: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    name: str
    certification_level: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    job_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    reported_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    id: str
    inspection_id: str
    severity: str
    description: str
    requires_repair: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    finding_id: str
    job_id: str
    description: str
    completed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WastewaterBatch(TypedDict, total=False):
    id: str
    terminal_id: str
    job_id: str
    volume_liters: int
    ph: Optional[float]
    tph_mg_l: Optional[float]
    lab_user_id: Optional[str]
    discharge_day: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
