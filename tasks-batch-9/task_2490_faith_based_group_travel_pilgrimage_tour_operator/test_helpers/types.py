"""Typed shapes for every row the pilgrimage tour-operator API returns.

Mirrors PRD §2.5: every row carries `id` (a bare UUID) and `created_at`.
Twelve of the thirteen record types also carry `updated_at` and `version`.
Cash receipts are the exception -- a `Payment` row carries only `id` and
`created_at`, so `PaymentRow` deliberately omits the mutation columns.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1 / §4)
# ---------------------------------------------------------------------------

UserRole = Literal[
    "ProgramManager",
    "RiskOfficer",
    "AirDeskAgent",
    "LandContractor",
    "FinanceController",
    "ProtectionAdministrator",
    "GroupLeader",
]

OPERATOR_ROLES: tuple[str, ...] = (
    "ProgramManager",
    "RiskOfficer",
    "AirDeskAgent",
    "LandContractor",
    "FinanceController",
    "ProtectionAdministrator",
)

ALL_ROLES: tuple[str, ...] = OPERATOR_ROLES + ("GroupLeader",)


# ---------------------------------------------------------------------------
# Enumerated vocabularies
# ---------------------------------------------------------------------------

FaithTradition = Literal["CATHOLIC", "PROTESTANT", "ORTHODOX", "JEWISH", "MUSLIM", "INTERFAITH"]

DepartureStatus = Literal[
    "PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED", "OPERATED", "CANCELLED"
]
RiskPosture = Literal["OPEN", "WATCH", "RESTRICTED", "SUSPENDED"]

AgreementStatus = Literal["PENDING_COUNTERSIGN", "ACTIVE", "SETTLED", "TERMINATED"]
CommissionMode = Literal["PER_PAX_CASH", "FREE_SEAT_CREDIT", "HYBRID"]
AccrualBasis = Literal["RECRUITED", "TRAVELED"]

BookingStatus = Literal[
    "INQUIRY", "DEPOSITED", "CONFIRMED", "IN_DEFAULT", "CANCELLED"
]
PaymentStatus = Literal[
    "UNPAID", "DEPOSIT_PAID", "PLAN_ACTIVE", "PAID_IN_FULL", "REFUNDED"
]
ProtectionMirrorStatus = Literal[
    "NONE",
    "QUOTED",
    "MEDICAL_REVIEWED",
    "WAIVER_APPROVED",
    "WAIVER_DECLINED",
    "PURCHASED",
    "VOIDED",
]
RoomType = Literal["SINGLE", "DOUBLE", "TWIN"]
MobilityCode = Literal["NONE", "CANE", "WALKER", "WHEELCHAIR"]
DeviationType = Literal["NONE", "ORIGIN_CHANGE", "DATE_DEVIATION", "CLASS_UPGRADE"]

PlanType = Literal["SINGLE_BALANCE", "MONTHLY_3", "MONTHLY_6"]
PlanStatus = Literal["ACTIVE", "COMPLETED", "DEFAULTED", "SUPERSEDED"]
InstallmentStatus = Literal[
    "SCHEDULED", "PARTIALLY_PAID", "PAID", "PAST_DUE", "WAIVED"
]

PaymentMethod = Literal["CARD", "ACH", "CHECK", "PARISH_TRANSFER"]
PaymentState = Literal["APPLIED", "REVERSED"]

AirBlockStatus = Literal["DRAFT", "OFFERED", "COUNTERED", "CONFIRMED", "EXPIRED", "RELEASED"]
NegotiationParty = Literal["CARRIER_OFFER", "OPERATOR_COUNTER"]

AccessRegime = Literal["OPEN_ACCESS", "PERMIT_REQUIRED", "TICKETED_SLOT"]
ServiceType = Literal["MASS", "LITURGY", "PRAYER_SERVICE", "GUIDED_VISIT"]
ServiceBookingStatus = Literal["SITE_HELD", "CLERGY_CONFIRMED", "CONFIRMED", "CANCELLED"]

ResourceType = Literal["HOTEL_ROOM_BLOCK", "MOTORCOACH", "GUIDE"]
LandAssignmentStatus = Literal["DRAFT", "COUNTERSIGNED", "TERMINATED"]

ProtectionPlanCode = Literal["BASIC", "STANDARD", "PREMIER"]
ProtectionStatus = Literal[
    "QUOTED",
    "MEDICAL_REVIEWED",
    "WAIVER_APPROVED",
    "WAIVER_DECLINED",
    "PURCHASED",
    "VOIDED",
]
AgeBand = Literal["A", "B", "C", "D"]

AdvisoryLevel = Literal["NORMAL", "EXERCISE_CAUTION", "RECONSIDER", "DO_NOT_TRAVEL"]
AdvisoryStatus = Literal["DRAFT", "PUBLISHED", "SUPERSEDED"]


# ---------------------------------------------------------------------------
# Common column groups (PRD §2.5)
# ---------------------------------------------------------------------------


class MutableRow(TypedDict):
    """The four columns twelve of the thirteen record types share."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ReceiptRow(TypedDict):
    """The two columns a cash receipt carries -- no `updated_at`, no `version`."""

    id: str
    created_at: str


# ---------------------------------------------------------------------------
# Entity row shapes
# ---------------------------------------------------------------------------


class PriceTier(TypedDict):
    tier_code: str
    min_pax: int
    max_pax: int
    per_pax_price_cents: int
    single_supplement_cents: int
    deposit_cents: int


class CancellationBucket(TypedDict):
    min_days_before: int
    penalty_bp: int


class ProgramRow(MutableRow):
    name: str
    destination_country: str
    faith_tradition: str
    duration_days: int
    price_tiers: list[PriceTier]
    cancellation_grid: list[CancellationBucket]
    departure_count: int


class DepartureRow(MutableRow):
    program_id: str
    departure_date: str
    return_date: str
    min_pax: int
    max_pax: int
    deposit_due_date: str
    final_payment_due_date: str
    mobility_accessible_coach: bool
    status: str
    risk_posture: str
    governing_advisory_id: str | None
    paying_pax_count: int
    provisional_tier_code: str | None
    provisional_per_pax_price_cents: int
    provisional_single_supplement_cents: int
    provisional_deposit_cents: int
    final_tier_code: str | None
    final_per_pax_price_cents: int
    land_cost_total_cents: int
    itinerary_cost_delta_cents: int
    service_coverage_ok: bool
    pending_modification_required: bool
    pending_modification_reason: str | None
    pending_modification_proposed_by_user_id: str | None
    pending_modification_cost_delta_cents: int
    ratified_modification_count: int
    sweep_run_count: int
    last_sweep_at: str | None


class GroupLeaderAgreementRow(MutableRow):
    departure_id: str
    leader_name: str
    leader_user_id: str
    free_travel_threshold: int
    commission_mode: str
    commission_rate_cents_per_pax: int
    accrual_basis: str
    status: str
    recruited_paying_count: int
    earned_free_seats: int
    free_seats_granted_count: int
    commission_payable_cents: int
    settled_recruited_count: int
    settled_earned_free_seats: int
    settled_commission_cents: int
    superseded_by_agreement_id: str | None


class PilgrimRow(MutableRow):
    departure_id: str
    recruited_by_agreement_id: str | None
    roommate_pilgrim_id: str | None
    full_name: str
    date_of_birth: str
    age_at_departure: int
    room_type_requested: str
    room_type_assigned: str | None
    room_label: str | None
    ground_floor: bool
    dietary_codes: list[str]
    mobility_code: str
    risk_acknowledged: bool
    is_free_seat_grant: bool
    is_paying: bool
    booking_status: str
    payment_status: str
    protection_status: str
    price_locked_cents: int | None
    single_supplement_applied_cents: int
    deviation_type: str
    deviation_fee_cents: int
    invoice_total_cents: int
    protection_premium_cents: int
    cash_applied_cents: int
    credit_balance_cents: int
    ticketed_name: str | None
    refund_cents: int
    penalty_retained_cents: int


class Installment(TypedDict):
    sequence_no: int
    due_date: str
    amount_due_cents: int
    amount_paid_cents: int
    status: str


class PaymentPlanRow(MutableRow):
    pilgrim_id: str
    plan_type: str
    first_due_date: str
    installment_count: int
    total_scheduled_cents: int
    installments: list[Installment]
    past_due_count: int
    status: str
    superseded_by_plan_id: str | None


class AllocationEntry(TypedDict):
    target: str
    sequence_no: int | None
    amount_cents: int


class PaymentRow(ReceiptRow):
    """Cash receipt. Deliberately carries no `updated_at` and no `version`."""

    pilgrim_id: str
    amount_cents: int
    method: str
    received_at: str
    status: str
    allocation: list[AllocationEntry]
    reversed_at: str | None


class AirBlockRow(MutableRow):
    departure_id: str
    carrier_code: str
    seats_held: int
    offered_fare_cents: int
    countered_fare_cents: int | None
    contracted_fare_cents: int | None
    negotiation_round: int
    name_change_deadline_utc: str
    deposit_deadline_utc: str
    seats_assigned: int
    status: str


class SacredSiteRow(MutableRow):
    name: str
    country: str
    access_regime: str
    daily_capacity_pax: int
    turnaround_buffer_minutes: int
    requires_local_clergy: bool


class ServiceBookingRow(MutableRow):
    departure_id: str
    sacred_site_id: str
    service_type: str
    scheduled_start_utc: str
    duration_minutes: int
    buffered_end_utc: str
    pax_count: int
    permit_reference: str | None
    clergy_contact_name: str | None
    clergy_tradition: str | None
    status: str
    cancelled_by_risk: bool


class LandResourceRow(MutableRow):
    operator_name: str
    country: str
    resource_type: str
    units_total: int
    unit_rate_local_cents: int
    fx_rate_bp: int
    force_majeure_notice_days: int


class LandAssignmentRow(MutableRow):
    land_resource_id: str
    departure_id: str
    date_from: str
    date_to: str
    units_requested: int
    days_inclusive: int
    line_local_cents: int
    line_usd_cents: int
    status: str
    terminated_penalty_free: bool


class TravelProtectionRow(MutableRow):
    pilgrim_id: str
    plan_code: str
    medical_limit_cents: int
    pre_existing_waiver_requested: bool
    insured_trip_cost_cents: int
    age_band: str
    base_premium_cents: int
    medical_uplift_cents: int
    waiver_surcharge_cents: int
    premium_cents: int
    questionnaire_complete: bool
    stable_period_days: int
    medical_review_by_user_id: str | None
    waiver_eligible: bool
    status: str
    deposit_reference_date: str | None


class RiskAdvisoryRow(MutableRow):
    country: str
    level: str
    effective_from: str
    source: str
    status: str
    affected_departure_count: int


# ---------------------------------------------------------------------------
# Envelope shapes (PRD §2.2)
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict):
    api_request_id: str
    api_request_timestamp: str
    limit: int | None
    offset: int | None
    total_count: int | None
    has_more: bool | None


class ErrorPayload(TypedDict):
    error_id: str
    message: str


AnyRow = dict[str, Any]

__all__ = [name for name in dir() if not name.startswith("_")]
