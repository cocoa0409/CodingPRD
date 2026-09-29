"""TypedDict shapes and enum vocabularies for every ScriptDrop resource.

Two collections are append-only records of something that already happened, so
they carry only ``id`` and ``created_at``: door-step attempts and courier PHI
disclosures. Every other resource carries the full identity block of ``id``,
``created_at``, ``updated_at`` and ``version``.
"""

from typing import List, Literal, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────

UserRole = Literal[
    "PharmacyOperator",
    "Patient",
    "Courier",
    "PlanAdministrator",
    "NetworkOps",
]

# ─── Enum vocabularies ────────────────────────────────

PayerType = Literal["COMMERCIAL", "MEDICAID", "MEDICARE_ADVANTAGE"]
GrantStatus = Literal["ACTIVE", "EXHAUSTED"]
ControlledLicenseTier = Literal["NONE", "CIII_V", "CII_V"]
ConsentStatus = Literal["GRANTED", "REVOKED"]
CourierMode = Literal["SCHEDULED", "ON_DEMAND"]
WindowStatus = Literal["OPEN", "FULL", "CLOSED"]
ControlledSchedule = Literal["NONE", "CIII", "CII"]
OrderStatus = Literal["INTAKE", "READY", "DISPATCHED", "CLOSED", "RETURNED_TO_STOCK"]
IdVerificationMethod = Literal["NONE", "DOB_MATCH", "PHOTO_ID", "GOVT_ID_SCAN"]
CourierStatus = Literal["OFFLINE", "AVAILABLE", "ON_ROUTE", "SUSPENDED"]
CustodyStatus = Literal[
    "QUEUED",
    "ASSIGNED",
    "PICKED_UP",
    "OUT_FOR_DELIVERY",
    "ATTEMPT_FAILED",
    "DELIVERED",
    "RETURN_PENDING",
    "RETURNED",
    "CANCELLED",
]
SettlementStatus = Literal["PROVISIONAL", "FINALIZED", "WAIVED", "VOIDED"]
HandlingClass = Literal["STANDARD", "COLD_CHAIN", "CONTROLLED", "COLD_CHAIN_CONTROLLED"]
AssignmentStatus = Literal[
    "OFFERED",
    "ACCEPTED",
    "DECLINED",
    "EXPIRED",
    "REVOKED",
    "RELEASED",
    "COMPLETED",
]
# What a courier is allowed to report at the door.
RequestedOutcome = Literal["DELIVERED", "NO_ANSWER", "REFUSED", "ADDRESS_INVALID", "ID_MISMATCH"]
# What the system may actually record: the reported set plus the forced breach.
AttemptOutcome = Literal[
    "DELIVERED",
    "NO_ANSWER",
    "REFUSED",
    "ADDRESS_INVALID",
    "ID_MISMATCH",
    "COLD_BREACH",
]
RecipientRelationship = Literal["SELF", "CAREGIVER", "UNATTENDED"]
AllocationVariant = Literal["PROVISIONAL", "FINAL"]
AllocationStatus = Literal["ACTIVE", "SUPERSEDED", "VOIDED"]
ExceptionType = Literal[
    "COLD_BREACH",
    "ID_MISMATCH_EXHAUSTED",
    "ATTEMPTS_EXHAUSTED",
    "DAMAGED",
    "LOST_IN_TRANSIT",
    "RETURN_OVERDUE",
]
ExceptionStatus = Literal[
    "OPEN",
    "UNDER_REVIEW",
    "RESHIP_AUTHORIZED",
    "CREDIT_ISSUED",
    "DENIED",
    "CLOSED",
]
Disposition = Literal["RESHIP", "CREDIT", "DENY"]
DisclosurePurpose = Literal["ROUTING", "DELIVERY_EXECUTION"]

# ─── Resources with the full identity block ───────────


class HealthPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    payer_type: PayerType
    member_cost_share_pct: float


class PlanGrant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    health_plan_id: str
    benefit_year: int
    grant_budget_cents: int
    per_delivery_cap_cents: int
    committed_cents: int
    consumed_cents: int
    remaining_cents: int
    status: GrantStatus


class Pharmacy(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    cold_chain_certified: bool
    controlled_license_tier: ControlledLicenseTier
    return_window_minutes: int


class Patient(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    date_of_birth: str
    phone_last4: str
    address_line: str
    zone_code: str
    hipaa_consent_status: ConsentStatus
    masked_name: str


class DeliveryZone(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    zone_code: str
    distance_band_miles: float
    base_fee_cents: int
    per_mile_cents: int
    cold_pack_fee_cents: int
    controlled_handling_fee_cents: int
    after_hours_fee_cents: int
    cold_chain_supported: bool
    controlled_delivery_allowed: bool


class DeliveryWindow(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    zone_id: str
    courier_mode: CourierMode
    window_start: str
    window_end: str
    capacity_slots: int
    reserved_slots: int
    available_slots: int
    is_after_hours: bool
    status: WindowStatus


class PharmacyOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    pharmacy_id: str
    patient_id: str
    health_plan_id: str
    rx_line_count: int
    cold_chain_required: bool
    controlled_schedule: ControlledSchedule
    total_rx_value_cents: int
    signature_required: bool
    required_id_verification: IdVerificationMethod
    hold_count: int
    status: OrderStatus


class Courier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    display_name: str
    mode: CourierMode
    served_zone_codes: List[str]
    cold_chain_equipped: bool
    controlled_certified: bool
    status: CourierStatus
    active_delivery_count: int
    attempt_total_count: int
    delivered_count: int
    rolling_reliability_score: float
    lifetime_reliability_score: float


class Delivery(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    window_id: str
    courier_id: Optional[str]
    reship_of_delivery_id: Optional[str]
    custody_status: CustodyStatus
    settlement_status: SettlementStatus
    handling_class: HandlingClass
    signature_required: bool
    required_id_verification: IdVerificationMethod
    attempt_count: int
    last_attempt_at: Optional[str]
    excluded_courier_ids: List[str]
    cold_chain_seal_id: Optional[str]
    picked_up_at: Optional[str]
    delivered_at: Optional[str]
    return_due_at: Optional[str]
    fee_subtotal_cents: int


class CourierAssignment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    delivery_id: str
    courier_id: str
    mode: CourierMode
    status: AssignmentStatus
    offered_at: str
    offer_expires_at: str
    responded_at: Optional[str]
    rank_score: float
    revoked_by_ops_user_id: Optional[str]


class FeeAllocation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    delivery_id: str
    plan_grant_id: Optional[str]
    variant: AllocationVariant
    status: AllocationStatus
    base_line_cents: int
    mileage_line_cents: int
    cold_pack_line_cents: int
    controlled_line_cents: int
    after_hours_line_cents: int
    reattempt_line_cents: int
    fee_subtotal_cents: int
    cost_share_pct_applied: float
    patient_gross_share_cents: int
    plan_grant_cents: int
    absorption_tier_cents: int
    pharmacy_absorption_cents: int
    patient_payable_cents: int
    pharmacy_payable_cents: int


class ExceptionCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    delivery_id: str
    reship_delivery_id: Optional[str]
    exception_type: ExceptionType
    status: ExceptionStatus
    opened_by_ops_user_id: Optional[str]
    adjudicated_by_ops_user_id: Optional[str]
    disposition: Optional[Disposition]
    credit_cents: int
    notes: Optional[str]


# ─── Append-only records: id and created_at only ──────


class DeliveryAttempt(TypedDict):
    id: str
    created_at: str
    delivery_id: str
    courier_id: str
    attempt_no: int
    attempted_at: str
    requested_outcome: RequestedOutcome
    outcome: AttemptOutcome
    id_verification_method: Optional[IdVerificationMethod]
    signature_captured: bool
    recipient_relationship: RecipientRelationship
    pod_photo_ref: Optional[str]
    elapsed_since_pickup_minutes: int
    reliability_credit: float


class CourierDataDisclosure(TypedDict):
    id: str
    created_at: str
    delivery_id: str
    courier_id: str
    disclosed_at: str
    purpose: DisclosurePurpose
    fields_disclosed: List[str]
    redacted_field_count: int
    minimization_profile: str


# ─── Non-entity response shapes ───────────────────────


class CourierView(TypedDict):
    """The minimum-necessary projection a courier is shown for one delivery."""

    delivery_id: str
    order_id: str
    patient_masked_name: str
    patient_phone_last4: str
    address_line: str
    window_start: str
    window_end: str
    handling_class: HandlingClass
    signature_required: bool
    required_id_verification: IdVerificationMethod
    rx_line_count: int
    redacted_field_count: int
    disclosure_id: str


class RoutingRunResult(TypedDict):
    expired_offer_count: int
    closed_window_count: int
    offers_created_count: int
    offered_delivery_ids: List[str]


class ClockState(TypedDict):
    current_utc: str
