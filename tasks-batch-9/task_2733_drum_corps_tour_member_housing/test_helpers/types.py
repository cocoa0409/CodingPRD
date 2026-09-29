"""Roles, enumerations and resource shapes declared by the PRD."""

from typing import Any, Dict, List, Optional, TypedDict


class Role:
    """The seven roles, spelled exactly as the PRD spells them."""

    CORPS_DIRECTOR = "CorpsDirector"
    MEMBERSHIP_COORDINATOR = "MembershipCoordinator"
    TOUR_MANAGER = "TourManager"
    BUSINESS_MANAGER = "BusinessManager"
    VOLUNTEER_SCREENER = "VolunteerScreener"
    MEMBER = "Member"
    VOLUNTEER = "Volunteer"

    ALL = [
        CORPS_DIRECTOR,
        MEMBERSHIP_COORDINATOR,
        TOUR_MANAGER,
        BUSINESS_MANAGER,
        VOLUNTEER_SCREENER,
        MEMBER,
        VOLUNTEER,
    ]


class LedgerStatus:
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"


class MembershipStatus:
    APPLICANT = "APPLICANT"
    OFFERED = "OFFERED"
    DECLINED = "DECLINED"
    CONTRACTED = "CONTRACTED"
    ON_TOUR = "ON_TOUR"
    WITHDRAWN = "WITHDRAWN"


class MedicalStatus:
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    SIDELINED = "SIDELINED"


class Section:
    BRASS = "BRASS"
    PERCUSSION = "PERCUSSION"
    COLOR_GUARD = "COLOR_GUARD"


class DietaryFlag:
    NONE = "NONE"
    VEGETARIAN = "VEGETARIAN"
    GLUTEN_FREE = "GLUTEN_FREE"
    SEVERE_ALLERGEN = "SEVERE_ALLERGEN"


class WithdrawalBasis:
    NONE = "NONE"
    PRORATED_SPRING = "PRORATED_SPRING"
    LIQUIDATED_LADDER = "LIQUIDATED_LADDER"


class ContractStatus:
    ISSUED = "ISSUED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SIGNED_BY_MEMBER = "SIGNED_BY_MEMBER"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class PaymentPlanType:
    STANDARD_3 = "STANDARD_3"
    EXTENDED_6 = "EXTENDED_6"


class PlanStatus:
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED_WITH_BALANCE = "CLOSED_WITH_BALANCE"


class PaymentStatus:
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod:
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"


class AgreementStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    CANCELLED = "CANCELLED"


class UsageType:
    SPRING_TRAINING = "SPRING_TRAINING"
    TOUR_REHEARSAL = "TOUR_REHEARSAL"


class HousingStatus:
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleasedReason:
    MANUAL = "MANUAL"
    MEMBER_WITHDRAWN = "MEMBER_WITHDRAWN"
    AGREEMENT_CANCELLED = "AGREEMENT_CANCELLED"
    STOP_CANCELLED = "STOP_CANCELLED"
    SCREENING_EXPIRED = "SCREENING_EXPIRED"


class StopType:
    SHOW = "SHOW"
    REHEARSAL_ONLY = "REHEARSAL_ONLY"


class StopStatus:
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementState:
    NONE = "NONE"
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class BookingStatus:
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class VolunteerRoleType:
    DRIVER = "DRIVER"
    COOK = "COOK"
    CHAPERONE = "CHAPERONE"
    ATHLETIC_TRAINER = "ATHLETIC_TRAINER"


class ScreeningStatus:
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ScreeningDecision:
    CLEAR = "CLEAR"
    REJECT = "REJECT"


class Duty:
    DRIVE = "DRIVE"
    COOK = "COOK"
    CHAPERONE = "CHAPERONE"
    TRAINER = "TRAINER"


class StaffAssignmentStatus:
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


class SettlementStatus:
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class RemittanceKind:
    PRIZE_ADJUSTMENT = "PRIZE_ADJUSTMENT"
    SANCTION_FEE = "SANCTION_FEE"
    FEE_REBATE = "FEE_REBATE"


class AuditionDecision:
    OFFER = "OFFER"
    DECLINE = "DECLINE"


# Duty <-> role_type pairing pinned by the PRD.
DUTY_FOR_ROLE_TYPE = {
    VolunteerRoleType.DRIVER: Duty.DRIVE,
    VolunteerRoleType.COOK: Duty.COOK,
    VolunteerRoleType.CHAPERONE: Duty.CHAPERONE,
    VolunteerRoleType.ATHLETIC_TRAINER: Duty.TRAINER,
}


class CommonFields(TypedDict):
    """The four server-managed properties every resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Season(CommonFields):
    name: str
    year: int
    tuition_base_cents: int
    spring_training_start_date: str
    spring_training_end_date: str
    tour_departure_date: str
    billing_epoch: int
    tuition_charged_cents: int
    tuition_collected_cents: int
    late_fee_collected_cents: int
    housing_cost_cents: int
    tour_revenue_cents: int
    ledger_status: str


class Member(CommonFields):
    season_id: str
    full_name: str
    email: str
    date_of_birth: str
    section: str
    dietary_flag: str
    is_minor: bool
    membership_status: str
    medical_status: str
    audition_score: Optional[float]
    tuition_charged_cents: int
    tuition_paid_cents: int
    tuition_balance_cents: int
    refund_due_cents: int
    withdrawal_date: Optional[str]
    withdrawal_obligation_cents: Optional[int]
    withdrawal_obligation_basis: str


class MemberContract(CommonFields):
    member_id: str
    tuition_amount_cents: int
    payment_plan_type: str
    status: str
    revision_round: int
    revision_note: Optional[str]
    signature_name: Optional[str]
    signed_at: Optional[str]
    executed_at: Optional[str]


class PaymentPlan(CommonFields):
    member_id: str
    member_contract_id: str
    plan_type: str
    principal_cents: int
    surcharge_cents: int
    financed_total_cents: int
    installment_count: int
    installment_base_cents: int
    installment_remainder_cents: int
    first_due_date: str
    status: str
    delinquency_strikes: int
    principal_paid_cents: int
    late_fee_accrued_cents: int
    late_fee_paid_cents: int
    installments_due_count: int
    due_amount_cents: int
    arrears_cents: int
    outstanding_cents: int


class TuitionPayment(CommonFields):
    payment_plan_id: str
    amount_cents: int
    received_on: str
    method: str
    allocated_to_late_fee_cents: int
    allocated_to_principal_cents: int
    status: str
    reversal_reason: Optional[str]
    reversed_at: Optional[str]


class HostSchool(CommonFields):
    name: str
    city: str
    state_code: str
    sleeping_space_count: int
    capacity_per_space: int
    rehearsal_field_count: int
    has_air_conditioning: bool
    booked_block_count: int
    reserved_bed_nights: int


class FacilityAgreement(CommonFields):
    host_school_id: str
    season_id: str
    usage_type: str
    start_date: str
    end_date: str
    nightly_rate_cents: int
    countered_nightly_rate_cents: Optional[int]
    effective_nightly_rate_cents: Optional[int]
    minimum_billable_beds: int
    status: str
    counter_round: int
    occupied_bed_nights: int
    billable_bed_nights: int
    billable_cents: int
    cancel_reason: Optional[str]


class HousingAssignment(CommonFields):
    facility_agreement_id: str
    member_id: str
    space_index: int
    check_in_date: str
    check_out_date: str
    nights: int
    occupant_is_minor: bool
    status: str
    released_reason: Optional[str]


class TourStop(CommonFields):
    season_id: str
    previous_stop_id: Optional[str]
    stop_type: str
    venue_name: str
    city: str
    state_code: str
    arrive_at: str
    depart_at: str
    show_start_at: Optional[str]
    travel_miles_from_previous: int
    uniform_trunks: int
    instrument_cases: int
    prop_units: int
    truck_count: int
    rehearsal_minutes: int
    heat_index_f: int
    total_load_cuft: int
    total_load_lbs: int
    trucks_required: int
    required_travel_minutes: int
    roster_head_count: int
    minor_head_count: int
    required_chaperone_count: int
    required_cook_count: int
    meal_cost_cents: int
    status: str
    settlement_state: str
    cancel_reason: Optional[str]


class SiteBooking(CommonFields):
    tour_stop_id: str
    host_school_id: str
    facility_agreement_id: str
    block_start_at: str
    block_end_at: str
    indoor: bool
    status: str
    released_reason: Optional[str]


class Volunteer(CommonFields):
    full_name: str
    email: str
    role_type: str
    cdl_number: Optional[str]
    credential_id: Optional[str]
    screening_status: str
    screening_decided_on: Optional[str]
    screening_expires_on: Optional[str]
    screened_by_user_id: Optional[str]
    assignment_count: int


class StaffAssignment(CommonFields):
    volunteer_id: str
    tour_stop_id: str
    duty: str
    shift_start_at: str
    shift_end_at: str
    status: str
    approved_by_user_id: Optional[str]
    released_reason: Optional[str]


class ShowSettlement(CommonFields):
    tour_stop_id: str
    appearance_fee_cents: int
    prize_pool_cents: int
    projected_placement: int
    final_placement: Optional[int]
    provisional_prize_cents: int
    provisional_gross_cents: int
    provisional_circuit_fee_cents: int
    provisional_net_cents: int
    final_prize_cents: Optional[int]
    final_gross_cents: Optional[int]
    final_circuit_fee_cents: Optional[int]
    sanctions_charged_cents: Optional[int]
    rebate_applied_cents: Optional[int]
    final_net_cents: Optional[int]
    variance_cents: Optional[int]
    remittance_line_count: int
    status: str
    prepared_by_user_id: str
    finalized_by_user_id: Optional[str]


RemittanceLine = Dict[str, Any]
JsonDict = Dict[str, Any]
JsonList = List[Any]
