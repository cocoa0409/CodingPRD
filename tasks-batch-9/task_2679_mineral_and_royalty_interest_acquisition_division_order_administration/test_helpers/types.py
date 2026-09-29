"""TypedDict shapes for every response entity.

Field names are taken verbatim from the PRD. Every entity carries id and
created_at; every entity except TitleChainEntry also carries updated_at and
version, because a chain-of-title entry is append-only and immutable.
"""

from typing import List, Optional, TypedDict


class Tract(TypedDict):
    id: str
    county: str
    state_code: str
    gross_acres: float
    operator_activity_tier: str
    title_status: str
    net_mineral_acres_certified: Optional[float]
    existing_burden_fraction: Optional[float]
    chain_entry_count: int
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitleChainEntry(TypedDict):
    id: str
    tract_id: str
    instrument_type: str
    instrument_date: str
    conveyed_fraction: Optional[float]
    conveyed_acres: Optional[float]
    county_book_page: str
    grantor_name: str
    grantee_name: str
    created_at: str


class RoyaltyOwner(TypedDict):
    id: str
    legal_name: str
    state_code: str
    contact_status: str
    tax_id_on_file: bool
    mailing_address: str
    suspense_total: float
    created_at: str
    updated_at: str
    version: int


class MineralInterest(TypedDict):
    id: str
    tract_id: str
    seller_owner_id: str
    seller_share_fraction: float
    lease_royalty_rate: float
    undeveloped_net_acres: float
    net_mineral_acres: float
    existing_burden_fraction: float
    interest_status: str
    current_valuation_id: Optional[str]
    acquiring_deed_book_page: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    mineral_interest_id: str
    current_monthly_net_revenue: float
    annual_decline_rate: float
    undeveloped_net_acres: float
    operator_activity_tier: str
    pdp_pv: float
    undeveloped_pv: float
    bid_floor: float
    max_bid: float
    valuation_status: str
    approved_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class OfferLetter(TypedDict):
    id: str
    mineral_interest_id: str
    offer_amount: float
    expires_on: str
    current_amount: float
    last_counter_amount: Optional[float]
    counter_round_count: int
    offer_status: str
    issued_by_user_id: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseSaleAgreement(TypedDict):
    id: str
    offer_letter_id: str
    mineral_interest_id: str
    tract_id: str
    purchase_price: float
    effective_date: str
    curative_days: int
    curative_deadline: str
    window_end_with_buffer: str
    individual_defect_threshold: float
    aggregate_defect_basket: float
    defect_adjustment_amount: float
    adjusted_purchase_price: float
    curative_status: str
    funding_status: str
    psa_status: str
    wire_reference: Optional[str]
    recording_county: Optional[str]
    recorded_book_page: Optional[str]
    recording_date: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TitleDefect(TypedDict):
    id: str
    psa_id: str
    defect_type: str
    affected_nma: float
    description: str
    allocated_value: float
    net_defect_value: float
    defect_status: str
    cure_round_count: int
    cure_instrument_book_page: Optional[str]
    raised_by_user_id: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    unit_name: str
    formation: str
    state_code: str
    unit_gross_acres: float
    royalty_rate_cap: float
    pugh_clause_active: bool
    pugh_deadline: Optional[str]
    producing_depth_count: int
    total_depth_count: int
    unallocated_acres: float
    active_allocation_count: int
    operator_user_id: str
    created_at: str
    updated_at: str
    version: int


class UnitTractAllocation(TypedDict):
    id: str
    unit_id: str
    tract_id: str
    allocated_acres: float
    effective_from: str
    effective_to: str
    pooling_election: str
    allocation_status: str
    released_acres: float
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DivisionOrder(TypedDict):
    id: str
    mineral_interest_id: str
    unit_id: str
    royalty_owner_id: str
    allocation_id: str
    expected_decimal: float
    pinned_decimal: Optional[float]
    operator_decimal: Optional[float]
    do_status: str
    dispute_reason: str
    effective_production_month: Optional[str]
    cumulative_variance_amount: float
    paid_net_total: float
    correction_round_count: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class RevenueCheckDetail(TypedDict):
    id: str
    division_order_id: str
    production_month: str
    product_code: str
    gross_volume: float
    gross_value: float
    operator_decimal_used: float
    reported_gross_royalty: float
    severance_tax_rate: float
    severance_tax_amount: float
    net_amount: float
    expected_gross_royalty: float
    expected_net_amount: float
    variance_amount: float
    audit_decimal: float
    audit_gross_royalty: float
    audit_variance_amount: float
    check_status: str
    created_at: str
    updated_at: str
    version: int


class SuspenseAccount(TypedDict):
    id: str
    division_order_id: str
    royalty_owner_id: str
    suspense_reason: str
    accrued_amount: float
    held_detail_count: int
    first_suspended_month: str
    months_held: int
    interest_accrued: float
    release_amount: float
    suspense_status: str
    escheat_state_code: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxStatement(TypedDict):
    royalty_owner_id: str
    tax_year: int
    gross_royalty: float
    severance_tax_withheld: float
    taxable_before_depletion: float
    depletion_allowance: float
    net_taxable: float
    detail_count: int


# Field name groups used by shape assertions.
COMMON_FIELDS_FULL: List[str] = ["id", "created_at", "updated_at", "version"]
COMMON_FIELDS_APPEND_ONLY: List[str] = ["id", "created_at"]
