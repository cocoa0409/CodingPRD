"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SPEC_AUTHOR = "SpecAuthor"
    QUALITY_MANAGER = "QualityManager"
    PROCUREMENT_MANAGER = "ProcurementManager"
    SUPPLIER_QUALITY_ENGINEER = "SupplierQualityEngineer"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    PLATFORM_ADMIN = "PlatformAdmin"


class IngredientStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class IngredientSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class Allergen(str, Enum):
    MILK = "MILK"
    EGG = "EGG"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"
    TREE_NUT = "TREE_NUT"
    PEANUT = "PEANUT"
    WHEAT = "WHEAT"
    SOY = "SOY"
    SESAME = "SESAME"
    NONE = "NONE"


class SupplierStatus(str, Enum):
    PROSPECT = "PROSPECT"
    IN_QUALIFICATION = "IN_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class RiskTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class QualificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovedSourceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    COA_RISK = "COA_RISK"
    SUPPLIER_SUSPENDED = "SUPPLIER_SUSPENDED"
    MANUAL = "MANUAL"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CoAStatus(str, Enum):
    REGISTERED = "REGISTERED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    CONDITIONALLY_ACCEPTED = "CONDITIONALLY_ACCEPTED"
    REJECTED = "REJECTED"


class FindingDisposition(str, Enum):
    REPORTED = "REPORTED"
    ACCEPT_AS_IS = "ACCEPT_AS_IS"
    DOWNGRADED_TO_MINOR = "DOWNGRADED_TO_MINOR"
    REJECT_LOT = "REJECT_LOT"


class DeclarationType(str, Enum):
    ALLERGEN = "ALLERGEN"
    COUNTRY_OF_ORIGIN = "COUNTRY_OF_ORIGIN"


class DeclarationStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    PENDING_REGULATORY = "PENDING_REGULATORY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class ReasonCode(str, Enum):
    SUPPLY_SHORTAGE = "SUPPLY_SHORTAGE"
    COST_REDUCTION = "COST_REDUCTION"
    QUALITY_ESCAPE = "QUALITY_ESCAPE"
    DUAL_SOURCE_BREACH = "DUAL_SOURCE_BREACH"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_ISSUED = "REPORT_ISSUED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CadenceSource(str, Enum):
    TIER_CADENCE = "TIER_CADENCE"
    ESCALATED = "ESCALATED"


class CapaStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts -------------------------------------------------------
# All entities carry id + created_at + updated_at + version, except the
# immutable price-index observation log, which carries only id + created_at
# (PRD §2.4).

class Ingredient(TypedDict, total=False):
    id: str
    ingredient_code: str
    name: str
    allergen_profile: List[str]
    requires_dual_source: bool
    status: str
    active_spec_id: Optional[str]
    current_dual_source_breach: bool
    created_at: str
    updated_at: str
    version: int


class IngredientSpec(TypedDict, total=False):
    id: str
    ingredient_id: str
    spec_version_label: str
    supersedes_spec_id: Optional[str]
    effective_date: str
    author_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    version_note: str
    created_at: str
    updated_at: str
    version: int


class SpecParameter(TypedDict, total=False):
    id: str
    spec_id: str
    parameter_name: str
    criticality: str
    uom: str
    target_value: float
    min_value: float
    max_value: float
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    supplier_code: str
    legal_name: str
    risk_tier: str
    country_of_operation: str
    status: str
    composite_risk_score: float
    last_audit_closed_at: Optional[str]
    open_overdue_capa_count: int
    requalification_cycle: int
    created_at: str
    updated_at: str
    version: int


class SupplierQualification(TypedDict, total=False):
    id: str
    supplier_id: str
    questionnaire_score: int
    document_pack_complete: bool
    decision_note: Optional[str]
    status: str
    evaluated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovedSource(TypedDict, total=False):
    id: str
    ingredient_id: str
    supplier_id: str
    pinned_spec_id: str
    approved_by_user_id: Optional[str]
    status: str
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    approved_source_id: str
    annual_committed_volume_kg: int
    index_base_value: float
    index_pass_through_pct: float
    window_start: str
    window_end: str
    status: str
    cumulative_shipped_kg: int
    created_at: str
    updated_at: str
    version: int


class PriceIndexObservation(TypedDict, total=False):
    # Append-only log: id + created_at only — NO updated_at, NO version (PRD §2.4).
    id: str
    index_name: str
    observed_at: str
    index_value: float
    created_at: str


class CertificateOfAnalysis(TypedDict, total=False):
    id: str
    approved_source_id: str
    contract_id: str
    lot_number: str
    shipped_qty_kg: int
    received_at: str
    measured_values: List[Dict[str, Any]]
    registered_by_user_id: str
    provisional_deviation_score: float
    final_deviation_score: Optional[float]
    unit_price_applied: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoAOutOfSpecFinding(TypedDict, total=False):
    id: str
    coa_id: str
    parameter_name: str
    observed_value: float
    violated_bound: float
    excess_ratio: float
    criticality_at_finding: str
    disposition: str
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryDeclaration(TypedDict, total=False):
    id: str
    approved_source_id: str
    declaration_type: str
    payload: Dict[str, Any]
    valid_from: str
    valid_until: str
    collected_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    ingredient_id: str
    from_approved_source_id: str
    to_approved_source_id: str
    reason_code: str
    formula_unit_cost_sensitivities: List[Dict[str, Any]]
    requested_by_user_id: str
    impact_delta_per_unit: Optional[float]
    requires_regulatory_signoff: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulaImpactAssessment(TypedDict, total=False):
    id: str
    substitution_request_id: str
    parameter_deltas: List[Dict[str, Any]]
    total_delta_per_unit: float
    allergen_delta_tags: List[str]
    coo_changed: bool
    created_at: str
    updated_at: str
    version: int


class SupplierAudit(TypedDict, total=False):
    id: str
    supplier_id: str
    scheduled_window_start: str
    scheduled_window_end: str
    audit_score: Optional[int]
    findings_summary: Optional[str]
    cadence_source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    audit_id: str
    description: str
    due_date: str
    response_text: Optional[str]
    verification_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
