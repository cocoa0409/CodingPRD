"""Domain types for the Semi-Trailer Rental & Leasing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    BRANCH_MANAGER = "BranchManager"
    INSPECTOR = "Inspector"
    CHARGEBACK_APPROVER = "ChargebackApprover"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class BranchRegion(str, Enum):
    WEST = "WEST"
    CENTRAL = "CENTRAL"
    EAST = "EAST"


class TrailerTypeCode(str, Enum):
    DRY_VAN_53 = "DRY_VAN_53"
    REEFER_53 = "REEFER_53"
    FLATBED_48 = "FLATBED_48"
    CHASSIS_40 = "CHASSIS_40"


class TrailerAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    ON_RENT = "ON_RENT"
    ON_LEASE = "ON_LEASE"
    IN_TRANSIT = "IN_TRANSIT"
    RETIRED = "RETIRED"
    SOLD = "SOLD"


class TrailerServiceStatus(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    PM_DUE = "PM_DUE"
    OOS_DAMAGE = "OOS_DAMAGE"
    OOS_DOT_EXPIRED = "OOS_DOT_EXPIRED"


class CreditTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProductLine(str, Enum):
    SHORT_TERM_RENTAL = "SHORT_TERM_RENTAL"
    FULL_SERVICE_LEASE = "FULL_SERVICE_LEASE"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_INSURANCE = "PENDING_INSURANCE"
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PurchaseOptionStatus(str, Enum):
    NOT_OFFERED = "NOT_OFFERED"
    OFFERED = "OFFERED"
    EXERCISED = "EXERCISED"
    DECLINED = "DECLINED"


class AgreementUnitStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    OUT = "OUT"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"
    SWAPPED_OUT = "SWAPPED_OUT"
    RELEASED = "RELEASED"


class MaintenanceEventType(str, Enum):
    PM_SERVICE = "PM_SERVICE"
    DOT_INSPECTION = "DOT_INSPECTION"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class DamageAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ChargebackStatus(str, Enum):
    PENDING = "PENDING"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    WAIVED = "WAIVED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RelocationOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity shapes.  Every primary resource carries id / created_at / updated_at /
# version (PRD 2.5).  MaintenanceEvent is the sole exception: it carries only
# id and created_at.
# --------------------------------------------------------------------------
class Branch(TypedDict, total=False):
    id: str
    code: str
    name: str
    region: str
    yard_capacity: int
    peak_season_start_date: str
    peak_season_end_date: str
    lease_reserve_pct: float
    on_hand_count: int
    serviceable_available_count: int
    created_at: str
    updated_at: str
    version: int


class TrailerType(TypedDict, total=False):
    id: str
    code: str
    description: str
    base_daily_rate_cents: int
    base_monthly_rate_cents: int
    residual_floor_cents: int
    dot_inspection_interval_days: int
    pm_interval_miles: int
    required_physical_damage_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Trailer(TypedDict, total=False):
    id: str
    unit_number: str
    trailer_type_id: str
    home_branch_id: str
    current_branch_id: str
    availability_status: str
    service_status: str
    hub_miles: int
    last_pm_hub_miles: int
    last_dot_inspection_date: str
    dot_expires_on: str
    last_dot_passed: bool
    last_damage_repair_at: Optional[str]
    damage_points: int
    acquisition_cost_cents: int
    in_service_date: str
    net_book_value_cents: int
    retired_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    dot_number: str
    credit_tier: str
    credit_limit_cents: int
    outstanding_chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    customer_id: str
    carrier_name: str
    policy_number: str
    physical_damage_limit_cents: int
    liability_limit_cents: int
    effective_date: str
    expiry_date: str
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict, total=False):
    id: str
    branch_id: str
    trailer_type_id: str
    product: str
    daily_rate_cents: int
    monthly_rate_cents: int
    peak_uplift_pct: float
    mileage_included_per_month: int
    excess_mileage_rate_cents_per_mile: int
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    customer_id: str
    branch_id: str
    product: str
    trailer_type_id: str
    unit_count: int
    start_date: str
    end_date: str
    term_months: Optional[int]
    status: str
    rate_card_id: Optional[str]
    insurance_certificate_id: Optional[str]
    underwriting_risk_score: Optional[int]
    quoted_total_cents: Optional[int]
    final_total_cents: Optional[int]
    allocated_unit_count: int
    purchase_option_status: str
    purchase_option_price_cents: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgreementUnit(TypedDict, total=False):
    id: str
    agreement_id: str
    trailer_id: str
    return_branch_id: Optional[str]
    status: str
    planned_start_date: str
    planned_end_date: str
    checkout_date: Optional[str]
    return_date: Optional[str]
    checkout_hub_miles: Optional[int]
    return_hub_miles: Optional[int]
    peak_days: Optional[int]
    excess_miles: Optional[int]
    drop_charge_cents: Optional[int]
    line_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceEvent(TypedDict, total=False):
    """Immutable ledger row: id and created_at only (PRD 2.5)."""
    id: str
    trailer_id: str
    event_type: str
    performed_on: str
    hub_miles_at_event: int
    cost_cents: int
    passed: Optional[bool]
    inspector_user_id: str
    created_at: str


class DamageLineItem(TypedDict, total=False):
    severity: str
    quantity: int
    unit_cost_cents: int
    description: str


class DamageAssessment(TypedDict, total=False):
    id: str
    agreement_unit_id: str
    trailer_id: str
    supersedes_assessment_id: Optional[str]
    assessor_user_id: str
    line_items: List[DamageLineItem]
    status: str
    assessed_amount_cents: Optional[int]
    insured_portion_cents: Optional[int]
    customer_liable_cents: Optional[int]
    admin_fee_cents: Optional[int]
    damage_points: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    damage_assessment_id: str
    customer_id: str
    amount_cents: int
    status: str
    approver_user_id: Optional[str]
    dispute_reason: Optional[str]
    waiver_reason: Optional[str]
    paid_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RelocationOrder(TypedDict, total=False):
    id: str
    trailer_id: str
    origin_branch_id: str
    destination_branch_id: str
    status: str
    planned_depart_date: str
    planned_arrive_date: str
    planned_miles: int
    actual_miles: Optional[int]
    deadhead_miles: Optional[int]
    actual_arrive_date: Optional[str]
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    reject_reason: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
