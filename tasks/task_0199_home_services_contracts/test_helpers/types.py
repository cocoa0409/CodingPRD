"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the PRD's vocabulary for the Home Services Contracts API.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    CUSTOMER = "Customer"


# --- Status enums ---
class MembershipStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class EquipmentOperationalStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    NEEDS_SERVICE = "NEEDS_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentWarrantyStatus(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class RenewalOfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    AUTO_ACCEPTED = "AUTO_ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class Trade(str, Enum):
    HVAC = "HVAC"
    PEST = "PEST"


class RefrigerantType(str, Enum):
    R410A = "R410A"
    R32 = "R32"
    R454B = "R454B"
    NONE = "NONE"


class VisitKind(str, Enum):
    SEASONAL = "SEASONAL"
    PRIORITY = "PRIORITY"
    WARRANTY = "WARRANTY"


class RefrigerantAction(str, Enum):
    ADD = "ADD"
    RECOVER = "RECOVER"


# --- First-class entities (id + created_at + updated_at + version) ---
class ServicePlan(TypedDict):
    id: str
    tier: str
    trade: str
    annual_fee_cents: int
    included_visits_per_year: int
    extra_visit_fee_cents: int
    sla_response_hours: int
    parts_discount_pct: float
    auto_renew_default: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    billing_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    customer_id: str
    address: str
    region_code: str
    access_notes: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    customer_id: str
    site_id: str
    plan_id: str
    status: str
    auto_renew: bool
    term_start: Optional[str]
    term_end: Optional[str]
    visits_consumed: int
    term_index: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    site_id: str
    model: str
    refrigerant_type: str
    nameplate_charge_grams: int
    current_charge_grams: int
    operational_status: str
    warranty_status: str
    warranty_expires_at: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    region_code: str
    trade: str
    epa_certified: bool
    daily_visit_capacity: int
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    membership_id: str
    site_id: str
    technician_id: Optional[str]
    visit_kind: str
    status: str
    requested_at: str
    window_start: str
    window_end: str
    sla_met: Optional[bool]
    billable_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    equipment_id: str
    origin_visit_id: str
    status: str
    claimed_amount_cents: int
    approved_amount_cents: int
    denial_reason: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict):
    id: str
    membership_id: str
    offered_plan_id: str
    status: str
    offered_annual_fee_cents: int
    expires_at: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entries (id + created_at only; no updated_at/version) ---
class RefrigerantLog(TypedDict):
    id: str
    visit_id: str
    equipment_id: str
    action: str
    grams: int
    posted_by_tech_id: str
    created_at: str


class PartUsage(TypedDict):
    id: str
    visit_id: str
    part_name: str
    quantity: int
    list_price_cents: int
    charged_cents: int
    created_at: str
