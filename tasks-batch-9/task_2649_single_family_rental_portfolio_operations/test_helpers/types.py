"""Typed shapes for every resource the Single-Family Rental Portfolio API returns.

One ``TypedDict`` per PRD entity, carrying the input, derived and audit fields the
PRD declares for it.  All thirteen entities declare the common audit fields, so every
shape below inherits ``CommonFields`` (PRD SS2.2: every resource carries ``id``,
``created_at``, ``updated_at`` and ``version``).
"""

from typing import Any, Dict, List, TypedDict


class CommonFields(TypedDict):
    """Audit fields present on every persisted resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Market(CommonFields):
    """Market resource (PRD SS3)."""

    code: str
    name: str
    tax_jurisdiction_code: str
    millage_bps: int
    rent_index_cents: int
    cost_index_bps: int
    cost_variance_tolerance_bps: int
    make_ready_target_days: int
    turn_holdback_cap_bps: int
    showing_buffer_minutes: int
    min_showing_duration_minutes: int
    pet_deposit_per_pet_cents: int
    pet_deposit_cap_cents: int
    max_pets: int
    restricted_breeds: List[Any]
    standard_lease_term_months: int
    fraud_block_threshold_bps: int
    rent_to_income_max_bps: int
    vacancy_loss_bps: int
    bad_debt_bps: int
    mgmt_fee_bps: int
    underwriting_yield_floor_bps: int
    disposition_yield_floor_bps: int
    max_rent_concession_bps: int


class ScopeTemplate(CommonFields):
    """ScopeTemplate resource (PRD SS3)."""

    code: str
    name: str
    certification_code: str
    unit: str
    benchmark_unit_cost_cents: int
    default_crew_size: int
    default_crew_days: int
    safety_critical: bool


class Home(CommonFields):
    """Home resource (PRD SS3)."""

    market_id: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    bedrooms: int
    bathrooms: float
    square_feet: int
    year_built: int
    assessed_value_cents: int
    asking_rent_cents: int
    insurance_carrier_name: str
    insurance_annual_premium_cents: int
    insurance_binder_expires_on: str
    hoa_name: str
    hoa_annual_cents: int
    property_tax_annual_cents: int
    asset_status: str
    occupancy_status: str
    leasing_posture: str
    booked_showing_count: int
    disposition_mode: str
    lot_code: str
    bpo_value_cents: int
    net_sale_proceeds_cents: int
    realized_gain_cents: int
    hold_sell_score_bps: int
    disposition_flagged: bool


class UnderwritingCase(CommonFields):
    """UnderwritingCase resource (PRD SS3)."""

    home_id: str
    purchase_price_cents: int
    acquisition_closing_costs_cents: int
    estimated_monthly_rent_cents: int
    turn_reserve_annual_cents: int
    planned_scope_lines: List[Any]
    planned_renovation_budget_cents: int
    underwritten_effective_gross_income_cents: int
    underwritten_noi_cents: int
    underwritten_all_in_basis_cents: int
    underwritten_yield_on_cost_bps: int
    realized_renovation_cost_cents: int
    realized_noi_cents: int
    realized_all_in_basis_cents: int
    realized_yield_on_cost_bps: int
    status: str
    revision_round: int
    submitted_by_user_id: str
    decided_by_user_id: str
    decision_note: str


class Vendor(CommonFields):
    """Vendor resource (PRD SS3)."""

    legal_name: str
    market_id: str
    daily_crew_capacity: int
    cost_index_bps: int
    quality_score_bps: int
    insurance_expires_on: str
    status: str
    suspension_reason: str
    committed_crew_days: int


class VendorCertification(CommonFields):
    """VendorCertification resource (PRD SS3)."""

    vendor_id: str
    certification_code: str
    effective_on: str
    expires_on: str


class RenovationProject(CommonFields):
    """RenovationProject resource (PRD SS3)."""

    home_id: str
    project_type: str
    approved_budget_cents: int
    committed_cost_cents: int
    budget_remaining_cents: int
    turn_started_on: str
    rent_ready_on: str
    turn_days: int
    overage_days: int
    gross_turn_cost_cents: int
    holdback_rate_bps: int
    vendor_holdback_cents: int
    net_turn_cost_cents: int
    status: str


class WorkOrder(CommonFields):
    """WorkOrder resource (PRD SS3)."""

    home_id: str
    project_id: str
    vendor_id: str
    scope_template_id: str
    work_type: str
    quantity: int
    crew_size: int
    scheduled_start_date: str
    scheduled_end_date: str
    crew_days: int
    fulfillment_channel: str
    quoted_cost_cents: int
    benchmark_total_cents: int
    variance_bps: int
    actual_cost_cents: int
    completed_on: str
    void_reason: str
    status: str


class Prospect(CommonFields):
    """Prospect resource (PRD SS3)."""

    email: str
    full_name: str
    phone: str
    market_id: str
    declared_monthly_income_cents: int
    verified_monthly_income_cents: int
    credit_tier: str
    prior_eviction_count: int
    document_type: str
    document_match_score_bps: int
    selfie_liveness_pass: bool
    device_reputation_bps: int
    ip_geo_distance_km: int
    fraud_risk_score_bps: int
    fraud_score_variant: str
    identity_status: str
    verification_attempt_count: int


class ShowingSlot(CommonFields):
    """ShowingSlot resource (PRD SS3)."""

    home_id: str
    prospect_id: str
    starts_at: str
    ends_at: str
    access_mode: str
    status: str
    cancel_reason: str


class RentalApplication(CommonFields):
    """RentalApplication resource (PRD SS3)."""

    prospect_id: str
    home_id: str
    requested_move_in_date: str
    lease_term_months: int
    pet_count: int
    pet_breeds: List[Any]
    rent_to_income_bps: int
    security_deposit_cents: int
    pet_deposit_cents: int
    total_move_in_deposit_cents: int
    risk_multiplier_bps: int
    adverse_action_reason: str
    status: str


class Lease(CommonFields):
    """Lease resource (PRD SS3)."""

    application_id: str
    home_id: str
    start_date: str
    term_months: int
    monthly_rent_cents: int
    required_deposit_cents: int
    deposit_paid_cents: int
    signed_on: str
    void_reason: str
    status: str


class ComplianceObligation(CommonFields):
    """ComplianceObligation resource (PRD SS3)."""

    home_id: str
    supersedes_obligation_id: str
    work_order_id: str
    obligation_type: str
    severity: str
    description: str
    due_on: str
    planned_resolution_on: str
    evidence_ref: str
    assessed_value_cents: int
    target_value_cents: int
    settled_value_cents: int
    consultant_fee_bps: int
    annual_tax_savings_cents: int
    consultant_fee_cents: int
    net_tax_benefit_cents: int
    resolution_round: int
    submitted_by_user_id: str
    status: str

