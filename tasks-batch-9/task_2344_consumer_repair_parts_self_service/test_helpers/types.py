"""Domain types for the Consumer Repair Parts & Self-Service Repair Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SAFETY_REVIEWER = "SafetyReviewer"
    DOCUMENTATION_ENGINEER = "DocumentationEngineer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SELF_REPAIR_CUSTOMER = "SelfRepairCustomer"
    REPAIR_PROVIDER_TECH = "RepairProviderTech"
    FAILURE_ANALYSIS_ENGINEER = "FailureAnalysisEngineer"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------- #
# ProductModel
# --------------------------------------------------------------------------- #
class RepairabilityTier(str, Enum):
    TIER_A_SELF_SERVICE = "TIER_A_SELF_SERVICE"
    TIER_B_GUIDED = "TIER_B_GUIDED"
    TIER_C_AUTHORIZED_ONLY = "TIER_C_AUTHORIZED_ONLY"
    TIER_D_NON_SERVICEABLE = "TIER_D_NON_SERVICEABLE"


class SupportState(str, Enum):
    ACTIVE_PRODUCTION = "ACTIVE_PRODUCTION"
    LEGACY_SUPPORT = "LEGACY_SUPPORT"
    SUPPORT_ENDED = "SUPPORT_ENDED"


class DocumentationPosture(str, Enum):
    MISSING = "MISSING"
    STALE = "STALE"
    CURRENT = "CURRENT"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    ORDER_RESTRICTED = "ORDER_RESTRICTED"


class ProductModel(TypedDict):
    id: str
    model_code: str
    product_family: str
    market_release_date: str
    end_of_production_date: Optional[str]
    last_hardware_change_date: Optional[str]
    repairability_tier: str
    support_state: str
    support_end_date: Optional[str]
    documentation_posture: str
    published_disassembly_revision_number: Optional[int]
    published_safety_sheet_revision_number: Optional[int]
    compliance_posture: str
    open_obligation_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# RegionalComplianceProfile
# --------------------------------------------------------------------------- #
class SelfServiceMandateTier(str, Enum):
    MANDATE_NONE = "MANDATE_NONE"
    MANDATE_BASIC = "MANDATE_BASIC"
    MANDATE_FULL = "MANDATE_FULL"


class RegionalComplianceProfile(TypedDict):
    id: str
    region_code: str
    min_parts_availability_years: int
    min_documentation_years: int
    requires_public_manual: bool
    max_documentation_fee_cents: int
    allows_pairing_restriction: bool
    self_service_mandate_tier: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# ComplianceObligation
# --------------------------------------------------------------------------- #
class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    AT_RISK = "AT_RISK"
    BREACHED_PARTS = "BREACHED_PARTS"
    BREACHED_DOCUMENTATION = "BREACHED_DOCUMENTATION"
    ATTESTED = "ATTESTED"
    CLOSED = "CLOSED"


class DeadlineBasis(str, Enum):
    PRODUCTION_ACTIVE = "PRODUCTION_ACTIVE"
    END_OF_PRODUCTION = "END_OF_PRODUCTION"


class ComplianceObligation(TypedDict):
    id: str
    model_id: str
    region_code: str
    parts_available_until: Optional[str]
    documentation_available_until: Optional[str]
    deadline_basis: str
    status: str
    documentation_verified: bool
    last_attested_at: Optional[str]
    last_attested_by_user_id: Optional[str]
    breach_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# PartCatalogItem
# --------------------------------------------------------------------------- #
class PartClass(str, Enum):
    COMPONENT = "COMPONENT"
    TOOL = "TOOL"
    RENTAL_KIT = "RENTAL_KIT"
    CONSUMABLE = "CONSUMABLE"


class SafetyClass(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    SAFETY_RESTRICTED_BATTERY = "SAFETY_RESTRICTED_BATTERY"
    SAFETY_RESTRICTED_HIGH_VOLTAGE = "SAFETY_RESTRICTED_HIGH_VOLTAGE"
    PAIRED_SECURITY = "PAIRED_SECURITY"


class PartStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RESTRICTED = "RESTRICTED"
    SUPERSEDED = "SUPERSEDED"


class PartCatalogItem(TypedDict):
    id: str
    sku: str
    part_class: str
    safety_class: str
    list_price_cents: int
    core_return_required: bool
    core_credit_cents: int
    rental_deposit_cents: int
    concurrent_rental_capacity: Optional[int]
    requires_authentication: bool
    requires_calibration: bool
    supersedes_part_id: Optional[str]
    status: str
    restriction_reason: Optional[str]
    core_face_value_committed_cents: int
    core_liability_outstanding_cents: int
    core_credit_settled_cents: int
    core_credit_forfeited_cents: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# PartModelCompatibility
# --------------------------------------------------------------------------- #
class PartModelCompatibility(TypedDict):
    id: str
    part_id: str
    model_id: str
    required_tool_part_id: Optional[str]
    self_service_eligible: bool
    install_minutes: int
    effective_from: str
    effective_until: Optional[str]
    superseded_by_safety_restriction: bool
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# ManualRevision
# --------------------------------------------------------------------------- #
class DocType(str, Enum):
    DISASSEMBLY_GUIDE = "DISASSEMBLY_GUIDE"
    SAFETY_SHEET = "SAFETY_SHEET"
    CALIBRATION_PROCEDURE = "CALIBRATION_PROCEDURE"
    PARTS_LIST = "PARTS_LIST"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ManualRevision(TypedDict):
    id: str
    model_id: str
    doc_type: str
    revision_number: int
    covered_part_skus: List[str]
    safety_warning_count: int
    status: str
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    rejection_cycle_count: int
    effective_from: Optional[str]
    published_at: Optional[str]
    coverage_gap_sku_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# EligibilityAssessment
# --------------------------------------------------------------------------- #
class RequesterClass(str, Enum):
    SELF_REPAIR_CONSUMER = "SELF_REPAIR_CONSUMER"
    AUTHORIZED_PROVIDER = "AUTHORIZED_PROVIDER"


class EligibilityDecision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_TOOL_RENTAL = "ELIGIBLE_WITH_TOOL_RENTAL"
    BLOCKED_NO_COMPATIBILITY = "BLOCKED_NO_COMPATIBILITY"
    BLOCKED_PART_UNAVAILABLE = "BLOCKED_PART_UNAVAILABLE"
    BLOCKED_TIER = "BLOCKED_TIER"
    BLOCKED_SAFETY = "BLOCKED_SAFETY"
    BLOCKED_NO_MANUAL = "BLOCKED_NO_MANUAL"


class WarrantyImpactClass(str, Enum):
    WARRANTY_PRESERVED = "WARRANTY_PRESERVED"
    WARRANTY_PRESERVED_WITH_LOG = "WARRANTY_PRESERVED_WITH_LOG"
    WARRANTY_LIMITED_COMPONENT_EXCLUSION = "WARRANTY_LIMITED_COMPONENT_EXCLUSION"
    WARRANTY_VOID_AFFECTED_SUBSYSTEM = "WARRANTY_VOID_AFFECTED_SUBSYSTEM"


class AssessmentStatus(str, Enum):
    VALID = "VALID"
    REVOKED_BY_SAFETY = "REVOKED_BY_SAFETY"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class EligibilityAssessment(TypedDict):
    id: str
    model_id: str
    part_id: str
    provider_id: Optional[str]
    pinned_manual_revision_id: Optional[str]
    region_code: str
    requester_class: str
    requester_user_id: str
    decision: str
    warranty_impact_class: str
    self_repair_risk_index: int
    liability_warning_version: Optional[str]
    tool_rental_part_id: Optional[str]
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# PartsOrder
# --------------------------------------------------------------------------- #
class BuyerClass(str, Enum):
    SELF_REPAIR_CONSUMER = "SELF_REPAIR_CONSUMER"
    AUTHORIZED_PROVIDER = "AUTHORIZED_PROVIDER"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DISCLOSURE = "PENDING_DISCLOSURE"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    BLOCKED_SAFETY_HOLD = "BLOCKED_SAFETY_HOLD"
    CANCELLED = "CANCELLED"


class CoreReturnStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_CORE = "PENDING_CORE"
    CORE_RECEIVED = "CORE_RECEIVED"
    CORE_CREDIT_ISSUED = "CORE_CREDIT_ISSUED"
    CORE_FORFEITED = "CORE_FORFEITED"
    CORE_RELEASED = "CORE_RELEASED"


class CoreCondition(str, Enum):
    INTACT = "INTACT"
    DAMAGED_SHELL = "DAMAGED_SHELL"
    INCOMPLETE = "INCOMPLETE"
    NON_RETURNABLE = "NON_RETURNABLE"


class PartsOrder(TypedDict):
    id: str
    assessment_id: str
    model_id: str
    provider_id: Optional[str]
    pinned_manual_revision_id: Optional[str]
    region_code: str
    buyer_class: str
    customer_user_id: str
    rental_window_start: Optional[str]
    rental_window_end: Optional[str]
    fulfillment_status: str
    core_return_status: str
    pinned_manual_revision_number: Optional[int]
    warranty_impact_class: str
    parts_subtotal_cents: int
    tool_purchase_cents: int
    rental_deposit_cents: int
    documentation_fee_cents: int
    core_deposit_cents: int
    total_due_cents: int
    core_credit_provisional_cents: int
    core_credit_final_cents: Optional[int]
    core_return_due_at: Optional[str]
    core_days_late: Optional[int]
    disclosure_acknowledged_at: Optional[str]
    confirmed_at: Optional[str]
    delivered_at: Optional[str]
    blocked_reason: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# PartsOrderLine
# --------------------------------------------------------------------------- #
class AuthenticationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_AUTHENTICATION = "PENDING_AUTHENTICATION"
    AUTHENTIC = "AUTHENTIC"
    COUNTERFEIT_SUSPECT = "COUNTERFEIT_SUSPECT"


class CalibrationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CALIBRATION_REQUIRED = "CALIBRATION_REQUIRED"
    CALIBRATION_IN_PROGRESS = "CALIBRATION_IN_PROGRESS"
    CALIBRATION_PASSED = "CALIBRATION_PASSED"
    CALIBRATION_FAILED = "CALIBRATION_FAILED"
    CALIBRATION_ESCALATED = "CALIBRATION_ESCALATED"


class PartsOrderLine(TypedDict):
    id: str
    order_id: str
    part_id: str
    quantity: int
    buyer_multiplier: float
    volume_multiplier: float
    tier_surcharge_multiplier: float
    unit_price_cents: int
    line_total_cents: int
    authentication_status: str
    calibration_status: str
    calibration_attempt_count: int
    last_measured_offset_ppm: Optional[int]
    pairing_token: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# DisclosureAcknowledgment — append-only legal record (PRD §2.4):
# carries only id and created_at, no updated_at and no version.
# --------------------------------------------------------------------------- #
class AcknowledgedScope(str, Enum):
    FULL_SELF_REPAIR = "FULL_SELF_REPAIR"
    TOOL_RENTAL_ONLY = "TOOL_RENTAL_ONLY"
    PROVIDER_MANAGED = "PROVIDER_MANAGED"


class DisclosureAcknowledgment(TypedDict):
    id: str
    order_id: str
    warranty_impact_class_ack: str
    liability_warning_version: str
    acknowledged_scope: str
    acknowledged_by_user_id: str
    manual_revision_number: Optional[int]
    acknowledged_at: str
    created_at: str


# --------------------------------------------------------------------------- #
# RepairProvider
# --------------------------------------------------------------------------- #
class PartsAccessTier(str, Enum):
    TIER_1_UNRESTRICTED = "TIER_1_UNRESTRICTED"
    TIER_2_SAFETY = "TIER_2_SAFETY"
    TIER_3_STANDARD = "TIER_3_STANDARD"


class AuthorizationStatus(str, Enum):
    APPLIED = "APPLIED"
    TRAINING_IN_PROGRESS = "TRAINING_IN_PROGRESS"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RepairProvider(TypedDict):
    id: str
    legal_name: str
    region_code: str
    requested_access_tier: str
    technician_count: int
    authorization_status: str
    parts_access_tier: Optional[str]
    training_credit_granted_total: int
    training_credit_balance: int
    training_credit_forfeited_total: int
    required_cert_count: int
    active_cert_count: int
    attested_compliance_score: Optional[int]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# TrainingCertification
# --------------------------------------------------------------------------- #
class CourseCode(str, Enum):
    CRS_BATTERY_SAFETY = "CRS_BATTERY_SAFETY"
    CRS_HIGH_VOLTAGE = "CRS_HIGH_VOLTAGE"
    CRS_PAIRING_CALIBRATION = "CRS_PAIRING_CALIBRATION"
    CRS_GENERAL_REPAIR = "CRS_GENERAL_REPAIR"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class TrainingCertification(TypedDict):
    id: str
    provider_id: str
    technician_user_id: str
    course_code: str
    valid_from: str
    valid_until: str
    exam_score: int
    status: str
    credits_consumed: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# DefectiveReturnCase
# --------------------------------------------------------------------------- #
class ReportedFailureCode(str, Enum):
    NO_POWER = "NO_POWER"
    INTERMITTENT = "INTERMITTENT"
    PHYSICAL_DAMAGE = "PHYSICAL_DAMAGE"
    CALIBRATION_DRIFT = "CALIBRATION_DRIFT"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"


class RootCauseCode(str, Enum):
    MANUFACTURING_DEFECT = "MANUFACTURING_DEFECT"
    PROVIDER_INSTALL_ERROR = "PROVIDER_INSTALL_ERROR"
    CUSTOMER_MISUSE = "CUSTOMER_MISUSE"
    PART_AUTHENTICATION_FAILURE = "PART_AUTHENTICATION_FAILURE"
    UNDETERMINED = "UNDETERMINED"


class ReturnCaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REJECTED = "REJECTED"


class DefectiveReturnCase(TypedDict):
    id: str
    order_line_id: str
    part_id: str
    quantity: int
    reported_failure_code: str
    status: str
    root_cause_code: Optional[str]
    defect_confirmed: Optional[bool]
    analyzed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Computed-read variants
# --------------------------------------------------------------------------- #
class ScoreVariant(str, Enum):
    ROLLING_ATTESTED = "ROLLING_ATTESTED"
    LIVE_RECOMPUTE = "LIVE_RECOMPUTE"


class ForecastVariant(str, Enum):
    TRAILING_ONLY = "TRAILING_ONLY"
    PIPELINE_WEIGHTED = "PIPELINE_WEIGHTED"


class ObsolescenceBand(str, Enum):
    CURRENT = "CURRENT"
    LEGACY = "LEGACY"
    LONG_TAIL = "LONG_TAIL"
