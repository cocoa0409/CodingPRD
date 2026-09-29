"""Domain types for the Chargemaster Governance API: status enums, role enum, entity shapes."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REVENUE_INTEGRITY_ANALYST = "RevenueIntegrityAnalyst"
    PRICING_COMMITTEE_APPROVER = "PricingCommitteeApprover"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTRACT_MANAGER = "ContractManager"
    DEPARTMENT_MANAGER = "DepartmentManager"


ALL_ROLE_NAMES = [r.value for r in UserRole]


class ChargemasterPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TransparencyStatus(str, Enum):
    CURRENT = "CURRENT"
    NEEDS_REFRESH = "NEEDS_REFRESH"


class RoundingMode(str, Enum):
    NEAREST_DOLLAR = "NEAREST_DOLLAR"
    NEAREST_CENT = "NEAREST_CENT"
    PSYCHOLOGICAL_99 = "PSYCHOLOGICAL_99"


class DuplicateDetectionMode(str, Enum):
    STRICT_CODE = "STRICT_CODE"
    FUZZY_DESCRIPTION = "FUZZY_DESCRIPTION"


class RevenueCodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PricingClass(str, Enum):
    SUPPLY = "SUPPLY"
    PHARMACY = "PHARMACY"
    PROCEDURE = "PROCEDURE"
    ROOM_AND_BOARD = "ROOM_AND_BOARD"


class CodeType(str, Enum):
    CPT = "CPT"
    HCPCS = "HCPCS"
    REV_ONLY = "REV_ONLY"
    CDM_INTERNAL = "CDM_INTERNAL"


class ItemLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class ItemPriceStatus(str, Enum):
    PRICED_CURRENT = "PRICED_CURRENT"
    PRICE_STALE = "PRICE_STALE"
    REPRICE_PENDING = "REPRICE_PENDING"
    PRICE_FROZEN = "PRICE_FROZEN"


class ItemLifecycleAction(str, Enum):
    SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
    RETURN_TO_DRAFT = "RETURN_TO_DRAFT"
    APPROVE = "APPROVE"
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"
    REACTIVATE = "REACTIVATE"
    ARCHIVE = "ARCHIVE"
    MARK_DUPLICATE = "MARK_DUPLICATE"


class PricingMethod(str, Enum):
    COST_PLUS_MARKUP = "COST_PLUS_MARKUP"
    MEDICARE_MULTIPLE = "MEDICARE_MULTIPLE"
    FLAT_FEE = "FLAT_FEE"


class PriceRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class RequestType(str, Enum):
    NEW_ITEM = "NEW_ITEM"
    PRICE_CHANGE = "PRICE_CHANGE"
    REVENUE_CODE_REMAP = "REVENUE_CODE_REMAP"
    DEACTIVATION = "DEACTIVATION"


class ChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    IMPLEMENTED = "IMPLEMENTED"
    VOIDED_STALE = "VOIDED_STALE"


class ChangeRequestDecision(str, Enum):
    REVIEW = "REVIEW"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"
    WITHDRAW = "WITHDRAW"


class CycleStatus(str, Enum):
    LOADED = "LOADED"
    MAPPING = "MAPPING"
    CROSSWALK_APPROVED = "CROSSWALK_APPROVED"
    ACTIVATED = "ACTIVATED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class CycleAction(str, Enum):
    START_MAPPING = "START_MAPPING"
    APPROVE_CROSSWALK = "APPROVE_CROSSWALK"
    ACTIVATE = "ACTIVATE"
    ROLL_BACK = "ROLL_BACK"
    CANCEL = "CANCEL"


class CodeSet(str, Enum):
    CPT = "CPT"
    HCPCS = "HCPCS"


class EntryAction(str, Enum):
    ADD = "ADD"
    DELETE = "DELETE"
    REVISE = "REVISE"
    CROSSWALK = "CROSSWALK"


class EntryStatus(str, Enum):
    PENDING = "PENDING"
    MAPPED = "MAPPED"
    DEFERRED = "DEFERRED"
    APPLIED = "APPLIED"
    REVERTED = "REVERTED"


class EntryDisposition(str, Enum):
    MAP = "MAP"
    DEFER = "DEFER"


class ProductLine(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID_MCO = "MEDICAID_MCO"


class ReimbursementMethod(str, Enum):
    PERCENT_OF_CHARGE = "PERCENT_OF_CHARGE"
    LESSER_OF_FEE_SCHEDULE = "LESSER_OF_FEE_SCHEDULE"
    CASE_RATE = "CASE_RATE"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class BatchStatus(str, Enum):
    INGESTED = "INGESTED"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    CLOSED = "CLOSED"


class BatchAction(str, Enum):
    FINALIZE = "FINALIZE"
    DISPUTE = "DISPUTE"
    CLOSE = "CLOSE"


class MatchStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    MATCHED = "MATCHED"
    PRICE_VARIANCE = "PRICE_VARIANCE"
    UNKNOWN_CODE = "UNKNOWN_CODE"
    INACTIVE_ITEM = "INACTIVE_ITEM"
    DUPLICATE_LINE = "DUPLICATE_LINE"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class FindingAction(str, Enum):
    CONFIRM = "CONFIRM"
    DISMISS = "DISMISS"
    RESOLVE = "RESOLVE"


class AnalysisVariant(str, Enum):
    FORWARD_PROJECTED = "FORWARD_PROJECTED"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class AnalysisStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SIGNED_OFF = "SIGNED_OFF"
    STALE = "STALE"


class FileFormat(str, Enum):
    CSV = "CSV"
    JSON = "JSON"


class TransparencyFileStatus(str, Enum):
    BUILDING = "BUILDING"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class TransparencyFileAction(str, Enum):
    VALIDATE = "VALIDATE"
    PUBLISH = "PUBLISH"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Entity shapes. Entities carrying the full complement of id / created_at /
# updated_at / version, per the PRD's resource-identity rules.
# ---------------------------------------------------------------------------

class Facility(TypedDict):
    id: str
    name: str
    cms_certification_number: str
    rounding_mode: str
    aggregate_markup_limit_bp: int
    volume_growth_bp: int
    impact_lookback_days: int
    duplicate_detection_mode: str
    chargemaster_posture: str
    active_item_count: int
    aggregate_gross_charge_cents: int
    aggregate_cost_basis_cents: int
    aggregate_markup_ratio_bp: int
    stale_price_item_count: int
    published_transparency_file_id: Optional[str]
    transparency_status: str
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    facility_id: str
    name: str
    cost_center_code: str
    allowed_revenue_code_values: List[str]
    manager_user_id: str
    capture_hold: bool
    unresolved_finding_amount_cents: int
    recovered_charge_cents: int
    open_request_count: int
    created_at: str
    updated_at: str
    version: int


# RevenueCode is national reference data: only id and created_at.
class RevenueCode(TypedDict):
    id: str
    code: str
    description: str
    requires_hcpcs: bool
    allowed_code_types: List[str]
    status: str
    pricing_class: str
    created_at: str


class ChargeItem(TypedDict):
    id: str
    facility_id: str
    department_id: str
    revenue_code_id: str
    duplicate_of_item_id: Optional[str]
    companion_required_item_id: Optional[str]
    companion_window_hours: int
    cdm_number: str
    description: str
    code_type: str
    code_value: Optional[str]
    cost_basis_cents: int
    medicare_rate_cents: int
    market_p75_cents: int
    gross_charge_cents: int
    prior_gross_charge_cents: int
    applied_price_rule_id: Optional[str]
    price_conflict: bool
    lifecycle_status: str
    price_status: str
    effective_from: str
    approved_by_user_id: Optional[str]
    last_code_cycle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# CapturedCharge is an append-only capture line: only id and created_at.
class CapturedCharge(TypedDict):
    id: str
    batch_id: str
    charge_item_id: Optional[str]
    submitted_cdm_number: str
    encounter_id: str
    payer_code: str
    service_datetime: str
    quantity: int
    posted_charge_cents: int
    expected_charge_cents: Optional[int]
    match_status: str
    line_variance_bp: Optional[int]
    created_at: str
