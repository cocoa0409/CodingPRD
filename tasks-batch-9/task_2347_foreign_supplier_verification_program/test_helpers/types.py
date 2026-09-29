"""TypedDict shapes for every entity the API returns.

Two families of rows exist in this API:

* Versioned rows carry ``id``, ``created_at``, ``updated_at`` and ``version``.
* Immutable rows (``Food`` and ``Hazard``) carry only ``id`` and ``created_at``
  and deliberately expose no ``updated_at`` and no ``version``.
"""

from typing import Optional, TypedDict


class Importer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    dnb_number: str
    unique_facility_identifier: str
    small_importer_flag: bool
    record_retention_months: int
    blocked_pair_count: int
    open_corrective_action_count: int
    qualified_individual_designated: bool
    program_status: str


class QualifiedIndividual(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    importer_id: str
    full_name: str
    email: str
    qualification_summary: str
    training_completed_at: str
    training_valid_until: str
    concurrent_activity_capacity: int
    status: str
    active_assignment_count: int


class ForeignSupplier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    importer_id: str
    name: str
    country_code: str
    facility_registration_number: str
    regulatory_compliance_status: str
    compliance_status_source_reference: Optional[str]
    performance_score_provisional: float
    performance_score_final: float
    performance_sample_weight_total: float
    status: str
    last_evaluated_at: Optional[str]
    open_corrective_action_count: int


class Food(TypedDict):
    """Immutable row: only ``id`` and ``created_at`` are common fields."""

    id: str
    created_at: str
    importer_id: str
    food_name: str
    fda_product_code: str
    is_raw_agricultural_commodity: bool
    intended_consumer_group: str
    process_control_category: str
    ready_to_eat: bool


class SupplierFoodPair(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    importer_id: str
    supplier_id: str
    food_id: str
    designated_qi_id: str
    active_hazard_analysis_id: Optional[str]
    verification_status: str
    entry_eligibility_status: str
    exemption_status: str
    exemption_type: Optional[str]
    modified_requirements_only: bool
    hazard_analysis_count: int
    composite_hazard_risk: float
    risk_tier: str
    required_annual_frequency: int
    required_coverage: float
    adequacy_score_planned: float
    adequacy_score_realized: float
    uncontrolled_significant_hazard_count: int
    last_reassessed_at: Optional[str]
    reassessment_due_at: Optional[str]


class HazardAnalysis(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pair_id: str
    authored_by_qi_id: str
    methodology_note: str
    pair_version_at_create: int
    status: str
    hazard_count: int
    significant_hazard_count: int
    risk_total: float
    approved_at: Optional[str]


class Hazard(TypedDict):
    """Immutable row: only ``id`` and ``created_at`` are common fields."""

    id: str
    created_at: str
    hazard_analysis_id: str
    hazard_type: str
    hazard_name: str
    severity: int
    probability: int
    control_owner: str
    risk_score: float
    requires_control: bool


class VerificationActivity(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pair_id: str
    proposed_by_qi_id: str
    assigned_qi_id: str
    reviewed_by_qi_id: Optional[str]
    activity_type: str
    frequency_per_year: int
    justification_text: str
    window_start: str
    window_end: str
    status: str
    revision_count: int
    coverage_weight: float


class VerificationRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    activity_id: str
    submitted_by_qi_id: str
    attested_by_qi_id: Optional[str]
    outcome: str
    performed_start: str
    performed_end: str
    findings_count: int
    document_reference: str
    record_status: str
    weight: float
    record_points: float
    retained_until: str
    available_for_inspection: bool


class CorrectiveAction(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    supplier_id: str
    pair_id: str
    trigger_reason: str
    status: str
    decision: Optional[str]
    rationale: Optional[str]
    decided_at: Optional[str]
    closed_at: Optional[str]
    pre_action_blocked_pair_count: int
    supplier_version_at_decision: Optional[int]


class EntrySubmission(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pair_id: str
    entry_number: str
    entry_line_number: int
    dnb_number_submitted: str
    ufi_submitted: str
    arrival_date: str
    identifier_match: bool
    filed_by_user_id: str
    status: str
    held_reason: Optional[str]


class RecordsPackage(TypedDict):
    importer_id: str
    program_status: str
    retained_record_count: int
    available_for_inspection_count: int
    expired_record_count: int
    rescinded_record_count: int
    qualified_individual_designated: bool
    generated_at: str


VERSIONED_ENTITY_KEYS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_ENTITY_KEYS = ("id", "created_at")
