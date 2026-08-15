"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    VERIFIER_ADMIN = "VerifierAdmin"
    BRAND_REP = "BrandRep"
    LAB_ANALYST = "LabAnalyst"
    AUDITOR = "Auditor"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    RENEWAL_DUE = "RENEWAL_DUE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    LAPSED = "LAPSED"


class CropType(str, Enum):
    HIGH_RISK = "HIGH_RISK"
    LOW_RISK = "LOW_RISK"
    NON_CROP = "NON_CROP"


class IngredientCompliance(str, Enum):
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLIANT = "COMPLIANT"
    EXEMPTED = "EXEMPTED"
    PENDING = "PENDING"


class AffidavitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RiskPoint(str, Enum):
    INGREDIENT_INTAKE = "INGREDIENT_INTAKE"
    IN_PROCESS = "IN_PROCESS"
    FINISHED_PRODUCT = "FINISHED_PRODUCT"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    RESULT_RECORDED = "RESULT_RECORDED"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"


class SampleOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SuspendReason(str, Enum):
    ENFORCEMENT = "ENFORCEMENT"
    SCOPE_CHANGE = "SCOPE_CHANGE"


class CaseSource(str, Enum):
    CONSUMER_COMPLAINT = "CONSUMER_COMPLAINT"
    MARKETPLACE_MONITOR = "MARKETPLACE_MONITOR"
    RETEST_FAILURE = "RETEST_FAILURE"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    DISMISSED = "DISMISSED"
    SUBSTANTIATED = "SUBSTANTIATED"


class Sanction(str, Enum):
    WARNING = "WARNING"
    LICENSE_SUSPENSION = "LICENSE_SUSPENSION"
    LICENSE_REVOCATION = "LICENSE_REVOCATION"


class StandingStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"


class ClaimStandard(TypedDict):
    id: str
    claim_code: str
    name: str
    ingredient_threshold_pct: float
    exemption_max_weight_pct: float
    audit_validity_months: int
    renewal_window_days: int
    license_term_days: int
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    name: str
    contact_email: str
    lifetime_penalty_points: int
    rolling_penalty_points: int
    standing_status: str
    verified_product_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    brand_id: str
    standard_id: str
    name: str
    gtin: str
    annual_volume_units: int
    enrollment_status: str
    rejection_reason: Optional[str]
    provisional_exposure_pct: float
    confirmed_exposure_pct: float
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict):
    id: str
    product_id: str
    name: str
    crop_type: str
    declared_weight_pct: float
    is_exempt: bool
    requires_pcr: bool
    requires_affidavit: bool
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class SupplierAffidavit(TypedDict):
    id: str
    ingredient_id: str
    supplier_name: str
    valid_from: str
    valid_until: str
    status: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SamplingPlan(TypedDict):
    id: str
    product_id: str
    risk_point: str
    required_sample_count: int
    confirmed_sample_count: int
    status: str
    superseded_by_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestSample(TypedDict):
    id: str
    sampling_plan_id: str
    ingredient_id: str
    result_gmo_pct: Optional[float]
    outcome: Optional[str]
    recorded_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FacilityAudit(TypedDict):
    id: str
    brand_id: str
    facility_name: str
    auditor_id: str
    scheduled_date: str
    lots: Optional[list]
    traceability_score_pct: Optional[float]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabelLicense(TypedDict):
    id: str
    product_id: str
    license_code: str
    valid_from: str
    valid_until: str
    suspended_at: Optional[str]
    suspend_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementCase(TypedDict):
    id: str
    product_id: str
    source: str
    description: str
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    sanction: Optional[str]
    penalty_points: int
    substantiated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
