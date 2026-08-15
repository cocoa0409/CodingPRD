"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class PlantStatus(str, Enum):
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CylinderStatus(str, Enum):
    IDLE = "IDLE"
    LOADED = "LOADED"
    CYCLE_RUNNING = "CYCLE_RUNNING"
    DRAINING = "DRAINING"
    NEEDS_CLEANING = "NEEDS_CLEANING"
    DECOMMISSIONED = "DECOMMISSIONED"


class PreservativeStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class ChargeStatus(str, Enum):
    STAGED = "STAGED"
    IN_CYLINDER = "IN_CYLINDER"
    CYCLE_COMPLETE = "CYCLE_COMPLETE"
    ASSAYED_PASS = "ASSAYED_PASS"
    ASSAYED_FAIL = "ASSAYED_FAIL"
    RE_TREAT_PENDING = "RE_TREAT_PENDING"
    TAGGED = "TAGGED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    SCRAPPED = "SCRAPPED"


class PieceStatus(str, Enum):
    RAW = "RAW"
    INCISED = "INCISED"
    TREATED = "TREATED"
    ASSAYED_PASS = "ASSAYED_PASS"
    ASSAYED_FAIL = "ASSAYED_FAIL"
    TAGGED = "TAGGED"
    RELEASED = "RELEASED"
    SCRAPPED = "SCRAPPED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class AssayOutcome(str, Enum):
    PASS = "PASS"
    FAIL_MARGINAL = "FAIL_MARGINAL"
    FAIL_GROSS = "FAIL_GROSS"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED_BY_RETREAT = "VOIDED_BY_RETREAT"
    LAPSED = "LAPSED"


class UserRole(str, Enum):
    PLANT_OPERATOR = "PlantOperator"
    LAB_TECHNICIAN = "LabTechnician"
    QUALITY_MANAGER = "QualityManager"
    QUALITY_AGENCY_INSPECTOR = "QualityAgencyInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ACCOUNTS_RECEIVABLE = "AccountsReceivable"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).

class TreatmentPlant(TypedDict, total=False):
    id: str
    plant_name: str
    alsc_license_number: str
    compliance_score: int
    hazardous_waste_liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentCylinder(TypedDict, total=False):
    id: str
    plant_id: str
    cylinder_code: str
    max_volume_mbf: float
    supported_process_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PreservativeConcentrate(TypedDict, total=False):
    id: str
    plant_id: str
    chemical_family: str
    concentrate_assay_pct: float
    inventory_gallons: float
    min_working_assay_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    customer_name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict, total=False):
    id: str
    cylinder_id: str
    customer_id: Optional[str]
    ownership_type: str
    species_group: str
    use_category: str
    volume_mbf: float
    target_retention_pcf: float
    provisional_retention_pcf: float
    final_retention_pcf: float
    requires_incising: bool
    is_custom_treat: bool
    hazard_containment_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargePiece(TypedDict, total=False):
    id: str
    charge_id: str
    piece_tag: str
    length_ft: float
    width_in: float
    thickness_in: float
    penetration_pct: float
    incised: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentCycle(TypedDict, total=False):
    id: str
    charge_id: str
    cycle_number: int
    process_type: str
    preservative_id: str
    vacuum_inhg: float
    pressure_psi: float
    pressure_minutes: int
    solution_assay_at_start_pct: float
    gross_absorption_pcf: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityInspection(TypedDict, total=False):
    id: str
    plant_id: str
    agency_code: str
    inspection_window_start: str
    inspection_window_end: str
    charges_in_scope: List[str]
    findings_count: int
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    id: str
    charge_id: str
    registered_by_user_id: str
    warranty_term_years: int
    registration_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only records carry ONLY id + created_at (PRD §2.4: RetentionAssay,
# DripPadLog, CylinderScheduleSlot have no updated_at and no version).

class RetentionAssay(TypedDict, total=False):
    id: str
    charge_id: str
    cycle_id: str
    assay_method: str
    sample_count: int
    mean_retention_pcf: float
    min_sample_retention_pcf: float
    recorded_by_agency: str
    pass_threshold_pcf: float
    outcome: str
    recorded_at: str
    created_at: str


class DripPadLog(TypedDict, total=False):
    id: str
    charge_id: str
    pad_code: str
    entered_pad_at: str
    exited_pad_at: str
    drip_volume_liters: float
    containment_breach: bool
    liability_cents: int
    created_at: str


class CylinderScheduleSlot(TypedDict, total=False):
    id: str
    cylinder_id: str
    charge_id: Optional[str]
    slot_start: str
    slot_end: str
    slot_kind: str
    buffer_minutes: int
    created_at: str
