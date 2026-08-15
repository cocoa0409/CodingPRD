"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RAILROAD_CONTRACTS_MANAGER = "RailroadContractsManager"
    SHIPPER_FACILITY_MANAGER = "ShipperFacilityManager"
    RAILROAD_ENGINEER = "RailroadEngineer"
    SAFETY_INSPECTOR = "SafetyInspector"
    RAILROAD_SERVICE_MANAGER = "RailroadServiceManager"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    ABANDONMENT_IN_PROGRESS = "ABANDONMENT_IN_PROGRESS"
    CLOSED = "CLOSED"


class AmendmentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AmendmentType(str, Enum):
    COST_SHARE = "COST_SHARE"
    LIABILITY_CAP = "LIABILITY_CAP"
    STORAGE_RATE = "STORAGE_RATE"
    DEMURRAGE_RATES = "DEMURRAGE_RATES"
    TERM = "TERM"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SPEC_SUBMITTED = "SPEC_SUBMITTED"
    SPEC_REJECTED = "SPEC_REJECTED"
    SPEC_APPROVED = "SPEC_APPROVED"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"


class SegmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    REMOVED = "REMOVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DeviceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    INSTALLED = "INSTALLED"
    NON_COMPLIANT = "NON_COMPLIANT"


class DeviceType(str, Enum):
    DERAIL = "DERAIL"
    WHEEL_STOP = "WHEEL_STOP"
    BUMPING_POST = "BUMPING_POST"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    SWITCHING = "SWITCHING"
    MAINTENANCE_POSSESSION = "MAINTENANCE_POSSESSION"


class DwellStatus(str, Enum):
    SPOTTED = "SPOTTED"
    RELEASED = "RELEASED"


class CarOwnership(str, Enum):
    RAILROAD = "RAILROAD"
    PRIVATE = "PRIVATE"


class PlacementStatus(str, Enum):
    STORED = "STORED"
    RELEASED = "RELEASED"
    FORCE_RELEASED = "FORCE_RELEASED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPORTIONED = "APPORTIONED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"


# All entities carry the common system-managed fields of PRD §2.5:
# id (UUID), created_at / updated_at (ISO 8601 UTC), version (int, starts at 1).


class TrackAgreement(TypedDict, total=False):
    id: str
    shipper_name: str
    shipper_user_id: str
    facility_name: str
    term_start_date: str
    term_end_date: str
    renewal_notice_days: int
    renewal_term_months: int
    shipper_cost_share_pct: float
    liability_cap_cents: int
    shipper_indemnity_default_pct: float
    free_time_hours: int
    demurrage_base_rate_cents: int
    demurrage_escalated_rate_cents: int
    storage_rate_per_car_month_cents: int
    inspection_cadence_days: int
    removal_period_days: int
    removal_penalty_per_day_cents: int
    service_days_of_week: List[str]
    max_switches_per_day: int
    abandonment_notice_date: Optional[str]
    removal_deadline_date: Optional[str]
    removal_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict, total=False):
    id: str
    agreement_id: str
    amendment_type: str
    new_shipper_cost_share_pct: Optional[float]
    new_liability_cap_cents: Optional[int]
    new_storage_rate_per_car_month_cents: Optional[int]
    new_demurrage_base_rate_cents: Optional[int]
    new_demurrage_escalated_rate_cents: Optional[int]
    new_term_end_date: Optional[str]
    proposed_by_role: str
    proposed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConstructionProject(TypedDict, total=False):
    id: str
    agreement_id: str
    project_name: str
    estimated_cost_cents: int
    shipper_share_pct: float
    rail_weight_lb_per_yard: Optional[float]
    tie_material: Optional[str]
    ballast_depth_inches: Optional[float]
    spec_revision_no: int
    shipper_estimated_share_cents: Optional[int]
    actual_cost_cents: Optional[int]
    shipper_final_share_cents: Optional[int]
    amount_paid_cents: int
    outstanding_share_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackSegment(TypedDict, total=False):
    id: str
    agreement_id: str
    segment_name: str
    length_feet: int
    storage_capacity_cars: int
    stored_car_count: int
    accrued_storage_cents: int
    safety_suspended: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict, total=False):
    id: str
    agreement_id: str
    segment_id: str
    scheduled_date: str
    due_date: str
    result: Optional[str]
    completed_date: Optional[str]
    cited_device_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DerailDevice(TypedDict, total=False):
    id: str
    segment_id: str
    device_type: str
    location_description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    agreement_id: str
    segment_id: str
    order_type: str
    service_date: str
    start_hour: int
    end_hour: int
    cars_spotted: Optional[int]
    cars_pulled: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarDwell(TypedDict, total=False):
    id: str
    agreement_id: str
    car_mark: str
    car_ownership: str
    placed_at: str
    released_at: Optional[str]
    dwell_minutes: Optional[int]
    chargeable_days: Optional[int]
    accrued_demurrage_cents: int
    final_demurrage_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class StoragePlacement(TypedDict, total=False):
    id: str
    segment_id: str
    car_mark: str
    placed_date: str
    released_date: Optional[str]
    accrued_storage_charge_cents: int
    days_charged: Optional[int]
    final_storage_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiabilityClaim(TypedDict, total=False):
    id: str
    agreement_id: str
    claimant_name: str
    incident_date: str
    claim_amount_cents: int
    shipper_fault_pct: Optional[float]
    shipper_liability_cents: Optional[int]
    railroad_liability_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
