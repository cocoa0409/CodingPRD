"""Domain types for the Store Cash Office & Deposit Reconciliation API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The six operator roles."""

    CASHIER = "Cashier"
    CASH_OFFICE_CLERK = "CashOfficeClerk"
    STORE_MANAGER = "StoreManager"
    ARMORED_CARRIER = "ArmoredCarrier"
    TREASURY_ANALYST = "TreasuryAnalyst"
    LOSS_PREVENTION_INVESTIGATOR = "LossPreventionInvestigator"


class SeasonalProfile(str, Enum):
    BASELINE = "BASELINE"
    BACK_TO_SCHOOL = "BACK_TO_SCHOOL"
    HOLIDAY = "HOLIDAY"


class TillEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    RESTRICTED = "RESTRICTED"
    BARRED = "BARRED"


class CoachingState(str, Enum):
    NONE = "NONE"
    COACHING_DUE = "COACHING_DUE"
    COACHING_ACKNOWLEDGED = "COACHING_ACKNOWLEDGED"


class SafeType(str, Enum):
    MANUAL = "MANUAL"
    SMART = "SMART"


class SafeOpenState(str, Enum):
    LOCKED = "LOCKED"
    OPEN_REQUESTED = "OPEN_REQUESTED"
    UNLOCKED = "UNLOCKED"


class SafePosture(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class SafeTxnType(str, Enum):
    OPENING_BALANCE = "OPENING_BALANCE"
    STARTING_BANK_ISSUE = "STARTING_BANK_ISSUE"
    MID_SHIFT_DROP = "MID_SHIFT_DROP"
    CLOSING_DROP = "CLOSING_DROP"
    SMART_DEPOSIT = "SMART_DEPOSIT"
    DEPOSIT_REMOVAL = "DEPOSIT_REMOVAL"
    DEPOSIT_RETURN = "DEPOSIT_RETURN"
    CHANGE_ORDER_RECEIPT = "CHANGE_ORDER_RECEIPT"
    VARIANCE_ADJUSTMENT = "VARIANCE_ADJUSTMENT"


#: Transaction kinds that add to the safe balance.
ADDING_TXN_TYPES = [
    SafeTxnType.OPENING_BALANCE.value,
    SafeTxnType.MID_SHIFT_DROP.value,
    SafeTxnType.CLOSING_DROP.value,
    SafeTxnType.SMART_DEPOSIT.value,
    SafeTxnType.DEPOSIT_RETURN.value,
    SafeTxnType.CHANGE_ORDER_RECEIPT.value,
]

#: Transaction kinds that subtract from the safe balance.
SUBTRACTING_TXN_TYPES = [
    SafeTxnType.STARTING_BANK_ISSUE.value,
    SafeTxnType.DEPOSIT_REMOVAL.value,
    SafeTxnType.VARIANCE_ADJUSTMENT.value,
]


class SalesJournalStatus(str, Enum):
    OPEN = "OPEN"
    TENDERS_POSTED = "TENDERS_POSTED"
    BALANCED = "BALANCED"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"


class TillSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_COUNT = "PENDING_COUNT"
    COUNTED = "COUNTED"
    RECONCILED = "RECONCILED"


class VarianceBasis(str, Enum):
    DECLARED_DROPS = "DECLARED_DROPS"
    VERIFIED_DROPS = "VERIFIED_DROPS"


class DepositType(str, Enum):
    MANUAL_ARMORED = "MANUAL_ARMORED"
    SMART_SAFE = "SMART_SAFE"


class DepositStatus(str, Enum):
    PREPARING = "PREPARING"
    SEALED = "SEALED"
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    RECONCILED = "RECONCILED"
    DISCREPANT = "DISCREPANT"
    VOIDED = "VOIDED"


class CreditBasis(str, Enum):
    CARRIER_PROVISIONAL = "CARRIER_PROVISIONAL"
    SMART_PROVISIONAL = "SMART_PROVISIONAL"


class CreditType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    ADJUSTMENT = "ADJUSTMENT"


class MatchState(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"


class CardNetwork(str, Enum):
    VISA_MC = "VISA_MC"
    AMEX = "AMEX"


class SettlementStatus(str, Enum):
    MATCHED = "MATCHED"
    VARIANCE = "VARIANCE"


class CaseType(str, Enum):
    SESSION_VARIANCE = "SESSION_VARIANCE"
    ROLLING_PATTERN = "ROLLING_PATTERN"
    DEPOSIT_CREDIT = "DEPOSIT_CREDIT"


class VarianceCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESEARCHING = "RESEARCHING"
    EXPLAINED = "EXPLAINED"
    ESCALATED = "ESCALATED"
    CLOSED_SUBSTANTIATED = "CLOSED_SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"


class AttributionBucket(str, Enum):
    REGISTER = "REGISTER"
    SAFE = "SAFE"
    BANK = "BANK"


class CaseDisposition(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"


#: Case statuses counted by a journal's or cashier's open_case_count.
OPEN_CASE_STATUSES = [
    VarianceCaseStatus.OPEN.value,
    VarianceCaseStatus.RESEARCHING.value,
    VarianceCaseStatus.ESCALATED.value,
]

#: Deposit statuses that satisfy the journal's deposit-present condition.
JOURNAL_DEPOSIT_PRESENT_STATUSES = [
    DepositStatus.SEALED.value,
    DepositStatus.SCHEDULED.value,
    DepositStatus.IN_TRANSIT.value,
    DepositStatus.RECONCILED.value,
]

#: The permitted denominations for a blind-count or deposit line.
PERMITTED_DENOMINATIONS = [2000, 1000, 500, 100, 25, 10, 5, 1]


class DenominationLine(TypedDict):
    """A blind-count or deposit-bag line."""

    denomination_cents: int
    quantity: int


class PlannedLine(TypedDict):
    """One row of a change order's denomination plan."""

    denomination_cents: int
    strap_count: int
    units: int
    planned_cents: int


class Attribution(TypedDict):
    """One entry on a variance case's attributions list."""

    bucket: str
    amount_cents: int
    note: str
    recorded_at: str


class Store(TypedDict):
    id: str
    store_code: str
    name: str
    region_code: str
    safe_time_delay_minutes: int
    safe_open_window_minutes: int
    dual_control_required: bool
    pickup_buffer_minutes: int
    max_daily_pickups: int
    single_event_variance_threshold_cents: int
    rolling_variance_threshold_cents: int
    rolling_window_days: int
    theft_escalation_threshold_cents: int
    provisional_credit_cap_cents: int
    seasonal_profile: str
    created_at: str
    updated_at: str
    version: int


class Cashier(TypedDict):
    id: str
    store_id: str
    employee_code: str
    display_name: str
    till_eligibility: str
    coaching_state: str
    coaching_due_at: Optional[str]
    rolling_absolute_variance_cents: int
    rolling_net_variance_cents: int
    reconciled_session_count: int
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class Safe(TypedDict):
    id: str
    store_id: str
    safe_code: str
    safe_type: str
    open_state: str
    posture: str
    open_requested_at: Optional[str]
    open_requested_by_user_id: Optional[str]
    unlocked_at: Optional[str]
    balance_cents: int
    provisional_credit_balance_cents: int
    suspect_note_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesJournal(TypedDict):
    id: str
    store_id: str
    business_date: str
    status: str
    journal_cash_sales_cents: Optional[int]
    journal_card_sales_cents: Optional[int]
    session_count: int
    reconciled_session_count: int
    settlement_count: int
    register_cash_tieout_cents: int
    settlement_variance_total_cents: int
    open_case_count: int
    net_unexplained_cents: int
    created_at: str
    updated_at: str
    version: int


class TillSession(TypedDict):
    id: str
    sales_journal_id: str
    cashier_id: str
    safe_id: str
    register_number: int
    shift_start_at: str
    shift_end_at: str
    status: str
    starting_bank_cents: int
    pos_cash_sales_cents: Optional[int]
    pos_card_sales_cents: Optional[int]
    pos_paid_out_cents: Optional[int]
    dropped_declared_cents: int
    dropped_verified_cents: Optional[int]
    counted_lines: List[DenominationLine]
    counted_cash_cents: Optional[int]
    expected_cash_cents: Optional[int]
    variance_cents: Optional[int]
    variance_basis: Optional[str]
    recount_count: int
    counted_by_user_id: Optional[str]
    forced_close: bool
    created_at: str
    updated_at: str
    version: int


class SafeTransaction(TypedDict):
    """An immutable safe ledger row: it carries only id and created_at.

    A safe transaction has no updated_at and no version field at all; its own
    timing information lives in occurred_at.
    """

    id: str
    safe_id: str
    till_session_id: Optional[str]
    deposit_id: Optional[str]
    change_order_id: Optional[str]
    txn_type: str
    declared_amount_cents: int
    verified_amount_cents: Optional[int]
    effective_amount_cents: int
    actor_user_id: str
    occurred_at: str
    memo: Optional[str]
    created_at: str


class Deposit(TypedDict):
    id: str
    safe_id: str
    sales_journal_id: str
    deposit_type: str
    status: str
    business_date: str
    counted_lines: List[DenominationLine]
    declared_total_cents: int
    suspect_note_cents: int
    credit_basis: str
    provisional_credit_cents: int
    carrier_fee_cents: int
    expected_credit_cents: int
    credited_total_cents: int
    credit_variance_cents: Optional[int]
    pickup_window_start: Optional[str]
    pickup_window_end: Optional[str]
    prepared_by_user_id: Optional[str]
    sealed_by_user_id: Optional[str]
    seal_number: Optional[str]
    carrier_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BankCreditRecord(TypedDict):
    id: str
    store_id: str
    deposit_id: Optional[str]
    credit_type: str
    amount_cents: int
    value_date: str
    bank_reference: str
    match_state: str
    created_at: str
    updated_at: str
    version: int


class CardSettlement(TypedDict):
    id: str
    sales_journal_id: str
    card_network: str
    gross_card_sales_cents: int
    txn_count: int
    chargeback_cents: int
    monthly_volume_cents: int
    funded_amount_cents: int
    expected_fee_cents: int
    expected_funded_cents: int
    settlement_variance_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class VarianceCase(TypedDict):
    id: str
    sales_journal_id: str
    cashier_id: Optional[str]
    deposit_id: Optional[str]
    case_type: str
    status: str
    total_variance_cents: int
    attributions: List[Attribution]
    attributed_register_cents: int
    attributed_safe_cents: int
    attributed_bank_cents: int
    unexplained_cents: int
    suspected_theft: bool
    escalated_by_user_id: Optional[str]
    disposition: Optional[str]
    closing_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    store_id: str
    target_week_start: str
    days_covered: int
    baseline_daily_cash_demand_cents: int
    growth_pct: float
    seasonal_profile_override: Optional[str]
    applied_seasonal_profile: str
    forecast_demand_cents: int
    planned_lines: List[PlannedLine]
    total_planned_cents: int
    status: str
    approved_by_user_id: Optional[str]
    received_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
