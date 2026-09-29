"""Domain types for the Marrow Donor Registry Search & Workup API.

Entity TypedDicts, status enums and the operator role enum, all derived from
the PRD's resource definitions.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


class UserRole(str, Enum):
    TRANSPLANT_COORDINATOR = "TransplantCoordinator"
    DONOR_REGISTRY_LIAISON = "DonorRegistryLiaison"
    MEDICAL_DIRECTOR = "MedicalDirector"
    COLLECTION_CENTER_OPS = "CollectionCenterOps"
    REGISTRY_OPERATIONS = "RegistryOperations"


class CooperationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class UrgencyTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CmvStatus(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class SearchScope(str, Enum):
    DOMESTIC_ONLY = "DOMESTIC_ONLY"
    DOMESTIC_AND_INTERNATIONAL = "DOMESTIC_AND_INTERNATIONAL"


class SearchRequestStatus(str, Enum):
    SEARCHING = "SEARCHING"
    NO_MATCH_FOUND = "NO_MATCH_FOUND"
    PRIMARY_ENGAGED = "PRIMARY_ENGAGED"
    WORKUP_ACTIVE = "WORKUP_ACTIVE"
    BACKUP_REQUIRED = "BACKUP_REQUIRED"
    STALLED = "STALLED"
    FULFILLED = "FULFILLED"


class DonorAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    TEMPORARILY_DEFERRED = "TEMPORARILY_DEFERRED"
    PERMANENTLY_DEFERRED = "PERMANENTLY_DEFERRED"
    WITHDRAWN = "WITHDRAWN"


class MatchCandidateStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    TYPING_REQUESTED = "TYPING_REQUESTED"
    TYPING_RESPONDED = "TYPING_RESPONDED"
    TYPING_EXPIRED = "TYPING_EXPIRED"
    SCREENING_PASSED = "SCREENING_PASSED"
    DEFERRED = "DEFERRED"
    EXCLUDED = "EXCLUDED"
    WORKUP_OPEN = "WORKUP_OPEN"
    COLLECTED = "COLLECTED"
    CLOSED = "CLOSED"


class CandidateRole(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"
    ARCHIVED_POOL = "ARCHIVED_POOL"


class ScreeningOutcome(str, Enum):
    PASS = "PASS"
    DEFER = "DEFER"
    FAIL = "FAIL"


class ScreeningDeferralType(str, Enum):
    NONE = "NONE"
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class TypingRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class LogisticsStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    METHOD_SET = "METHOD_SET"
    BOOKED = "BOOKED"
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    PRODUCT_LOST = "PRODUCT_LOST"


class CollectionMethod(str, Enum):
    PBSC = "PBSC"
    MARROW = "MARROW"


class ClearanceItemType(str, Enum):
    PHYSICAL_EXAM = "PHYSICAL_EXAM"
    IDM_PANEL = "IDM_PANEL"
    CONSENT = "CONSENT"


class ClearanceResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class UnavailabilityReason(str, Enum):
    PERSONAL = "PERSONAL"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    DEFERRAL = "DEFERRAL"
    COLLECTION_WINDOW = "COLLECTION_WINDOW"


class UnavailabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DISCARDED = "DISCARDED"
    CANCELLED = "CANCELLED"


class DoseAdequacy(str, Enum):
    ADEQUATE = "ADEQUATE"
    INADEQUATE = "INADEQUATE"


class ShipmentEventType(str, Enum):
    DEPARTED = "DEPARTED"
    DELIVERED = "DELIVERED"
    LOST = "LOST"


class ConditioningStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    STARTED = "STARTED"
    INFUSED = "INFUSED"
    ABORTED = "ABORTED"


class ConditioningAction(str, Enum):
    SCHEDULE = "SCHEDULE"
    START = "START"
    INFUSE = "INFUSE"
    ABORT = "ABORT"


class FollowUpEventType(str, Enum):
    DAY_7_CONTACT = "DAY_7_CONTACT"
    DAY_30_CONTACT = "DAY_30_CONTACT"
    ONE_YEAR_CONTACT = "ONE_YEAR_CONTACT"
    ADVERSE_EVENT = "ADVERSE_EVENT"


class ClaimStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class ClaimVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ClaimLineType(str, Enum):
    CT_TYPING = "CT_TYPING"
    WORKUP_PHYSICAL = "WORKUP_PHYSICAL"
    IDM_PANEL = "IDM_PANEL"
    COLLECTION = "COLLECTION"
    COURIER = "COURIER"
    DONOR_LOST_WAGE = "DONOR_LOST_WAGE"
    CANCELLATION = "CANCELLATION"


# ---------------------------------------------------------------------------
# Entity shapes.  Resources carrying the four common record properties list
# id / created_at / updated_at / version; the append-only follow-up row lists
# only id and created_at, as the PRD requires.
# ---------------------------------------------------------------------------

class Registry(TypedDict):
    id: str
    code: str
    name: str
    country_code: str
    currency_code: str
    fx_rate_to_usd: float
    is_domestic: bool
    cooperation_status: str
    cooperation_tier: int
    ct_response_deadline_hours: int
    donor_count: int
    created_at: str
    updated_at: str
    version: int


class CollectionCenter(TypedDict):
    id: str
    name: str
    country_code: str
    concurrent_collection_capacity: int
    committed_slot_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    transplant_center_code: str
    country_code: str
    diagnosis_code: str
    urgency_tier: str
    weight_kg: float
    cmv_status: str
    hla_typing: Dict[str, List[str]]
    case_budget_cents: int
    coordinating_user_id: str
    conditioning_status: str
    conditioning_start_date: Optional[str]
    committed_cost_cents: int
    conditioning_aborted_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SearchRequest(TypedDict):
    id: str
    patient_id: str
    search_scope: str
    min_preliminary_score: float
    status: str
    match_pool_size: int
    backup_candidate_count: int
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorProfile(TypedDict):
    id: str
    registry_id: str
    donor_code: str
    age_years: int
    sex: str
    weight_kg: float
    cmv_status: str
    hla_typing_registry: Dict[str, List[str]]
    ambiguous_loci: List[str]
    consented_methods: List[str]
    prior_donation_count: int
    availability_status: str
    deferral_until: Optional[str]
    blocked_day_count: int
    adverse_event_count: int
    last_followup_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchCandidate(TypedDict):
    id: str
    search_request_id: str
    donor_id: str
    preliminary_score: float
    confirmed_score: Optional[float]
    confirmed_match_grade: Optional[str]
    rank_score: float
    rank_position: int
    candidate_role: str
    status: str
    ct_attempt_count: int
    screening_outcome: Optional[str]
    screening_deferral_type: Optional[str]
    promoted_from_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ConfirmatoryTypingRequest(TypedDict):
    id: str
    match_candidate_id: str
    attempt_number: int
    priority_flag: bool
    requested_at: str
    deadline_at: str
    status: str
    responded_at: Optional[str]
    reported_hla_typing: Optional[Dict[str, List[str]]]
    reported_match_grade: Optional[str]
    donor_available_flag: Optional[bool]
    expired_by_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkupCase(TypedDict):
    id: str
    match_candidate_id: str
    case_status: str
    clearance_status: str
    logistics_status: str
    collection_method: Optional[str]
    method_decided_by_user_id: Optional[str]
    physical_cleared_by_user_id: Optional[str]
    idm_resulted_at: Optional[str]
    opened_by_user_id: str
    planned_window_days: int
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearanceItem(TypedDict):
    id: str
    workup_case_id: str
    item_type: str
    result: str
    resulted_at: Optional[str]
    resulted_by_user_id: Optional[str]
    expires_at: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionBooking(TypedDict):
    id: str
    workup_case_id: str
    collection_center_id: str
    method: str
    start_at: str
    end_at: str
    duration_minutes: int
    collection_date: str
    status: str
    confirmed_at: Optional[str]
    cancel_reason: Optional[str]
    cancelled_after_confirmation: bool
    created_at: str
    updated_at: str
    version: int


class DonorUnavailability(TypedDict):
    id: str
    donor_id: str
    source_booking_id: Optional[str]
    date_from: str
    date_to: str
    reason: str
    day_count: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductShipment(TypedDict):
    id: str
    collection_booking_id: str
    collected_at: str
    collected_cd34_e6_per_kg: float
    collected_volume_ml: float
    courier_reference: str
    must_infuse_by: str
    dose_adequacy: str
    status: str
    departed_at: Optional[str]
    delivered_at: Optional[str]
    transit_event_count: int
    created_at: str
    updated_at: str
    version: int


class DonorFollowUp(TypedDict):
    """Immutable append-only audit row: carries only id and created_at."""
    id: str
    donor_id: str
    event_type: str
    severity_grade: int
    description: Optional[str]
    reported_at: str
    triggered_permanent_deferral: bool
    created_at: str


class ReimbursementClaim(TypedDict):
    id: str
    workup_case_id: str
    patient_id: str
    billing_registry_id: str
    status: str
    variant_applied: str
    currency_code: str
    fx_rate_snapshot: float
    line_items: List[Dict[str, Any]]
    subtotal_usd_cents: int
    volume_discount_pct: float
    discount_usd_cents: int
    intl_coordination_fee_usd_cents: int
    total_usd_cents: int
    billed_amount_local_cents: int
    cancellation_fee_applied: bool
    finalized_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
