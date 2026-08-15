"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.4 (common resource properties): every entity in the
district system carries id + created_at + updated_at + version.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    DITCH_RIDER = "DitchRider"
    WATER_USER = "WaterUser"


class PriorityClass(str, Enum):
    SENIOR = "SENIOR"
    JUNIOR = "JUNIOR"


class WaterAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CURTAILED = "CURTAILED"
    CLOSED = "CLOSED"


class TurnoutOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    FLOWING = "FLOWING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class WorkOrderStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    MEASUREMENT_SUBMITTED = "MEASUREMENT_SUBMITTED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DELINQUENT = "DELINQUENT"
    LIEN_FILED = "LIEN_FILED"
    PAID = "PAID"


class ReachStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    SHUTDOWN = "SHUTDOWN"


class WindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DroughtStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    LIFTED = "LIFTED"


class DroughtStage(str, Enum):
    STAGE_1 = "STAGE_1"
    STAGE_2 = "STAGE_2"
    STAGE_3 = "STAGE_3"


class BillingMethod(str, Enum):
    PER_ACRE = "PER_ACRE"
    PER_AF_DELIVERED = "PER_AF_DELIVERED"


# ---------------------------------------------------------------------------
# Entity bodies (all carry the full common set per PRD §2.4)
# ---------------------------------------------------------------------------

class WaterAccount(TypedDict):
    id: str
    holder_name: str
    parcel_number: str
    irrigated_acres: float
    water_right_priority_date: str
    priority_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IrrigationSeason(TypedDict):
    id: str
    year: int
    announced_af_per_acre: float
    carryover_cap_pct: float
    billing_method: str
    assessment_rate_per_acre: float
    toll_tier1_cap_af: float
    toll_tier1_rate_per_af: float
    toll_tier2_rate_per_af: float
    overage_rate_per_af: float
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonAllocation(TypedDict):
    id: str
    water_account_id: str
    season_id: str
    base_entitlement_af: float
    curtailed_entitlement_af: Optional[float]
    effective_entitlement_af: float
    carryover_in_af: float
    carryover_out_af: Optional[float]
    transfers_in_af: float
    transfers_out_af: float
    delivered_af: float
    committed_af: float
    available_af: float
    over_allocated_af: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TurnoutOrder(TypedDict):
    id: str
    water_account_id: str
    season_allocation_id: str
    canal_reach_id: str
    requested_cfs: float
    requested_start_at: str
    requested_end_at: str
    requested_quantity_af: float
    actual_delivered_af: Optional[float]
    over_delivered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RiderWorkOrder(TypedDict):
    id: str
    turnout_order_id: str
    rider_user_id: str
    measured_cfs: Optional[float]
    measured_hours: Optional[float]
    measured_af: Optional[float]
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssessmentInvoice(TypedDict):
    id: str
    water_account_id: str
    season_id: str
    billing_method_snapshot: str
    acreage_line_amount: float
    toll_line_amount: float
    penalty_line_amount: float
    total_amount: float
    issued_at: Optional[str]
    due_date: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CanalReach(TypedDict):
    id: str
    name: str
    max_capacity_cfs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    canal_reach_id: str
    start_at: str
    end_at: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    from_account_id: str
    to_account_id: str
    season_id: str
    quantity_af: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DroughtDeclaration(TypedDict):
    id: str
    season_id: str
    stage: str
    senior_curtailment_pct: float
    junior_curtailment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int
