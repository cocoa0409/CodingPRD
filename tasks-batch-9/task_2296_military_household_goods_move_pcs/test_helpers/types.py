"""Domain types for the military household-goods move API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    SERVICE_MEMBER = "ServiceMember"
    MOVE_COUNSELOR = "MoveCounselor"
    TSP_COORDINATOR = "TspCoordinator"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    PROGRAM_ADMIN = "ProgramAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    ISSUED = "ISSUED"
    AMENDED = "AMENDED"
    CLOSED = "CLOSED"


class CounselingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EntitlementStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MovingCompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class CapacityBlockStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class ShipmentMovementStatus(str, Enum):
    AWARDED = "AWARDED"
    ON_HOLD = "ON_HOLD"
    SURVEYED = "SURVEYED"
    PACKED = "PACKED"
    PICKED_UP = "PICKED_UP"
    IN_SIT = "IN_SIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WeightReconStatus(str, Enum):
    PENDING = "PENDING"
    ESTIMATED = "ESTIMATED"
    ACTUAL_RECORDED = "ACTUAL_RECORDED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"


class ProGearStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    REJECTED = "REJECTED"


class SitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    RELEASED = "RELEASED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class ClaimItemDisposition(str, Enum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class PpmStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    LATE = "LATE"


# ---------------------------------------------------------------------------
# Enumerated value domains
# ---------------------------------------------------------------------------


class MoveType(str, Enum):
    PCS_CONUS = "PCS_CONUS"
    PCS_OCONUS = "PCS_OCONUS"
    SEPARATION = "SEPARATION"
    RETIREMENT = "RETIREMENT"
    LOCAL = "LOCAL"


class Branch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINE_CORPS = "MARINE_CORPS"
    SPACE_FORCE = "SPACE_FORCE"
    COAST_GUARD = "COAST_GUARD"


class SessionType(str, Enum):
    SELF_SERVICE = "SELF_SERVICE"
    VIRTUAL = "VIRTUAL"
    IN_PERSON = "IN_PERSON"


class DependentStatus(str, Enum):
    WITHOUT_DEPENDENTS = "WITHOUT_DEPENDENTS"
    WITH_DEPENDENTS = "WITH_DEPENDENTS"


class ShipmentMethod(str, Enum):
    HHG = "HHG"
    UB = "UB"
    NTS = "NTS"
    PPM = "PPM"


class EstimateMethod(str, Enum):
    CUBE_X7 = "CUBE_X7"
    INVENTORY_TABLE = "INVENTORY_TABLE"


class BillableBasis(str, Enum):
    NONE = "NONE"
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class ProGearOwner(str, Enum):
    MEMBER = "MEMBER"
    SPOUSE = "SPOUSE"


class DocumentationType(str, Enum):
    ITEMIZED_INVENTORY = "ITEMIZED_INVENTORY"
    EMPLOYER_LETTER = "EMPLOYER_LETTER"
    ORDERS_EXTRACT = "ORDERS_EXTRACT"
    NONE = "NONE"


class SitType(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"


class ClaimType(str, Enum):
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"
    BOTH = "BOTH"


class SettlementBasis(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    FULL_REPLACEMENT_VALUE = "FULL_REPLACEMENT_VALUE"
    DEPRECIATED_VALUE = "DEPRECIATED_VALUE"


class ClaimItemCategory(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    FURNITURE = "FURNITURE"
    APPLIANCE = "APPLIANCE"
    CLOTHING = "CLOTHING"
    OTHER = "OTHER"


class ElectedBasis(str, Enum):
    AUTO = "AUTO"
    INCENTIVE_BASIS = "INCENTIVE_BASIS"
    ACTUAL_EXPENSE_BASIS = "ACTUAL_EXPENSE_BASIS"


class NotificationType(str, Enum):
    PACK_DATE_CONFIRMED = "PACK_DATE_CONFIRMED"
    PICKUP_CONFIRMED = "PICKUP_CONFIRMED"
    SIT_ENTRY = "SIT_ENTRY"
    WEIGHT_RECON_COMPLETE = "WEIGHT_RECON_COMPLETE"
    CLAIM_ACK = "CLAIM_ACK"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PORTAL = "PORTAL"


# ---------------------------------------------------------------------------
# Entity shapes — every entity carries id, created_at, updated_at and version
# ---------------------------------------------------------------------------


class ServiceMember(TypedDict):
    id: str
    dod_id: str
    full_name: str
    rank_code: str
    branch: str
    email: str
    dependents_count: int
    spouse_present: bool
    active_shipment_count: int
    created_at: str
    updated_at: str
    version: int


class PcsOrder(TypedDict):
    id: str
    service_member_id: str
    order_number: str
    move_type: str
    issue_date: str
    report_no_later_than_date: str
    origin_duty_station: str
    destination_duty_station: str
    origin_market_code: str
    distance_miles: int
    is_dependent_restricted: bool
    dependents_count_at_issue: int
    status: str
    amendment_count: int
    last_amendment_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    order_id: str
    session_type: str
    scheduled_at: str
    counseling_deadline_at: str
    counselor_user_id: Optional[str]
    completed_at: Optional[str]
    entitlement_briefed: bool
    is_late_counseling: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict):
    id: str
    order_id: str
    counseling_session_id: str
    rank_code_at_authorization: str
    dependent_status_effective: str
    base_weight_allowance_lbs: int
    pro_gear_member_allowance_lbs: int
    pro_gear_spouse_allowance_lbs: int
    admin_weight_bump_lbs: int
    total_billable_cap_lbs: int
    charged_billable_weight_lbs: int
    pro_gear_excluded_total_lbs: int
    excess_weight_lbs: int
    gross_excess_cost_usd: float
    excess_cost_waived_usd: float
    excess_cost_due_usd: float
    status: str
    suspension_reason: Optional[str]
    authorized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MovingCompany(TypedDict):
    id: str
    name: str
    scac_code: str
    markets: List[str]
    performance_score: float
    settled_claim_count: int
    claim_settlement_total_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityBlock(TypedDict):
    id: str
    tsp_id: str
    market_code: str
    week_start_date: str
    week_end_date: str
    peak_season: bool
    total_capacity_lbs: int
    short_notice_reserve_pct: float
    effective_reserve_pct: float
    general_pool_lbs: int
    short_notice_pool_lbs: int
    committed_general_lbs: int
    committed_short_notice_lbs: int
    committed_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    entitlement_id: str
    tsp_id: str
    capacity_block_id: Optional[str]
    superseded_shipment_id: Optional[str]
    shipment_code: str
    shipment_method: str
    origin_market_code: str
    requested_pack_date: str
    requested_pickup_date: str
    requested_delivery_date: str
    is_short_notice: bool
    peak_season: bool
    spread_start_date: str
    spread_end_date: str
    transit_days_allowed: int
    required_delivery_by: Optional[str]
    movement_status: str
    weight_recon_status: str
    hold_reason: Optional[str]
    cancel_reason: Optional[str]
    survey_date: Optional[str]
    estimate_method: Optional[str]
    estimated_gross_lbs: Optional[int]
    actual_gross_lbs: Optional[int]
    actual_tare_lbs: Optional[int]
    net_actual_lbs: Optional[int]
    weigh_date: Optional[str]
    reweigh_required: bool
    pro_gear_excluded_lbs: int
    billable_weight_lbs: int
    billable_basis: str
    pack_date: Optional[str]
    actual_pickup_date: Optional[str]
    delivery_date: Optional[str]
    booked_at: str
    created_at: str
    updated_at: str
    version: int


class ProGearDeclaration(TypedDict):
    id: str
    shipment_id: str
    owner: str
    item_description: str
    claimed_weight_lbs: int
    documentation_type: str
    verified_weight_lbs: int
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    resubmission_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SitAuthorization(TypedDict):
    id: str
    shipment_id: str
    sit_type: str
    entry_date: str
    requested_days: int
    authorized_days: int
    extension_days: int
    total_authorized_days: int
    release_date: Optional[str]
    days_used: Optional[int]
    excess_days: int
    sit_base_cost_usd: float
    fuel_surcharge_pct: float
    fuel_surcharge_usd: float
    sit_total_cost_usd: float
    member_liability_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LossDamageClaim(TypedDict):
    id: str
    shipment_id: str
    claim_type: str
    notice_date: str
    incident_description: str
    filed_date: Optional[str]
    filing_window_days: Optional[int]
    settlement_basis: str
    claimed_total_usd: float
    settlement_total_usd: float
    item_count: int
    info_request_count: int
    reviewed_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimItem(TypedDict):
    id: str
    claim_id: str
    item_description: str
    inventory_item_number: str
    category: str
    replacement_cost_usd: float
    age_years: float
    high_value_inventory_documented: bool
    depreciation_rate_pct_per_year: float
    disposition: str
    adjudication_note: Optional[str]
    item_settlement_usd: float
    created_at: str
    updated_at: str
    version: int


class PpmSubmission(TypedDict):
    id: str
    shipment_id: str
    trip_tickets: List[Dict[str, Any]]
    moved_weight_lbs: int
    allowable_weight_lbs: int
    documented_expenses_usd: float
    advance_paid_usd: float
    elected_basis: str
    applied_basis: str
    gcc_usd: float
    incentive_usd: float
    reimbursement_usd: float
    net_payable_usd: float
    debt_owed_usd: float
    taxable_amount_usd: float
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    shipment_id: str
    notification_type: str
    trigger_event_at: str
    sla_hours: int
    due_by: str
    channel: Optional[str]
    sent_at: Optional[str]
    hours_late: float
    status: str
    created_at: str
    updated_at: str
    version: int
