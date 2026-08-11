"""Domain types for the Direct-Mail & Handwritten-Note Fulfillment API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Three resource types are append-only records that carry only ``id``
and ``created_at`` -- PostageLedgerEntry, ReturnEvent and BlackoutDate -- and
their TypedDicts therefore omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_OWNER = "AccountOwner"
    CAMPAIGN_MANAGER = "CampaignManager"
    LIST_OPERATOR = "ListOperator"
    PRODUCTION_OPERATOR = "ProductionOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CampaignLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class CampaignComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"


class CampaignBillingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WriteGate(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"


class ImportStatus(str, Enum):
    UPLOADED = "UPLOADED"
    CASS_RUN = "CASS_RUN"
    DEDUPED = "DEDUPED"
    LOCKED = "LOCKED"


class DedupeMode(str, Enum):
    EXACT = "EXACT"
    HOUSEHOLD = "HOUSEHOLD"


class CassStatus(str, Enum):
    PENDING = "PENDING"
    STANDARDIZED = "STANDARDIZED"
    UNMAILABLE = "UNMAILABLE"


class DeliverabilityTier(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    AUTOMATION = "AUTOMATION"
    RETAIL = "RETAIL"
    UNMAILABLE = "UNMAILABLE"


class DedupeStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    UNIQUE = "UNIQUE"
    HOUSEHOLD_HEAD = "HOUSEHOLD_HEAD"
    DUP_EXACT = "DUP_EXACT"
    DUP_HOUSEHOLD = "DUP_HOUSEHOLD"


class MailStatus(str, Enum):
    NOT_MAILED = "NOT_MAILED"
    QUEUED = "QUEUED"
    MAILED = "MAILED"
    DELIVERED_ASSUMED = "DELIVERED_ASSUMED"
    RETURNED = "RETURNED"


class MoveStatus(str, Enum):
    NONE = "NONE"
    MOVE_APPLIED = "MOVE_APPLIED"
    MOVE_NO_FORWARD = "MOVE_NO_FORWARD"


class DpvConfirmationCode(str, Enum):
    Y = "Y"
    D = "D"
    S = "S"
    N = "N"
    U = "U"


class JobKind(str, Enum):
    ADDRESSED = "ADDRESSED"
    EDDM = "EDDM"


class MailClass(str, Enum):
    FIRST_CLASS = "FIRST_CLASS"
    MARKETING_MAIL = "MARKETING_MAIL"
    EDDM = "EDDM"


class EddmRateVariant(str, Enum):
    SATURATION = "SATURATION"
    HIGH_DENSITY_PLUS = "HIGH_DENSITY_PLUS"


class MailJobStatus(str, Enum):
    DRAFT = "DRAFT"
    PROOFED = "PROOFED"
    SCHEDULED = "SCHEDULED"
    COMMITTED = "COMMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    MAILED = "MAILED"
    CLOSED = "CLOSED"


class PresortTier(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    PRESORT_5D = "PRESORT_5D"
    PRESORT_AADC = "PRESORT_AADC"
    PRESORT_MIXED_AADC = "PRESORT_MIXED_AADC"
    NO_PRESORT = "NO_PRESORT"
    EDDM_ROUTE = "EDDM_ROUTE"


class ProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class EnvelopeStyle(str, Enum):
    STANDARD = "STANDARD"
    WINDOW = "WINDOW"
    HAND_ADDRESSED = "HAND_ADDRESSED"


class PenType(str, Enum):
    GEL = "GEL"
    FOUNTAIN = "FOUNTAIN"
    ROLLERBALL = "ROLLERBALL"


class InkType(str, Enum):
    INK_BLUE_A = "INK_BLUE_A"
    INK_BLACK_B = "INK_BLACK_B"
    INK_NAVY_C = "INK_NAVY_C"


class MachineStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class InkLotStatus(str, Enum):
    SEALED = "SEALED"
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class CapacityVariant(str, Enum):
    SINGLE_PASS = "SINGLE_PASS"
    SPLIT_RUN = "SPLIT_RUN"


class ProductionRunStatus(str, Enum):
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class AnchorVariant(str, Enum):
    ANCHOR_IN_HOME = "ANCHOR_IN_HOME"
    ANCHOR_MAIL_DATE = "ANCHOR_MAIL_DATE"


class DripScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class DripStepStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    MAILED = "MAILED"
    CANCELLED = "CANCELLED"


class EntryType(str, Enum):
    TOPUP = "TOPUP"
    DRAW = "DRAW"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"


class ReturnReason(str, Enum):
    MOVED_NO_FORWARD = "MOVED_NO_FORWARD"
    VACANT = "VACANT"
    REFUSED = "REFUSED"
    INSUFFICIENT_ADDRESS = "INSUFFICIENT_ADDRESS"


class Entitlement(str, Enum):
    REPRINT = "REPRINT"
    REFUND = "REFUND"


class ReprintRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Entity shapes (resources that carry id + created_at + updated_at + version)
# --------------------------------------------------------------------------
class Account(TypedDict):
    id: str
    name: str
    permit_number: str
    permit_balance_cents: int
    lifetime_topup_cents: int
    lifetime_draw_cents: int
    lifetime_refund_cents: int
    lifetime_forfeit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    account_id: str
    name: str
    lifecycle_status: str
    compliance_status: str
    billing_status: str
    write_gate: str
    hold_reason: Optional[str]
    mailed_piece_count: int
    returned_piece_count: int
    committed_postage_cents: int
    refunded_postage_cents: int
    forfeited_postage_cents: int
    created_at: str
    updated_at: str
    version: int


class HandwritingStyle(TypedDict):
    id: str
    name: str
    pen_type: str
    ink_type: str
    chars_per_minute: int
    ink_ul_per_1000_chars: float
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    account_id: str
    handwriting_style_id: str
    name: str
    body_text: str
    character_count: int
    version_no: int
    envelope_style: str
    created_at: str
    updated_at: str
    version: int


class MailingList(TypedDict):
    id: str
    account_id: str
    name: str
    import_status: str
    dedupe_mode: Optional[str]
    record_count: int
    automation_count: int
    retail_count: int
    unmailable_count: int
    duplicate_count: int
    mailable_count: int
    created_at: str
    updated_at: str
    version: int


class ListRecord(TypedDict):
    id: str
    mailing_list_id: str
    first_name: str
    last_name: str
    address_line1: str
    address_line2: Optional[str]
    city: str
    state_code: str
    zip5: str
    country_code: str
    dpv_confirmation_code: str
    cass_status: str
    deliverability_tier: str
    dedupe_status: str
    mail_status: str
    move_status: str
    exact_key: str
    household_key: str
    reprint_count: int
    last_mail_job_id: Optional[str]
    insertion_seq: int
    created_at: str
    updated_at: str
    version: int


class MailJob(TypedDict):
    id: str
    campaign_id: str
    template_id: str
    mailing_list_id: Optional[str]
    job_kind: str
    mail_class: str
    eddm_rate_variant: Optional[str]
    status: str
    pinned_template_version: Optional[int]
    automation_piece_count: int
    retail_piece_count: int
    unmailable_piece_count: int
    eddm_piece_count: int
    billable_piece_count: int
    presort_tier: str
    provisional_postage_cents: Optional[int]
    final_postage_cents: Optional[int]
    handling_fee_cents: Optional[int]
    volume_credit_cents: Optional[int]
    total_due_cents: Optional[int]
    drawn_postage_cents: int
    refunded_postage_cents: int
    returned_piece_count: int
    target_in_home_date: Optional[str]
    mail_date: Optional[str]
    blackout_shifted_days: int
    scheduled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EddmRouteSelection(TypedDict):
    id: str
    mail_job_id: str
    route_code: str
    total_deliveries: int
    residential_piece_count: int
    business_piece_count: int
    selected_piece_count: int
    saturation_pct: float
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    mail_job_id: str
    template_id: str
    pinned_template_version: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WritingMachine(TypedDict):
    id: str
    machine_code: str
    daily_capacity_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InkLot(TypedDict):
    id: str
    lot_code: str
    ink_type: str
    initial_volume_ul: int
    remaining_ul: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    mail_job_id: str
    machine_id: str
    ink_lot_id: str
    run_date: str
    piece_count: int
    capacity_variant: str
    planned_write_minutes: int
    planned_slot_minutes: int
    planned_ink_ul: int
    status: str
    spoiled_piece_count: int
    created_at: str
    updated_at: str
    version: int


class DripSchedule(TypedDict):
    id: str
    campaign_id: str
    name: str
    anchor_variant: str
    status: str
    step_count: int
    created_at: str
    updated_at: str
    version: int


class DripStep(TypedDict):
    id: str
    drip_schedule_id: str
    mail_job_id: str
    sequence_no: int
    anchor_date: str
    computed_mail_date: Optional[str]
    computed_in_home_date: Optional[str]
    shifted_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReprintRequest(TypedDict):
    id: str
    list_record_id: str
    return_event_id: str
    campaign_id: str
    status: str
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only records: id + created_at only, no updated_at and no version
# --------------------------------------------------------------------------
class PostageLedgerEntry(TypedDict):
    id: str
    account_id: str
    mail_job_id: Optional[str]
    campaign_id: Optional[str]
    entry_type: str
    amount_cents: int
    signed_amount_cents: int
    balance_after_cents: int
    reason: Optional[str]
    created_at: str


class ReturnEvent(TypedDict):
    id: str
    list_record_id: str
    mail_job_id: str
    return_reason: str
    entitlement: str
    return_fee_cents: int
    created_at: str


class BlackoutDate(TypedDict):
    id: str
    blackout_date: str
    reason: str
    created_at: str


APPEND_ONLY_ENTITIES = ("PostageLedgerEntry", "ReturnEvent", "BlackoutDate")
