"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    BILLING_CLERK = "BillingClerk"
    TREASURER = "Treasurer"
    BOARD_DIRECTOR = "BoardDirector"
    FIELD_OPERATOR = "FieldOperator"


class CovenantStatus(str, Enum):
    IN_COMPLIANCE = "IN_COMPLIANCE"
    RESERVE_DEFICIENT = "RESERVE_DEFICIENT"
    RATE_COVENANT_BREACH = "RATE_COVENANT_BREACH"


class ServiceAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ANNEXED_IN = "ANNEXED_IN"
    RETIRED = "RETIRED"


class MemberClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    AGRICULTURAL = "AGRICULTURAL"


class MembershipStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MeterSize(str, Enum):
    FIVE_EIGHTS_INCH = "FIVE_EIGHTS_INCH"
    THREE_QUARTER_INCH = "THREE_QUARTER_INCH"
    ONE_INCH = "ONE_INCH"
    TWO_INCH = "TWO_INCH"


class TapStatus(str, Enum):
    FEE_PENDING = "FEE_PENDING"
    PAID = "PAID"
    INSTALLED = "INSTALLED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTED = "RECONNECTED"
    ABANDONED = "ABANDONED"


class ReadingType(str, Enum):
    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"
    FINAL_OFF = "FINAL_OFF"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    READINGS_COMPLETE = "READINGS_COMPLETE"
    BILLED = "BILLED"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class CollectionStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    NOTICED = "NOTICED"
    DISCONNECT_ELIGIBLE = "DISCONNECT_ELIGIBLE"
    DISCONNECTED = "DISCONNECTED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ReserveEntryType(str, Enum):
    MONTHLY_DEPOSIT = "MONTHLY_DEPOSIT"
    WITHDRAWAL_AUTH = "WITHDRAWAL_AUTH"
    ANNUAL_TRUE_UP = "ANNUAL_TRUE_UP"


class BoilOrderStatus(str, Enum):
    IN_EFFECT = "IN_EFFECT"
    SAMPLING = "SAMPLING"
    LIFTED = "LIFTED"
    VIOLATION_ESCALATED = "VIOLATION_ESCALATED"


class NotificationChannel(str, Enum):
    DOOR_HANGER = "DOOR_HANGER"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PHONE_TREE = "PHONE_TREE"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    ABSENT = "ABSENT"
    PRESENT = "PRESENT"


class ResolutionType(str, Enum):
    RATE_ADOPTION = "RATE_ADOPTION"
    RESERVE_WITHDRAWAL = "RESERVE_WITHDRAWAL"
    ANNEXATION_RATIFICATION = "ANNEXATION_RATIFICATION"
    LOAN_AMENDMENT = "LOAN_AMENDMENT"


class ResolutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    FAILED = "FAILED"


class PetitionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FEASIBILITY_REVIEW = "FEASIBILITY_REVIEW"
    APPROVED_PENDING_VOTE = "APPROVED_PENDING_VOTE"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts ---
# Common resources carry id, created_at, updated_at, version.
# Ledger-style records (MeterReading, MasterMeterReading, ReserveEntry,
# NotificationReceipt) carry only id and created_at per PRD section 2.4.


class District(TypedDict, total=False):
    id: str
    district_name: str
    usda_loan_principal_cents: int
    annual_debt_service_cents: int
    reserve_target_cents: int
    reserve_balance_cents: int
    reserve_deficit_cents: int
    covenant_status: str
    active_rate_schedule_id: Optional[str]
    current_billing_epoch: int
    boil_order_active: bool
    created_at: str
    updated_at: str
    version: int


class ServiceArea(TypedDict):
    id: str
    district_id: str
    area_name: str
    boundary_acres: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    district_id: str
    legal_name: str
    service_area_id: str
    member_class: str
    membership_status: str
    credit_balance_cents: int
    consecutive_delinquent_cycles: int
    created_at: str
    updated_at: str
    version: int


class TapConnection(TypedDict):
    id: str
    district_id: str
    member_id: str
    tap_fee_cents: int
    tap_fee_paid_cents: int
    meter_size: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict):
    # Ledger-style record: id + created_at only (no updated_at, no version)
    id: str
    district_id: str
    tap_id: str
    cycle_id: str
    reading_gallons: int
    reading_type: str
    usage_gallons: int
    created_at: str


class MasterMeterReading(TypedDict):
    # Ledger-style record: id + created_at only
    id: str
    district_id: str
    cycle_id: str
    master_gallons: int
    created_at: str


class RateSchedule(TypedDict):
    id: str
    district_id: str
    schedule_label: str
    base_minimum_cents: int
    included_gallons: int
    tier2_rate_cents_per_kgal: int
    tier2_cap_gallons: int
    tier3_rate_cents_per_kgal: int
    tap_fee_schedule: dict
    reconnect_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict, total=False):
    id: str
    district_id: str
    cycle_index: int
    period_start_utc: str
    period_end_utc: str
    due_date_utc: str
    status: str
    provisional_loss_pct: float
    final_loss_pct: float
    billed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    district_id: str
    member_id: str
    tap_id: str
    cycle_id: str
    rate_schedule_id: str
    usage_gallons: int
    usage_charge_cents: int
    minimum_charge_cents: int
    reconnect_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    billing_status: str
    collection_status: str
    days_past_due: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    district_id: str
    member_id: str
    invoice_id: str
    amount_cents: int
    applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReserveEntry(TypedDict):
    # Ledger-style record: id + created_at only
    id: str
    district_id: str
    entry_type: str
    amount_cents: int
    cycle_id: Optional[str]
    resulting_balance_cents: int
    created_at: str


class BoilOrder(TypedDict):
    id: str
    district_id: str
    issued_utc: str
    reason: str
    notification_deadline_utc: str
    notified_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NotificationReceipt(TypedDict):
    # Ledger-style record: id + created_at only
    id: str
    district_id: str
    boil_order_id: str
    member_id: str
    channel: str
    notified_utc: str
    created_at: str


class ComplianceSample(TypedDict):
    id: str
    district_id: str
    boil_order_id: str
    sample_point: str
    collected_utc: str
    result: str
    created_at: str
    updated_at: str
    version: int


class BoardResolution(TypedDict):
    id: str
    district_id: str
    resolution_type: str
    subject_id: str
    payload: dict
    votes_for: int
    votes_against: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnexationPetition(TypedDict, total=False):
    id: str
    district_id: str
    petitioner_name: str
    parcel_acres: int
    parent_service_area_id: str
    deposit_cents: int
    feasibility_fee_cents: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
