"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource in this system carries
the four standard system-managed fields (id, created_at, updated_at, version)
from the PRD common-resource-properties section.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class SizeCode(str, Enum):
    NEWBORN = "NEWBORN"
    SIZE_1 = "SIZE_1"
    SIZE_2 = "SIZE_2"
    SIZE_3 = "SIZE_3"
    SIZE_4 = "SIZE_4"
    SIZE_5 = "SIZE_5"
    SIZE_6 = "SIZE_6"
    TRAINING_PANTS = "TRAINING_PANTS"


class UserRole(str, Enum):
    BANK_ADMIN = "BankAdmin"
    WAREHOUSE_MANAGER = "WarehouseManager"
    FINANCE_MANAGER = "FinanceManager"
    AGENCY_COORDINATOR = "AgencyCoordinator"
    PRIVACY_OFFICER = "PrivacyOfficer"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    VOLUNTEER = "Volunteer"


class PartnerAgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXHAUSTED = "EXHAUSTED"


class GrantRestriction(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    PRODUCT_PURCHASE_ONLY = "PRODUCT_PURCHASE_ONLY"
    OPERATIONS_ONLY = "OPERATIONS_ONLY"


class IntakeSourceType(str, Enum):
    DONATION = "DONATION"
    PURCHASE = "PURCHASE"


class IntakeBatchStatus(str, Enum):
    COUNTED = "COUNTED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class AllocationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FINALIZED = "FINALIZED"


class FormulaVariant(str, Enum):
    NEED_WEIGHTED = "NEED_WEIGHTED"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class AllocationLineStatus(str, Enum):
    PROJECTED = "PROJECTED"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class DistributionEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IssuanceStatus(str, Enum):
    RECORDED = "RECORDED"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class EligibilityStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class VolunteerShiftStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class ForecastVariant(str, Enum):
    TRAILING_ACTUAL = "TRAILING_ACTUAL"
    BOOKED_PIPELINE = "BOOKED_PIPELINE"


class PartnerAgency(TypedDict, total=False):
    id: str
    name: str
    agency_code: str
    contact_email: str
    children_served_monthly: int
    storage_capacity_units: int
    status: str
    active_allocated_units: int
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    funder_name: str
    grant_code: str
    total_amount_cents: int
    restriction: str
    start_date: str
    end_date: str
    committed_cents: int
    spent_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventorySizeEntry(TypedDict, total=False):
    on_hand_units: int
    reserved_units: int
    reorder_threshold_units: int
    available_units: int
    restock_needed: bool


class Inventory(TypedDict, total=False):
    id: str
    sizes: Dict[str, InventorySizeEntry]
    initialized: bool
    total_on_hand_units: int
    created_at: str
    updated_at: str
    version: int


class IntakeLine(TypedDict):
    size_code: str
    quantity: int


class IntakeBatch(TypedDict, total=False):
    id: str
    source_type: str
    donor_name: Optional[str]
    purchase_order_id: Optional[str]
    lines: List[IntakeLine]
    total_units: int
    valued_total_cents: int
    status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrderLine(TypedDict):
    size_code: str
    quantity: int
    unit_cost_cents: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    grant_id: str
    vendor_name: str
    lines: List[PurchaseOrderLine]
    discount_pct: float
    total_cost_cents: int
    status: str
    created_by_user_id: str
    submitted_by_user_id: Optional[str]
    received_intake_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    period: str
    formula_variant: str
    status: str
    computed_at: Optional[str]
    total_allocated_units: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict, total=False):
    id: str
    allocation_run_id: str
    agency_id: str
    size_code: str
    allocated_units: int
    fulfilled_units: int
    released_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict, total=False):
    id: str
    host_agency_id: str
    site_name: str
    starts_at: str
    ends_at: str
    status: str
    completed_at: Optional[str]
    issued_total_units: int
    created_at: str
    updated_at: str
    version: int


class Issuance(TypedDict, total=False):
    id: str
    event_id: str
    household_id: str
    lines: List[IntakeLine]
    total_units: int
    status: str
    fulfilled_at: Optional[str]
    recorded_by_role: str
    created_at: str
    updated_at: str
    version: int


class ClientHousehold(TypedDict, total=False):
    id: str
    household_code: str
    children_sizes: List[str]
    consent_on_file: bool
    privacy_restricted: bool
    eligibility_status: str
    eligibility_reason: Optional[str]
    monthly_allotment_units: int
    consumed_this_month_units: int
    created_at: str
    updated_at: str
    version: int


class ShiftSignup(TypedDict, total=False):
    volunteer_email: str
    volunteer_name: str
    signed_up_at: str


class VolunteerShift(TypedDict, total=False):
    id: str
    title: str
    starts_at: str
    ends_at: str
    capacity: int
    signups: List[ShiftSignup]
    signup_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
