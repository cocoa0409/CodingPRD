"""Status vocabularies, role names and entity shapes for the Statement
Composition & Print-Mail Bureau API.

Every enum member is a literal drawn from the API contract. The TypedDicts
document which keys each entity's ``data`` payload is expected to carry; they
are used for readability and by the per-entity assertion helpers.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class Role(str, Enum):
    """The six operator roles. Every role carries opaque identity: the
    ``X-User-ID`` header is never compared against any entity's ``id``."""

    BUREAU_ADMIN = "BureauAdmin"
    CLIENT_LIAISON = "ClientLiaison"
    COMPOSITION_OPERATOR = "CompositionOperator"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    POSTAGE_CONTROLLER = "PostageController"
    INTEGRITY_AUDITOR = "IntegrityAuditor"


ALL_ROLES: List[str] = [r.value for r in Role]


# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    REVOKED = "REVOKED"


class EnrollmentChannel(str, Enum):
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"


class InsertStockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    WITHDRAWN = "WITHDRAWN"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MailClass(str, Enum):
    FIRST_CLASS = "FIRST_CLASS"
    MARKETING = "MARKETING"


class DataFileStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FORMAT_VALIDATED = "FORMAT_VALIDATED"
    HELD_VARIANCE = "HELD_VARIANCE"
    ACCEPTED = "ACCEPTED"
    CONSUMED = "CONSUMED"


class FormatSpecCode(str, Enum):
    FIXED_WIDTH = "FIXED_WIDTH"
    DELIMITED = "DELIMITED"
    XML = "XML"


class HygieneStatus(str, Enum):
    DELIVERABLE = "DELIVERABLE"
    CORRECTED = "CORRECTED"
    UNDELIVERABLE_AS_ADDRESSED = "UNDELIVERABLE_AS_ADDRESSED"
    STALE = "STALE"


class DeliveryChannel(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    SUPPRESSED = "SUPPRESSED"
    NONE_ELECTRONIC = "NONE_ELECTRONIC"


class JobStatus(str, Enum):
    COMPOSED = "COMPOSED"
    PRESORTED = "PRESORTED"
    SCHEDULED = "SCHEDULED"
    PRINTING = "PRINTING"
    PRINTED = "PRINTED"
    INTEGRITY_HELD = "INTEGRITY_HELD"
    VERIFIED = "VERIFIED"
    MANIFESTED = "MANIFESTED"
    CLOSED = "CLOSED"


class JobIntegrityStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    BREACHED = "BREACHED"


class PieceStatus(str, Enum):
    COMPOSED = "COMPOSED"
    SUPPRESSED = "SUPPRESSED"
    PRINTED = "PRINTED"
    INSERTED = "INSERTED"
    INDUCTED = "INDUCTED"
    VOID = "VOID"


class PieceIntegrityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    SCAN_MATCHED = "SCAN_MATCHED"
    RECONCILED = "RECONCILED"
    SCAN_MISSING = "SCAN_MISSING"
    DUPLICATE_SCAN = "DUPLICATE_SCAN"


class PresortBucket(str, Enum):
    FIVE_DIGIT = "FIVE_DIGIT"
    THREE_DIGIT = "THREE_DIGIT"
    AADC = "AADC"
    MIXED_AADC = "MIXED_AADC"
    NONMACHINABLE = "NONMACHINABLE"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    MANIFESTED = "MANIFESTED"


class ScanStage(str, Enum):
    PRINT = "PRINT"
    INSERT = "INSERT"
    INDUCT = "INDUCT"


class LastScanStage(str, Enum):
    NONE = "NONE"
    PRINT = "PRINT"
    INSERT = "INSERT"
    INDUCT = "INDUCT"


class ScanRejectionReason(str, Enum):
    UNKNOWN_BARCODE = "UNKNOWN_BARCODE"
    DUPLICATE_STAGE = "DUPLICATE_STAGE"
    OUT_OF_SEQUENCE = "OUT_OF_SEQUENCE"


class PressLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class PressCapability(str, Enum):
    DUPLEX = "DUPLEX"
    COLOR = "COLOR"
    INSERT = "INSERT"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SelectionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    SELECTED = "SELECTED"


class FacilityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FacilityType(str, Enum):
    SCF = "SCF"
    NDC = "NDC"
    DDU = "DDU"


class ReturnReasonCode(str, Enum):
    MOVED_NO_FORWARD = "MOVED_NO_FORWARD"
    INSUFFICIENT_ADDRESS = "INSUFFICIENT_ADDRESS"
    VACANT = "VACANT"
    REFUSED = "REFUSED"
    DECEASED = "DECEASED"


class ReturnDisposition(str, Enum):
    SCANNED = "SCANNED"
    ADDRESS_UPDATED = "ADDRESS_UPDATED"
    UNRESOLVED = "UNRESOLVED"
    FEEDBACK_SENT = "FEEDBACK_SENT"


class DrReadinessStatus(str, Enum):
    UNTESTED = "UNTESTED"
    READY = "READY"
    STALE = "STALE"
    FAILED = "FAILED"


class DrillResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# --------------------------------------------------------------------------
# Common field bundles
# --------------------------------------------------------------------------


class CommonFields(TypedDict):
    """Identity, timestamps and version carried by every entity except the
    append-only scan event."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """The scan event is an immutable audit row: it carries identity and a
    creation timestamp only, with no ``updated_at`` and no ``version``."""

    id: str
    created_at: str


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class Client(CommonFields, total=False):
    client_code: str
    name: str
    status: str
    sla_turnaround_hours: int
    sla_penalty_rate_cents_per_hour: int
    sla_penalty_cap_cents: int
    control_total_tolerance_bp: int
    dr_readiness_required: bool
    postage_deposited_cents: int
    postage_committed_cents: int
    postage_escrow_available_cents: int
    paperless_sync_epoch: int
    pending_address_feedback_count: int
    address_feedback_batch_count: int


class PaperlessEnrollment(CommonFields, total=False):
    client_id: str
    account_ref: str
    channel: str
    status: str
    enrolled_epoch: Optional[int]
    revoked_epoch: Optional[int]
    confirmed_at: Optional[str]
    suppression_effective: bool


class InsertStock(CommonFields, total=False):
    insert_code: str
    description: str
    jurisdiction_code: str
    effective_from: str
    effective_to: Optional[str]
    sheets_per_insert: int
    received_count: int
    on_hand_count: int
    reserved_count: int
    consumed_count: int
    status: str


class CompositionTemplate(CommonFields, total=False):
    client_id: str
    template_code: str
    version_no: int
    status: str
    duplex_required: bool
    sheets_per_document: int
    color_pages_per_document: int
    mail_class_preference: str
    required_insert_codes: List[str]
    variable_content_rules: List[dict]
    activated_at: Optional[str]
    retired_at: Optional[str]


class DataFile(CommonFields, total=False):
    client_id: str
    file_name: str
    format_spec_code: str
    status: str
    declared_record_count: int
    declared_control_total_cents: int
    actual_record_count: int
    actual_control_total_cents: int
    record_count_variance: int
    control_total_variance_bp: int
    format_error_count: int
    amendment_count: int
    accepted_at: Optional[str]


class StatementRecord(CommonFields, total=False):
    data_file_id: str
    account_ref: str
    sequence_no: int
    statement_amount_cents: int
    address_line1: str
    address_line2: Optional[str]
    city: str
    region_code: str
    postal_code: str
    postal_code_plus4: Optional[str]
    format_valid: bool
    hygiene_confidence: float
    hygiene_status: str
    delivery_channel: str
    address_update_pending: bool


class CompositionJob(CommonFields, total=False):
    client_id: str
    data_file_id: str
    template_id: str
    status: str
    integrity_status: str
    composition_epoch: int
    composed_by_user_id: str
    rush_requested: bool
    expected_piece_count: int
    print_piece_count: int
    electronic_piece_count: int
    accountable_piece_count: int
    void_piece_count: int
    reprint_piece_count: int
    total_sheet_count: int
    print_sheet_count: int
    insert_sheet_total: int
    color_page_count: int
    matched_piece_count: int
    missing_scan_count: int
    duplicate_scan_count: int
    reprint_chain_depth: int
    integrity_held_since: Optional[str]
    sla_due_at: str
    sla_hold_minutes: int
    projected_completion_at: Optional[str]
    projected_penalty_cents: Optional[int]
    assessed_penalty_cents: Optional[int]
    sla_late_hours: Optional[int]
    billing_total_cents: Optional[int]
    closed_at: Optional[str]


class MailPiece(CommonFields, total=False):
    composition_job_id: str
    statement_record_id: str
    piece_seq: int
    imb_barcode: str
    piece_status: str
    integrity_status: str
    last_scan_stage: str
    accepted_scan_count: int
    sheet_count: int
    insert_sheet_count: int
    color_page_count: int
    applied_insert_codes: List[str]
    mail_class: str
    presort_bucket: Optional[str]
    presort_batch_id: Optional[str]
    billable: bool
    undeliverable_flag: bool
    reprint_of_piece_id: Optional[str]
    reprint_depth: int


class ScanEvent(AppendOnlyFields, total=False):
    mail_piece_id: str
    stage: str
    scanned_barcode: str
    device_code: str
    scanned_at: str
    accepted: bool
    rejection_reason: Optional[str]


class PressLine(CommonFields, total=False):
    line_code: str
    capabilities: List[str]
    sheets_per_hour: int
    daily_sheet_capacity: int
    changeover_buffer_minutes: int
    status: str
    committed_sheet_count: int
    utilization_bp: int


class PrintRun(CommonFields, total=False):
    composition_job_id: str
    press_line_id: str
    status: str
    selection_mode: str
    selection_score: float
    window_start: str
    window_end: str
    run_minutes: int
    planned_sheet_count: int
    started_at: Optional[str]
    completed_at: Optional[str]
    aborted_at: Optional[str]


class EntryFacility(CommonFields, total=False):
    facility_code: str
    facility_type: str
    tray_capacity_per_window: int
    discount_bp_first_class: int
    discount_bp_marketing: int
    status: str
    committed_tray_count: int


class PresortBatch(CommonFields, total=False):
    composition_job_id: str
    mail_class: str
    presort_bucket: str
    status: str
    piece_count: int
    tray_count: int
    estimated_postage_cents: Optional[int]
    manifested_postage_cents: Optional[int]
    postage_variance_cents: Optional[int]
    sealed_by_user_id: Optional[str]
    manifested_by_user_id: Optional[str]
    entry_facility_id: Optional[str]
    induction_window_start: Optional[str]
    induction_window_end: Optional[str]


class UndeliverableReturn(CommonFields, total=False):
    mail_piece_id: str
    reason_code: str
    disposition: str
    corrected_address_line1: Optional[str]
    corrected_postal_code: Optional[str]
    feedback_batch_seq: Optional[int]


class DrSite(CommonFields, total=False):
    site_code: str
    replication_lag_minutes: int
    readiness_status: str
    readiness_valid_until: Optional[str]
    last_drill_at: Optional[str]
    last_drill_result: Optional[str]
    drill_count: int
