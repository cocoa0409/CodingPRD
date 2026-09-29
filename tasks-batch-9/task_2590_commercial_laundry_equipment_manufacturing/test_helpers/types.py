"""TypedDict shapes for every resource the commercial-laundry API returns.

Field names and nullability follow the PRD exactly. Per PRD 2.4 every resource
carries ``id`` and ``created_at``; most also carry ``updated_at`` and ``version``,
but ``StationLog`` and ``QuoteLine`` are immutable journal rows that carry only
``id`` and ``created_at`` -- they have no ``updated_at`` and no ``version``.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD 2.4: id, created_at, updated_at, version."""

    id: str
    created_at: str
    updated_at: str
    version: int


class JournalFields(TypedDict):
    """PRD 2.4: a StationLog and a QuoteLine carry only id and created_at."""

    id: str
    created_at: str


class MachineModel(CommonFields):
    model_code: str
    product_line: str
    capacity_rating_lb: int
    rated_water_gal_per_cwt: float
    rated_kwh_per_cwt: float
    drum_alloy_grade: str
    payment_module_options: List[str]
    max_rework_cycles: int
    min_first_pass_yield_pct: float
    list_price_cents: int
    certification_state: str
    suspended_reason: str
    accepted_unit_count: int
    scrapped_unit_count: int
    quality_hold_unit_count: int
    first_pass_yield_pct: float
    rebate_program_codes: List[str]
    rebate_amount_cents: int


class RebateProgram(CommonFields):
    program_code: str
    utility_code: str
    program_class: str
    eligible_product_lines: List[str]
    max_water_gal_per_cwt: float
    max_kwh_per_cwt: float
    min_capacity_rating_lb: int
    rebate_base_cents: int
    capacity_bonus_cents_per_10lb: int
    rebate_cap_cents: int
    effective_from: str
    effective_to: str
    program_state: str


class CertificationDossier(CommonFields):
    model_id: str
    prepared_by_user_id: str
    measured_water_gal_per_cwt: float
    measured_kwh_per_cwt: float
    test_cycle_count: int
    energy_review_state: str
    water_review_state: str
    energy_reviewer_user_id: Optional[str]
    water_reviewer_user_id: Optional[str]
    dossier_state: str
    resurvey_reason: str
    qualified_program_codes: List[str]
    rebate_amount_cents: int
    certified_at: Optional[str]
    resurvey_count: int


class ServicePart(CommonFields):
    part_number: str
    component_class: str
    supersedes_part_id: Optional[str]
    fits_product_lines: List[str]
    fits_min_capacity_lb: int
    fits_max_capacity_lb: int
    rated_duty_cycles: int
    warranty_months: int
    unit_price_cents: int
    requires_cert_scope: str
    on_hand_qty: int
    reserved_qty: int
    reorder_point_qty: int
    stock_state: str


class AssemblyStation(CommonFields):
    station_code: str
    station_type: str
    parallel_capacity: int
    changeover_buffer_minutes: int
    supported_product_lines: List[str]
    station_state: str


class Technician(CommonFields):
    employee_code: str
    full_name: str
    employer: str
    distributor_id: Optional[str]
    cert_scopes: List[str]
    cert_state: str
    cert_expires_on: Optional[str]
    last_cert_action_at: Optional[str]
    revocation_count: int


class BuildOrder(CommonFields):
    model_id: str
    serial_number: str
    planned_start_at: str
    build_state: str
    rework_count: int
    integrity_hold: bool
    labor_minutes_total: int
    station_pass_count: int
    scrap_reason: str
    qa_inspector_user_id: Optional[str]
    accepted_at: Optional[str]


class StationLog(JournalFields):
    """PRD 2.4: no updated_at and no version on this row."""

    build_order_id: str
    station_id: str
    technician_id: str
    station_type: str
    started_at: str
    completed_at: str
    outcome: str
    defect_code: str
    bearing_preload_micron: Optional[float]
    labor_minutes: int
    occupation_from: str
    occupation_to: str


class Distributor(CommonFields):
    distributor_code: str
    legal_name: str
    territory_code: str
    territory_exclusive: bool
    completed_training_keys: List[str]
    trained_technician_count: int
    installation_training_state: str
    distributor_state: str
    probation_reason: str
    warranty_credit_cents: int
    open_claim_count: int


class PackageQuote(CommonFields):
    distributor_id: str
    customer_name: str
    laundromat_site_code: str
    stated_credit_score: int
    verified_credit_score: Optional[int]
    financing_program: str
    down_payment_cents: int
    package_discount_pct: float
    freight_cents: int
    quote_state: str
    line_count: int
    line_subtotal_cents: int
    discount_cents: int
    total_cents: int
    origination_fee_cents: int
    financed_principal_cents: int
    provisional_apr_bp: Optional[int]
    provisional_monthly_payment_cents: Optional[int]
    final_apr_bp: Optional[int]
    monthly_payment_cents: Optional[int]
    decided_by_user_id: Optional[str]
    revision_round: int


class QuoteLine(JournalFields):
    """PRD 2.4: no updated_at and no version on this row."""

    quote_id: str
    model_id: str
    quantity: int
    payment_module: str
    line_discount_pct: float
    unit_price_cents: int
    payment_surcharge_cents: int
    line_total_cents: int


class WarrantyClaim(CommonFields):
    build_order_id: str
    part_id: str
    distributor_id: str
    reported_by_technician_id: str
    failure_cycle_count: int
    in_service_months: int
    duty_cycle_class: str
    diagnostics_code: str
    claim_state: str
    effective_rated_cycles: int
    coverage_variant: str
    covered_amount_cents: int
    denial_reason: str
    block_reason: str
    adjudicated_by_user_id: Optional[str]
    voided_at: Optional[str]


class WarrantyAnalysis(TypedDict):
    """Computed read returned by the per-model warranty analysis endpoint."""

    model_id: str
    claim_count: int
    approved_claim_count: int
    denied_claim_count: int
    blocked_claim_count: int
    voided_claim_count: int
    covered_amount_total_cents: int
    full_replacement_count: int
    pro_rata_count: int
    component_class_breakdown: str
    duty_cycle_breakdown: str


class ClockState(TypedDict):
    """Response of the logical-clock capability described in PRD 2.5."""

    current_utc: str
    expired_technician_count: int
    retired_program_count: int
