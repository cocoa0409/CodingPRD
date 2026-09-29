"""Domain types for the Solar Reroof Coordination API: status enums, entity
TypedDicts and the role enumeration.

Every type here mirrors the field names the PRD uses verbatim.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROJECT_COORDINATOR = "ProjectCoordinator"
    SOLAR_CONTRACTOR = "SolarContractor"
    ROOFING_CONTRACTOR = "RoofingContractor"
    SOLAR_OWNER = "SolarOwner"
    SYSTEM_OWNER = "SystemOwner"
    AHJ_INSPECTOR = "AHJInspector"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PartyType(str, Enum):
    ROOFER = "ROOFER"
    SOLAR_OWNER = "SOLAR_OWNER"
    SYSTEM_OWNER = "SYSTEM_OWNER"
    SOLAR_CONTRACTOR = "SOLAR_CONTRACTOR"


class OwnershipModel(str, Enum):
    HOST_OWNED = "HOST_OWNED"
    LEASE = "LEASE"
    PPA = "PPA"


class ProjectPhase(str, Enum):
    INTAKE = "INTAKE"
    APPROVALS_OPEN = "APPROVALS_OPEN"
    AUTHORIZED = "AUTHORIZED"
    DEENERGIZED = "DEENERGIZED"
    DECK_WORK = "DECK_WORK"
    REINSTALL = "REINSTALL"
    COMMISSIONED = "COMMISSIONED"
    CLOSED = "CLOSED"


class ProjectPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class WarrantyNoticeStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    FILED = "FILED"
    LAPSED = "LAPSED"


class ApprovalRole(str, Enum):
    ROOFER = "ROOFER"
    SOLAR_OWNER = "SOLAR_OWNER"
    SYSTEM_OWNER = "SYSTEM_OWNER"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class CircuitStatus(str, Enum):
    ENERGIZED = "ENERGIZED"
    ISOLATION_PENDING = "ISOLATION_PENDING"
    ISOLATED = "ISOLATED"


class UnitType(str, Enum):
    PANEL = "PANEL"
    OPTIMIZER = "OPTIMIZER"


class HandlingStatus(str, Enum):
    ON_ROOF = "ON_ROOF"
    REMOVED = "REMOVED"
    STORED = "STORED"
    REINSTALLED = "REINSTALLED"
    SCRAPPED = "SCRAPPED"


class ConditionGrade(str, Enum):
    UNINSPECTED = "UNINSPECTED"
    SERVICEABLE = "SERVICEABLE"
    DAMAGED = "DAMAGED"
    REPLACED = "REPLACED"


class WarrantyVariant(str, Enum):
    MANUFACTURER_STRICT = "MANUFACTURER_STRICT"
    INSTALLER_LENIENT = "INSTALLER_LENIENT"


class FindingType(str, Enum):
    SHEATHING_ROT = "SHEATHING_ROT"
    FASTENER_PULLOUT = "FASTENER_PULLOUT"
    FLASHING_FAILURE = "FLASHING_FAILURE"
    MOISTURE_INTRUSION = "MOISTURE_INTRUSION"
    STRUCTURAL_DEFLECTION = "STRUCTURAL_DEFLECTION"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    UPGRADE_SCOPED = "UPGRADE_SCOPED"
    UPGRADE_COMPLETED = "UPGRADE_COMPLETED"
    WAIVED = "WAIVED"


class PermitScope(str, Enum):
    REINSTALL_ONLY = "REINSTALL_ONLY"
    STRUCTURAL_UPGRADE = "STRUCTURAL_UPGRADE"
    FULL_REPERMIT = "FULL_REPERMIT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InspectionType(str, Enum):
    ROOF_DECK = "ROOF_DECK"
    MOUNTING = "MOUNTING"
    ELECTRICAL_FINAL = "ELECTRICAL_FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


class Trade(str, Enum):
    ROOFING = "ROOFING"
    SOLAR_REMOVAL = "SOLAR_REMOVAL"
    SOLAR_REINSTALL = "SOLAR_REINSTALL"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WEATHER_ABORTED = "WEATHER_ABORTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class MatchClass(str, Enum):
    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    MISMATCHED = "MISMATCHED"


class SourcingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Party(TypedDict):
    """Carries id, created_at, updated_at and version (PRD §2.4)."""

    id: str
    name: str
    party_type: str
    contact_email: str
    mobilization_buffer_minutes: int
    daily_crew_capacity: int
    license_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    """Immutable: carries ONLY id and created_at — no updated_at, no version."""

    id: str
    name: str
    code: str
    repermit_required_for_reinstall: bool
    reinspection_required: bool
    inspection_slots_per_day: int
    backlog_days: int
    permit_review_days: int
    expedite_fee_cents: int
    created_at: str


class ReroofProject(TypedDict):
    id: str
    site_address: str
    ownership_model: str
    system_dc_kw: float
    roofer_party_id: str
    solar_owner_party_id: str
    system_owner_party_id: Optional[str]
    solar_contractor_party_id: str
    baseline_daily_kwh: float
    downtime_days_estimated: int
    upgrade_budget_cents: int
    phase: str
    posture: str
    negotiation_round: int
    required_approval_party_count: int
    authorized_at: Optional[str]
    deenergized_at: Optional[str]
    reenergized_at: Optional[str]
    provisional_credit_cents: int
    final_credit_cents: int
    credit_authorized_cents: int
    credit_reserved_cents: int
    credit_settled_cents: int
    credit_released_cents: int
    weather_abort_count: int
    warranty_notice_status: str
    warranty_notice_filed_at: Optional[str]
    warranty_notice_reference: Optional[str]
    warranty_preserved: bool
    registered_unit_count: int
    stored_unit_count: int
    reinstalled_unit_count: int
    scrapped_unit_count: int
    damaged_unit_count: int
    open_critical_finding_count: int
    scoped_upgrade_cost_cents: int
    downtime_days_actual: int
    created_at: str
    updated_at: str
    version: int


class PartyApproval(TypedDict):
    id: str
    project_id: str
    party_id: str
    approval_role: str
    status: str
    round_recorded: int
    decision_note: Optional[str]
    decided_at: Optional[str]
    veto_flag: bool
    change_request_count: int
    created_at: str
    updated_at: str
    version: int


class ArrayCircuit(TypedDict):
    id: str
    project_id: str
    circuit_label: str
    module_count: int
    dc_kw: float
    status: str
    interlock_verified: bool
    isolation_note: Optional[str]
    isolated_at: Optional[str]
    reenergized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict):
    id: str
    project_id: str
    bin_label: str
    capacity_slots: int
    climate_controlled: bool
    accepts_unit_types: List[str]
    occupied_slots: int
    created_at: str
    updated_at: str
    version: int


class HardwareUnit(TypedDict):
    id: str
    project_id: str
    array_circuit_id: str
    storage_bin_id: Optional[str]
    unit_type: str
    manufacturer: str
    model_code: str
    serial_number: str
    rated_watts: int
    handling_status: str
    condition_grade: str
    storage_label: Optional[str]
    storage_position: Optional[int]
    warranty_variant: Optional[str]
    warranty_preserved: Optional[bool]
    warranty_risk_points: int
    damage_note: Optional[str]
    removed_at: Optional[str]
    stored_at: Optional[str]
    reinstalled_at: Optional[str]
    off_roof_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DeckFinding(TypedDict):
    id: str
    project_id: str
    scoped_by_party_id: Optional[str]
    completed_by_party_id: Optional[str]
    finding_type: str
    severity: str
    affected_area_sqft: float
    attachment_count_affected: int
    status: str
    upgrade_cost_cents: int
    requires_repermit: bool
    waiver_reason: Optional[str]
    scoped_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    project_id: str
    jurisdiction_id: str
    scope: str
    status: str
    expedited: bool
    fee_cents: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    review_deadline_utc: Optional[str]
    revision_count: int
    rejection_reason: Optional[str]
    reopened_by_finding_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    permit_application_id: str
    inspection_type: str
    slot_date: str
    window_start_utc: str
    window_end_utc: str
    status: str
    attempt_number: int
    result_note: Optional[str]
    inspected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkWindow(TypedDict):
    id: str
    project_id: str
    party_id: str
    supersedes_window_id: Optional[str]
    trade: str
    start_utc: str
    end_utc: str
    status: str
    weather_risk_score: int
    abort_reason: Optional[str]
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourcingOrder(TypedDict):
    id: str
    project_id: str
    hardware_unit_id: str
    requested_model_code: str
    offered_manufacturer: str
    offered_model_code: str
    offered_rated_watts: int
    unit_cost_cents: int
    waiver_ref: Optional[str]
    watt_delta_pct: float
    tolerance_pct: float
    match_class: str
    status: str
    review_note: Optional[str]
    received_serial_number: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DowntimeSummary(TypedDict):
    downtime_days_actual: int
    provisional_credit_cents: int
    final_credit_cents: int
    credit_authorized_cents: int
    credit_reserved_cents: int
    credit_settled_cents: int
    credit_released_cents: int
    ledger_balanced: bool
