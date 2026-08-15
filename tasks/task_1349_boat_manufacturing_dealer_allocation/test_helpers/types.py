"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity descriptions (§3) and endpoint table (§4).
Entities with the standard system-managed field set carry id + created_at +
updated_at + version. OrderOptionLine deviates (PRD §2.4): it carries only
id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    ALLOCATION_MANAGER = "AllocationManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    DEALER_PRINCIPAL = "DealerPrincipal"
    ANY = "Any"


class BoatModelStatus(str, Enum):
    ORDERABLE = "ORDERABLE"
    DISCONTINUED = "DISCONTINUED"


class DealerStanding(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    PROBATION = "PROBATION"


class RateTier(str, Enum):
    TIER_STANDARD = "TIER_STANDARD"
    TIER_ELEVATED = "TIER_ELEVATED"
    TIER_HIGH = "TIER_HIGH"


class Season(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class ProductionRunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BuildSlotStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"


class OrderSource(str, Enum):
    RETAIL = "RETAIL"
    FLEET = "FLEET"
    BOAT_SHOW = "BOAT_SHOW"


class DealerOrderStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    ALLOCATED = "ALLOCATED"
    COMMITTED = "COMMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DELIVERED = "DELIVERED"
    RETAILED = "RETAILED"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    RECALL_HOLD = "RECALL_HOLD"


class DeliveryStatus(str, Enum):
    AT_PLANT = "AT_PLANT"
    DELIVERED = "DELIVERED"


class AdvanceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ClaimVariant(str, Enum):
    STANDARD = "STANDARD"
    RECALL_GOODWILL = "RECALL_GOODWILL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CampaignSeverity(str, Enum):
    SAFETY_STOP = "SAFETY_STOP"
    SAFETY_STANDARD = "SAFETY_STANDARD"
    EMISSIONS = "EMISSIONS"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class NoticeStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    REMEDIED = "REMEDIED"


class RemedyPath(str, Enum):
    WARRANTY_CLAIM = "WARRANTY_CLAIM"
    PLANT_REMEDY = "PLANT_REMEDY"


# ---------------------------------------------------------------------------
# Entity TypedDicts (standard common field set: id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class BoatModel(TypedDict, total=False):
    id: str
    model_code: str
    model_name: str
    model_year: int
    base_price_cents: int
    length_feet: float
    production_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionPackage(TypedDict, total=False):
    id: str
    model_id: str
    option_code: str
    name: str
    price_cents: int
    production_hours: int
    incompatible_with_option_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    region: str
    standing: str
    annual_allocation_quota: int
    allocation_used: int
    floor_plan_limit_cents: int
    floor_plan_utilized_cents: int
    current_rate_tier: str
    created_at: str
    updated_at: str
    version: int


class BoatShowEvent(TypedDict, total=False):
    id: str
    event_name: str
    region: str
    start_date: str
    end_date: str
    surge_deposit_rate: float
    allocation_boost: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    plant_line_code: str
    season: str
    build_week_start: str
    build_week_end: str
    option_change_cutoff_at: str
    status: str
    total_carrying_actual_cents: int
    total_carrying_seasonal_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildSlot(TypedDict, total=False):
    id: str
    run_id: str
    slot_code: str
    capacity_hours: int
    reserved_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DealerOrder(TypedDict, total=False):
    id: str
    dealer_id: str
    model_id: str
    slot_id: Optional[str]
    show_event_id: Optional[str]
    source: str
    status: str
    base_price_cents: int
    options_total_cents: int
    surcharge_cents: int
    invoice_total_cents: int
    required_deposit_cents: int
    deposit_paid_cents: int
    production_hours: int
    cancel_fee_cents: Optional[int]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderOptionLine(TypedDict, total=False):
    """Immutable line entity (PRD §2.4): carries only id + created_at."""

    id: str
    created_at: str
    order_id: str
    option_package_id: str
    unit_price_cents: int
    discount_pct_applied: float
    line_total_cents: int


class Hull(TypedDict, total=False):
    id: str
    hin: str
    serial_no: int
    order_id: str
    slot_id: str
    model_id: str
    certification_status: str
    delivery_status: str
    completed_at: str
    delivered_at: Optional[str]
    created_by_user_id: str
    carrying_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class FloorPlanAdvance(TypedDict, total=False):
    id: str
    dealer_id: str
    hull_id: str
    principal_cents: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    rate_tier: str
    annual_rate: float
    opened_at: str
    last_accrual_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    id: str
    hull_id: str
    dealer_id: str
    retail_sale_date: str
    registered_at: str
    coverage_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    registration_id: str
    recall_notice_id: Optional[str]
    defect_description: str
    labor_hours: float
    parts_cents: int
    variant_applied: str
    labor_charge_cents: Optional[int]
    parts_credit_cents: Optional[int]
    reimbursement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict, total=False):
    id: str
    campaign_code: str
    severity: str
    model_code: str
    model_year: int
    hin_serial_start: int
    hin_serial_end: int
    status: str
    issued_at: Optional[str]
    notice_count: int
    open_notice_count: int
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict, total=False):
    id: str
    campaign_id: str
    hull_id: str
    status: str
    notified_at: str
    remedied_at: Optional[str]
    remedy_path: Optional[str]
    created_at: str
    updated_at: str
    version: int
