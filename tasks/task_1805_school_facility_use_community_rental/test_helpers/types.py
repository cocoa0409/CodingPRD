"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    FACILITIES_DIRECTOR = "FacilitiesDirector"
    SITE_COORDINATOR = "SiteCoordinator"
    CUSTODIAL_SUPERVISOR = "CustodialSupervisor"
    RENTER_ORG_REP = "RenterOrgRep"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class FacilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"
    RETIRED = "RETIRED"


class FacilityTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ATHLETIC = "ATHLETIC"


class RateClass(str, Enum):
    INTERNAL = "INTERNAL"
    NONPROFIT = "NONPROFIT"
    FOR_PROFIT = "FOR_PROFIT"


class OrgStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    SUSPENDED = "SUSPENDED"
    BARRED = "BARRED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class RequestPriorityClass(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CertStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PermitLifecycleStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PermitFinancialStatus(str, Enum):
    DEPOSIT_PENDING = "DEPOSIT_PENDING"
    SECURED = "SECURED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    FORFEIT_PENDING = "FORFEIT_PENDING"
    FORFEITED = "FORFEITED"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    BILLED = "BILLED"
    CANCELLED = "CANCELLED"


class InvoiceKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REFUND = "REFUND"
    DAMAGE = "DAMAGE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    ADJUDICATED = "ADJUDICATED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"


class TxnKind(str, Enum):
    DEPOSIT_CAPTURE = "DEPOSIT_CAPTURE"
    FEE_PAYMENT = "FEE_PAYMENT"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    DEPOSIT_FORFEIT = "DEPOSIT_FORFEIT"
    FEE_REFUND = "FEE_REFUND"
    DAMAGE_CHARGE = "DAMAGE_CHARGE"


class SeriesStatus(str, Enum):
    PENDING_GENERATION = "PENDING_GENERATION"
    ACTIVE = "ACTIVE"
    PARTIALLY_BLOCKED = "PARTIALLY_BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: id + created_at + updated_at + version) ---


class SchoolSite(TypedDict, total=False):
    id: str
    site_code: str
    display_name: str
    site_status: str
    rental_timezone: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    site_id: str
    facility_code: str
    facility_tier: str
    capacity: int
    setup_buffer_minutes: int
    teardown_buffer_minutes: int
    requires_custodian: bool
    facility_status: str
    created_at: str
    updated_at: str
    version: int


class RenterOrganization(TypedDict, total=False):
    id: str
    org_name: str
    rate_class: str
    nonprofit_registration_no: Optional[str]
    org_standing: str
    credit_balance_cents: int
    outstanding_balance_cents: int
    forfeiture_count: int
    created_at: str
    updated_at: str
    version: int


class RateClassPolicy(TypedDict, total=False):
    id: str
    policy_code: str
    rate_class: str
    facility_tier: str
    hourly_rate_cents: int
    deposit_basis_points: int
    deposit_floor_cents: int
    custodial_hourly_cents: int
    effective_from: str
    effective_to: Optional[str]
    policy_status: str
    unique_key: str
    created_at: str
    updated_at: str
    version: int


class SchoolCalendarEvent(TypedDict, total=False):
    id: str
    site_id: str
    facility_id: Optional[str]
    title: str
    starts_at: str
    ends_at: str
    event_priority_tier: int
    event_status: str
    created_at: str
    updated_at: str
    version: int


class RentalRequest(TypedDict, total=False):
    id: str
    renter_org_id: str
    facility_id: str
    event_title: str
    headcount_estimate: int
    starts_at: str
    ends_at: str
    request_priority_class: str
    district_sponsored: bool
    request_status: str
    revision_round: int
    denial_reason_code: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    renter_org_id: str
    insurer_name: str
    per_occurrence_limit_cents: int
    aggregate_limit_cents: int
    effective_from: str
    effective_to: str
    cert_status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    rental_request_id: str
    renter_org_id: str
    facility_id: str
    occupancy_start: str
    occupancy_end: str
    blocked_start: str
    blocked_end: str
    lifecycle_status: str
    financial_status: str
    deposit_required_cents: int
    deposit_held_cents: int
    seasonal_permit_id: Optional[str]
    superseded_by_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustodialWorkOrder(TypedDict, total=False):
    id: str
    permit_id: str
    facility_id: str
    scheduled_start: str
    scheduled_end: str
    estimated_hours: float
    actual_hours: Optional[float]
    after_hours_flag: bool
    weekend_flag: bool
    wo_status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    permit_id: str
    renter_org_id: str
    invoice_kind: str
    rental_fee_cents: int
    staffing_charge_cents: int
    after_hours_charge_cents: int
    discount_cents: int
    total_cents: int
    amount_paid_cents: int
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict, total=False):
    id: str
    permit_id: str
    facility_id: str
    recorded_by_user_id: str
    line_items: List[Dict[str, Any]]
    total_claimed_cents: int
    adjudicated_amount_cents: Optional[int]
    assessment_status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalPermit(TypedDict, total=False):
    id: str
    renter_org_id: str
    facility_id: str
    series_name: str
    recurrence_rule: str
    season_start: str
    season_end: str
    renewed_from_id: Optional[str]
    seniority_key: str
    series_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry (PRD §2.5): carries id + created_at only;
# NO updated_at, NO version. Posting instant recorded in posted_at.
class PaymentTransaction(TypedDict, total=False):
    id: str
    permit_id: str
    invoice_id: Optional[str]
    txn_kind: str
    amount_cents: int
    posted_at: str
    idempotency_key: str
    created_at: str
