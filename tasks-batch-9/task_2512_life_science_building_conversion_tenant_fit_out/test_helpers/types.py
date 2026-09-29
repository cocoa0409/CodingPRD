"""Domain types for the Life Science Conversion API.

Enumerations and response shapes for the fourteen peer resources described by
the PRD. Every resource carries ``id``, ``created_at``, ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The five recognised roles, spelled exactly as the PRD spells them."""

    LANDLORD_ASSET_MANAGER = "LandlordAssetManager"
    BASE_BUILDING_ENGINEER = "BaseBuildingEngineer"
    TENANT = "Tenant"
    AHJ_PERMIT_OFFICER = "AHJPermitOfficer"
    COMMISSIONING_AGENT = "CommissioningAgent"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    PARTIALLY_OCCUPIED = "PARTIALLY_OCCUPIED"
    FULLY_OCCUPIED = "FULLY_OCCUPIED"


class VibrationClass(str, Enum):
    VC_A = "VC_A"
    VC_B = "VC_B"
    VC_C = "VC_C"
    VC_D = "VC_D"
    VC_E = "VC_E"


class SuitabilityState(str, Enum):
    DRAFT = "DRAFT"
    ASSESSING = "ASSESSING"
    ASSESSED_SUITABLE = "ASSESSED_SUITABLE"
    ASSESSED_CONDITIONAL = "ASSESSED_CONDITIONAL"
    ASSESSED_UNSUITABLE = "ASSESSED_UNSUITABLE"
    CONVERSION_APPROVED = "CONVERSION_APPROVED"
    CONVERSION_COMPLETE = "CONVERSION_COMPLETE"


class AssessmentBasis(str, Enum):
    SCREENING = "SCREENING"
    INVESTIGATION = "INVESTIGATION"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class Verdict(str, Enum):
    SUITABLE = "SUITABLE"
    SUITABLE_WITH_CONVERSION = "SUITABLE_WITH_CONVERSION"
    UNSUITABLE = "UNSUITABLE"


class AssessmentDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class ScopeDiscipline(str, Enum):
    LAB_EXHAUST = "LAB_EXHAUST"
    EMERGENCY_POWER = "EMERGENCY_POWER"
    CHEMICAL_STORAGE = "CHEMICAL_STORAGE"
    WASTE_HANDLING = "WASTE_HANDLING"


class ScopeItemStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETE = "COMPLETE"


class AmenityType(str, Enum):
    GLASSWASH = "GLASSWASH"
    AUTOCLAVE = "AUTOCLAVE"
    NMR_SUITE = "NMR_SUITE"
    CONFERENCE = "CONFERENCE"
    LOADING_DOCK = "LOADING_DOCK"


class ResearchType(str, Enum):
    BSL2_BIOLOGY = "BSL2_BIOLOGY"
    CHEMISTRY_SYNTHESIS = "CHEMISTRY_SYNTHESIS"
    VIVARIUM = "VIVARIUM"
    ANALYTICAL_QC = "ANALYTICAL_QC"


class CreditTier(str, Enum):
    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    VENTURE_BACKED = "VENTURE_BACKED"
    EARLY_STAGE = "EARLY_STAGE"


class LeaseStatus(str, Enum):
    LOI = "LOI"
    NEGOTIATING = "NEGOTIATING"
    COUNTER_PENDING = "COUNTER_PENDING"
    TERMS_ACCEPTED = "TERMS_ACCEPTED"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    SURRENDERED = "SURRENDERED"


class ProposalStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    EXPIRED = "EXPIRED"
    ACCEPTED = "ACCEPTED"


class ProposedBy(str, Enum):
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"


class PermitStatus(str, Enum):
    """The construction permit dimension of a fit-out project."""

    P_UNPERMITTED = "P_UNPERMITTED"
    P_APPLIED = "P_APPLIED"
    P_ISSUED = "P_ISSUED"


class ConstructionStatus(str, Enum):
    """The construction dimension of a fit-out project."""

    C_NOT_STARTED = "C_NOT_STARTED"
    C_IN_PROGRESS = "C_IN_PROGRESS"
    C_SUSPENDED = "C_SUSPENDED"
    C_SUBSTANTIAL_COMPLETION = "C_SUBSTANTIAL_COMPLETION"
    C_ACCEPTED = "C_ACCEPTED"


class DeliveryRisk(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"


class PhaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    VIBRATION_HOLD = "VIBRATION_HOLD"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class PremiumClass(str, Enum):
    SHELL = "SHELL"
    LAB_MEP = "LAB_MEP"
    VIVARIUM = "VIVARIUM"
    CLEANROOM = "CLEANROOM"


class WorkClass(str, Enum):
    QUIET = "QUIET"
    VIBRATION_GENERATING = "VIBRATION_GENERATING"
    SHUTDOWN_REQUIRED = "SHUTDOWN_REQUIRED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class HazardClass(str, Enum):
    FLAMMABLE_IB = "FLAMMABLE_IB"
    FLAMMABLE_II = "FLAMMABLE_II"
    CORROSIVE = "CORROSIVE"
    OXIDIZER_2 = "OXIDIZER_2"


class UseCondition(str, Enum):
    STORAGE_CABINET = "STORAGE_CABINET"
    CLOSED_SYSTEM_USE = "CLOSED_SYSTEM_USE"
    OPEN_SYSTEM_USE = "OPEN_SYSTEM_USE"


class HazmatPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SURRENDERED = "SURRENDERED"


class HazmatDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    REVOKE = "REVOKE"


class AllocationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


class ScriptType(str, Enum):
    IQ = "IQ"
    OQ = "OQ"
    PQ = "PQ"
    EXHAUST_AIRFLOW = "EXHAUST_AIRFLOW"
    EPSS_LOAD_TEST = "EPSS_LOAD_TEST"
    CONTAINMENT_VERIFICATION = "CONTAINMENT_VERIFICATION"


class CommissioningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CommissioningResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Building(TypedDict, total=False):
    id: str
    name: str
    address_city: str
    occupancy_status: str
    published_floor_to_floor_ft: float
    published_live_load_psf: float
    published_vibration_class: str
    exhaust_riser_capacity_cfm: float
    emergency_power_capacity_kw: float
    chilled_water_capacity_tons: float
    suitability_state: str
    latest_assessment_verdict: Optional[str]
    exhaust_capacity_total_cfm: float
    exhaust_reserved_cfm: float
    exhaust_committed_cfm: float
    exhaust_available_cfm: float
    power_capacity_total_kw: float
    power_reserved_kw: float
    power_committed_kw: float
    power_available_kw: float
    scope_disciplines_covered: List[str]
    scope_disciplines_complete: List[str]
    created_at: str
    updated_at: str
    version: int


class Floor(TypedDict, total=False):
    id: str
    building_id: str
    floor_number: int
    floor_to_floor_ft: float
    live_load_psf: float
    vibration_class: str
    sprinklered: bool
    control_areas_allowed: int
    percent_maq: float
    created_at: str
    updated_at: str
    version: int


class SuitabilityAssessment(TypedDict, total=False):
    id: str
    building_id: str
    assessment_basis: str
    required_vibration_class: str
    required_exhaust_cfm: float
    required_power_kw: float
    measured_floor_to_floor_ft: Optional[float]
    measured_live_load_psf: Optional[float]
    measured_vibration_class: Optional[str]
    height_credit: int
    structural_credit: int
    vibration_credit: int
    utility_credit: int
    utility_headroom_ratio: float
    suitability_score: float
    hard_fail_capped: bool
    verdict: Optional[str]
    status: str
    return_note: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionScopeItem(TypedDict, total=False):
    id: str
    building_id: str
    discipline: str
    description: str
    budget_usd: float
    capacity_delta_cfm: float
    capacity_delta_kw: float
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SharedAmenity(TypedDict, total=False):
    id: str
    building_id: str
    name: str
    amenity_type: str
    serving_floor_number: int
    concurrent_capacity: int
    vibration_sensitive: bool
    utility_draw_kw: float
    created_at: str
    updated_at: str
    version: int


class TenantRecord(TypedDict, total=False):
    id: str
    legal_name: str
    research_type: str
    credit_tier: str
    lab_premium_psf: float
    required_commissioning_scripts: List[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    tenant_id: str
    building_id: str
    premises_floor_id: str
    rentable_sf: int
    term_months: int
    base_rent_psf: float
    delivery_deadline: str
    status: str
    negotiation_round_count: int
    accepted_proposal_round: Optional[int]
    accepted_allowance_psf: Optional[float]
    lab_premium_psf_applied: Optional[float]
    provisional_authorized_ti_usd: Optional[float]
    volume_credit_psf: Optional[float]
    final_allowance_psf: Optional[float]
    ti_authorized_usd: float
    ti_uncommitted_usd: float
    ti_committed_usd: float
    ti_disbursed_usd: float
    ti_forfeited_usd: float
    last_disbursement_usd: float
    restoration_escrow_required_usd: Optional[float]
    restoration_escrow_held_usd: float
    restoration_escrow_refunded_usd: Optional[float]
    restoration_liability_usd: Optional[float]
    restoration_cash_due_usd: Optional[float]
    expiration_date: Optional[str]
    terms_accepted_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TiProposal(TypedDict, total=False):
    id: str
    lease_id: str
    round_number: int
    proposed_by: str
    proposed_allowance_psf: float
    note: Optional[str]
    status: str
    expires_at: str
    authored_by_user_id: str
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FitOutProject(TypedDict, total=False):
    id: str
    lease_id: str
    floor_id: str
    design_exhaust_cfm: float
    design_power_kw: float
    scope_summary: str
    permit_status: str
    construction_status: str
    delivery_risk: str
    required_commissioning_scripts: List[str]
    passed_script_count: int
    permit_applied_at: Optional[str]
    permit_issued_at: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhasePackage(TypedDict, total=False):
    id: str
    project_id: str
    sequence_no: int
    premium_class: str
    work_class: str
    hard_cost_usd: float
    restoration_cost_usd: float
    predecessor_phase_id: Optional[str]
    affected_amenity_id: Optional[str]
    status: str
    prior_status: Optional[str]
    hold_reason: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    ti_eligible_usd: float
    ti_committed_usd: float
    ti_disbursed_usd: float
    created_at: str
    updated_at: str
    version: int


class CapacityReservation(TypedDict, total=False):
    id: str
    project_id: str
    building_id: str
    exhaust_cfm: float
    power_kw: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HazmatPermit(TypedDict, total=False):
    id: str
    project_id: str
    floor_id: str
    hazard_class: str
    use_condition: str
    quantity_gal: float
    control_area_index: int
    allowance_per_control_area_gal: float
    aggregate_allowance_gal: float
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AmenityAllocation(TypedDict, total=False):
    id: str
    amenity_id: str
    project_id: str
    window_start: str
    window_end: str
    headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissioningRecord(TypedDict, total=False):
    id: str
    project_id: str
    script_type: str
    scheduled_for: str
    executed_by_user_id: str
    witnessed_by_user_id: Optional[str]
    result: Optional[str]
    measured_value: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class HazmatUtilizationReport(TypedDict, total=False):
    floor_id: str
    hazard_class: str
    control_area_index: int
    control_areas_allowed: int
    allowance_per_control_area_gal: float
    aggregate_allowance_gal: float
    per_control_area_basis_gal: float
    per_control_area_utilization_pct: float
    aggregate_basis_gal: float
    aggregate_utilization_pct: float
