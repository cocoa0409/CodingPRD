"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    REGULATORY_AFFAIRS = "REGULATORY_AFFAIRS"
    QA_MANAGER = "QA_MANAGER"
    QUALITY_ANALYST = "QUALITY_ANALYST"
    PRODUCTION_SUPERVISOR = "PRODUCTION_SUPERVISOR"
    SUPPLY_CHAIN_PLANNER = "SUPPLY_CHAIN_PLANNER"
    COMPLAINT_HANDLER = "COMPLAINT_HANDLER"


class NutrientProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class SupplierStatus(str, Enum):
    PENDING_AUDIT = "PENDING_AUDIT"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class AuditResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class RiskRating(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LotQcStatus(str, Enum):
    PENDING_QC = "PENDING_QC"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    QUARANTINED = "QUARANTINED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    BLENDING_COMPLETE = "BLENDING_COMPLETE"
    PROCESSING_COMPLETE = "PROCESSING_COMPLETE"
    TESTING = "TESTING"
    POSITIVE_RELEASE_HOLD = "POSITIVE_RELEASE_HOLD"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class ValidationStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    NOTIFIED = "NOTIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class RecallScopeStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    RECOVERED = "RECOVERED"
    VERIFIED = "VERIFIED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class EntryStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    SHORTFALL = "SHORTFALL"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---

class NutrientProfile(TypedDict, total=False):
    id: str
    profile_code: str
    nutrient_specs: List[dict]
    regulation_ref: str
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    supplier_code: str
    legal_name: str
    ingredient_categories: List[str]
    qualification_status: str
    last_audit_date: Optional[str]
    next_audit_due: Optional[str]
    audit_frequency_days: int
    risk_rating: str
    created_at: str
    updated_at: str
    version: int


class AuditRecord(TypedDict, total=False):
    id: str
    supplier_id: str
    audit_type: str
    audit_date: str
    auditor_name: str
    score: float
    findings: List[dict]
    capa_deadline: Optional[str]
    result: str
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    ingredient_code: str
    ingredient_name: str
    category: str
    pathogen_risk_class: str
    storage_condition: str
    allergen_flags: List[str]
    created_at: str
    updated_at: str
    version: int


class IngredientLot(TypedDict, total=False):
    id: str
    ingredient_id: str
    supplier_id: str
    lot_number: str
    quantity_kg: float
    remaining_kg: float
    received_date: str
    expiry_date: str
    qc_status: str
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    formula_code: str
    product_name: str
    nutrient_profile_id: str
    ingredients: List[dict]
    process_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    formula_id: str
    batch_number: str
    batch_size_kg: float
    actual_yield_kg: Optional[float]
    status: str
    production_date: str
    expiry_date: Optional[str]
    ingredient_consumptions: List[dict]
    nutrient_results: Optional[List[dict]]
    pathogen_results: Optional[List[dict]]
    release_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcessValidation(TypedDict, total=False):
    id: str
    formula_id: str
    validation_type: str
    status: str
    protocol_version: str
    started_at: Optional[str]
    completed_at: Optional[str]
    test_results: Optional[List[dict]]
    valid_until: Optional[str]
    validation_validity_days: int
    created_at: str
    updated_at: str
    version: int


class LabelSubmission(TypedDict, total=False):
    id: str
    formula_id: str
    submission_type: str
    label_text: str
    claims: List[str]
    status: str
    reviewer_id: Optional[str]
    review_comments: Optional[List[dict]]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    complaint_ref: str
    complainant_name: str
    complainant_contact: str
    product_formula_id: str
    batch_id: Optional[str]
    complaint_type: str
    severity: str
    description: str
    status: str
    is_adverse_event: bool
    escalated_at: Optional[str]
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallCampaign(TypedDict, total=False):
    id: str
    recall_ref: str
    reason: str
    recall_class: str
    scope_description: str
    status: str
    initiated_by: str
    initiated_at: str
    completed_at: Optional[str]
    effectiveness_checks: Optional[List[dict]]
    created_at: str
    updated_at: str
    version: int


class RecallScope(TypedDict, total=False):
    id: str
    recall_id: str
    batch_id: str
    withdrawal_level: str
    status: str
    quantity_shipped_kg: float
    quantity_recovered_kg: float
    recovery_pct: float
    created_at: str
    updated_at: str
    version: int


class AllocationPlan(TypedDict, total=False):
    id: str
    plan_ref: str
    formula_id: str
    total_available_kg: float
    allocation_method: str
    status: str
    activated_at: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationEntry(TypedDict, total=False):
    id: str
    plan_id: str
    customer_code: str
    customer_name: str
    requested_kg: float
    priority_tier: Optional[int]
    allocated_kg: float
    fulfilled_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


# SystemUser is the sole exception to the common-fields convention (PRD §2.4):
# it carries only id and created_at — no updated_at, no version.
class SystemUser(TypedDict, total=False):
    id: str
    username: str
    full_name: str
    role: str
    department: str
    created_at: str
