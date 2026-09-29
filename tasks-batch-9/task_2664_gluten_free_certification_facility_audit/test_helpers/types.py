"""Entity shapes, enumerations and role names for the gluten-free certification API."""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is optional
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role:
    APPLICANT_CONTACT = "ApplicantContact"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    FIELD_AUDITOR = "FieldAuditor"
    CERTIFICATION_DECISION_MAKER = "CertificationDecisionMaker"
    LAB_TECHNICIAN = "LabTechnician"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"


ALL_ROLES = (
    Role.APPLICANT_CONTACT,
    Role.CERTIFICATION_REVIEWER,
    Role.FIELD_AUDITOR,
    Role.CERTIFICATION_DECISION_MAKER,
    Role.LAB_TECHNICIAN,
    Role.PROGRAM_ADMINISTRATOR,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class CompliancePosture:
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AirHandlingClass:
    OPEN_PLENUM = "OPEN_PLENUM"
    FILTERED_ZONED = "FILTERED_ZONED"
    DEDICATED_NEGATIVE_PRESSURE = "DEDICATED_NEGATIVE_PRESSURE"


class GlutenContainingOperations:
    NONE = "NONE"
    ADJACENT_LINES = "ADJACENT_LINES"
    SAME_LINE = "SAME_LINE"


class SanitationStatus:
    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"
    EXPIRED = "EXPIRED"


class SupplierStatus:
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"


class DocType:
    ALLERGEN_STATEMENT = "ALLERGEN_STATEMENT"
    PROCESS_FLOW = "PROCESS_FLOW"
    COA = "COA"
    GF_CERTIFICATE_OF_ORIGIN = "GF_CERTIFICATE_OF_ORIGIN"


class DocRejectionReason:
    ILLEGIBLE = "ILLEGIBLE"
    PPM_ABOVE_LIMIT = "PPM_ABOVE_LIMIT"
    EXPIRED_ON_SUBMISSION = "EXPIRED_ON_SUBMISSION"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"


class IngredientRejectionReason:
    DOCS_INSUFFICIENT = "DOCS_INSUFFICIENT"
    PPM_CLAIM_TOO_HIGH = "PPM_CLAIM_TOO_HIGH"
    SUPPLIER_UNDISCLOSED_GLUTEN = "SUPPLIER_UNDISCLOSED_GLUTEN"


class BlockedReason:
    SUPPLIER_SUSPENDED = "SUPPLIER_SUSPENDED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    DOCUMENT_EXPIRED = "DOCUMENT_EXPIRED"
    SUB_COMPONENT_BLOCKED = "SUB_COMPONENT_BLOCKED"


class LabelRejectionReason:
    MARK_PLACEMENT_INVALID = "MARK_PLACEMENT_INVALID"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    MISSING_CERT_NUMBER = "MISSING_CERT_NUMBER"
    TIER_MISMATCH = "TIER_MISMATCH"


class CaRejectionReason:
    INSUFFICIENT_ROOT_CAUSE = "INSUFFICIENT_ROOT_CAUSE"
    NO_VERIFICATION_EVIDENCE = "NO_VERIFICATION_EVIDENCE"
    TIMELINE_TOO_LONG = "TIMELINE_TOO_LONG"


class AssayMethod:
    R5_ELISA = "R5_ELISA"
    G12_ELISA = "G12_ELISA"
    COMPETITIVE_ELISA = "COMPETITIVE_ELISA"


class DocumentStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RiskClass:
    INHERENTLY_GF = "INHERENTLY_GF"
    GF_PROCESSED = "GF_PROCESSED"
    HIGH_RISK_GRAIN = "HIGH_RISK_GRAIN"


class IngredientStatus:
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class FormulaStatus:
    DRAFT = "DRAFT"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class LabelStatus:
    NOT_SUBMITTED = "NOT_SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FROZEN = "FROZEN"


class TestingPlanStatus:
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class MarkTier:
    NONE = "NONE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ELITE = "ELITE"


class LotTestType:
    SCHEDULED = "SCHEDULED"
    UNANNOUNCED = "UNANNOUNCED"
    FOR_CAUSE = "FOR_CAUSE"


class LotTestStatus:
    RECORDED = "RECORDED"
    SUPERSEDED_BY_RETEST = "SUPERSEDED_BY_RETEST"


class Verdict:
    PASS = "PASS"
    FAIL = "FAIL"


class AuditType:
    INITIAL = "INITIAL"
    SURVEILLANCE = "SURVEILLANCE"
    FOR_CAUSE = "FOR_CAUSE"


class AuditStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_CONDITIONAL = "CLOSED_CONDITIONAL"
    CLOSED_FAIL = "CLOSED_FAIL"
    CANCELLED = "CANCELLED"


class NcCategory:
    SHARED_EQUIPMENT = "SHARED_EQUIPMENT"
    AIR_HANDLING = "AIR_HANDLING"
    SANITATION = "SANITATION"
    DOCUMENTATION = "DOCUMENTATION"
    LABELING = "LABELING"
    THRESHOLD_EXCEEDANCE = "THRESHOLD_EXCEEDANCE"


class NcSeverity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class NcStatus:
    OPEN = "OPEN"
    CA_SUBMITTED = "CA_SUBMITTED"
    CA_ACCEPTED = "CA_ACCEPTED"
    CA_REJECTED = "CA_REJECTED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


#: Statuses that keep a finding charging penalty points against the applicant.
OPEN_NC_STATUSES = (
    NcStatus.OPEN,
    NcStatus.CA_SUBMITTED,
    NcStatus.CA_REJECTED,
    NcStatus.ESCALATED,
)


class NcSourceType:
    AUDIT = "AUDIT"
    LOT_TEST = "LOT_TEST"
    COMPLAINT = "COMPLAINT"
    CHANGE_NOTIFICATION = "CHANGE_NOTIFICATION"
    SURVEILLANCE_RUN = "SURVEILLANCE_RUN"


class CertificateStatus:
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SurveillanceStatus:
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class SuspensionReason:
    FAILED_UNANNOUNCED_TEST = "FAILED_UNANNOUNCED_TEST"
    SURVEILLANCE_OVERDUE = "SURVEILLANCE_OVERDUE"
    CRITICAL_NONCONFORMANCE = "CRITICAL_NONCONFORMANCE"
    INGREDIENT_BLOCKED = "INGREDIENT_BLOCKED"
    SUBSTANTIATED_COMPLAINT = "SUBSTANTIATED_COMPLAINT"
    CHANGE_REQUIRES_RECERT = "CHANGE_REQUIRES_RECERT"


class RevocationReason:
    VOLUNTARY_WITHDRAWAL = "VOLUNTARY_WITHDRAWAL"
    UNRESOLVED_NONCONFORMANCE = "UNRESOLVED_NONCONFORMANCE"
    REPEAT_FAILURE = "REPEAT_FAILURE"
    FRAUD = "FRAUD"


class ChangeType:
    INGREDIENT_SUBSTITUTION = "INGREDIENT_SUBSTITUTION"
    SUPPLIER_CHANGE = "SUPPLIER_CHANGE"
    FORMULA_PCT_CHANGE = "FORMULA_PCT_CHANGE"
    FACILITY_LINE_CHANGE = "FACILITY_LINE_CHANGE"


class ChangeNotificationStatus:
    SUBMITTED = "SUBMITTED"
    ACCEPTED_NO_IMPACT = "ACCEPTED_NO_IMPACT"
    ACCEPTED_WITH_CONDITIONS = "ACCEPTED_WITH_CONDITIONS"
    REJECTED_REQUIRES_RECERT = "REJECTED_REQUIRES_RECERT"


class ImpactLevel:
    NONE = "NONE"
    LOW = "LOW"
    HIGH = "HIGH"


class SymptomSeverity:
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    ANAPHYLAXIS = "ANAPHYLAXIS"


class ComplaintStatus:
    RECEIVED = "RECEIVED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    RECALL_COORDINATION = "RECALL_COORDINATION"
    CLOSED = "CLOSED"


class OutcomeEvidence:
    LOT_TEST_FAILURE = "LOT_TEST_FAILURE"
    LABEL_ERROR = "LABEL_ERROR"
    CROSS_CONTACT = "CROSS_CONTACT"
    NO_EVIDENCE = "NO_EVIDENCE"


class TriagePriority:
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ComplaintOutcome:
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class RecallAction:
    ADVISORY_ONLY = "ADVISORY_ONLY"
    VOLUNTARY_RECALL = "VOLUNTARY_RECALL"
    MANDATORY_RECALL_SUPPORT = "MANDATORY_RECALL_SUPPORT"


class Decision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CLEAR = "CLEAR"
    ACCEPT = "ACCEPT"


# ---------------------------------------------------------------------------
# Entity shapes (loose TypedDicts: reads are asserted field-by-field)
# ---------------------------------------------------------------------------
class Applicant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    country_code: str
    compliance_posture: str
    posture_score_cycle: int
    posture_score_rolling_12m: int
    open_nc_penalty_points: int
    active_certified_product_count: int
    suspended_certificate_count: int
    revoked_certificate_count: int
    substantiated_complaint_count_rolling: int
    substantiated_complaint_count_cycle: int
    fee_balance_cents: int
    current_cycle_started_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    applicant_id: str
    site_name: str
    air_handling_class: str
    shared_equipment_present: bool
    gluten_containing_operations: str
    sanitation_validation_status: str
    sanitation_method: Optional[str]
    sanitation_swab_ppm: Optional[float]
    sanitation_validated_on: Optional[str]
    sanitation_expires_on: Optional[str]
    last_closed_audit_outcome: str
    last_closed_audit_closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    gluten_handling_disclosed: bool
    status: str
    verified_document_count: int


class SupplierDocument(TypedDict, total=False):
    id: str
    supplier_id: str
    ingredient_id: str
    doc_type: str
    issued_on: str
    expires_on: str
    lab_ppm_claim: Optional[float]
    status: str
    verified_on: Optional[str]
    verified_by_user_id: Optional[str]


class Ingredient(TypedDict, total=False):
    id: str
    applicant_id: str
    supplier_id: str
    parent_ingredient_id: Optional[str]
    name: str
    risk_class: str
    status: str
    verified_doc_types: List[str]
    approved_on: Optional[str]
    review_cycle_count: int
    blocked_reason: Optional[str]
    rejection_reason: Optional[str]
    reviewed_by_user_id: Optional[str]


class Product(TypedDict, total=False):
    id: str
    applicant_id: str
    facility_id: str
    name: str
    sku: str
    requested_mark_tier: str
    mark_tier_granted: str
    formula_status: str
    label_status: str
    testing_plan_status: str
    testing_plan_revision: int
    threshold_ppm: Optional[int]
    sampling_lots_per_year: Optional[int]
    sampling_exclusion_days: Optional[int]
    linked_ingredient_count: int
    blocked_ingredient_count: int
    last_scheduled_sample_on: Optional[str]
    formula_cleared_by_user_id: Optional[str]
    label_reviewed_by_user_id: Optional[str]
    label_rejection_reason: Optional[str]
    version: int


class ProductIngredient(TypedDict, total=False):
    id: str
    product_id: str
    ingredient_id: str
    inclusion_pct: float
    is_risk_carrier: bool
    created_at: str


class LotTest(TypedDict, total=False):
    id: str
    product_id: str
    lot_code: str
    test_type: str
    sample_collected_on: str
    ppm_result: float
    lab_method: str
    threshold_applied_ppm: int
    verdict: str
    status: str
    in_recall_scope: bool


class Audit(TypedDict, total=False):
    id: str
    facility_id: str
    audit_type: str
    onsite_start_at: str
    onsite_end_at: str
    status: str
    lead_auditor_user_id: Optional[str]
    provisional_score: Optional[int]
    final_score: Optional[int]
    finding_count: int
    critical_finding_count: int
    shared_equipment_verified: Optional[bool]
    air_handling_verified: Optional[bool]
    sanitation_validation_reviewed: Optional[bool]
    closed_on: Optional[str]
    closed_by_user_id: Optional[str]


class Certificate(TypedDict, total=False):
    id: str
    product_id: str
    applicant_id: str
    status: str
    mark_tier_granted: str
    certified_threshold_ppm: int
    issued_on: str
    expires_on: str
    surveillance_due_on: str
    surveillance_status: str
    suspension_count: int
    suspended_on: Optional[str]
    suspension_reason: Optional[str]
    revoked_on: Optional[str]
    revocation_reason: Optional[str]
    mark_usage_locked: bool
    base_fee_cents: int
    surveillance_surcharge_cents: int
    total_fee_cents: int
    fee_charged: bool
    fee_refunded: bool
    issued_by_user_id: str


class Nonconformance(TypedDict, total=False):
    id: str
    applicant_id: str
    source_type: str
    category: str
    severity: str
    description: str
    status: str
    penalty_points: int
    certificate_id: Optional[str]
    audit_id: Optional[str]
    lot_test_id: Optional[str]
    complaint_id: Optional[str]
    raised_by_user_id: str
    ca_plan_text: Optional[str]
    ca_due_on: str
    ca_revision_count: int
    ca_decided_by_user_id: Optional[str]
    ca_rejection_reason: Optional[str]
    ca_verified: bool
    closed_on: Optional[str]
    version: int


class ChangeNotification(TypedDict, total=False):
    id: str
    certificate_id: str
    change_type: str
    effective_on: str
    description: str
    replacement_ingredient_id: Optional[str]
    status: str
    impact_level: Optional[str]
    required_retest: bool
    notified_days_before_effective: int
    late_notification: bool
    assessed_by_user_id: Optional[str]
    assessed_on: Optional[str]


class ConsumerComplaint(TypedDict, total=False):
    id: str
    certificate_id: str
    exposure_date: str
    symptom_severity: str
    lot_code: Optional[str]
    status: str
    reported_on: str
    triage_priority: Optional[str]
    recall_scope_lot_codes: List[str]
    recall_action: str
    outcome_evidence: Optional[str]
    investigated_by_user_id: Optional[str]
    closed_on: Optional[str]


SweepResult = Dict[str, Any]
