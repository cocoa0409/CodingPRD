"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3).

Append-only records (repair milestones, class change records, communication
log entries) carry only ``id`` and ``created_at`` per PRD §2.5 — their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------- enums


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    RENTAL_DESK_AGENT = "RentalDeskAgent"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    SETTLEMENT_APPROVER = "SettlementApprover"
    REPAIR_SHOP = "RepairShop"
    RENTAL_PARTNER = "RentalPartner"
    RECOVERY_SPECIALIST = "RecoverySpecialist"
    SYSTEM_ADMIN = "SystemAdmin"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClaimRentalTrackStatus(str, Enum):
    OPEN = "OPEN"
    COVERAGE_VERIFIED = "COVERAGE_VERIFIED"
    COVERAGE_DENIED = "COVERAGE_DENIED"
    RENTAL_ACTIVE = "RENTAL_ACTIVE"
    RENTAL_CLOSED = "RENTAL_CLOSED"


class ClaimLossOfUseTrackStatus(str, Enum):
    NONE = "NONE"
    LOU_SUBMITTED = "LOU_SUBMITTED"
    LOU_DOCUMENTED = "LOU_DOCUMENTED"
    LOU_APPROVED = "LOU_APPROVED"
    LOU_PAID = "LOU_PAID"
    LOU_DENIED = "LOU_DENIED"


class ClaimOverallStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class CoverageVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class RepairOrderStatus(str, Enum):
    ESTIMATE_SUBMITTED = "ESTIMATE_SUBMITTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class MilestoneType(str, Enum):
    REPAIR_STARTED = "REPAIR_STARTED"
    PARTS_DELAYED = "PARTS_DELAYED"
    DELAY_REPORTED = "DELAY_REPORTED"
    REPAIR_COMPLETED = "REPAIR_COMPLETED"


class VehicleClass(str, Enum):
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ReservationStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    EXTENSION_REVIEW = "EXTENSION_REVIEW"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExtensionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class PayoutMethod(str, Enum):
    STANDARD_PER_DIEM = "STANDARD_PER_DIEM"
    COMPARABLE_VEHICLE = "COMPARABLE_VEHICLE"


class LossOfUseClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DOCUMENTED = "DOCUMENTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AUTO_APPROVED = "AUTO_APPROVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class AuditDecision(str, Enum):
    APPROVE_AS_SUBMITTED = "APPROVE_AS_SUBMITTED"
    ADJUST_TO_AUTHORIZED = "ADJUST_TO_AUTHORIZED"
    DISPUTE_UNNECESSARY_DAYS = "DISPUTE_UNNECESSARY_DAYS"


class RecoveryCaseSource(str, Enum):
    RETURN_OVERSTAY = "RETURN_OVERSTAY"
    INVOICE_DISPUTE = "INVOICE_DISPUTE"


class RecoveryCaseStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL_RECOVERY = "PARTIAL_RECOVERY"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class CommunicationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PHONE = "PHONE"


class CommunicationTemplate(str, Enum):
    COVERAGE_EXPLAINED = "COVERAGE_EXPLAINED"
    EXPECTATION_SET = "EXPECTATION_SET"
    EXTENSION_UPDATE = "EXTENSION_UPDATE"
    RETURN_REMINDER = "RETURN_REMINDER"
    RECOVERY_NOTICE = "RECOVERY_NOTICE"


# ---------------------------------------------------------------- TypedDicts
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class PolicyHolder(TypedDict):
    id: str
    full_name: str
    policy_number: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class RepairShop(TypedDict):
    id: str
    shop_name: str
    shop_code: str
    created_at: str
    updated_at: str
    version: int


class RentalPartner(TypedDict):
    id: str
    partner_name: str
    partner_code: str
    economy_rate_cents: int
    standard_rate_cents: int
    premium_rate_cents: int
    economy_capacity: int
    standard_capacity: int
    premium_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policyholder_id: str
    incident_date: str
    coverage_daily_limit_cents: int
    coverage_duration_cap_days: int
    loss_of_use_per_diem_cents: int
    rental_reserve_cents: int
    authorized_days_total: int
    recovery_balance_cents: int
    rental_track_status: str
    loss_of_use_track_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class CoverageVerification(TypedDict):
    id: str
    claim_id: str
    status: str
    rental_eligible: Optional[bool]
    loss_of_use_eligible: Optional[bool]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    claim_id: str
    shop_id: str
    estimated_completion_date: str
    actual_completion_date: Optional[str]
    labor_hours_estimate: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairMilestone(TypedDict):
    # Append-only record: id + created_at only, no updated_at / version (PRD §2.5).
    id: str
    repair_order_id: str
    milestone_type: str
    reported_at: str
    new_estimated_completion_date: Optional[str]
    note: Optional[str]
    created_at: str


class RentalReservation(TypedDict):
    id: str
    claim_id: str
    rental_partner_id: str
    repair_order_id: str
    vehicle_class: str
    pickup_date: str
    authorized_return_date: str
    actual_pickup_date: Optional[str]
    actual_return_date: Optional[str]
    rate_card_snapshot: dict
    daily_rate_cents: int
    authorized_days: int
    consumed_days: Optional[int]
    unnecessary_days: int
    estimated_charge_cents: int
    audited_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict):
    id: str
    reservation_id: str
    milestone_id: str
    requested_additional_days: int
    granted_days: Optional[int]
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassChangeRecord(TypedDict):
    # Append-only record: id + created_at only, no updated_at / version (PRD §2.5).
    id: str
    reservation_id: str
    from_class: str
    to_class: str
    effective_date: str
    upgrade_waiver: bool
    per_day_customer_cents: int
    customer_responsibility_cents: int
    insurer_delta_cents: int
    created_at: str


class LossOfUseClaim(TypedDict):
    id: str
    claim_id: str
    vehicle_description: str
    period_start: str
    period_end: str
    claimed_amount_cents: int
    payout_method: str
    documentation_provided: bool
    payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    reservation_id: str
    rental_partner_id: str
    invoice_number: str
    period_start: str
    period_end: str
    daily_rate_cents: int
    tax_cents: int
    fees_cents: int
    total_cents: int
    audited_payable_cents: Optional[int]
    unauthorized_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryCase(TypedDict):
    id: str
    claim_id: str
    reservation_id: str
    source: str
    unnecessary_days: int
    assessed_amount_cents: int
    recovered_amount_cents: int
    waived_amount_cents: int
    outstanding_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunicationLog(TypedDict):
    # Append-only record: id + created_at only, no updated_at / version (PRD §2.5).
    id: str
    claim_id: str
    channel: str
    template: str
    body_summary: str
    sent_at: str
    created_at: str
