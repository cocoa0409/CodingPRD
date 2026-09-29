"""Entity shapes, enum vocabularies and role names for the Ticket Access Control API.

The scan event and the audit log entry are append-only and carry neither
``updated_at`` nor ``version``, so their TypedDicts expose only ``id`` and
``created_at`` on top of their domain fields.
"""

from typing import List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────────────────────────────


class Role:
    """The six roles, spelled exactly as the API expects them."""

    PATRON = "Patron"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    TICKETING_APPROVER = "TicketingApprover"
    GATE_OPERATOR = "GateOperator"
    SECURITY_INVESTIGATOR = "SecurityInvestigator"
    VENUE_ADMIN = "VenueAdmin"


ALL_ROLES = [
    Role.PATRON,
    Role.BOX_OFFICE_AGENT,
    Role.TICKETING_APPROVER,
    Role.GATE_OPERATOR,
    Role.SECURITY_INVESTIGATOR,
    Role.VENUE_ADMIN,
]


# ─── Enum vocabularies ────────────────────────────────────────────────────────


class EventStatus:
    DRAFT = "DRAFT"
    ON_SALE = "ON_SALE"
    DOORS_OPEN = "DOORS_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class PriceCapRegime:
    STATUTORY = "STATUTORY"
    VENUE_POLICY = "VENUE_POLICY"
    NONE = "NONE"


class EntitlementLevel:
    GA = "GA"
    PREMIUM = "PREMIUM"
    BACK_OF_HOUSE = "BACK_OF_HOUSE"


class ZonePosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class GateStatus:
    IDLE = "IDLE"
    SCANNING = "SCANNING"


class FraudRiskBasis:
    PROVISIONAL = "PROVISIONAL"
    ADJUDICATED = "ADJUDICATED"


class TicketType:
    PAID = "PAID"
    COMP = "COMP"
    WILL_CALL = "WILL_CALL"
    CREDENTIAL = "CREDENTIAL"


class LifecycleStatus:
    ISSUED = "ISSUED"
    LISTED = "LISTED"
    TRANSFERRED = "TRANSFERRED"
    RESOLD = "RESOLD"
    VOIDED = "VOIDED"


class AdmissionStatus:
    NOT_ADMITTED = "NOT_ADMITTED"
    INSIDE = "INSIDE"
    EXITED = "EXITED"
    DENIED_FLAGGED = "DENIED_FLAGGED"


class DeviceBindingStatus:
    UNBOUND = "UNBOUND"
    BOUND = "BOUND"
    RELEASED = "RELEASED"


class TransferStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class Marketplace:
    VERIFIED_PRIMARY = "VERIFIED_PRIMARY"
    VERIFIED_PARTNER = "VERIFIED_PARTNER"
    UNVERIFIED = "UNVERIFIED"


class ListingStatus:
    LISTED = "LISTED"
    SOLD = "SOLD"
    DELISTED = "DELISTED"
    SUSPENDED = "SUSPENDED"


class SessionMode:
    ONLINE = "ONLINE"
    OFFLINE_CAPABLE = "OFFLINE_CAPABLE"


class SessionStatus:
    OPEN = "OPEN"
    SYNCING = "SYNCING"
    CLOSED = "CLOSED"


class ScanDirection:
    IN = "IN"
    OUT = "OUT"


class ScanSource:
    ONLINE = "ONLINE"
    OFFLINE_BATCH = "OFFLINE_BATCH"


class ScanResult:
    ADMITTED = "ADMITTED"
    EXIT_RECORDED = "EXIT_RECORDED"
    DENIED_DUPLICATE = "DENIED_DUPLICATE"
    DENIED_COUNTERFEIT = "DENIED_COUNTERFEIT"
    DENIED_DEVICE_MISMATCH = "DENIED_DEVICE_MISMATCH"
    DENIED_ZONE = "DENIED_ZONE"
    DENIED_CAPACITY = "DENIED_CAPACITY"
    DENIED_VOIDED = "DENIED_VOIDED"
    DENIED_STALE_BARCODE = "DENIED_STALE_BARCODE"
    DENIED_REENTRY_LOCKOUT = "DENIED_REENTRY_LOCKOUT"


class DistributionType:
    COMP = "COMP"
    WILL_CALL = "WILL_CALL"
    CREDENTIAL = "CREDENTIAL"


class CredentialRequestStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class IncidentCategory:
    COUNTERFEIT = "COUNTERFEIT"
    UNAUTHORIZED_RESALE = "UNAUTHORIZED_RESALE"
    DUPLICATE = "DUPLICATE"
    ZONE_VIOLATION = "ZONE_VIOLATION"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"


class IncidentStatus:
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMEDIATED = "REMEDIATED"
    DISMISSED = "DISMISSED"


class ReportStatus:
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    REOPENED = "REOPENED"


class AuditSubjectType:
    CREDENTIAL_REQUEST = "CREDENTIAL_REQUEST"
    TICKET = "TICKET"
    RESALE_LISTING = "RESALE_LISTING"
    DENIED_ENTRY_INCIDENT = "DENIED_ENTRY_INCIDENT"
    RECONCILIATION_REPORT = "RECONCILIATION_REPORT"


class AuditAction:
    CREDENTIAL_REQUEST_SUBMITTED = "CREDENTIAL_REQUEST_SUBMITTED"
    CREDENTIAL_REQUEST_CHANGES_REQUESTED = "CREDENTIAL_REQUEST_CHANGES_REQUESTED"
    CREDENTIAL_REQUEST_APPROVED = "CREDENTIAL_REQUEST_APPROVED"
    CREDENTIAL_REQUEST_REJECTED = "CREDENTIAL_REQUEST_REJECTED"
    TICKET_VOIDED = "TICKET_VOIDED"
    RESALE_LISTED = "RESALE_LISTED"
    RESALE_SOLD = "RESALE_SOLD"
    RESALE_LISTING_SUSPENDED = "RESALE_LISTING_SUSPENDED"
    DENIED_ENTRY_REMEDIATED = "DENIED_ENTRY_REMEDIATED"
    DENIED_ENTRY_DISMISSED = "DENIED_ENTRY_DISMISSED"
    RECONCILIATION_FINALIZED = "RECONCILIATION_FINALIZED"


# ─── Entity shapes ────────────────────────────────────────────────────────────


class _Versioned(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class _AppendOnly(TypedDict):
    id: str
    created_at: str


class Event(_Versioned):
    name: str
    venue_name: str
    fire_code_capacity: int
    barcode_anchor_at: str
    doors_open_at: str
    event_start_at: str
    transfer_window_closes_at: str
    price_cap_regime: str
    transfer_limit_per_ticket: int
    status: str
    live_occupancy: int
    peak_live_occupancy: int
    entitlements_outstanding: int
    settlement_pool_cents: int


class AccessZone(_Versioned):
    event_id: str
    zone_code: str
    required_entitlement_level: str
    fire_code_capacity: int
    credential_capacity: int
    face_value_reference_cents: int
    comp_discount_pct: float
    occupancy_count: int
    issued_entitlement_count: int
    posture: str
    comp_forgone_cents: int


class Gate(_Versioned):
    event_id: str
    access_zone_id: str
    gate_code: str
    throughput_per_minute: int
    lanes_open: int
    status: str
    last_session_closed_at: Optional[str]
    admitted_scan_count: int


class Patron(_Versioned):
    email: str
    display_name: str
    identity_verified: bool
    device_rebind_count: int
    strike_count: int
    fraud_risk_score: int
    fraud_risk_basis: str
    remediation_credit_cents: int
    payout_balance_cents: int


class Ticket(_Versioned):
    event_id: str
    access_zone_id: str
    holder_patron_id: str
    credential_request_id: Optional[str]
    ticket_type: str
    face_value_cents: int
    barcode_seed: str
    lifecycle_status: str
    admission_status: str
    transfer_count: int
    bound_device_fingerprint: Optional[str]
    device_binding_status: str
    last_admitted_at: Optional[str]
    last_exited_at: Optional[str]
    admitted_scan_count: int


class TicketBarcode(TypedDict):
    ticket_id: str
    barcode_seed: str
    barcode_epoch_index: int
    current_barcode: str
    accepted_epoch_floor: int


class TransferRequest(_Versioned):
    ticket_id: str
    from_patron_id: str
    to_patron_id: str
    status: str
    decided_at: Optional[str]


class ResaleListing(_Versioned):
    ticket_id: str
    seller_patron_id: str
    buyer_patron_id: Optional[str]
    superseded_listing_id: Optional[str]
    marketplace: str
    ask_price_cents: int
    cap_price_cents: Optional[int]
    status: str
    platform_fee_cents: Optional[int]
    venue_royalty_cents: Optional[int]
    processing_fee_cents: Optional[int]
    seller_payout_cents: Optional[int]


class ScanSession(_Versioned):
    gate_id: str
    operator_device_id: str
    mode: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    online_scan_count: int
    offline_uploaded_count: int
    duplicate_suppressed_count: int


class ScanEvent(_AppendOnly):
    scan_session_id: str
    ticket_id: Optional[str]
    presented_barcode: str
    device_fingerprint: str
    direction: str
    scanned_at: Optional[str]
    recorded_at: str
    source: str
    result: str
    dedupe_key: str
    denied_reason_code: Optional[str]


class OfflineBatchReceipt(TypedDict):
    accepted_count: int
    duplicate_suppressed_count: int
    denied_count: int
    scan_event_ids: List[str]


class CredentialRequest(_Versioned):
    event_id: str
    access_zone_id: str
    recipient_patron_id: str
    distribution_type: str
    quantity: int
    valid_from: str
    valid_until: str
    justification: str
    requested_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    revision_count: int
    issued_ticket_count: int
    forgone_revenue_cents: int


class DeniedEntryIncident(_Versioned):
    scan_event_id: str
    ticket_id: Optional[str]
    patron_id: Optional[str]
    category: str
    status: str
    reviewer_user_id: Optional[str]
    resolution_note: Optional[str]
    remediation_credit_cents: Optional[int]


class ReconciliationReport(_Versioned):
    event_id: str
    reported_attendance: int
    scan_derived_attendance: int
    variance_count: int
    variance_pct: float
    fire_code_breach: bool
    override_reason: Optional[str]
    status: str
    finalized_by_user_id: Optional[str]


class AuditLogEntry(_AppendOnly):
    event_id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_user_id: str
    occurred_at: str
    detail: str


class ZoneOccupancy(TypedDict):
    id: str
    zone_code: str
    occupancy_count: int
    fire_code_capacity: int


class EventOccupancy(TypedDict):
    event_id: str
    live_occupancy: int
    peak_live_occupancy: int
    reconciled_attendance: int
    fire_code_capacity: int
    headroom: int
    projected_clearance_minutes: Optional[int]
    zone_occupancy: List[ZoneOccupancy]


class ClockReading(TypedDict):
    current_utc: str
    previous_utc: str
