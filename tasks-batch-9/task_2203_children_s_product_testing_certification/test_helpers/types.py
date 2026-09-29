"""Entity shapes, enum vocabularies and role names for the compliance API."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    COMPLIANCE_ADMINISTRATOR = "ComplianceAdministrator"
    TEST_COORDINATOR = "TestCoordinator"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    DISTRIBUTION_MANAGER = "DistributionManager"
    LABORATORY_USER = "LaboratoryUser"
    SUPPLIER_USER = "SupplierUser"


ALL_ROLES: List[str] = [r.value for r in Role]


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------

HAZARD_CLASSES = [
    "LEAD_PAINT",
    "LEAD_CONTENT",
    "PHTHALATES",
    "MECHANICAL_HAZARD",
    "FLAMMABILITY",
]

LIMIT_UNITS = ["PPM", "PERCENT_BY_WEIGHT", "NEWTON", "MILLIMETRE"]

LIMIT_COMPARATORS = ["AT_OR_BELOW", "AT_OR_ABOVE"]

APPLICABILITY_CONDITIONS = [
    "ALWAYS",
    "IF_PAINTED_SURFACE",
    "IF_PLASTICIZED_PART",
    "IF_SMALL_PART_PRESENT",
    "IF_ACCESSIBLE_METAL",
]

MAPPING_STATES = ["ACTIVE", "RETIRED"]

RELIANCE_AGREEMENT_STATES = ["NOT_ON_FILE", "ON_FILE"]

INDEPENDENCE_CLASSES = ["INDEPENDENT", "FIREWALLED_GOVERNMENT", "MANUFACTURER_OWNED"]

LAB_OPERATIONAL_STATES = ["ACTIVE", "BARRED"]

INFLUENCE_ATTESTATION_STATES = ["MISSING", "CURRENT", "EXPIRED"]

ACCREDITATION_STATES = ["ACCREDITED", "SUSPENDED", "EXPIRED"]

CERTIFICATION_STATES = [
    "DRAFT",
    "SCOPED",
    "EVIDENCE_RELIANCE",
    "FULL_TEST_PROGRAM",
    "EVIDENCE_COMPLETE",
    "CERTIFIED",
    "SUSPENDED",
    "REMEDIATION",
    "ARCHIVED",
]

EVIDENCE_PATHS = ["COMPONENT_RELIANCE", "FULL_PRODUCT_TEST"]

COMPLIANCE_POSTURES = ["UNSCOPED", "CLEARED", "RESTRICTED", "SUSPENDED"]

MATERIAL_CLASSES = [
    "PAINTED_COATING",
    "PLASTICIZED_PLASTIC",
    "ACCESSIBLE_METAL",
    "TEXTILE",
    "RIGID_UNPAINTED_PLASTIC",
]

PART_RELIANCE_STATUSES = ["PENDING", "VALID", "SUPERSEDED"]

PART_CERTIFICATE_STATES = ["SUBMITTED", "RELIED_UPON", "REJECTED", "RELIANCE_VOID"]

PLAN_TYPES = ["INITIAL", "PERIODIC"]

PLAN_STATES = ["DRAFT", "ACTIVE", "RESAMPLE_DUE", "LAPSED", "SUPERSEDED"]

RESAMPLE_TRIGGERS = ["NONE", "PERIODIC_INTERVAL", "MATERIAL_CHANGE", "RELIANCE_VOID"]

ORDER_STATES = [
    "SCHEDULED",
    "IN_TESTING",
    "REPORTED_PASS",
    "REPORTED_FAIL",
    "CANCELLED",
    "INVALIDATED",
]

TEST_RESULTS = ["PASS", "FAIL"]

ISSUANCE_STATUSES = ["DRAFT", "ISSUED", "SUPERSEDED", "WITHDRAWN", "VOIDED"]

ACCOMPANIMENT_STATUSES = ["NOT_FURNISHED", "FURNISHED", "RECALLED_FROM_SHIPMENTS"]

DISTRIBUTION_STATES = ["HELD", "RELEASED", "STOP_DISTRIBUTION", "DESTROYED"]

CASE_STATES = [
    "OPEN",
    "STOP_DISTRIBUTION_ISSUED",
    "RETEST_ORDERED",
    "RETEST_FAILED",
    "RETEST_PASSED",
    "CORRECTIVE_ACTION_APPROVED",
    "CLOSED",
    "ESCALATED_RECALL",
]

SCOPE_VARIANTS = ["BATCH_SCOPED", "LOT_TRACEBACK"]

SUBJECT_TYPES = ["PRODUCT", "COMPONENT_PART"]

CHANGE_KINDS = [
    "SUPPLIER_SWITCH",
    "MATERIAL_SUBSTITUTION",
    "COATING_CHANGE",
    "DESIGN_GEOMETRY_CHANGE",
    "PACKAGING_ONLY",
]

RELIANCE_DECISIONS = ["RELY", "REJECT"]


# ---------------------------------------------------------------------------
# Entity shapes.  Every entity carries id/created_at/updated_at/version except
# MaterialChangeEvent, which carries only id and created_at (PRD 2.4).
# ---------------------------------------------------------------------------


class AuditedEntity(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ApplicableRule(AuditedEntity):
    rule_code: str
    hazard_class: str
    test_method_code: str
    limit_value: float
    limit_unit: str
    limit_comparator: str
    periodic_interval_months: int
    base_method_fee_cents: int
    component_reliance_allowed: bool
    severity_weight: int


class ProductCategory(AuditedEntity):
    category_code: str
    display_name: str
    durable_infant_product: bool
    intended_age_max_months: int
    sampling_floor_units: int


class CategoryRuleMapping(AuditedEntity):
    category_id: str
    rule_id: str
    applicability_condition: str
    effective_from: str
    mapping_state: str


class Supplier(AuditedEntity):
    legal_name: str
    country_code: str
    reliance_agreement_state: str
    certificates_issued_count: int


class Laboratory(AuditedEntity):
    lab_name: str
    accreditation_body_code: str
    independence_class: str
    operational_state: str
    influence_attestation_state: str
    influence_attestation_valid_through: Optional[str]
    concurrent_slot_capacity: int
    billed_fee_cents_total: int
    credited_fee_cents_total: int


class LabAccreditation(AuditedEntity):
    laboratory_id: str
    rule_id: str
    test_method_code: str
    valid_from: str
    valid_through: str
    accreditation_state: str
    suspension_reason: Optional[str]
    fee_surcharge_basis_points: int


class Product(AuditedEntity):
    category_id: str
    model_name: str
    manufacture_site_code: str
    projected_annual_units: int
    testing_budget_cents: int
    certification_state: str
    evidence_path: Optional[str]
    compliance_posture: str
    required_rule_ids: List[str]
    risk_weighted_gap_score: int
    units_held: int
    units_released: int
    units_stopped: int
    units_destroyed: int
    material_change_count: int


class ComponentPart(AuditedEntity):
    product_id: str
    supplier_id: str
    part_name: str
    material_class: str
    accessible_to_child: bool
    small_part_when_detached: bool
    reliance_status: str
    last_material_change_at: Optional[str]


class ComponentPartCertificate(AuditedEntity):
    component_part_id: str
    supplier_id: str
    laboratory_id: str
    rule_id: str
    measured_value: float
    coverage_from: str
    coverage_through: str
    reliance_state: str
    reliance_documentation_ref: Optional[str]
    reliance_recorded_by_user_id: Optional[str]


class SamplingPlan(AuditedEntity):
    product_id: str
    plan_type: str
    baseline_units_produced: int
    units_authorized: int
    units_committed: int
    units_available: int
    plan_state: str
    activated_at: Optional[str]
    last_verified_at: Optional[str]
    periodic_due_at: Optional[str]
    resample_trigger: str
    resample_grace_days: int


class TestOrder(AuditedEntity):
    product_id: str
    sampling_plan_id: str
    laboratory_id: str
    rule_id: str
    sample_count: int
    window_start: str
    window_end: str
    order_state: str
    ordered_by_user_id: str
    is_retest: bool
    retest_case_id: Optional[str]
    line_fee_cents: int
    invoice_total_cents: int
    expedite_requested: bool
    measured_value: Optional[float]
    result: Optional[str]
    reported_at: Optional[str]
    reported_by_user_id: Optional[str]


class ChildrensProductCertificate(AuditedEntity):
    product_id: str
    supersedes_certificate_id: Optional[str]
    issuance_status: str
    accompaniment_status: str
    certifier_legal_name: str
    certifier_contact_email: str
    manufacture_place: str
    manufacture_date_month: str
    testing_place: str
    cited_rule_ids: List[str]
    cited_evidence_count: int
    content_completeness_pct: int
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    expected_product_version_seen: int


class ProductionBatch(AuditedEntity):
    product_id: str
    certificate_id: str
    batch_code: str
    produced_on: str
    quantity: int
    label_on_product: bool
    label_on_packaging: bool
    label_batch_code_printed: bool
    tracking_label_compliant: bool
    distribution_state: str
    released_at: Optional[str]
    release_rescind_count: int


class NoncomplianceCase(AuditedEntity):
    product_id: str
    triggering_test_order_id: str
    failed_rule_id: str
    case_state: str
    retest_round_count: int
    active_retest_order_id: Optional[str]
    scope_variant: str
    scope_units: int
    corrective_action_ref: Optional[str]
    corrective_action_revision: int
    opened_by_user_id: str
    closed_by_user_id: Optional[str]


class MaterialChangeEvent(TypedDict):
    id: str
    created_at: str
    product_id: str
    component_part_id: Optional[str]
    subject_type: str
    change_kind: str
    description: str
    occurred_at: str
    triggers_resample: bool
    recorded_by_user_id: str


ComplianceSummary = Dict[str, Any]
