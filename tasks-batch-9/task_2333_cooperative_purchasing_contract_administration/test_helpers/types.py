"""TypedDict shapes for the persisted entities of the cooperative purchasing API."""

from typing import Any, Optional, TypedDict


class StateLawRule(TypedDict):
    """Immutable configuration row: it carries only id and created_at."""

    id: str
    created_at: str
    state_code: str
    piggyback_doctrine: str
    min_notice_days: int
    requires_lead_agency_in_state: bool
    allows_nonprofit_participation: bool
    max_contract_term_months: int
    requires_local_solicitation_waiver: bool
    reciprocity_state_codes: list[str]


class Solicitation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    title: str
    solicitation_number: str
    lead_agency_name: str
    lead_agency_state_code: str
    response_due_at: str
    technical_weight_pct: float
    price_weight_pct: float
    specification_document_ref: Optional[str]
    method_justification_ref: Optional[str]
    amendment_log_document_ref: Optional[str]
    status: str
    posted_at: Optional[str]
    notice_days: Optional[int]
    addenda_count: int
    responsive_response_count: int
    recommended_by_user_id: Optional[str]
    awarded_by_user_id: Optional[str]
    audit_package_status: str
    audit_required_doc_codes: list[str]
    audit_present_doc_codes: list[str]
    audit_completeness_pct: Optional[float]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]


class Supplier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    home_state_code: str
    qualification_status: str
    performance_score: float
    deduction_points_total: float
    performance_tier: str
    substantiated_complaint_count: int
    delinquent_report_count: int
    fee_assessed_cents_total: int
    fee_remitted_cents_total: int


class SolicitationResponse(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    solicitation_id: str
    supplier_id: str
    proposed_annual_value_cents: int
    responsiveness_note: Optional[str]
    status: str
    info_request_rounds: int
    technical_score: Optional[float]
    price_score: Optional[float]
    composite_score: Optional[float]
    award_rank: Optional[int]


class MasterContract(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    solicitation_id: str
    supplier_id: str
    contract_number: str
    admin_fee_rate_bps: int
    base_term_start: str
    base_term_end: str
    current_term_end: Optional[str]
    max_renewals: int
    renewals_used: int
    price_escalation_cap_pct: float
    nationwide_pricing_flag: bool
    discount_tiers: list[dict[str, Any]]
    permitted_add_ons: list[dict[str, Any]]
    status: str
    compliance_posture: str
    usage_chargeable_cents_total: int
    fee_assessed_cents_total: int
    fee_remitted_cents_total: int
    fee_outstanding_cents: int
    delinquent_report_count: int


class ContractLineItem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contract_id: str
    sku: str
    item_description: str
    unit_of_measure: str
    base_unit_price_cents: int
    price_floor_cents: int
    origin: str
    status: str
    price_effective_from: Optional[str]
    last_price_change_at: Optional[str]
    price_change_count: int


class MemberAgency(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    state_code: str
    member_category: str
    annual_spend_ceiling_cents: int
    committed_spend_cents: int
    governing_body_resolution_number: Optional[str]
    irs_determination_letter_number: Optional[str]
    registration_status: str
    docs_request_count: int
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]


class PiggybackAnalysis(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    member_agency_id: str
    contract_id: str
    status: str
    determination: Optional[str]
    doctrine_applied: Optional[str]
    authority_score: Optional[float]
    deduction_detail: list[dict[str, Any]]
    local_waiver_required: bool
    waiver_reference: Optional[str]
    determined_at: Optional[str]
    expires_on: Optional[str]
    voided_reason: Optional[str]


class ContractUsage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contract_id: str
    member_agency_id: str
    line_item_id: str
    piggyback_analysis_id: str
    usage_report_id: Optional[str]
    quantity: int
    add_on_codes: list[str]
    add_on_detail: list[dict[str, Any]]
    ordered_at: str
    spend_basis_cents: int
    discount_tier_index: int
    total_discount_pct: float
    net_unit_price_cents: int
    subtotal_cents: int
    add_on_charges_cents: int
    chargeable_base_cents: int
    effective_fee_rate_bps: int
    admin_fee_cents: int
    total_cents: int
    status: str
    retracted_at: Optional[str]


class UsageReport(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contract_id: str
    period_start: str
    period_end: str
    status: str
    fee_status: str
    swept_usage_count: int
    reported_chargeable_cents: int
    reported_usage_cents: int
    reported_fee_cents: int
    audited_fee_cents: Optional[int]
    fee_true_up_cents: Optional[int]
    fee_rebate_cents: Optional[int]
    variance_pct: Optional[float]
    variance_flagged: bool
    remitted_cents: int
    accepted_at: Optional[str]
    fee_due_at: Optional[str]
    rejection_reason: Optional[str]


class ContractAmendment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contract_id: str
    amendment_type: str
    status: str
    requested_term_end: Optional[str]
    target_line_item_id: Optional[str]
    new_unit_price_cents: Optional[int]
    price_index: Optional[str]
    index_change_pct: Optional[float]
    price_ceiling_cents: Optional[int]
    new_line_items: Optional[list[dict[str, Any]]]
    expansion_scope_overlap_pct: Optional[float]
    effective_from: Optional[str]
    proposed_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class MemberComplaint(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    contract_id: str
    member_agency_id: str
    related_usage_id: Optional[str]
    severity: str
    category: str
    narrative: str
    status: str
    deduction_points: Optional[float]
    points_reversed: bool
    investigator_user_id: Optional[str]
    adjudicator_user_id: Optional[str]
    substantiated_at: Optional[str]
    appeal_filed_at: Optional[str]
    appeal_deadline_at: Optional[str]
