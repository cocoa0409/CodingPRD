"""TypedDict shapes for every resource family the API exposes.

Every family carries the four common properties `id`, `created_at`,
`updated_at` and `version`; none is exempt.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Brand(CommonFields):
    name: str
    owner_legal_entity: str
    home_jurisdiction: str
    authorized_msrp_cents: int
    enforcement_budget_cents: int
    enforcement_spend_cents: int
    status: str


class TrademarkRegistration(CommonFields):
    brand_id: str
    registration_number: str
    jurisdiction: str
    nice_class: int
    registration_date: str
    expiry_date: str
    principal_register: bool
    status: str


class MarketplaceEnrollment(CommonFields):
    brand_id: str
    asserted_registration_id: str
    marketplace_code: str
    requested_nice_class: int
    enrollment_status: str
    activated_at: Optional[str]
    suspension_reason_code: Optional[str]
    superseded_by_enrollment_id: Optional[str]


class AuthorizedRepresentative(CommonFields):
    enrollment_id: str
    authority_scope: str
    effective_from: str
    effective_to: Optional[str]
    power_of_attorney_ref: str
    designation_status: str
    revoked_at: Optional[str]


class Seller(CommonFields):
    marketplace_code: str
    seller_ref: str
    legal_name: str
    jurisdiction: Optional[str]
    canonical_seller_id: Optional[str]
    standalone_strike_points: float
    cluster_strike_points: float
    status: str


class Listing(CommonFields):
    brand_id: str
    seller_id: str
    marketplace_code: str
    listing_ref: str
    title_text: str
    image_hash: str
    price_cents: int
    nice_class: int
    image_match_score: Optional[float]
    text_match_score: Optional[float]
    price_deviation_factor: Optional[float]
    match_score: Optional[float]
    monitor_status: str
    enforcement_status: str
    violation_type: str


class InfringementClaim(CommonFields):
    brand_id: str
    listing_id: str
    asserted_registration_id: str
    claimed_violation_type: str
    registration_strength: float
    preliminary_score: float
    substantiation_score: float
    status: str
    dismissal_reason_code: Optional[str]


class TestBuy(CommonFields):
    claim_id: str
    seller_id: str
    order_ref: str
    purchase_price_cents: int
    shipping_cents: int
    lab_fee_cents: int
    subtotal_cents: int
    service_fee_rate: float
    service_fee_cents: int
    billable_total_cents: int
    status: str
    ordered_at: Optional[str]
    received_at: Optional[str]
    lot_code: Optional[str]
    chain_of_custody_ref: Optional[str]
    authentication_result: Optional[str]
    lab_ref: Optional[str]


class EvidenceItem(TypedDict):
    item_type: str
    item_ref: str
    added_at: str


class EvidencePackage(CommonFields):
    claim_id: str
    package_ref: str
    items: List[EvidenceItem]
    item_count: int
    required_type_coverage: int
    completeness_score: float
    status: str
    sealed_at: Optional[str]


class TakedownNotice(CommonFields):
    enrollment_id: str
    claim_id: str
    evidence_package_id: str
    submitted_by_rep_id: Optional[str]
    round_number: int
    status: str
    submitted_at: Optional[str]
    decision_due_at: Optional[str]
    decided_at: Optional[str]
    counter_notice_deadline_at: Optional[str]
    marketplace_case_ref: Optional[str]


class CounterNotice(CommonFields):
    takedown_id: str
    seller_id: str
    sworn_statement_ref: str
    status: str
    filed_at: str
    response_due_at: str
    resolved_at: Optional[str]
    rebuttal_ref: Optional[str]


class EnforcementCase(CommonFields):
    brand_id: str
    seller_id: str
    originating_takedown_id: Optional[str]
    cease_desist_sent_by_rep_id: Optional[str]
    litigation_authorized_by_rep_id: Optional[str]
    letter_ref: Optional[str]
    cd_sent_at: Optional[str]
    cd_response_due_at: Optional[str]
    response_kind: Optional[str]
    docket_ref: Optional[str]
    closure_outcome: Optional[str]
    correspondence_status: str
    litigation_status: str
    case_status: str


class CustomsRecordation(CommonFields):
    brand_id: str
    registration_id: str
    customs_authority_code: str
    nice_class: int
    recorded_on: str
    expires_on: str
    recordation_number: Optional[str]
    status: str


class DiversionInvestigation(CommonFields):
    brand_id: str
    source_kind: str
    lot_code: str
    recordation_id: Optional[str]
    source_test_buy_id: Optional[str]
    seller_id: Optional[str]
    seizure_ref: Optional[str]
    port_code: Optional[str]
    seized_qty: Optional[int]
    declared_value_cents: Optional[int]
    detention_notice_at: Optional[str]
    response_due_at: Optional[str]
    evidence_ref: Optional[str]
    suspected_distributor_ref: Optional[str]
    concluded_at: Optional[str]
    findings_ref: Optional[str]
    status: str


class EnforcementMetrics(TypedDict):
    listing_removal_rate: float
    repeat_infringer_count: int
    decided_takedown_count: int
    removed_takedown_count: int
    open_case_count: int
    enforcement_spend_cents: int


SweepResult = Dict[str, Any]
