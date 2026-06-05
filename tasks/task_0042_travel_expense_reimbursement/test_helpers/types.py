"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the Travel & Expense Reimbursement PRD (Section 3).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    TRAVELER = "Traveler"
    APPROVER = "Approver"
    FINANCE_ADMIN = "FinanceAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class TravelPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TripRequestStatus(str, Enum):
    PENDING = "PENDING"
    PENDING_OOP_APPROVAL = "PENDING_OOP_APPROVAL"
    AUTO_APPROVED = "AUTO_APPROVED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class VirtualCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ExpenseReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExpenseLineStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOID = "VOID"


class LineType(str, Enum):
    FLIGHT = "FLIGHT"
    LODGING = "LODGING"
    MEAL = "MEAL"
    RENTAL_CDW = "RENTAL_CDW"
    MILEAGE = "MILEAGE"


class CabinClass(str, Enum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"


class ReceiptStatus(str, Enum):
    UPLOADED = "UPLOADED"
    OCR_PROCESSED = "OCR_PROCESSED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class ApprovalStepDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (PerDiemRate)
# --------------------------------------------------------------------------
class Traveler(TypedDict):
    id: str
    email: str
    full_name: str
    home_office_state: str
    manager_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Approver(TypedDict):
    id: str
    email: str
    full_name: str
    approval_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelPolicy(TypedDict):
    id: str
    name: str
    max_economy_fare_cents: int
    business_class_min_hours: int
    advance_purchase_days: int
    cdw_daily_cap_cents: int
    mileage_rate_milli_cents: int
    receipt_required_threshold_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable GSA reference data: id + created_at only
class PerDiemRate(TypedDict):
    id: str
    state_code: str
    lodging_cap_cents: int
    mie_cents: int
    created_at: str


class TripRequest(TypedDict):
    id: str
    traveler_id: str
    policy_id: str
    destination_state: str
    start_date: str
    end_date: str
    budget_total_cents: int
    committed_amount_cents: int
    remaining_budget_cents: int
    requires_oop: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VirtualCard(TypedDict):
    id: str
    trip_request_id: str
    load_limit_cents: int
    authorized_holds_cents: int
    captured_total_cents: int
    available_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseReport(TypedDict):
    id: str
    trip_request_id: str
    title: str
    per_diem_method: str
    meal_reimbursable_cents: int
    total_reimbursable_cents: int
    return_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseLine(TypedDict, total=False):
    id: str
    report_id: str
    virtual_card_id: Optional[str]
    line_type: str
    claimed_amount_cents: int
    cabin_class: Optional[str]
    scheduled_hours: Optional[int]
    advance_days: Optional[int]
    check_in_date: Optional[str]
    check_out_date: Optional[str]
    rental_days: Optional[int]
    miles: Optional[int]
    reimbursable_amount_cents: int
    in_policy: bool
    settlement_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    expense_line_id: str
    image_ref: str
    ocr_amount_cents: Optional[int]
    ocr_merchant: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalStep(TypedDict):
    id: str
    report_id: str
    approver_id: str
    step_order: int
    decision: str
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int
