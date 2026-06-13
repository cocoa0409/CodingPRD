"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Auto Title Loan PRD. Entities carrying the full common-field set
(id + created_at + updated_at + version) are typed accordingly; the RegulatoryProfile
is configuration data and carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    APPRAISER = "Appraiser"
    UNDERWRITER = "Underwriter"
    LOAN_SERVICER = "LoanServicer"
    RECOVERY_MANAGER = "RecoveryManager"
    TITLE_CLERK = "TitleClerk"


# ─── Status / enum value sets ─────────────────────────────────────────────
class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BARRED = "BARRED"


class VehicleLienState(str, Enum):
    CLEAR = "CLEAR"
    ENCUMBERED = "ENCUMBERED"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    CONSUMED = "CONSUMED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class ValuationBasis(str, Enum):
    TRADE_IN = "TRADE_IN"
    AUCTION = "AUCTION"


class LoanApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LoanPayoffStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    REDEEMED = "REDEEMED"
    PAID_OFF = "PAID_OFF"
    CHARGED_OFF = "CHARGED_OFF"


class LoanDelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"


class TitleLienStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    RELEASED = "RELEASED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    WAIVED = "WAIVED"


class PaymentType(str, Enum):
    REGULAR = "REGULAR"
    REINSTATEMENT = "REINSTATEMENT"
    REDEMPTION = "REDEMPTION"


class RepossessionOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    ASSIGNED = "ASSIGNED"
    RECOVERED = "RECOVERED"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class DeviceStarterState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class DeviceCommandType(str, Enum):
    STARTER_DISABLE = "STARTER_DISABLE"
    STARTER_ENABLE = "STARTER_ENABLE"
    LOCATE = "LOCATE"


class DeviceCommandStatus(str, Enum):
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true — id + created_at + updated_at + version
class Borrower(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    monthly_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — configuration data, only id + created_at
class RegulatoryProfile(TypedDict):
    id: str
    state_code: str
    max_apr_bps: int
    max_ltv_bps: int
    max_renewals: int
    min_term_months: int
    max_term_months: int
    redemption_grace_days: int
    valuation_basis: str
    created_at: str


class Vehicle(TypedDict):
    id: str
    borrower_id: str
    vin: str
    year: int
    make: str
    model: str
    odometer_miles: int
    lien_state: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    vehicle_id: str
    trade_in_value_cents: int
    auction_value_cents: int
    condition_grade: str
    basis_value_cents: Optional[int]
    max_principal_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    borrower_id: str
    appraisal_id: str
    requested_principal_cents: int
    contract_apr_bps: int
    term_months: int
    effective_apr_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    borrower_id: str
    vehicle_id: str
    original_principal_cents: int
    effective_apr_bps: int
    term_months: int
    principal_balance_cents: int
    accrued_interest_cents: int
    fees_balance_cents: int
    renewal_count: int
    payoff_status: str
    delinquency_status: str
    created_at: str
    updated_at: str
    version: int


class TitleLien(TypedDict):
    id: str
    loan_id: str
    vehicle_id: str
    dmv_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    loan_id: str
    sequence_no: int
    due_date: str
    principal_due_cents: int
    interest_due_cents: int
    late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    payment_type: str
    posted_at: str
    principal_applied_cents: int
    interest_applied_cents: int
    fees_applied_cents: int
    overpayment_cents: int
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict):
    id: str
    loan_id: str
    expected_loan_version: int
    new_term_months: int
    rolled_fees_cents: int
    new_principal_cents: int
    renewal_index: int
    created_at: str
    updated_at: str
    version: int


class RepossessionOrder(TypedDict):
    id: str
    loan_id: str
    vehicle_id: str
    recovered_at: Optional[str]
    redemption_deadline: Optional[str]
    sale_proceeds_cents: Optional[int]
    deficiency_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepossessionAssignment(TypedDict):
    id: str
    repossession_order_id: str
    agent_name: str
    window_start: str
    window_end: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    vehicle_id: str
    serial_number: str
    starter_state: str
    active_disable_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceCommand(TypedDict):
    id: str
    device_id: str
    command_type: str
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoffQuote(TypedDict):
    redemption_amount_cents: int
    reinstatement_amount_cents: int
