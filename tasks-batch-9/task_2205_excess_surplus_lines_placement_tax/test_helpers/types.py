"""TypedDict shapes for the fifteen resource types of the Surplus Lines
Placement Tax API.

Every resource carries the four system-managed properties described in
PRD 2.5: ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Broker(CommonFields):
    firm_name: str
    home_state: str
    status: str


class BrokerLicense(CommonFields):
    broker_id: str
    state_code: str
    license_number: str
    license_type: str
    expires_on: str
    status: str


class StateProgram(CommonFields):
    state_code: str
    premium_tax_rate: float
    stamping_fee_rate: float
    stamping_fee_cap_cents: Optional[int]
    stamping_office_required: bool
    allocation_method: str
    diligent_search_min_declinations: int
    export_list_exempts_search: bool
    filing_frequency: str
    filing_deadline_days: int
    return_premium_tax_refundable: bool
    return_premium_stamping_refundable: bool
    min_carrier_capital_surplus_cents: int
    required_notice_codes: List[str]


class Carrier(CommonFields):
    naic_number: str
    legal_name: str
    domicile_type: str
    capital_surplus_cents: int
    am_best_rating: str
    trust_fund_cents: int
    naic_quarterly_listing: bool
    security_status: str


class CarrierEligibility(CommonFields):
    carrier_id: str
    state_program_id: str
    listed_on: str
    removed_on: Optional[str]
    listing_status: str


class MarketSecurityReview(CommonFields):
    carrier_id: str
    status: str
    score: int
    variant_applied: Optional[str]
    capital_surplus_at_review_cents: Optional[int]
    rating_at_review: Optional[str]
    reviewer_user_id: Optional[str]
    conditions_note: Optional[str]


class StateExposure(TypedDict):
    state_code: str
    insured_value_cents: int


class Placement(CommonFields):
    broker_id: str
    insured_name: str
    principal_place_of_business_state: str
    coverage_class: str
    is_export_list_risk: bool
    state_exposures: List[StateExposure]
    total_insured_value_cents: int
    home_state: str
    declination_count: int
    status: str
    diligent_search_completed_at: Optional[str]


class Declination(CommonFields):
    placement_id: str
    admitted_insurer_name: str
    naic_number: Optional[str]
    state_code: str
    reason_code: str
    declined_on: str
    status: str


class Policy(CommonFields):
    placement_id: str
    carrier_id: str
    broker_id: str
    policy_number: str
    effective_date: str
    expiration_date: str
    original_gross_premium_cents: int
    gross_premium_cents: int
    policy_fee_cents: int
    broker_fee_cents: int
    min_earned_premium_pct: float
    taxable_premium_cents: int
    total_tax_cents: int
    total_stamping_fee_cents: int
    home_state: str
    allocation_method_applied: str
    notice_codes_affixed: List[str]
    stamping_submitted_at: Optional[str]
    status: str
    compliance_status: str
    tax_status: str
    stamping_status: str


class PolicyStateAllocation(CommonFields):
    policy_id: str
    state_code: str
    state_program_id: str
    allocation_pct: float
    allocated_premium_cents: int
    premium_tax_rate_applied: float
    stamping_fee_rate_applied: float
    tax_cents: int
    stamping_fee_cents: int
    allocation_basis: str


class Endorsement(CommonFields):
    policy_id: str
    sequence_number: int
    endorsement_type: str
    premium_delta_cents: int
    effective_date: str
    supersedes_endorsement_id: Optional[str]
    tax_adjustment_cents: int
    stamping_fee_adjustment_cents: int
    status: str


class Cancellation(CommonFields):
    policy_id: str
    cancellation_type: str
    cancellation_date: str
    earned_premium_cents: int
    return_premium_cents: int
    tax_refund_cents: int
    stamping_fee_refund_cents: int
    status: str


class TaxFilingLine(CommonFields):
    policy_id: str
    state_program_id: str
    filing_batch_id: Optional[str]
    source_endorsement_id: Optional[str]
    source_cancellation_id: Optional[str]
    line_type: str
    period_key: str
    taxable_premium_cents: int
    tax_cents: int
    stamping_fee_cents: int
    status: str


class FilingBatch(CommonFields):
    state_program_id: str
    broker_id: str
    period_key: str
    line_count: int
    total_tax_cents: int
    total_stamping_fee_cents: int
    penalty_cents: int
    total_due_cents: int
    late: bool
    due_date: Optional[str]
    prepared_by_user_id: Optional[str]
    remitted_by_user_id: Optional[str]
    status: str


class Affidavit(CommonFields):
    policy_id: str
    affidavit_type: str
    declination_count_attested: int
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    status: str
