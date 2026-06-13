"""Domain types: entity TypedDicts, status enums, role enum.

All field names are taken verbatim from the PRD. Every entity in this domain is
mutable and therefore carries id + created_at + updated_at + version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    RESORT_MANAGER = "ResortManager"
    OWNER = "Owner"
    RESALE_AGENT = "ResaleAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SYSTEM = "System"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class OwnerStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class InventoryUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPOSITED_TO_EXCHANGE = "DEPOSITED_TO_EXCHANGE"


class Season(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"


class OwnershipType(str, Enum):
    DEEDED = "DEEDED"
    RIGHT_TO_USE = "RIGHT_TO_USE"


class InventoryModel(str, Enum):
    POINTS = "POINTS"
    FIXED_WEEK = "FIXED_WEEK"


class ContractStatus(str, Enum):
    PENDING_RESCISSION = "PENDING_RESCISSION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESCINDED = "RESCINDED"
    TERMINATED = "TERMINATED"
    FORECLOSED = "FORECLOSED"
    TRANSFERRED = "TRANSFERRED"


class PointsAccountStatus(str, Enum):
    OPEN = "OPEN"
    ROLLED_OVER = "ROLLED_OVER"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    DEPOSITED_TO_EXCHANGE = "DEPOSITED_TO_EXCHANGE"
    EXPIRED = "EXPIRED"


class InvoiceSourceType(str, Enum):
    ANNUAL = "ANNUAL"
    SPECIAL_ASSESSMENT = "SPECIAL_ASSESSMENT"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class SpecialAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    LEVIED = "LEVIED"


class ExchangeNetwork(str, Enum):
    RCI = "RCI"
    II = "II"


class ExchangeDepositStatus(str, Enum):
    DEPOSITED = "DEPOSITED"
    REDEEMED = "REDEEMED"
    RECALLED = "RECALLED"


class ResaleTransferStatus(str, Enum):
    PENDING_RESCISSION = "PENDING_RESCISSION"
    COMPLETED = "COMPLETED"
    RESCINDED = "RESCINDED"


class LateChargeBasis(str, Enum):
    SIMPLE = "SIMPLE"
    COMPOUNDING = "COMPOUNDING"


class DelinquencyCaseStatus(str, Enum):
    NOTICE = "NOTICE"
    LIEN = "LIEN"
    FORECLOSURE = "FORECLOSURE"
    TERMINATION = "TERMINATION"
    CURED = "CURED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Resort(TypedDict):
    id: str
    name: str
    points_per_week_base: int
    annual_fee_cents_per_1000_points: int
    rescission_days: int
    borrow_surcharge_pct: float
    current_use_year: int
    current_utc: str
    delinquency_grace_days: int
    foreclosure_threshold_periods: int
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    resort_id: str
    full_name: str
    email: str
    status: str
    open_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict):
    id: str
    resort_id: str
    unit_label: str
    week_number: int
    season: str
    points_value: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    resort_id: str
    owner_id: str
    ownership_type: str
    inventory_model: str
    annual_points_allotment: int
    fixed_unit_id: Optional[str]
    rtu_expiry_use_year: Optional[int]
    signed_at: str
    superseded_by_contract_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PointsAccount(TypedDict):
    id: str
    contract_id: str
    use_year: int
    allotment_points: int
    banked_in_points: int
    banked_out_points: int
    borrowed_out_points: int
    committed_points: int
    available_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    contract_id: str
    inventory_unit_id: str
    use_year: int
    points_cost: int
    borrowed_points: int
    source_use_year_account_id: str
    borrow_source_account_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceFeeInvoice(TypedDict):
    id: str
    contract_id: str
    owner_id: str
    source_type: str
    special_assessment_id: Optional[str]
    use_year: int
    amount_cents: int
    late_charge_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    contract_id: str
    amount_cents: int
    invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialAssessment(TypedDict):
    id: str
    resort_id: str
    reason: str
    total_amount_cents: int
    use_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeDeposit(TypedDict):
    id: str
    reservation_id: str
    contract_id: str
    exchange_network: str
    exchange_credits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResaleTransfer(TypedDict):
    id: str
    source_contract_id: str
    resort_id: str
    buyer_owner_id: str
    sale_price_cents: int
    transfer_use_year: int
    transfer_day_of_year: int
    new_contract_id: Optional[str]
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DelinquencyCase(TypedDict):
    id: str
    contract_id: str
    owner_id: str
    trigger_invoice_id: str
    escalation_periods: int
    late_charge_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int
