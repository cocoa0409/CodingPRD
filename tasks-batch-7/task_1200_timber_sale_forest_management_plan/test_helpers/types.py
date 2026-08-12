"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PlatformAdmin = "PlatformAdmin"
    Forester = "Forester"
    Landowner = "Landowner"
    Buyer = "Buyer"
    Contractor = "Contractor"
    AgencyInspector = "AgencyInspector"


class TractStatus(str, Enum):
    OPEN = "OPEN"
    ENROLLED_CONSERVATION = "ENROLLED_CONSERVATION"


class CruiseStatus(str, Enum):
    DRAFT = "DRAFT"
    TALLIED = "TALLIED"
    RECONCILED = "RECONCILED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    BIDDING_OPEN = "BIDDING_OPEN"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    AWARDED = "AWARDED"
    NO_SALE = "NO_SALE"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"
    WINNING = "WINNING"
    LOST = "LOST"


class ContractStatus(str, Enum):
    PENDING_BOND = "PENDING_BOND"
    ACTIVE = "ACTIVE"
    HARVESTING = "HARVESTING"
    SUSPENDED = "SUSPENDED"
    HARVEST_COMPLETE = "HARVEST_COMPLETE"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class BondStatus(str, Enum):
    POSTED = "POSTED"
    FORFEIT_CLAIMED = "FORFEIT_CLAIMED"
    FORFEITED = "FORFEITED"
    RELEASED = "RELEASED"


class TicketStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"
    CORRECTIVE_VERIFIED = "CORRECTIVE_VERIFIED"


class ObligationStatus(str, Enum):
    IMPOSED = "IMPOSED"
    PLANTED = "PLANTED"
    SURVEYED = "SURVEYED"
    SATISFIED = "SATISFIED"
    REPLANT_REQUIRED = "REPLANT_REQUIRED"
    DELINQUENT = "DELINQUENT"


class SurveyStatus(str, Enum):
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class ValuationStatus(str, Enum):
    VALUED = "VALUED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SaleType(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    PER_UNIT = "PER_UNIT"


class ScalingRule(str, Enum):
    DOYLE = "DOYLE"
    INTERNATIONAL_14 = "INTERNATIONAL_14"


class SilviculturalMethod(str, Enum):
    CLEARCUT = "CLEARCUT"
    SHELTERWOOD = "SHELTERWOOD"
    SEED_TREE = "SEED_TREE"
    SELECTION = "SELECTION"
    COMMERCIAL_THINNING = "COMMERCIAL_THINNING"


class SettlementKind(str, Enum):
    PER_UNIT_PERIOD = "PER_UNIT_PERIOD"
    LUMP_MILESTONE = "LUMP_MILESTONE"


class Milestone(str, Enum):
    MOBILIZATION = "MOBILIZATION"
    MIDPOINT = "MIDPOINT"
    COMPLETION = "COMPLETION"


class InspectionType(str, Enum):
    PRE_HARVEST = "PRE_HARVEST"
    ACTIVE_HARVEST = "ACTIVE_HARVEST"
    CLOSEOUT = "CLOSEOUT"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class Recommendation(str, Enum):
    CONSERVATION_FAVORED = "CONSERVATION_FAVORED"
    TIMBER_FAVORED = "TIMBER_FAVORED"


# ---------------------------------------------------------------------------
# Registry entities: common_fields false — ONLY id + created_at, no version.
# ---------------------------------------------------------------------------


class Forester(TypedDict, total=False):
    id: str
    license_no: str
    full_name: str
    email: str
    created_at: str


class Landowner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    tax_id: str
    created_at: str


class Buyer(TypedDict, total=False):
    id: str
    company_name: str
    license_no: str
    prior_defaults: int
    created_at: str


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    license_no: str
    created_at: str


# ---------------------------------------------------------------------------
# Versioned entities (common_fields true) — id + created_at + updated_at + version.
# ---------------------------------------------------------------------------


class ForestTract(TypedDict, total=False):
    id: str
    name: str
    county: str
    total_acres: float
    landowner_id: str
    forester_id: str
    status: str
    conservation_enrollment_start: Optional[str]
    conservation_enrollment_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stand(TypedDict, total=False):
    id: str
    tract_id: str
    name: str
    acres: float
    primary_species: str
    certified_cruise_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryCruise(TypedDict, total=False):
    id: str
    stand_id: str
    cruise_date: str
    plots: List[dict]
    status: str
    reconciled_plot_numbers: Optional[List[int]]
    n_plots: int
    expansion_factor: float
    provisional_volume_bf: Optional[int]
    certified_volume_bf: Optional[int]
    certified_volume_by_species: Optional[List[dict]]
    sampling_error_pct: Optional[float]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestPrescription(TypedDict, total=False):
    id: str
    stand_id: str
    cruise_id: str
    silvicultural_method: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TimberSale(TypedDict, total=False):
    id: str
    tract_id: str
    stand_id: str
    prescription_id: str
    sale_type: str
    scaling_rule: str
    advertised_minimum_cents: int
    species_minimum_rates: Optional[List[dict]]
    bid_open_at: str
    bid_close_at: str
    harvest_window_start: str
    harvest_window_end: str
    status: str
    winning_bid_id: Optional[str]
    awarded_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    sale_id: str
    buyer_id: str
    deposit_cents: int
    lump_sum_amount_cents: Optional[int]
    species_rates: Optional[List[dict]]
    bid_total_cents: int
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestContract(TypedDict, total=False):
    id: str
    sale_id: str
    buyer_id: str
    contractor_id: Optional[str]
    status: str
    awarded_value_cents: int
    governing_scaling_rule: str
    required_bond_amount_cents: int
    cumulative_verified_bf: int
    verified_volume_by_species: List[dict]
    billed_total_cents: int
    disbursed_total_cents: int
    refunded_total_cents: int
    holdback_balance_cents: int
    consulting_fee_total_cents: int
    open_major_findings_count: int
    defaulted_at: Optional[str]
    harvest_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceBond(TypedDict, total=False):
    id: str
    contract_id: str
    amount_cents: int
    status: str
    reforestation_hold_cents: int
    admin_fee_cents: int
    remediation_offset_cents: int
    shortfall_offset_cents: int
    refunded_cents: int
    released_cents: int
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict, total=False):
    id: str
    contract_id: str
    scaled_date: str
    species: str
    small_end_diameter_in: float
    length_ft: float
    log_count: int
    bf_doyle: int
    bf_international: int
    bf_governing: int
    status: str
    flagged_for_review: bool
    recorded_by_id: str
    verified_by_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    contract_id: str
    kind: str
    period_start: Optional[str]
    period_end: Optional[str]
    milestone: Optional[str]
    ticket_ids: List[str]
    gross_cents: int
    holdback_cents: int
    fee_cents: int
    net_cents: int
    status: str
    due_date: Optional[str]
    accrued_interest_cents: int
    created_at: str
    updated_at: str
    version: int


class BMPInspection(TypedDict, total=False):
    id: str
    contract_id: str
    inspection_type: str
    scheduled_date: str
    status: str
    severity: Optional[str]
    remediation_cost_estimate_cents: int
    findings: str
    created_at: str
    updated_at: str
    version: int


class ReforestationObligation(TypedDict, total=False):
    id: str
    contract_id: str
    status: str
    plant_by_date: str
    current_planted_count: int
    planted_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurvivalSurvey(TypedDict, total=False):
    id: str
    obligation_id: str
    survey_date: str
    live_seedlings_count: int
    survival_pct: Optional[float]
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarbonValuation(TypedDict, total=False):
    id: str
    tract_id: str
    annual_credits_tco2e: float
    baseline_credits_tco2e: float
    price_cents_per_tco2e: int
    estimated_timber_net_cents: int
    enrollment_start: str
    enrollment_end: str
    gross_npv_cents: int
    net_npv_cents: int
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int
