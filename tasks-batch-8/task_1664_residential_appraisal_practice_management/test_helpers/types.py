"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API carries the four system-managed properties
``id``, ``created_at``, ``updated_at`` and ``version`` (PRD 2.5), so every
TypedDict below includes them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    CLIENT_USER = "ClientUser"
    APPRAISER = "Appraiser"
    QC_REVIEWER = "QCReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClientType(str, Enum):
    AMC = "AMC"
    DIRECT_LENDER = "DIRECT_LENDER"
    PRIVATE = "PRIVATE"


class LicenseLevel(str, Enum):
    TRAINEE = "TRAINEE"
    LICENSED = "LICENSED"
    CERTIFIED_RESIDENTIAL = "CERTIFIED_RESIDENTIAL"


class AppraiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    PANEL_SUSPENDED = "PANEL_SUSPENDED"


class PanelMembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ComplexityTier(str, Enum):
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    HIGH_VALUE = "HIGH_VALUE"


class PropertyType(str, Enum):
    SFR = "SFR"
    CONDO = "CONDO"
    MULTI_2_4 = "MULTI_2_4"
    MANUFACTURED = "MANUFACTURED"


class LoanType(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    FHA = "FHA"
    VA = "VA"


class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCOPE_DETERMINED = "SCOPE_DETERMINED"
    ACCEPTED = "ACCEPTED"
    ASSIGNED = "ASSIGNED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTED = "INSPECTED"
    IN_ANALYSIS = "IN_ANALYSIS"
    DRAFTING = "DRAFTING"
    QC_REVIEW = "QC_REVIEW"
    DELIVERED = "DELIVERED"
    IN_REVISION = "IN_REVISION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ComparableStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    LOCKED = "LOCKED"
    EXCLUDED = "EXCLUDED"


class IneligibleReason(str, Enum):
    NET_ADJ_EXCEEDED = "NET_ADJ_EXCEEDED"
    GROSS_ADJ_EXCEEDED = "GROSS_ADJ_EXCEEDED"
    DISTANCE_EXCEEDED = "DISTANCE_EXCEEDED"
    SALE_TOO_OLD = "SALE_TOO_OLD"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_QC = "PENDING_QC"
    QC_PASSED = "QC_PASSED"
    DELIVERED = "DELIVERED"
    UNDER_REVISION = "UNDER_REVISION"


class ReportType(str, Enum):
    FORM_1004 = "FORM_1004"
    FORM_1073 = "FORM_1073"
    FORM_1025 = "FORM_1025"


class ConditionRating(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"
    C6 = "C6"


class RevisionKind(str, Enum):
    CORRECTION = "CORRECTION"
    RECONSIDERATION_OF_VALUE = "RECONSIDERATION_OF_VALUE"


class RevisionStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REBUTTED = "REBUTTED"
    SUPERSEDED = "SUPERSEDED"
    RESOLVED = "RESOLVED"


class SnapshotType(str, Enum):
    ORDER_FORM = "ORDER_FORM"
    INSPECTION_NOTES = "INSPECTION_NOTES"
    COMP_DATA = "COMP_DATA"
    REPORT_PDF = "REPORT_PDF"
    CERTIFICATION = "CERTIFICATION"
    REVISION_CORRESPONDENCE = "REVISION_CORRESPONDENCE"


class WorkfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEGAL_HOLD = "LEGAL_HOLD"
    PURGED = "PURGED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_SANCTIONED = "CLOSED_SANCTIONED"


class FeeAdjustmentKind(str, Enum):
    SURCHARGE = "SURCHARGE"
    WAIVER = "WAIVER"


class Client(TypedDict, total=False):
    id: str
    name: str
    client_type: str
    contact_email: str
    default_turn_time_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict, total=False):
    id: str
    full_name: str
    license_level: str
    license_number: str
    license_expiry: str
    supervisor_id: Optional[str]
    status: str
    sanction_override: bool
    completed_count: int
    on_time_count: int
    no_show_count: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class PanelMembership(TypedDict, total=False):
    id: str
    client_id: str
    appraiser_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    client_id: str
    complexity_tier: str
    base_fee_cents: int
    rush_multiplier_bps: int
    revision_fee_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppraisalOrder(TypedDict, total=False):
    id: str
    client_id: str
    property_address: str
    property_type: str
    estimated_value_cents: int
    loan_type: str
    requested_turn_days: int
    complexity_tier: str
    requires_inspection: bool
    assigned_appraiser_id: Optional[str]
    requires_supervisor_cosign: bool
    fee_quoted_cents: Optional[int]
    fee_current_cents: Optional[int]
    surcharge_total_cents: int
    waived_total_cents: int
    revision_fees_collected_cents: int
    cancellation_fee_cents: Optional[int]
    status: str
    accepted_at: Optional[str]
    due_at: Optional[str]
    first_delivered_at: Optional[str]
    inspection_completed_at: Optional[str]
    open_complaint_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    order_id: str
    appraiser_id: str
    window_start: str
    window_end: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Comparable(TypedDict, total=False):
    id: str
    order_id: str
    address: str
    sale_price_cents: int
    sale_date: str
    distance_miles: float
    site_adjustment_cents: int
    gla_adjustment_cents: int
    condition_adjustment_cents: int
    other_adjustment_cents: int
    adjusted_price_cents: int
    net_adjustment_pct: float
    gross_adjustment_pct: float
    is_eligible: bool
    ineligible_reasons: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    order_id: str
    report_type: str
    condition_rating: str
    value_conclusion_cents: int
    signing_appraiser_id: str
    co_signer_appraiser_id: Optional[str]
    reviewer_id: Optional[str]
    revision_round: int
    qc_fail_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    detail: str
    submitted_value_cents: Optional[int]
    status: str
    revision_fee_charged_cents: Optional[int]
    rebuttal: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkfileRecord(TypedDict, total=False):
    id: str
    order_id: str
    snapshot_type: str
    recorded_at: str
    retention_until: Optional[str]
    status: str
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    order_id: str
    respondent_appraiser_id: str
    description: str
    received_at: str
    response_due_at: str
    response_text: Optional[str]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict, total=False):
    appraiser_id: str
    completed_count: int
    on_time_count: int
    on_time_rate: Optional[float]
    avg_calendar_turn_days: Optional[float]
    avg_business_turn_days: Optional[float]
    confirmed_minutes: int
    standing: str
    sanction_override: bool
