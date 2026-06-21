"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3.x (entities), §3.x (state machines), and §2.1 (roles).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────


class ContractPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RENEWED = "RENEWED"


class ClaimTicketStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ASSESSED = "ASSESSED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class DispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RETURN_NEEDED = "RETURN_NEEDED"


class CoveredItemCategory(str, Enum):
    HVAC = "HVAC"
    WATER_HEATER = "WATER_HEATER"
    REFRIGERATOR = "REFRIGERATOR"
    DISHWASHER = "DISHWASHER"
    WASHER = "WASHER"
    DRYER = "DRYER"
    OVEN = "OVEN"


class RejectionReason(str, Enum):
    PRE_EXISTING_EXCLUDED = "PRE_EXISTING_EXCLUDED"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"
    NOT_COVERED_CATEGORY = "NOT_COVERED_CATEGORY"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────
# Entities with common_fields (id + created_at + updated_at + version):
#   ContractPackage, Customer, Contract, CoveredItem, ClaimTicket, Dispatch.
# Append-only / immutable (id + created_at only):
#   RenewalReminder.


class ContractPackage(TypedDict, total=False):
    id: str
    code: str
    name: str
    annual_premium_cents: int
    service_fee_cents: int
    copay_cap_cents: int
    copay_share_pct: float
    return_visit_window_days: int
    max_covered_items: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_address: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    customer_id: str
    package_id: str
    status: str
    coverage_start_utc: Optional[str]
    coverage_end_utc: Optional[str]
    renewal_reminder_sent_at: Optional[str]
    claims_in_period_count: int
    total_paid_out_cents: int
    annual_premium_due_cents: int
    created_at: str
    updated_at: str
    version: int


class CoveredItem(TypedDict, total=False):
    id: str
    contract_id: str
    category: str
    brand: str
    model: str
    install_year: int
    pre_existing_flag: bool
    last_dispatch_completed_utc: Optional[str]
    last_dispatch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimTicket(TypedDict, total=False):
    id: str
    contract_id: str
    covered_item_id: str
    issue_summary: str
    status: str
    is_return_visit: bool
    prior_dispatch_id: Optional[str]
    rejection_reason: Optional[str]
    repair_cost_cents: int
    provisional_copay_cents: int
    final_copay_cents: int
    service_fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict, total=False):
    id: str
    claim_id: str
    technician_id: str
    scheduled_utc: str
    status: str
    completed_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — NO updated_at, NO version.
class RenewalReminder(TypedDict, total=False):
    id: str
    contract_id: str
    sent_utc: str
    days_to_expiry: int
    created_at: str
