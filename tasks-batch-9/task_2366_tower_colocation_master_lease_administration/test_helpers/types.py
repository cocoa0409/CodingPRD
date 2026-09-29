"""TypedDict shapes for every resource named in the PRD.

These are documentation-grade hints for the test author; the tests assert on the
JSON dictionaries the API returns rather than instantiating these classes.

Per PRD §2.4 every resource carries ``id`` and ``created_at``, and all of them
also carry ``updated_at`` and ``version`` except the landlord payment record,
which is immutable once written and carries neither.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD §2.4: id, created_at, updated_at and version."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableFields(TypedDict):
    """PRD §2.4: the landlord payment record carries only id and created_at."""

    id: str
    created_at: str


class OccupiedElevationBand(TypedDict):
    """PRD §2.7: one entry per contributing amendment."""

    amendment_id: str
    bottom_ft: float
    top_ft: float
    tenant_id: str


class Tower(CommonFields):
    site_name: str
    structure_type: str
    rated_capacity_load_units: float
    min_colocation_elevation_ft: float
    max_elevation_ft: float
    ground_space_total_sqft: int
    baseline_reserved_load_units: float
    baseline_reserved_ground_sqft: int
    reserved_load_units: float
    reserved_load_pct: float
    reserved_ground_space_sqft: int
    available_ground_space_sqft: int
    occupied_elevation_bands: List[OccupiedElevationBand]
    open_review_count: int
    capacity_posture: str


class CapacitySummary(TypedDict):
    """PRD §3.1: computed read with nine members; not a stored entity."""

    tower_id: str
    rated_capacity_load_units: float
    reserved_load_units: float
    reserved_load_pct: float
    available_ground_space_sqft: int
    capacity_posture: str
    open_review_count: int
    occupied_band_count: int
    capacity_hold_application_count: int


class Landlord(CommonFields):
    legal_name: str
    remit_contact_email: str
    w9_on_file: bool


class GroundLease(CommonFields):
    tower_id: str
    landlord_id: str
    base_monthly_rent_cents: int
    escalator_pct: float
    commencement_date: str
    term_end_date: str
    renewal_option_count: int
    renewal_term_years: int
    buyout_price_cents: int
    status: str
    renewals_exercised: int
    paid_through_date: Optional[str]
    buyout_paid_cents: int
    current_monthly_rent_cents: int


class LandlordPayment(ImmutableFields):
    """PRD §2.4: neither updated_at nor version is present on this record."""

    ground_lease_id: str
    period_start_date: str
    period_end_date: str
    months_covered: int
    amount_cents: int


class Tenant(CommonFields):
    legal_name: str
    carrier_code: str
    outstanding_balance_cents: int
    credit_status: str


class MasterLeaseAgreement(CommonFields):
    tenant_id: str
    base_monthly_rent_cents: int
    escalator_pct: float
    initial_term_years: int
    renewal_terms_count: int
    expires_on: str
    expedited_review_days: Optional[int]
    status: str
    application_privilege: str
    executed_amendment_count: int


class ColocationApplication(CommonFields):
    tower_id: str
    master_lease_agreement_id: str
    requested_elevation_bottom_ft: float
    requested_elevation_top_ft: float
    requested_ground_space_sqft: int
    expedited_requested: bool
    status: str
    total_load_units: float
    revision_count: int
    sla_breached: bool
    submitted_at: Optional[str]
    review_deadline_at: Optional[str]


class EquipmentLine(CommonFields):
    colocation_application_id: str
    equipment_type: str
    model_code: str
    quantity: int
    unit_weight_lbs: float
    wind_area_sqft: float
    mount_elevation_ft: float
    load_units: float
    installed_amendment_id: Optional[str]


class StructuralAnalysis(CommonFields):
    colocation_application_id: str
    variant: str
    status: str
    engineer_user_id: str
    issued_at: str
    included_load_units: float
    projected_loading_pct: float
    result: str
    modification_construction_cost_cents: Optional[int]
    quoted_at: Optional[str]


class SiteAmendment(CommonFields):
    master_lease_agreement_id: str
    tower_id: str
    colocation_application_id: str
    supersedes_amendment_id: Optional[str]
    effective_date: str
    term_end_date: str
    base_monthly_rent_cents: int
    escalator_pct: float
    restoration_deposit_cents: int
    elevation_bottom_ft: float
    elevation_top_ft: float
    ground_space_sqft: int
    reserved_load_units: float
    execution_status: str
    billing_status: str
    restoration_status: str
    current_monthly_rent_cents: int
    notice_given_at: Optional[str]
    terminated_at: Optional[str]


class ModificationProject(CommonFields):
    tower_id: str
    originating_analysis_id: str
    construction_window_start_date: str
    construction_window_end_date: str
    allocation_basis: str
    status: str
    proposing_engineer_user_id: str
    certified_by_user_id: Optional[str]
    base_construction_cost_cents: int
    volume_discount_pct: float
    engineering_fee_cents: int
    total_cost_cents: int
    allocated_cents: int
    added_capacity_load_units: Optional[float]
    funded_at: Optional[str]
    cancellation_reason: Optional[str]


class CostShare(CommonFields):
    modification_project_id: str
    tenant_id: str
    site_amendment_id: Optional[str]
    allocation_basis: str
    basis_load_units: float
    basis_created_at: str
    share_cents: int
    status: str
    accepted_at: Optional[str]
    decline_reason: Optional[str]


class EquipmentAudit(CommonFields):
    tower_id: str
    audit_date: str
    basis: str
    status: str
    auditor_user_id: str
    finding_count: int
    retroactive_billing_total_cents: int


class AuditFinding(CommonFields):
    equipment_audit_id: str
    tenant_id: str
    site_amendment_id: Optional[str]
    description: str
    observed_load_units: float
    installed_on_date: str
    mount_elevation_ft: float
    status: str
    months_billable: int
    retroactive_billing_cents: int


class ClockAdvanceSummary(TypedDict):
    """PRD §2.4: the clock response is a summary object, not a stored entity."""

    current_utc: str
    expired_ground_lease_count: int
    expired_master_lease_count: int
    frozen_tower_count: int
