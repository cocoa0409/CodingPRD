"""Domain types for the Landfill Airspace & Cell Development Management API.

Status enums, role enum and entity TypedDicts. Every one of the thirteen
resource types carries the same four common properties (``id``, ``created_at``,
``updated_at``, ``version``), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SITE_OPERATOR = "SiteOperator"
    SCALE_OPERATOR = "ScaleOperator"
    CQA_ENGINEER = "CqaEngineer"
    SURVEYOR_OF_RECORD = "SurveyorOfRecord"
    ENVIRONMENTAL_MANAGER = "EnvironmentalManager"
    REGULATORY_AGENCY = "RegulatoryAgency"
    FINANCE_OFFICER = "FinanceOfficer"


class OperatingStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED_AIRSPACE = "RESTRICTED_AIRSPACE"
    SUSPENDED_NO_AIRSPACE = "SUSPENDED_NO_AIRSPACE"
    SUSPENDED_FINANCIAL = "SUSPENDED_FINANCIAL"
    CLOSED = "CLOSED"


class GasCollectionStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"


class FinancialAssuranceStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    SHORTFALL_REVIEW = "SHORTFALL_REVIEW"
    LAPSED = "LAPSED"


class CellStatus(str, Enum):
    DESIGN = "DESIGN"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    QA_REVIEW = "QA_REVIEW"
    QA_CERTIFIED = "QA_CERTIFIED"
    READY_FOR_WASTE = "READY_FOR_WASTE"
    ACTIVE = "ACTIVE"
    FULL = "FULL"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class LinerType(str, Enum):
    SINGLE_COMPOSITE = "SINGLE_COMPOSITE"
    DOUBLE_COMPOSITE = "DOUBLE_COMPOSITE"
    GCL_ONLY = "GCL_ONLY"


class LinerQaPackageStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AerialSurveyStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class OperatingDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AMENDED = "AMENDED"


class CoverMaterialType(str, Enum):
    SOIL_6IN = "SOIL_6IN"
    ALTERNATIVE_TARP = "ALTERNATIVE_TARP"
    ADC_FOAM = "ADC_FOAM"
    AUTO_SHRED_FINES = "AUTO_SHRED_FINES"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class WasteStream(str, Enum):
    MSW = "MSW"
    CD = "CD"
    INDUSTRIAL_SPECIAL = "INDUSTRIAL_SPECIAL"
    ASBESTOS_SPECIAL = "ASBESTOS_SPECIAL"


class LoadCheckResult(str, Enum):
    PASS = "PASS"
    PROHIBITED_FOUND = "PROHIBITED_FOUND"
    UNMANIFESTED = "UNMANIFESTED"


class ProfileStream(str, Enum):
    INDUSTRIAL_SPECIAL = "INDUSTRIAL_SPECIAL"
    ASBESTOS_SPECIAL = "ASBESTOS_SPECIAL"


class SpecialWasteApprovalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"
    EXHAUSTED = "EXHAUSTED"


class TreatmentAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class LeachateShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    REJECTED_AT_GATE = "REJECTED_AT_GATE"
    CANCELLED = "CANCELLED"


class GasWellStatus(str, Enum):
    DRILLED = "DRILLED"
    CONNECTED = "CONNECTED"
    ONLINE = "ONLINE"
    TUNING_REQUIRED = "TUNING_REQUIRED"
    OFFLINE = "OFFLINE"
    ABANDONED = "ABANDONED"


class SurfaceEmissionScanStatus(str, Enum):
    PASSED = "PASSED"
    EXCEEDANCE_OPEN = "EXCEEDANCE_OPEN"
    RESOLVED = "RESOLVED"


class ClosureCostEstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class InstrumentType(str, Enum):
    TRUST_FUND = "TRUST_FUND"
    SURETY_BOND = "SURETY_BOND"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"
    INSURANCE = "INSURANCE"


class HostCommunityAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    TERMINATED = "TERMINATED"


class Landfill(TypedDict):
    id: str
    name: str
    permit_number: str
    permitted_total_airspace_cy: float
    design_footprint_sf: float
    planned_density_tons_per_cy: float
    annual_tonnage_forecast: float
    daily_load_limit: int
    operating_status: str
    gas_collection_status: str
    financial_assurance_status: str
    assurance_funded_amount: float
    certified_airspace_cy: float
    consumed_airspace_cy: float
    remaining_airspace_cy: float
    remaining_life_years: float
    active_cell_count: int
    created_at: str
    updated_at: str
    version: int


class Cell(TypedDict):
    id: str
    landfill_id: str
    cell_code: str
    design_airspace_cy: float
    design_area_sf: float
    liner_type: str
    construction_start_date: str
    construction_end_date: str
    piggyback_over_cell_id: Optional[str]
    status: str
    consumed_airspace_cy: float
    fill_pct: float
    authorized_by_agency_user_id: Optional[str]
    final_cover_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LinerQaPackage(TypedDict):
    id: str
    cell_id: str
    seam_length_ft: float
    destructive_test_count: int
    passing_test_count: int
    panel_count: int
    defect_count: int
    qa_conformance_score: float
    status: str
    revision_round: int
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    certification_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AerialSurvey(TypedDict):
    id: str
    landfill_id: str
    flown_on: str
    coverage_period_start: str
    coverage_period_end: str
    measured_remaining_airspace_cy: float
    tons_placed_in_period: float
    airspace_consumed_in_period_cy: float
    measured_density_tons_per_cy: float
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatingDay(TypedDict):
    id: str
    landfill_id: str
    active_cell_id: str
    operating_date: str
    working_face_area_sf: float
    cover_material_type: str
    tons_placed: float
    effective_density_tons_per_cy: float
    airspace_consumed_cy: float
    status: str
    amend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteLoad(TypedDict):
    id: str
    operating_day_id: str
    hauler_ref: str
    waste_stream: str
    manifest_tons: float
    load_check_result: str
    special_waste_approval_id: Optional[str]
    certified_net_tons: Optional[float]
    screening_status: str
    billing_status: str
    screening_state_reason: Optional[str]
    gate_charge_amount: Optional[float]
    host_royalty_amount: Optional[float]
    final_charge_amount: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SpecialWasteApproval(TypedDict):
    id: str
    landfill_id: str
    generator_name: str
    waste_code: str
    profile_stream: str
    approved_tons_cap: float
    effective_from: str
    expires_on: str
    consumed_tons: float
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentAgreement(TypedDict):
    id: str
    landfill_id: str
    facility_name: str
    daily_gallon_cap: float
    base_haul_fee: float
    treatment_rate_per_kgal: float
    concurrent_slot_capacity: int
    effective_from: str
    expires_on: str
    scheduled_gallons_today: float
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeachateShipment(TypedDict):
    id: str
    treatment_agreement_id: str
    gallons: float
    window_start: str
    window_end: str
    hauler_ref: Optional[str]
    treatment_fee: float
    surcharge_pct: float
    invoice_total: Optional[float]
    status: str
    gate_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GasWell(TypedDict):
    id: str
    cell_id: str
    well_code: str
    depth_ft: float
    last_vacuum_in_h2o: Optional[float]
    last_methane_pct: Optional[float]
    last_oxygen_pct: Optional[float]
    last_tuned_at: Optional[str]
    status: str
    offline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurfaceEmissionScan(TypedDict):
    id: str
    landfill_id: str
    scanned_on: str
    grid_points_count: int
    max_reading_ppm: float
    exceedance_point_ref: Optional[str]
    corrective_well_id: Optional[str]
    status: str
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosureCostEstimate(TypedDict):
    id: str
    landfill_id: str
    estimate_year: int
    closure_unit_cost_per_sf: float
    post_closure_annual_cost: float
    inflation_pct: float
    post_closure_years: int
    closure_cost_total: float
    post_closure_cost_total: float
    required_assurance_amount: float
    funding_shortfall: float
    instrument_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HostCommunityAgreement(TypedDict):
    id: str
    landfill_id: str
    community_name: str
    posted_tipping_fee_per_ton: float
    host_fee_per_ton: float
    tier1_monthly_tons: float
    royalty_tier1_pct: float
    royalty_tier2_pct: float
    minimum_annual_payment: float
    effective_from: str
    expires_on: str
    status: str
    amendment_round: int
    amendment_reason: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemainingLifeProjection(TypedDict):
    landfill_id: str
    variant: str
    remaining_airspace_cy: float
    density_tons_per_cy: float
    annual_tonnage_forecast: float
    remaining_life_years: float
    source_survey_id: Optional[str]
