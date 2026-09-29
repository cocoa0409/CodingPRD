"""Domain types for the Hazard Mitigation Buyout Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Three record types (ParcelAdjacency, MonitoringInspection,
ProgramIncomeLedgerEntry) are append-only audit artifacts and carry only ``id``
and ``created_at`` -- their TypedDicts deliberately omit ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    SUBRECIPIENT_COORDINATOR = "SubrecipientCoordinator"
    STAFF_APPRAISER = "StaffAppraiser"
    REVIEW_APPRAISER = "ReviewAppraiser"
    RELOCATION_SPECIALIST = "RelocationSpecialist"
    COMPLIANCE_MONITOR = "ComplianceMonitor"


# ─── Status enums ─────────────────────────────────────────────────────────────

class MitigationProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CLOSEOUT_PENDING = "CLOSEOUT_PENDING"
    CLOSED_OUT = "CLOSED_OUT"
    DENIED = "DENIED"


class ViabilityStatus(str, Enum):
    VIABLE = "VIABLE"
    AT_RISK = "AT_RISK"
    NONVIABLE = "NONVIABLE"


class BenefitCostAnalysisStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ParticipationStatus(str, Enum):
    NOT_CONTACTED = "NOT_CONTACTED"
    INTERESTED = "INTERESTED"
    VOLUNTARY_CONFIRMED = "VOLUNTARY_CONFIRMED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class AcquisitionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    APPRAISAL_IN_PROGRESS = "APPRAISAL_IN_PROGRESS"
    VALUE_ESTABLISHED = "VALUE_ESTABLISHED"
    OFFER_OUTSTANDING = "OFFER_OUTSTANDING"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    CLOSED = "CLOSED"
    DEMOLISHED = "DEMOLISHED"
    OPEN_SPACE_RECORDED = "OPEN_SPACE_RECORDED"
    ACQUISITION_CANCELLED = "ACQUISITION_CANCELLED"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DobRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class PurchaseOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class RelocationCaseStatus(str, Enum):
    OPENED = "OPENED"
    ELIGIBILITY_DETERMINED = "ELIGIBILITY_DETERMINED"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_PAID = "CLAIM_PAID"
    CLAIM_DENIED = "CLAIM_DENIED"
    APPEALED = "APPEALED"
    CLAIM_DENIED_FINAL = "CLAIM_DENIED_FINAL"


class ClosingRecordStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FUNDED = "FUNDED"
    RECORDED = "RECORDED"


class DemolitionContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DemolitionWorkOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    UTILITY_HOLD = "UTILITY_HOLD"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED_INSPECTION = "FAILED_INSPECTION"
    COMPLETED = "COMPLETED"


class UtilityDisconnectionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class DeedRestrictionStatus(str, Enum):
    RECORDED = "RECORDED"
    IN_COMPLIANCE = "IN_COMPLIANCE"
    VIOLATION_OPEN = "VIOLATION_OPEN"
    CURED = "CURED"
    TERMINATED = "TERMINATED"


class ProgramIncomeEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


# ─── Value enums ──────────────────────────────────────────────────────────────

class GrantProgram(str, Enum):
    HMGP = "HMGP"
    FMA = "FMA"
    BRIC = "BRIC"


class AnalysisMethod(str, Enum):
    FEMA_BCA_TOOLKIT = "FEMA_BCA_TOOLKIT"
    PRE_CALCULATED_BENEFIT = "PRE_CALCULATED_BENEFIT"


class HazardType(str, Enum):
    RIVERINE_FLOOD = "RIVERINE_FLOOD"
    COASTAL_SURGE = "COASTAL_SURGE"
    WILDFIRE = "WILDFIRE"
    LANDSLIDE = "LANDSLIDE"


class SfhaZone(str, Enum):
    AE = "AE"
    VE = "VE"
    A = "A"
    X = "X"


class OccupancyType(str, Enum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    TENANT_OCCUPIED = "TENANT_OCCUPIED"
    VACANT = "VACANT"


class StructureType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MULTI_FAMILY = "MULTI_FAMILY"
    MANUFACTURED_HOME = "MANUFACTURED_HOME"
    NONE = "NONE"


class PreEventValueBasis(str, Enum):
    ASSESSOR_ROLL = "ASSESSOR_ROLL"
    PRE_EVENT_APPRAISAL = "PRE_EVENT_APPRAISAL"
    MARKET_STUDY = "MARKET_STUDY"


class ParticipationDecision(str, Enum):
    INTERESTED = "INTERESTED"
    CONFIRM_VOLUNTARY = "CONFIRM_VOLUNTARY"
    DECLINE = "DECLINE"
    WITHDRAW = "WITHDRAW"


class AppraisalType(str, Enum):
    INITIAL = "INITIAL"
    REVIEW = "REVIEW"


class ValuationBasis(str, Enum):
    PRE_EVENT = "PRE_EVENT"
    POST_EVENT = "POST_EVENT"


class BenefitSource(str, Enum):
    NFIP_CLAIM = "NFIP_CLAIM"
    ICC = "ICC"
    PRIVATE_INSURANCE = "PRIVATE_INSURANCE"
    SBA_LOAN = "SBA_LOAN"
    CDBG_DR = "CDBG_DR"


class OfferBasis(str, Enum):
    PRE_EVENT_FMV = "PRE_EVENT_FMV"
    POST_EVENT_FMV = "POST_EVENT_FMV"


class DisplaceeType(str, Enum):
    OWNER_OCCUPANT = "OWNER_OCCUPANT"
    TENANT_90_DAY = "TENANT_90_DAY"
    TENANT_UNDER_90_DAY = "TENANT_UNDER_90_DAY"
    BUSINESS = "BUSINESS"


class RhpMethod(str, Enum):
    COMPARABLE_DWELLING = "COMPARABLE_DWELLING"
    ACTUAL_REPLACEMENT = "ACTUAL_REPLACEMENT"


class AsbestosSurveyStatus(str, Enum):
    NOT_PERFORMED = "NOT_PERFORMED"
    PERFORMED_POSITIVE = "PERFORMED_POSITIVE"
    ABATED = "ABATED"
    CLEARED = "CLEARED"


class UtilityType(str, Enum):
    WATER = "WATER"
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"
    SEWER = "SEWER"


class DisconnectionOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class DisposalFacilityType(str, Enum):
    LANDFILL = "LANDFILL"
    RECYCLING = "RECYCLING"
    COMBINED = "COMBINED"


class RestrictionType(str, Enum):
    OPEN_SPACE_PERPETUAL = "OPEN_SPACE_PERPETUAL"


class ProhibitedUseCode(str, Enum):
    NEW_STRUCTURE = "NEW_STRUCTURE"
    FILL_PLACEMENT = "FILL_PLACEMENT"
    RESALE_FOR_DEVELOPMENT = "RESALE_FOR_DEVELOPMENT"
    PERMANENT_STORAGE = "PERMANENT_STORAGE"


class InspectionFinding(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROHIBITED_USE_OBSERVED = "PROHIBITED_USE_OBSERVED"


class ProgramIncomeEntryType(str, Enum):
    LEASE_REVENUE = "LEASE_REVENUE"
    SALVAGE_PROCEEDS = "SALVAGE_PROCEEDS"
    EASEMENT_FEE = "EASEMENT_FEE"
    DOB_RECOVERY = "DOB_RECOVERY"
    EXPENDITURE = "EXPENDITURE"


# ─── Entity TypedDicts (id + created_at + updated_at + version) ───────────────

class MitigationProject(TypedDict):
    id: str
    project_code: str
    grant_program: str
    disaster_declaration_number: Optional[str]
    subrecipient_name: str
    cost_share_federal_pct: float
    total_federal_share_cap_cents: int
    period_of_performance_end_date: str
    status: str
    validated_bcr: Optional[float]
    validated_bca_method: Optional[str]
    validated_by_user_id: Optional[str]
    federal_obligated_cents: int
    program_income_balance_cents: int
    protected_open_space_acres: float
    participating_parcel_count: int
    holdout_parcel_count: int
    contiguous_open_space_parcel_count: int
    largest_component_parcel_ids: List[str]
    neighborhood_viability_ratio: float
    viability_status: str
    created_at: str
    updated_at: str
    version: int


class BenefitCostAnalysis(TypedDict):
    id: str
    project_id: str
    analysis_method: str
    hazard_type: str
    sfha_zone: str
    repetitive_loss_flag: bool
    annualized_loss_avoided_cents: int
    project_useful_life_years: int
    discount_rate_pct: float
    mitigation_cost_cents: int
    pv_annuity_factor: float
    npv_benefits_cents: int
    bcr: float
    status: str
    validated_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    project_id: str
    apn: str
    site_address: str
    acreage: float
    occupancy_type: str
    structure_type: str
    substantial_damage_pct: float
    participation_status: str
    acquisition_status: str
    pre_event_fmv_cents: Optional[int]
    pre_event_value_basis: Optional[str]
    pre_event_value_determined_at: Optional[str]
    voluntary_acknowledgement_signed_on: Optional[str]
    dob_deduction_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    parcel_id: str
    appraisal_type: str
    valuation_basis: str
    appraiser_user_id: str
    appraiser_license_no: str
    effective_date: str
    validity_end_date: Optional[str]
    indicated_value_cents: int
    reviewed_appraisal_id: Optional[str]
    status: str
    revision_count: int
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DuplicationOfBenefitsRecord(TypedDict):
    id: str
    parcel_id: str
    benefit_source: str
    amount_cents: int
    repair_documented_cents: int
    received_on: str
    deductible_cents: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOffer(TypedDict):
    id: str
    parcel_id: str
    source_appraisal_id: str
    offer_basis: str
    base_value_cents: int
    dob_deduction_cents: int
    pre_incentive_net_cents: int
    incentive_cents: int
    net_offer_cents: int
    status: str
    presented_at: Optional[str]
    expires_at: Optional[str]
    withdrawal_reason: Optional[str]
    superseded_by_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RelocationCase(TypedDict):
    id: str
    parcel_id: str
    displacee_type: str
    household_reference: str
    rhp_method: str
    acquisition_price_cents: int
    comparable_dwelling_price_cents: int
    actual_purchase_price_cents: int
    current_rent_cents: int
    current_utility_cents: int
    comparable_rent_cents: int
    comparable_utility_cents: int
    monthly_gross_income_cents: int
    moving_expense_cents: int
    rental_assistance_start_date: str
    rental_assistance_end_date: Optional[str]
    rental_assistance_months: int
    replacement_housing_payment_cents: int
    rental_assistance_cents: int
    total_relocation_benefit_cents: int
    status: str
    appeal_count: int
    denial_reason: Optional[str]
    appeal_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosingRecord(TypedDict):
    id: str
    parcel_id: str
    accepted_offer_id: str
    scheduled_closing_date: str
    purchase_price_cents: int
    settlement_cost_cents: int
    status: str
    funded_at: Optional[str]
    funded_by_user_id: Optional[str]
    recording_reference: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemolitionContractor(TypedDict):
    id: str
    name: str
    license_no: str
    asbestos_certified: bool
    max_concurrent_work_orders: int
    status: str
    status_reason: Optional[str]
    active_work_order_count: int
    created_at: str
    updated_at: str
    version: int


class DemolitionWorkOrder(TypedDict):
    id: str
    parcel_id: str
    contractor_id: str
    asbestos_survey_status: str
    scheduled_start: str
    scheduled_end: str
    buffered_start: str
    buffered_end: str
    status: str
    failed_inspection_count: int
    required_utility_types: List[str]
    confirmed_utility_types: List[str]
    total_debris_tons: float
    recycled_tons: float
    diversion_pct: float
    disposal_manifest_no: Optional[str]
    disposal_facility_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilityDisconnection(TypedDict):
    id: str
    work_order_id: str
    utility_type: str
    provider_name: str
    status: str
    failed_attempt_count: int
    confirmation_reference: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeedRestriction(TypedDict):
    id: str
    parcel_id: str
    closing_record_id: str
    restriction_type: str
    prohibited_uses: List[str]
    recorded_on: str
    monitoring_interval_months: int
    next_monitoring_due_date: str
    maintenance_responsible_party: str
    status: str
    corrective_deadline_date: Optional[str]
    open_violation_code: Optional[str]
    violation_reported_by_user_id: Optional[str]
    cured_on: Optional[str]
    termination_authorization_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records (id + created_at ONLY) ───────────────────────────────

class ParcelAdjacency(TypedDict):
    id: str
    project_id: str
    parcel_a_id: str
    parcel_b_id: str
    shared_boundary_feet: float
    created_at: str


class MonitoringInspection(TypedDict):
    id: str
    deed_restriction_id: str
    inspector_user_id: str
    inspection_date: str
    finding: str
    prohibited_use_code: Optional[str]
    narrative: str
    created_at: str


class ProgramIncomeLedgerEntry(TypedDict):
    id: str
    project_id: str
    entry_type: str
    amount_cents: int
    federal_share_cents: int
    posted_on: str
    applied_to_parcel_id: Optional[str]
    reverses_entry_id: Optional[str]
    status: str
    created_at: str
