"""Domain types for the Wet Lease Charter Operations API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LESSOR_OPS_CONTROLLER = "LessorOpsController"
    LESSEE = "Lessee"
    REGULATORY_AUTHORITY = "RegulatoryAuthority"
    MAINTENANCE_CONTROLLER = "MaintenanceController"
    BILLING_ADMIN = "BillingAdmin"
    INSURANCE_UNDERWRITER = "InsuranceUnderwriter"


class LesseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    AOG = "AOG"
    RETIRED = "RETIRED"


class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GROUNDED = "GROUNDED"
    INACTIVE = "INACTIVE"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    CABIN = "CABIN"


class LeaseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REGULATORY_APPROVAL = "PENDING_REGULATORY_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATING = "TERMINATING"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class SuspensionReason(str, Enum):
    INSURANCE_LAPSED = "INSURANCE_LAPSED"
    REGULATORY_APPROVAL_REVOKED = "REGULATORY_APPROVAL_REVOKED"
    AIRFRAME_AOG = "AIRFRAME_AOG"


class ResponsibilityParty(str, Enum):
    LESSOR = "LESSOR"
    LESSEE = "LESSEE"


class SubstitutionRights(str, Enum):
    LESSOR_UNILATERAL = "LESSOR_UNILATERAL"
    LESSEE_CONSENT_REQUIRED = "LESSEE_CONSENT_REQUIRED"


class ReliabilityBasis(str, Enum):
    DEPARTURE = "DEPARTURE"
    SCHEDULED = "SCHEDULED"


class Determination(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class InsuranceCertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CrewQualificationStatus(str, Enum):
    TRAINING = "TRAINING"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LegClass(str, Enum):
    REVENUE = "REVENUE"
    REPOSITIONING = "REPOSITIONING"
    MAINTENANCE_FERRY = "MAINTENANCE_FERRY"


class FlightLegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED_LESSEE = "CANCELLED_LESSEE"
    CANCELLED_LESSOR = "CANCELLED_LESSOR"
    DIVERTED = "DIVERTED"


class BillingState(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONALLY_BILLED = "PROVISIONALLY_BILLED"
    FINALIZED = "FINALIZED"
    CREDITED = "CREDITED"


class CancellingParty(str, Enum):
    LESSEE = "LESSEE"
    LESSOR = "LESSOR"


class CancelReason(str, Enum):
    TECHNICAL = "TECHNICAL"
    COMMERCIAL = "COMMERCIAL"
    WEATHER = "WEATHER"
    CREW = "CREW"
    INSURANCE_LAPSE = "INSURANCE_LAPSE"
    REGULATORY = "REGULATORY"


class SubstitutionReason(str, Enum):
    AOG = "AOG"
    SCHEDULED_MAINTENANCE = "SCHEDULED_MAINTENANCE"
    IRREGULAR_OPS = "IRREGULAR_OPS"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    LESSEE_CONSENT_PENDING = "LESSEE_CONSENT_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class SelectionBasis(str, Enum):
    CLIENT_SPECIFIED = "CLIENT_SPECIFIED"
    SERVER_SELECTED = "SERVER_SELECTED"


class UtilizationPeriodStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_SETTLEMENT = "PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    REOPENED = "REOPENED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementInvoiceStatus(str, Enum):
    PREPARED = "PREPARED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    VOID = "VOID"


class ReliabilityReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReturnConditionStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    DISCREPANCIES_OPEN = "DISCREPANCIES_OPEN"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"


class MaintenanceEventType(str, Enum):
    GROUND_SCHEDULED = "GROUND_SCHEDULED"
    GROUND_AOG = "GROUND_AOG"
    RETURN_TO_SERVICE = "RETURN_TO_SERVICE"
    RETIRE = "RETIRE"


class Lessee(TypedDict):
    id: str
    name: str
    icao_code: str
    home_base_icao: str
    credit_limit_usd_cents: int
    outstanding_balance_usd_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    tail_number: str
    type_designator: str
    type_family: str
    seat_count: int
    mtow_kg: int
    maintenance_program_ref: str
    airframe_hours_total: float
    hours_since_last_check: float
    cycles_since_last_check: int
    assigned_lease_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    employee_no: str
    crew_role: str
    type_ratings: List[str]
    rolling_duty_minutes_7d: int
    rolling_block_minutes_28d: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict):
    id: str
    lessee_id: str
    primary_aircraft_id: str
    term_start_date: str
    term_end_date: str
    block_hour_rate_usd_cents: int
    min_guaranteed_block_hours_per_month: float
    shortfall_credit_pct: float
    crew_provided_by: str
    maintenance_provided_by: str
    insurance_provided_by: str
    operational_control: str
    substitution_rights: str
    reliability_basis: str
    required_maintenance_program_ref: str
    return_hours_since_check_max: float
    return_cycles_since_check_max: int
    return_fuel_kg_required: int
    return_liability_cap_cents: int
    return_deposit_cents: int
    redelivery_icao: str
    return_deposit_applied_cents: int
    return_deposit_remaining_cents: int
    lifetime_credited_block_minutes: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryApproval(TypedDict):
    id: str
    lease_id: str
    authority_docket_no: str
    determination: str
    conditions: List[str]
    open_condition_codes: List[str]
    review_round: int
    decided_at: Optional[str]
    expires_on: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    lease_id: str
    certificate_no: str
    hull_limit_usd_cents: int
    liability_limit_usd_cents: int
    breach_of_warranty_endorsed: bool
    additional_insured_lessee: bool
    effective_from: str
    expires_at: str
    status: str
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewQualification(TypedDict):
    id: str
    crew_member_id: str
    lease_id: str
    differences_training_completed_on: Optional[str]
    checkride_valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict):
    id: str
    lease_id: str
    aircraft_id: str
    captain_id: str
    first_officer_id: str
    origin_icao: str
    dest_icao: str
    leg_class: str
    scheduled_out: str
    scheduled_in: str
    actual_out: Optional[str]
    actual_in: Optional[str]
    technical_delay_minutes: int
    cancelling_party: Optional[str]
    cancel_reason: Optional[str]
    scheduled_block_minutes: int
    block_minutes: int
    billable_block_minutes: int
    status: str
    billing_state: str
    crew_requalification_required: bool
    created_at: str
    updated_at: str
    version: int


class AircraftSubstitution(TypedDict):
    id: str
    lease_id: str
    original_aircraft_id: str
    substitute_aircraft_id: Optional[str]
    reason: str
    effective_from: str
    selection_basis: Optional[str]
    seat_delta: int
    repointed_leg_count: int
    status: str
    consent_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilizationPeriod(TypedDict):
    id: str
    lease_id: str
    period_month: str
    mgh_effective_hours: float
    credited_block_minutes: int
    credited_hours: float
    shortfall_hours: float
    lessor_attributable_shortfall_hours: float
    overrun_hours: float
    base_charge_cents: int
    shortfall_credit_cents: int
    overrun_charge_cents: int
    gross_charge_cents: int
    reliability_penalty_cents: int
    provisional_charge_cents: int
    final_charge_cents: int
    variant_applied: str
    dispute_reason: Optional[str]
    disputed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementInvoice(TypedDict):
    id: str
    period_id: str
    lease_id: str
    variant: str
    amount_cents: int
    line_items: List[dict]
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    due_on: str
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReliabilityReport(TypedDict):
    id: str
    lease_id: str
    aircraft_id: str
    period_month: str
    revenue_departures: int
    scheduled_revenue_legs: int
    technical_delay_events: int
    technical_cancellations: int
    tdr_departure_basis_pct: float
    tdr_scheduled_basis_pct: float
    technical_dispatch_reliability_pct: float
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnCondition(TypedDict):
    id: str
    lease_id: str
    aircraft_id: str
    repositioning_leg_id: Optional[str]
    hours_since_check_at_return: Optional[float]
    cycles_since_check_at_return: Optional[int]
    fuel_on_board_kg: Optional[int]
    discrepancy_codes: List[str]
    discrepancy_cost_cents: int
    billed_to_lessee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
