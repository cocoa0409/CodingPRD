"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes follow PRD §2.4 (common resource properties) and §3
(entity narratives). The PerDiemRate and Receipt entities are
append-only — per PRD §2.4 they carry only `id` and `created_at`,
without `updated_at` or `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TRAVELER = "TRAVELER"
    MANAGER = "MANAGER"
    FINANCE_REVIEWER = "FINANCE_REVIEWER"
    OOP_APPROVER = "OOP_APPROVER"
    ADMIN = "ADMIN"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VirtualCardStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class ExpenseReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    REIMBURSED = "REIMBURSED"


class ExpenseCategory(str, Enum):
    FLIGHT = "FLIGHT"
    LODGING = "LODGING"
    RENTAL_CAR = "RENTAL_CAR"
    MEAL = "MEAL"
    MILEAGE = "MILEAGE"
    OTHER = "OTHER"


class PolicyStatus(str, Enum):
    PENDING_EVAL = "PENDING_EVAL"
    IN_POLICY = "IN_POLICY"
    OUT_OF_POLICY = "OUT_OF_POLICY"
    OOP_APPROVED = "OOP_APPROVED"
    OOP_DENIED = "OOP_DENIED"


class OcrStatus(str, Enum):
    NO_RECEIPT = "NO_RECEIPT"
    PENDING_OCR = "PENDING_OCR"
    OCR_VERIFIED = "OCR_VERIFIED"
    OCR_MISMATCH = "OCR_MISMATCH"
    OCR_WAIVED = "OCR_WAIVED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REIMBURSED = "REIMBURSED"
    VOIDED = "VOIDED"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    INCIDENTAL = "INCIDENTAL"


class PerDiemMethod(str, Enum):
    ACTUAL = "ACTUAL"
    PER_DIEM = "PER_DIEM"


class OOPChainLevel(str, Enum):
    AWAITING_L1 = "AWAITING_L1"
    AWAITING_L2 = "AWAITING_L2"
    AWAITING_FINAL = "AWAITING_FINAL"
    FINAL_APPROVED = "FINAL_APPROVED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields branching per PRD §2.4
# Entities WITH common_fields (id, created_at, updated_at, version):
#   Employee, Trip, VirtualCard, ExpenseReport, ExpenseLine,
#   OutOfPolicyApproval.
# Entities WITHOUT common_fields (only id and created_at):
#   PerDiemRate, Receipt.
# ---------------------------------------------------------------------------
class Employee(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    role: str
    manager_id: Optional[str]
    cost_center: str
    home_address_state: str
    created_at: str
    updated_at: str
    version: int


class PerDiemRate(TypedDict, total=False):
    id: str
    city: str
    state: str
    effective_from: str
    effective_to: str
    lodging_cap_cents: int
    mie_cap_cents: int
    is_high_cost_locality: bool
    created_at: str


class Trip(TypedDict, total=False):
    id: str
    traveler_id: str
    purpose: str
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    start_date: str
    end_date: str
    status: str
    estimated_budget_cents: int
    pinned_per_diem_rate_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VirtualCard(TypedDict, total=False):
    id: str
    trip_id: str
    card_last4: Optional[str]
    credit_limit_cents: int
    status: str
    authorized_amount_cents: int
    locked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseReport(TypedDict, total=False):
    id: str
    trip_id: str
    status: str
    total_claimed_cents: int
    total_reimbursable_cents: int
    policy_violation_count: int
    reviewer_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    reimbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseLine(TypedDict, total=False):
    id: str
    report_id: str
    category: str
    expense_date: str
    amount_claimed_cents: int
    amount_reimbursable_cents: int
    policy_status: str
    ocr_status: str
    line_status: str
    receipt_id: Optional[str]
    miles_driven: Optional[float]
    rental_days: Optional[int]
    meal_type: Optional[str]
    meal_was_provided: Optional[bool]
    per_diem_method: Optional[str]
    cdw_purchased: Optional[bool]
    virtual_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict, total=False):
    id: str
    uploader_employee_id: str
    merchant_name: str
    merchant_total_cents: int
    ocr_extracted_date: str
    ocr_confidence: float
    used_by_line_id: Optional[str]
    created_at: str


class OutOfPolicyApproval(TypedDict, total=False):
    id: str
    expense_line_id: str
    requester_employee_id: str
    justification: str
    chain_level: str
    l1_approver_id: Optional[str]
    l2_approver_id: Optional[str]
    final_approver_id: Optional[str]
    requires_final_escalation: bool
    created_at: str
    updated_at: str
    version: int


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "TripStatus",
    "VirtualCardStatus",
    "ExpenseReportStatus",
    "ExpenseCategory",
    "PolicyStatus",
    "OcrStatus",
    "LineStatus",
    "MealType",
    "PerDiemMethod",
    "OOPChainLevel",
    # Entities
    "Employee",
    "PerDiemRate",
    "Trip",
    "VirtualCard",
    "ExpenseReport",
    "ExpenseLine",
    "Receipt",
    "OutOfPolicyApproval",
]
