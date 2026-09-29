"""TypedDict shapes for the eleven resource types of the Supplement Label Claim
Compliance API.

Every resource carries the four common properties of PRD §2.4 — ``id``,
``created_at``, ``updated_at`` and ``version`` — so each shape below extends
``CommonFields``. Field names are PRD-exact.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD §2.4: all eleven resource types carry all four properties."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Product(CommonFields, total=False):
    brand_name: str
    product_name: str
    net_quantity_g: float
    servings_per_container: int
    lifecycle_status: str
    label_posture: str
    marketing_start_date: Optional[str]
    serious_ae_count: int
    nonserious_ae_count: int
    late_notification_count: int
    rejected_coa_count: int
    compliance_risk_index: int
    active_claim_count: int
    withdrawn_claim_count: int
    requires_label_revision: bool


class Ingredient(CommonFields, total=False):
    ingredient_name: str
    ingredient_class: str
    pre_dshea_marketed: bool
    chemical_alteration: bool
    daily_intake_mg: float
    rdi_mg: Optional[float]
    allergen_code: Optional[str]
    contraindication_code: Optional[str]
    predecessor_ingredient_id: Optional[str]
    eligibility_status: str
    ndi_notification_required: bool
    determined_at: Optional[str]


class ProductIngredient(CommonFields, total=False):
    product_id: str
    ingredient_id: str
    amount_per_serving_mg: float
    panel_position: int
    line_status: str
    percent_dv_declared: Optional[int]
    dv_established: bool


class NDINotification(CommonFields, total=False):
    ingredient_id: str
    submitter_reference: str
    safety_narrative: str
    agency_objection_reason: Optional[str]
    notification_status: str
    submitted_at: Optional[str]
    waiting_period_end: Optional[str]
    agency_response_at: Optional[str]


class StructureFunctionClaim(CommonFields, total=False):
    product_id: str
    ingredient_id: str
    claim_text: str
    claim_type: str
    submission_reference: Optional[str]
    withdrawal_reason: Optional[str]
    substantiation_status: str
    notification_status: str
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    notification_due_date: Optional[str]
    notification_due_basis: Optional[str]
    notified_at: Optional[str]
    revision_round: int
    requires_recheck: bool


class SubstantiationDossier(CommonFields, total=False):
    claim_id: str
    dossier_summary: str
    review_decision: Optional[str]
    rejection_reason: Optional[str]
    authored_by_user_id: str
    dossier_status: str
    evidence_studies: List[Dict[str, Any]]
    study_count: int
    screening_score: float
    final_score: Optional[float]
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]


class LabelPanel(CommonFields, total=False):
    product_id: str
    supersedes_panel_id: Optional[str]
    panel_format: str
    serving_size_text: str
    serving_weight_g: float
    servings_per_container_declared: int
    effective_from: str
    effective_until: str
    declared_warning_codes: List[str]
    disclaimer_text: Optional[str]
    panel_status: str
    required_warning_codes: List[str]
    panel_lines_required: Optional[int]
    panel_lines_allowed: Optional[int]
    panel_total_dv_coverage_pct: Optional[int]
    validated_at: Optional[str]
    locked_at: Optional[str]


class AdverseEventReport(CommonFields, total=False):
    product_id: str
    reporter_type: str
    received_date: str
    narrative: str
    outcome_codes: List[str]
    submission_reference: Optional[str]
    is_serious: bool
    aer_status: str
    submission_due_date: Optional[str]
    submitted_at: Optional[str]
    submission_timeliness: Optional[str]
    retention_until: str
    triaged_at: Optional[str]


class Supplier(CommonFields, total=False):
    supplier_name: str
    country_code: str
    audit_score: Optional[float]
    remediation_reference: Optional[str]
    qualification_status: str
    coa_rejection_count: int
    total_released_kg: float
    last_decision_at: Optional[str]


class IngredientLot(CommonFields, total=False):
    supplier_id: str
    ingredient_id: str
    lot_code: str
    quantity_kg: float
    recall_reason: Optional[str]
    quarantined_quantity_kg: float
    released_quantity_kg: float
    rejected_quantity_kg: float
    lot_status: str
    identity_verified: bool
    released_at: Optional[str]
    recalled_at: Optional[str]


class CertificateOfAnalysis(CommonFields, total=False):
    lot_id: str
    lab_name: str
    identity_test_method: str
    identity_match: bool
    assay_percent_of_label: float
    heavy_metals_pass: bool
    microbial_pass: bool
    review_decision: Optional[str]
    rejection_reason: Optional[str]
    coa_acceptable: bool
    coa_status: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]


class RiskProfile(TypedDict, total=False):
    """Computed read of PRD §3.3 — the risk profile of one product."""

    serious_ae_count: int
    nonserious_ae_count: int
    late_notification_count: int
    rejected_coa_count: int
    compliance_risk_index: int
    label_posture: str
