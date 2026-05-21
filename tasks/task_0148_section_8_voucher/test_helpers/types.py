"""Domain types: entity TypedDicts, status enums, role enum.

Status enum values are taken verbatim from PRD §2.11; field names
are the PRD-exact names from the §3 prose and §4 endpoint table.

Append-only entities (PaymentStandard, HAPPayment, RentReasonablenessRecord)
carry only `id` and `created_at` per PRD §2.4 — their TypedDicts MUST
NOT list `updated_at` or `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    LANDLORD = "Landlord"
    INSPECTOR = "Inspector"
    CASE_WORKER = "CaseWorker"
    PORTABILITY_COORDINATOR = "PortabilityCoordinator"
    PHA_ADMIN = "PHAAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §2.11
# ---------------------------------------------------------------------------
class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    SEARCHING = "SEARCHING"
    LEASED = "LEASED"
    SEARCHING_REISSUED = "SEARCHING_REISSUED"
    PORTED_OUT = "PORTED_OUT"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    REVOKED = "REVOKED"


class TenancyStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    PENDING_RENT_REASONABLE = "PENDING_RENT_REASONABLE"
    ACTIVE = "ACTIVE"
    ABATED = "ABATED"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class TenancyTerminationReason(str, Enum):
    HQS_UNCURED = "HQS_UNCURED"
    ANNUAL_REVIEW_DENIED = "ANNUAL_REVIEW_DENIED"
    TENANT_MOVE_OUT = "TENANT_MOVE_OUT"
    PORTABILITY_ABSORBED = "PORTABILITY_ABSORBED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL_CURABLE = "COMPLETED_FAIL_CURABLE"
    COMPLETED_FAIL_LIFETHREAT = "COMPLETED_FAIL_LIFETHREAT"
    CURED = "CURED"
    EXPIRED_UNCURED = "EXPIRED_UNCURED"


class InspectionOutcome(str, Enum):
    PASS_ = "PASS"
    FAIL_NONLIFETHREATENING = "FAIL_NONLIFETHREATENING"
    FAIL_LIFETHREATENING = "FAIL_LIFETHREATENING"
    CURED = "CURED"


class InspectionType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    REINSPECTION = "REINSPECTION"


class AnnualReviewStatus(str, Enum):
    DUE = "DUE"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PortabilityOutcome(str, Enum):
    INITIATED = "INITIATED"
    ABSORBED = "ABSORBED"
    BILLED = "BILLED"
    DENIED = "DENIED"


class PortabilityDenialReason(str, Enum):
    RECEIVING_PHA_OVER_LEASING_CAP = "RECEIVING_PHA_OVER_LEASING_CAP"
    INELIGIBLE_HOUSEHOLD = "INELIGIBLE_HOUSEHOLD"
    MOBILITY_ZONE_RESTRICTION = "MOBILITY_ZONE_RESTRICTION"


class UnitOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED_PENDING = "OCCUPIED_PENDING"
    OCCUPIED_ACTIVE = "OCCUPIED_ACTIVE"
    OCCUPIED_ABATED = "OCCUPIED_ABATED"


class IncomeBand(str, Enum):
    EXTREMELY_LOW = "EXTREMELY_LOW"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    OVER_INCOME = "OVER_INCOME"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class HAPPaymentStatus(str, Enum):
    PAID = "PAID"
    ABATED_SUSPENDED = "ABATED_SUSPENDED"
    VOIDED_RETROACTIVE = "VOIDED_RETROACTIVE"


class HAPPaymentEventRefType(str, Enum):
    SCHEDULED_MONTHLY = "SCHEDULED_MONTHLY"
    ABATEMENT = "ABATEMENT"
    AR_RECALC = "AR_RECALC"
    PORTABILITY_CLOSEOUT = "PORTABILITY_CLOSEOUT"


class Zone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"


# ---------------------------------------------------------------------------
# Entity TypedDicts — `common_fields: true` entities carry id +
# created_at + updated_at + version (PRD §2.4).
# ---------------------------------------------------------------------------
class Applicant(TypedDict, total=False):
    id: str
    household_name: str
    household_size: int
    dependents_count: int
    elderly_or_disabled_head: bool
    gross_annual_income_cents: int
    childcare_expense_annual_cents: int
    medical_expense_annual_cents: int
    adjusted_annual_income_cents: int
    income_band: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    applicant_id: str
    bedroom_size: int
    issued_at: str
    search_deadline: str
    zone: str
    special_mobility_flag: bool
    administering_pha_id: str
    status: str
    remaining_search_days: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    landlord_id: str
    street_address: str
    zone: str
    bedroom_count: int
    asking_rent_cents: int
    tenant_paid_utilities_cents: int
    last_inspection_passed_at: Optional[str]
    next_annual_inspection_due: Optional[str]
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict, total=False):
    id: str
    voucher_id: str
    unit_id: str
    requested_at: str
    lease_start: str
    gross_rent_cents: int
    applicable_payment_standard_cents: int
    rent_reasonable: Optional[bool]
    initial_total_tenant_payment_cents: int
    initial_hap_cents: int
    current_total_tenant_payment_cents: int
    current_hap_cents: int
    rent_burden_at_lease_up_pct: float
    status: str
    abatement_started_at: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    tenancy_id: str
    unit_id: str
    inspection_type: str
    scheduled_for: str
    completed_at: Optional[str]
    outcome: Optional[str]
    defects: List[str]
    cure_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReview(TypedDict, total=False):
    id: str
    tenancy_id: str
    review_due_date: str
    submitted_at: Optional[str]
    declared_gross_annual_income_cents: Optional[int]
    declared_household_size: Optional[int]
    new_adjusted_income_cents: Optional[int]
    new_total_tenant_payment_cents: Optional[int]
    new_hap_cents: Optional[int]
    deficiency_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PortabilityRequest(TypedDict, total=False):
    id: str
    voucher_id: str
    receiving_pha_id: str
    requested_at: str
    outcome: str
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at ONLY (PRD §2.4).
class PaymentStandard(TypedDict, total=False):
    id: str
    zone: str
    bedroom_size: int
    standard_amount_cents: int
    mobility_amount_cents: int
    effective_from: str
    created_at: str


class RentReasonablenessRecord(TypedDict, total=False):
    id: str
    tenancy_id: str
    comparable_rents_cents: List[int]
    median_comparable_cents: int
    reasonable_threshold_cents: int
    is_reasonable: bool
    recorded_at: str
    created_at: str


class HAPPayment(TypedDict, total=False):
    id: str
    tenancy_id: str
    pay_period_month: str
    amount_cents: int
    status: str
    event_ref_type: str
    event_ref_id: str
    created_at: str


__all__ = [
    "UserRole",
    "VoucherStatus",
    "TenancyStatus",
    "TenancyTerminationReason",
    "InspectionStatus",
    "InspectionOutcome",
    "InspectionType",
    "AnnualReviewStatus",
    "PortabilityOutcome",
    "PortabilityDenialReason",
    "UnitOccupancyStatus",
    "IncomeBand",
    "EligibilityStatus",
    "HAPPaymentStatus",
    "HAPPaymentEventRefType",
    "Zone",
    "Applicant",
    "Voucher",
    "Unit",
    "Tenancy",
    "Inspection",
    "AnnualReview",
    "PortabilityRequest",
    "PaymentStandard",
    "RentReasonablenessRecord",
    "HAPPayment",
]
