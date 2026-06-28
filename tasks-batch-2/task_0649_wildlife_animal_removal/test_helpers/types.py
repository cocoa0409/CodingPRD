"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the common fields id, created_at, updated_at,
and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class WorkOrderLifecycle(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RemovalStatus(str, Enum):
    PENDING = "PENDING"
    TRAPPING = "TRAPPING"
    CLEARED = "CLEARED"


class ExclusionStatus(str, Enum):
    PENDING = "PENDING"
    SEALING = "SEALING"
    SEALED = "SEALED"


class TrapPlacementStatus(str, Enum):
    SET = "SET"
    SPENT = "SPENT"
    EMPTY = "EMPTY"
    CANCELLED = "CANCELLED"


class ExclusionRepairStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PropertyPosture(str, Enum):
    OPEN = "OPEN"
    ACTIVE_REMEDIATION = "ACTIVE_REMEDIATION"
    REGULATORY_HOLD = "REGULATORY_HOLD"


class EntryPointSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class SealStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"


class LicenseTier(str, Enum):
    BASIC = "BASIC"
    CERTIFIED = "CERTIFIED"


class LineType(str, Enum):
    TRAP = "TRAP"
    EXCLUSION = "EXCLUSION"


class Disposition(str, Enum):
    RELOCATED = "RELOCATED"


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    PROPERTY_OWNER = "PropertyOwner"
    FIELD_TECHNICIAN = "FieldTechnician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Entity TypedDicts (all carry common fields) ───────────────────────────

class SpeciesProfile(TypedDict):
    id: str
    common_name: str
    code: str
    is_regulated: bool
    relocation_min_miles: float
    relocation_max_miles: float
    humane_check_interval_hours: int
    base_trap_fee_cents: int
    risk_weight: float
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    license_tier: str
    kit_trap_capacity: int
    traps_deployed: int
    traps_available: int
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    account_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    account_id: str
    latitude: float
    longitude: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    property_id: str
    scheduled_for: str
    is_emergency: bool
    status: str
    detected_individual_count: int
    created_at: str
    updated_at: str
    version: int


class EntryPoint(TypedDict):
    id: str
    inspection_id: str
    species_id: str
    location_label: str
    severity: str
    estimated_individuals: int
    seal_status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    inspection_id: str
    status: str
    provisional_total_cents: int
    final_total_cents: int
    emergency_flag: bool
    created_at: str
    updated_at: str
    version: int


class QuoteLineItem(TypedDict):
    id: str
    quote_id: str
    species_id: str
    line_type: str
    quantity: int
    unit_price_cents: int
    performed: bool
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    quote_id: str
    property_id: str
    assigned_technician_id: str
    lifecycle: str
    removal_status: str
    exclusion_status: str
    net_charged_cents: int
    initial_risk_score: float
    residual_risk_score: float
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    work_order_id: str
    species_id: str
    status: str
    permit_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrapPlacement(TypedDict):
    id: str
    work_order_id: str
    species_id: str
    technician_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CaptureEvent(TypedDict):
    id: str
    trap_placement_id: str
    captured_at: str
    release_latitude: float
    release_longitude: float
    release_distance_miles: float
    disposition: str
    created_at: str
    updated_at: str
    version: int


class ExclusionRepair(TypedDict):
    id: str
    work_order_id: str
    entry_point_id: str
    sanitation_included: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringVisit(TypedDict):
    id: str
    work_order_id: str
    property_id: str
    visit_start: str
    visit_end: str
    traps_reset: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    work_order_id: str
    reported_at: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
