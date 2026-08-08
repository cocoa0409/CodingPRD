"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PRODUCER = "Producer"
    HEALTH_INSPECTOR = "HealthInspector"
    MARKET_MANAGER = "MarketManager"
    HEALTH_ADMIN = "HealthAdmin"


class ProducerStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class ProductComplianceStatus(str, Enum):
    DECLARED = "DECLARED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class ProductLabelStatus(str, Enum):
    LABEL_DRAFT = "LABEL_DRAFT"
    LABEL_APPROVED = "LABEL_APPROVED"
    LABEL_REJECTED = "LABEL_REJECTED"


class PermitClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    ISSUED = "ISSUED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class MarketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CHECKED_IN = "CHECKED_IN"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    VOIDED = "VOIDED"


class SalesRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    RESOLVED = "RESOLVED"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
# common_fields: false (AllowedFoodPolicy) -> id + created_at only


class Producer(TypedDict):
    id: str
    business_name: str
    operator_name: str
    contact_email: str
    county: str
    water_source: str
    status: str
    verification_token: str
    verified_at: Optional[str]
    ytd_gross_sales_cents: int
    created_at: str
    updated_at: str
    version: int


class AllowedFoodPolicy(TypedDict):
    id: str
    food_category: str
    is_cottage_allowed: bool
    max_ph: Optional[float]
    max_water_activity: Optional[float]
    class_b_required: bool
    requires_allergen_label: bool
    created_at: str


class Product(TypedDict):
    id: str
    producer_id: str
    name: str
    food_category: str
    requires_refrigeration: bool
    ph_value: Optional[float]
    water_activity: Optional[float]
    unit_price_cents: int
    compliance_status: str
    label_status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    producer_id: str
    permit_class: str
    status: str
    inspection_required: bool
    annual_cap_cents: int
    fee_cents: int
    term_start: str
    expires_at: str
    renewal_count: int
    is_expired: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    permit_id: str
    inspection_type: str
    status: str
    scheduled_for: str
    violation_count: int
    inspector_user_id: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    producer_id: str
    product_id: Optional[str]
    category: str
    description: str
    status: str
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FarmersMarket(TypedDict):
    id: str
    name: str
    county: str
    venue_type: str
    max_vendors_per_day: int
    allowed_classes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketManifest(TypedDict):
    id: str
    producer_id: str
    market_id: str
    permit_id: str
    event_date: str
    product_ids: List[str]
    status: str
    booth_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesRecord(TypedDict):
    id: str
    manifest_id: str
    producer_id: str
    gross_amount_cents: int
    status: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict):
    id: str
    producer_id: str
    product_id: str
    reason: str
    severity: str
    status: str
    recalled_units: int
    estimated_liability_cents: int
    final_liability_cents: int
    created_at: str
    updated_at: str
    version: int
