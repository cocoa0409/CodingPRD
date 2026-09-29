"""Domain vocabulary and response shapes for the SNAP Retailer Authorization
and Redemption Compliance API.

Every enum member and every TypedDict field below is named by the PRD. Fields
the PRD does not name are deliberately absent, because a shape assertion is
only as trustworthy as the contract it transcribes.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is present on 3.9/3.10
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RETAILER_OWNER = "RetailerOwner"
    STORE_CLERK = "StoreClerk"
    INSPECTOR = "Inspector"
    FNS_ADMIN = "FnsAdmin"
    FNS_ANALYST = "FnsAnalyst"
    ADMIN_REVIEW_OFFICER = "AdminReviewOfficer"


# --------------------------------------------------------------------------
# Owner
# --------------------------------------------------------------------------

class OwnershipType(str, Enum):
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR"
    PARTNERSHIP = "PARTNERSHIP"
    CORPORATION = "CORPORATION"
    LLC = "LLC"


class OwnerSanctionFlag(str, Enum):
    CLEAR = "CLEAR"
    HAS_ACTIVE_CMP_DEBT = "HAS_ACTIVE_CMP_DEBT"
    PERMANENTLY_DISQUALIFIED = "PERMANENTLY_DISQUALIFIED"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BARRED = "BARRED"


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

class StoreType(str, Enum):
    SUPERMARKET = "SUPERMARKET"
    GROCERY = "GROCERY"
    CONVENIENCE = "CONVENIENCE"
    SPECIALTY = "SPECIALTY"
    FARMERS_MARKET = "FARMERS_MARKET"
    MEAL_SERVICE = "MEAL_SERVICE"


class AuthorizationStatus(str, Enum):
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class StoreSanctionStatus(str, Enum):
    NONE = "NONE"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CHARGED = "CHARGED"
    UNDER_ADMIN_REVIEW = "UNDER_ADMIN_REVIEW"
    SANCTION_FINAL = "SANCTION_FINAL"
    SANCTION_REVERSED = "SANCTION_REVERSED"


class FlagLevel(str, Enum):
    FLAG_L0 = "FLAG_L0"
    FLAG_L1 = "FLAG_L1"
    FLAG_L2 = "FLAG_L2"
    FLAG_L3 = "FLAG_L3"


# --------------------------------------------------------------------------
# Application and field verification
# --------------------------------------------------------------------------

class ApplicationType(str, Enum):
    INITIAL = "INITIAL"
    REAUTHORIZATION_OWNERSHIP_CHANGE = "REAUTHORIZATION_OWNERSHIP_CHANGE"
    RENEWAL = "RENEWAL"


class ClaimedCriterion(str, Enum):
    CRITERION_A = "CRITERION_A"
    CRITERION_B = "CRITERION_B"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_VISIT = "PENDING_VISIT"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class HoldReasonCode(str, Enum):
    STAPLE_STOCK_INSUFFICIENT = "STAPLE_STOCK_INSUFFICIENT"
    SHELF_DISCREPANCY = "SHELF_DISCREPANCY"
    DEPTH_OF_STOCK_INSUFFICIENT = "DEPTH_OF_STOCK_INSUFFICIENT"
    NO_ACCESS = "NO_ACCESS"
    INVESTIGATION_HOLD = "INVESTIGATION_HOLD"


class DecisionReasonCode(str, Enum):
    APPROVED_CRITERION_A = "APPROVED_CRITERION_A"
    APPROVED_CRITERION_B = "APPROVED_CRITERION_B"
    STAPLE_STOCK_INSUFFICIENT = "STAPLE_STOCK_INSUFFICIENT"
    DEFICIENCY_CYCLES_EXHAUSTED = "DEFICIENCY_CYCLES_EXHAUSTED"
    OWNER_PERMANENTLY_DISQUALIFIED = "OWNER_PERMANENTLY_DISQUALIFIED"
    TRANSFER_CMP_OUTSTANDING = "TRANSFER_CMP_OUTSTANDING"
    WITHDRAWN_BY_APPLICANT = "WITHDRAWN_BY_APPLICANT"


class StapleCategory(str, Enum):
    BREAD_CEREAL = "BREAD_CEREAL"
    DAIRY = "DAIRY"
    FRUIT_VEG = "FRUIT_VEG"
    MEAT_POULTRY_FISH = "MEAT_POULTRY_FISH"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VisitType(str, Enum):
    PRE_AUTHORIZATION = "PRE_AUTHORIZATION"
    COMPLIANCE = "COMPLIANCE"
    REVERIFICATION = "REVERIFICATION"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_SUBMITTED = "FINDINGS_SUBMITTED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Point of sale and monitoring
# --------------------------------------------------------------------------

class ItemClass(str, Enum):
    STAPLE_FOOD = "STAPLE_FOOD"
    NONSTAPLE_FOOD = "NONSTAPLE_FOOD"
    SEED_PLANT = "SEED_PLANT"
    HOT_PREPARED = "HOT_PREPARED"
    ALCOHOL = "ALCOHOL"
    TOBACCO = "TOBACCO"
    NONFOOD = "NONFOOD"
    ENERGY_DRINK_SUPPLEMENT = "ENERGY_DRINK_SUPPLEMENT"
    LIVE_ANIMAL = "LIVE_ANIMAL"


ELIGIBLE_ITEM_CLASSES = (
    ItemClass.STAPLE_FOOD.value,
    ItemClass.NONSTAPLE_FOOD.value,
    ItemClass.SEED_PLANT.value,
)


class PosStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class DeclineReasonCode(str, Enum):
    NO_ELIGIBLE_ITEMS = "NO_ELIGIBLE_ITEMS"
    INSUFFICIENT_SPLIT_TENDER = "INSUFFICIENT_SPLIT_TENDER"


class VoidReasonCode(str, Enum):
    CLERK_ERROR = "CLERK_ERROR"
    CUSTOMER_ABANDONED = "CUSTOMER_ABANDONED"
    PROCESSOR_REVERSAL = "PROCESSOR_REVERSAL"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReconciliationStatus(str, Enum):
    NOT_IMPORTED = "NOT_IMPORTED"
    MATCHED = "MATCHED"
    VARIANCE = "VARIANCE"


# --------------------------------------------------------------------------
# Investigations and sanction cases
# --------------------------------------------------------------------------

class OpenedReason(str, Enum):
    ANOMALY_FLAG_L3 = "ANOMALY_FLAG_L3"
    TIP = "TIP"
    ALE_REFERRAL = "ALE_REFERRAL"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class EvidenceType(str, Enum):
    UNDERCOVER_BUY = "UNDERCOVER_BUY"
    INVENTORY_PURCHASE_MISMATCH = "INVENTORY_PURCHASE_MISMATCH"
    EBT_ONLY_TRANSACTION_PATTERN = "EBT_ONLY_TRANSACTION_PATTERN"
    INFORMANT_STATEMENT = "INFORMANT_STATEMENT"
    HOUSEHOLD_INTERVIEW = "HOUSEHOLD_INTERVIEW"


class SubstantiatedViolation(str, Enum):
    TRAFFICKING = "TRAFFICKING"
    INELIGIBLE_ITEM_SALES = "INELIGIBLE_ITEM_SALES"
    NONE = "NONE"


class ViolationType(str, Enum):
    TRAFFICKING = "TRAFFICKING"
    INELIGIBLE_ITEMS_HARDSHIP = "INELIGIBLE_ITEMS_HARDSHIP"
    STOCK_FAILURE = "STOCK_FAILURE"


class CaseStatus(str, Enum):
    CHARGE_DRAFT = "CHARGE_DRAFT"
    CHARGE_ISSUED = "CHARGE_ISSUED"
    REPLY_RECEIVED = "REPLY_RECEIVED"
    DETERMINED = "DETERMINED"
    ADMIN_REVIEW_REQUESTED = "ADMIN_REVIEW_REQUESTED"
    REMANDED = "REMANDED"
    SANCTION_FINAL = "SANCTION_FINAL"
    SANCTION_REVERSED = "SANCTION_REVERSED"
    ENFORCED = "ENFORCED"


class SanctionType(str, Enum):
    PERMANENT_DISQUALIFICATION = "PERMANENT_DISQUALIFICATION"
    TEMPORARY_DISQUALIFICATION = "TEMPORARY_DISQUALIFICATION"
    CMP_IN_LIEU = "CMP_IN_LIEU"
    WARNING = "WARNING"


class AdminReviewOutcome(str, Enum):
    SUSTAINED = "SUSTAINED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class AdminReviewReasonCode(str, Enum):
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    PROCEDURAL_DEFECT = "PROCEDURAL_DEFECT"
    NEW_EVIDENCE = "NEW_EVIDENCE"


class CmpBasisVariant(str, Enum):
    TRAILING_12_PERIOD_AVERAGE = "TRAILING_12_PERIOD_AVERAGE"
    PEAK_3_PERIOD_AVERAGE = "PEAK_3_PERIOD_AVERAGE"


class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    SUPERSEDED = "SUPERSEDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class LedgerEntryType(str, Enum):
    CMP_ASSESSED = "CMP_ASSESSED"
    CMP_PAYMENT = "CMP_PAYMENT"
    CMP_ABATEMENT = "CMP_ABATEMENT"


class LedgerReasonCode(str, Enum):
    DETERMINATION = "DETERMINATION"
    RETAILER_REMITTANCE = "RETAILER_REMITTANCE"
    REVIEW_REVERSAL = "REVIEW_REVERSAL"


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------

class TerminalModel(str, Enum):
    EBT_ONLY_WIRELESS = "EBT_ONLY_WIRELESS"
    EBT_ONLY_DIAL = "EBT_ONLY_DIAL"
    COMMERCIAL_INTEGRATED = "COMMERCIAL_INTEGRATED"


class TerminalStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    PENDING_RETURN = "PENDING_RETURN"
    RETIRED = "RETIRED"


class DeploymentStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RECALL_PENDING = "RECALL_PENDING"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class CloseReasonCode(str, Enum):
    AUTHORIZATION_LOST = "AUTHORIZATION_LOST"
    INVESTIGATION_FREEZE = "INVESTIGATION_FREEZE"
    RETAILER_REQUEST = "RETAILER_REQUEST"
    END_OF_TERM = "END_OF_TERM"
    DAMAGED = "DAMAGED"


class ItemCode(str, Enum):
    EBT_ONLY_WIRELESS_TERMINAL = "EBT_ONLY_WIRELESS_TERMINAL"
    EBT_ONLY_DIAL_TERMINAL = "EBT_ONLY_DIAL_TERMINAL"
    COMMERCIAL_POS_INTEGRATION = "COMMERCIAL_POS_INTEGRATION"
    MANUAL_VOUCHER_KIT = "MANUAL_VOUCHER_KIT"
    SIGNAGE_PACK = "SIGNAGE_PACK"
    RECEIPT_PAPER_CASE = "RECEIPT_PAPER_CASE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CancelReasonCode(str, Enum):
    RETAILER_REQUEST = "RETAILER_REQUEST"
    AUTHORIZATION_LOST = "AUTHORIZATION_LOST"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"


# --------------------------------------------------------------------------
# Response shapes. Every resource but PenaltyLedgerEntry carries id,
# created_at, updated_at and version; the ledger row carries id and created_at
# only, because it is append-only.
# --------------------------------------------------------------------------

class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Owner(CommonFields):
    legal_name: str
    ownership_type: str
    tax_id_last4: str
    permanent_disqualification_count: int
    cmp_outstanding_cents: int
    sanction_flag: str
    status: str


class Store(CommonFields):
    owner_id: str
    store_name: str
    state_code: str
    store_type: str
    checkout_lane_count: int
    staple_shelf_linear_feet: int
    annual_gross_sales_cents: int
    annual_staple_sales_cents: int
    max_terminal_slots: int
    tax_rate_bps: int
    hardship_designated: bool
    predecessor_store_id: Optional[str]
    staple_sales_bps: int
    criterion_b_pass: bool
    authorization_status: str
    sanction_status: str
    redemption_flag_level: str
    active_terminal_count: int
    fns_number: Optional[str]
    authorized_at: Optional[str]
    disqualified_until: Optional[str]
    permanently_disqualified: bool


class Application(CommonFields):
    store_id: str
    application_type: str
    claimed_criterion: str
    status: str
    deficiency_cycle_count: int
    hold_reason_code: Optional[str]
    decision_reason_code: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    desk_qualifying_categories: int
    desk_perishable_categories: int
    desk_criterion_pass: bool
    verified_criterion_pass: Optional[bool]


class Inspector(CommonFields):
    full_name: str
    state_code: str
    max_daily_minutes: int
    committed_minutes: int
    status: str


class StoreVisit(CommonFields):
    application_id: str
    inspector_id: str
    visit_type: str
    window_start: str
    window_end: str
    window_minutes: int
    status: str
    findings_submitted_at: Optional[str]
    verified_qualifying_categories: Optional[int]
    verified_perishable_categories: Optional[int]
    verified_criterion_a_pass: Optional[bool]
    depth_of_stock_pass: Optional[bool]
    shelf_discrepancy_bps: Optional[int]
    shelf_discrepancy_flag: Optional[bool]


class PosTransaction(CommonFields):
    store_id: str
    terminal_deployment_id: str
    household_ebt_card_last4: str
    snap_benefit_available_cents: int
    other_tender_offered_cents: int
    eligible_subtotal_cents: int
    ineligible_subtotal_cents: int
    tax_cents: int
    ebt_tender_cents: int
    other_tender_cents: int
    split_tender_applied: bool
    flagged_line_skus: List[str]
    status: str
    decline_reason_code: Optional[str]
    void_reason_code: Optional[str]


class RedemptionPeriod(CommonFields):
    store_id: str
    period_index: int
    period_start: str
    period_end: str
    status: str
    pos_derived_total_cents: int
    pos_derived_transaction_count: int
    imported_total_cents: Optional[int]
    imported_transaction_count: Optional[int]
    imported_large_transaction_cents: Optional[int]
    imported_even_dollar_transaction_count: Optional[int]
    redemption_total_cents: int
    transaction_count: int
    large_transaction_cents: int
    even_dollar_transaction_count: int
    reconciliation_variance_cents: Optional[int]
    reconciliation_status: str
    closed_at: Optional[str]
    size_expectation_cents: Optional[int]
    anomaly_score: Optional[int]
    flag_level: Optional[str]


class Investigation(CommonFields):
    store_id: str
    opened_reason: str
    trigger_period_id: Optional[str]
    status: str
    trafficking_confidence_score: int
    substantiated_violation: Optional[str]
    opened_by_user_id: str
    concluded_by_user_id: Optional[str]
    concluded_at: Optional[str]


class SanctionCase(CommonFields):
    store_id: str
    investigation_id: str
    violation_type: str
    status: str
    predecessor_case_id: Optional[str]
    prior_final_sanction_count: int
    charge_letter_sent_at: Optional[str]
    charge_issued_by_user_id: Optional[str]
    reply_due_at: Optional[str]
    cmp_election_due_at: Optional[str]
    reply_received_at: Optional[str]
    sanction_type: Optional[str]
    determined_at: Optional[str]
    determined_by_user_id: Optional[str]
    disqualification_months: Optional[int]
    admin_review_due_at: Optional[str]
    admin_review_requested_at: Optional[str]
    admin_review_outcome: Optional[str]
    admin_review_decided_by_user_id: Optional[str]
    remand_count: int
    final_decision_at: Optional[str]
    effective_date: Optional[str]
    enforced_at: Optional[str]
    cmp_basis_variant: Optional[str]
    cmp_basis_period_ids: Optional[List[str]]
    avg_monthly_redemption_cents: Optional[int]
    monthly_penalty_cents: Optional[int]
    cmp_amount_cents: Optional[int]
    cmp_capped: Optional[bool]
    cmp_outstanding_cents: int


class CmpElection(CommonFields):
    sanction_case_id: str
    elected_at: str
    status: str
    quoted_amount_cents: int
    quoted_basis_variant: str
    hardship_ownership_change_pending: bool


class PenaltyLedgerEntry(TypedDict):
    id: str
    created_at: str
    sanction_case_id: str
    entry_type: str
    amount_cents: int
    reason_code: str
    balance_after_cents: int


class EquipmentDepot(CommonFields):
    state_code: str
    total_units_owned: int
    units_in_stock: int
    units_reserved: int
    units_deployed: int
    units_pending_return: int
    units_retired: int


class EbtTerminal(CommonFields):
    depot_id: str
    serial_number: str
    model: str
    status: str


class TerminalDeployment(CommonFields):
    store_id: str
    terminal_id: str
    deploy_start: str
    deploy_end: str
    status: str
    activated_at: Optional[str]
    closed_at: Optional[str]
    close_reason_code: Optional[str]


class EquipmentOrder(CommonFields):
    store_id: str
    status: str
    subtotal_cents: int
    subsidy_cents: int
    net_equipment_cents: int
    handling_fee_cents: int
    total_due_cents: int
    placed_at: Optional[str]
    cancel_reason_code: Optional[str]


InventoryLine = Dict[str, Any]
LineItem = Dict[str, Any]
OrderLine = Dict[str, Any]
