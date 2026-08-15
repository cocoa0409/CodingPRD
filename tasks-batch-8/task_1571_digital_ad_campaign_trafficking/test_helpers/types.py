"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    AD_OPS_MANAGER = "AdOpsManager"
    TRAFFICKER = "Trafficker"
    VERIFICATION_ANALYST = "VerificationAnalyst"
    BILLING_MANAGER = "BillingManager"


class InsertionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LineItemStatus(str, Enum):
    DRAFT = "DRAFT"
    TRAFFICKED = "TRAFFICKED"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FraudPosture(str, Enum):
    CLEAR = "CLEAR"
    BREACH = "BREACH"


class CreativeStatus(str, Enum):
    UPLOADED = "UPLOADED"
    IN_QA = "IN_QA"
    QA_PASSED = "QA_PASSED"
    QA_FAILED = "QA_FAILED"
    TAGGED = "TAGGED"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class DeliverySnapshotStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Vendor(str, Enum):
    MOAT = "MOAT"
    IAS = "IAS"
    DOUBLEVERIFY = "DOUBLEVERIFY"


class Assessment(str, Enum):
    PASS = "PASS"
    BREACH = "BREACH"


class MakeGoodStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class MakeGoodKind(str, Enum):
    CREDIT = "CREDIT"
    BONUS_IMPRESSIONS = "BONUS_IMPRESSIONS"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    LOCKED = "LOCKED"


class WrapReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class BillingBasis(str, Enum):
    AGENCY_PLATFORM = "AGENCY_PLATFORM"
    THIRD_PARTY_TAG = "THIRD_PARTY_TAG"
    LOWER_OF = "LOWER_OF"


class PacingMode(str, Enum):
    EVEN = "EVEN"
    ASAP = "ASAP"


class AttributionModel(str, Enum):
    LINEAR_CLICKS = "LINEAR_CLICKS"
    VIEW_WEIGHTED = "VIEW_WEIGHTED"


# --- Primary resources: id + created_at + updated_at + version (PRD §2.4) ---

class InsertionOrder(TypedDict, total=False):
    id: str
    advertiser_name: str
    total_budget_cents: int
    flight_start: str
    flight_end: str
    billing_basis: str
    viewability_threshold_pct: float
    ivt_threshold_pct: float
    status: str
    booked_budget_cents: int
    total_applied_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict, total=False):
    id: str
    io_id: str
    name: str
    goal_impressions: int
    cpm_rate_cents: int
    start_date: str
    end_date: str
    pacing_mode: str
    targeting: dict
    frequency_cap_max_impressions: Optional[int]
    frequency_cap_window_hours: Optional[int]
    status: str
    fraud_posture: str
    budget_cents: int
    delivered_impressions: int
    delivered_clicks: int
    delivered_spend_cents: int
    pacing_projection_impressions: int
    pacing_projection_trailing_impressions: int
    pacing_alert: bool
    created_at: str
    updated_at: str
    version: int


class Creative(TypedDict, total=False):
    id: str
    line_item_id: str
    name: str
    asset_url: str
    width: int
    height: int
    ad_tag: Optional[str]
    qa_failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VerificationReport(TypedDict, total=False):
    id: str
    line_item_id: str
    vendor: str
    period_start: str
    period_end: str
    measured_impressions: int
    viewable_impressions: int
    ivt_impressions: int
    viewability_rate: float
    ivt_rate: float
    assessment: str
    make_good_max_credit_cents: int
    status: str
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class MakeGood(TypedDict, total=False):
    id: str
    verification_report_id: str
    kind: str
    credit_cents: Optional[int]
    bonus_impressions: Optional[int]
    status: str
    proposed_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    line_item_id: str
    period_start: str
    period_end: str
    third_party_impressions: int
    agency_impressions: int
    discrepancy_pct: Optional[float]
    billing_impressions: Optional[int]
    billable_cents: Optional[int]
    status: str
    reconciled_by_user_id: Optional[str]
    locked_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WrapReport(TypedDict, total=False):
    id: str
    io_id: str
    attribution_model: str
    total_conversions: int
    status: str
    total_delivered_impressions: int
    total_spend_cents: int
    total_billable_cents: int
    total_applied_credit_cents: int
    net_billable_cents: int
    attribution: List[dict]
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger records: ONLY id + created_at (PRD §2.4) ---

class DeliverySnapshot(TypedDict, total=False):
    id: str
    line_item_id: str
    snapshot_date: str
    impressions: int
    clicks: int
    spend_cents: int
    status: str
    created_at: str
    # NO updated_at, NO version — absent on append-only ledger records


class ImpressionEvent(TypedDict, total=False):
    id: str
    line_item_id: str
    user_key: str
    occurred_at: str
    created_at: str
    # NO updated_at, NO version — absent on append-only ledger records
