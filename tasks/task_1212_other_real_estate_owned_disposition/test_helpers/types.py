"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class LifecycleStatus(str, Enum):
    HELD = "HELD"
    MARKETED = "MARKETED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    DISPOSED = "DISPOSED"
    CHARGED_OFF = "CHARGED_OFF"


class AppraisalStatus(str, Enum):
    UNAPPRAISED = "UNAPPRAISED"
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class PropertyType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"
    LAND = "LAND"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AppraisalLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"


class WriteDownStatus(str, Enum):
    PROPOSED = "PROPOSED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class WriteDownReason(str, Enum):
    MARKET_DECLINE = "MARKET_DECLINE"
    MEASUREMENT_PERIOD_ADJUSTMENT = "MEASUREMENT_PERIOD_ADJUSTMENT"
    REGULATORY_CHARGE_OFF = "REGULATORY_CHARGE_OFF"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class ListingTerminationReason(str, Enum):
    MANUAL = "MANUAL"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CHARGE_OFF = "CHARGE_OFF"


class OfferStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"
    CLOSED = "CLOSED"


class OfferRejectionReason(str, Enum):
    MANUAL = "MANUAL"
    SUPERSEDED = "SUPERSEDED"
    PROPERTY_CHARGED_OFF = "PROPERTY_CHARGED_OFF"


class FinancingType(str, Enum):
    CASH = "CASH"
    SELLER_FINANCED = "SELLER_FINANCED"


class CostType(str, Enum):
    TAXES = "TAXES"
    INSURANCE = "INSURANCE"
    MAINTENANCE = "MAINTENANCE"
    UTILITIES = "UTILITIES"
    HOA = "HOA"
    CAPITAL_IMPROVEMENT = "CAPITAL_IMPROVEMENT"


class IssueType(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    TITLE = "TITLE"


class IssueSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    IN_REMEDIATION = "IN_REMEDIATION"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class ClosingStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ExtensionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class LedgerEntryType(str, Enum):
    ACQUISITION = "ACQUISITION"
    CARRYING_COST = "CARRYING_COST"
    WRITE_DOWN = "WRITE_DOWN"
    CHARGE_OFF = "CHARGE_OFF"
    PROCEEDS = "PROCEEDS"
    GAIN_RECOGNIZED = "GAIN_RECOGNIZED"
    LOSS_RECOGNIZED = "LOSS_RECOGNIZED"


class ApprovalRole(str, Enum):
    OREO_SPECIALIST = "OREOSpecialist"
    CREDIT_OFFICER = "CreditOfficer"
    OREO_COMMITTEE = "OREOCommittee"


class UserRole(str, Enum):
    OREO_ADMIN = "OREOAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    OREO_SPECIALIST = "OREOSpecialist"
    APPRAISER = "Appraiser"
    CHIEF_APPRAISER = "ChiefAppraiser"
    CREDIT_OFFICER = "CreditOfficer"
    OREO_COMMITTEE = "OREOCommittee"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BROKER = "Broker"


class OREOProperty(TypedDict, total=False):
    id: str
    address: str
    state_code: str
    county: str
    property_type: str
    acquisition_date: str
    bpo_value: float
    foreclosure_debt: float
    fair_value_at_acquisition: float
    acquisition_basis: float
    carrying_value: float
    capitalized_cost_total: float
    expensed_cost_total: float
    current_fair_value: Optional[float]
    net_realizable_value: Optional[float]
    holding_deadline: str
    extension_days_approved: int
    lifecycle_status: str
    appraisal_status: str
    active_listing_count: int
    open_environmental_issue_count: int
    open_title_issue_count: int
    recognized_gain_loss_total: float
    pending_write_down_count: int
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict):
    id: str
    name: str
    license_number: str
    coverage_states: List[str]
    fee_flat: float
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict):
    id: str
    name: str
    license_number: str
    coverage_states: List[str]
    status: str
    performance_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


# CarryingCost is append-only: carries id + created_at only (no updated_at / version).
class CarryingCost(TypedDict):
    id: str
    property_id: str
    cost_type: str
    amount: float
    incurred_date: str
    description: Optional[str]
    created_at: str


class Appraisal(TypedDict, total=False):
    id: str
    property_id: str
    appraiser_id: str
    effective_date: str
    appraised_value: float
    status: str
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WriteDown(TypedDict, total=False):
    id: str
    property_id: str
    amount: float
    reason: str
    status: str
    auto_generated: bool
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ListingAgreement(TypedDict, total=False):
    id: str
    property_id: str
    broker_id: str
    start_date: str
    end_date: str
    listing_price: float
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    property_id: str
    listing_agreement_id: Optional[str]
    buyer_name: str
    offer_price: float
    financing_type: str
    down_payment: Optional[float]
    earnest_money: float
    status: str
    current_price: float
    counter_round: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IssueCase(TypedDict, total=False):
    id: str
    property_id: str
    issue_type: str
    severity: str
    description: str
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosingStatement(TypedDict, total=False):
    id: str
    offer_id: str
    property_id: str
    closing_date: str
    contract_price: float
    commission_total: float
    listing_broker_share: float
    selling_broker_share: float
    closing_cost_flat: float
    net_proceeds: float
    carrying_value_at_closing: float
    gain_loss: float
    recognized_gain_at_settlement: float
    deferred_gain: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    property_id: str
    requested_extension_days: int
    justification: str
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# LedgerEntry is append-only: carries id + created_at only (no updated_at / version).
class LedgerEntry(TypedDict, total=False):
    id: str
    property_id: str
    write_down_id: Optional[str]
    closing_statement_id: Optional[str]
    entry_type: str
    amount: float
    memo: str
    created_at: str


class ApprovalTier(TypedDict, total=False):
    id: str
    name: str
    min_net_proceeds: float
    max_net_proceeds: Optional[float]
    required_role: str
    required_rank: int
    created_at: str
    updated_at: str
    version: int
