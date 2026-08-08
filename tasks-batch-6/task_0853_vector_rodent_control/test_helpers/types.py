"""Domain types for the Vector & Rodent Control Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SUPERVISOR = "Supervisor"
    INSPECTOR = "Inspector"
    INTAKE_CLERK = "IntakeClerk"
    FINANCE_OFFICER = "FinanceOfficer"
    PROPERTY_OWNER = "PropertyOwner"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class ZonePosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HOTSPOT = "HOTSPOT"


class NoticePreference(str, Enum):
    FIRST_CLASS_MAIL = "FIRST_CLASS_MAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PERSONAL_SERVICE = "PERSONAL_SERVICE"


class PropertyType(str, Enum):
    RESIDENTIAL_SINGLE = "RESIDENTIAL_SINGLE"
    RESIDENTIAL_MULTI = "RESIDENTIAL_MULTI"
    COMMERCIAL_FOOD = "COMMERCIAL_FOOD"
    COMMERCIAL_OTHER = "COMMERCIAL_OTHER"
    VACANT_LOT = "VACANT_LOT"


class OfficerRank(str, Enum):
    FIELD_INSPECTOR = "FIELD_INSPECTOR"
    SUPERVISOR = "SUPERVISOR"


class ComplaintType(str, Enum):
    RODENT_SIGHTING = "RODENT_SIGHTING"
    HARBORAGE = "HARBORAGE"
    GARBAGE_ACCUMULATION = "GARBAGE_ACCUMULATION"
    DEAD_ANIMAL = "DEAD_ANIMAL"
    MOSQUITO_BREEDING = "MOSQUITO_BREEDING"


class ReporterType(str, Enum):
    RESIDENT = "RESIDENT"
    OWNER = "OWNER"
    AGENCY = "AGENCY"
    ANONYMOUS = "ANONYMOUS"


class Severity(str, Enum):
    ROUTINE = "ROUTINE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    INSPECTED = "INSPECTED"
    ABATEMENT_ORDERED = "ABATEMENT_ORDERED"
    CLOSED_NO_VIOLATION = "CLOSED_NO_VIOLATION"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    CLOSED_WITHDRAWN = "CLOSED_WITHDRAWN"
    CLOSED_DUPLICATE = "CLOSED_DUPLICATE"


class ClosureReason(str, Enum):
    NO_VIOLATION = "NO_VIOLATION"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"
    DUPLICATE = "DUPLICATE"


class InspectionKind(str, Enum):
    INITIAL = "INITIAL"
    REINSPECTION = "REINSPECTION"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    VIOLATION_FOUND = "VIOLATION_FOUND"
    NO_VIOLATION = "NO_VIOLATION"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NO_ACCESS = "NO_ACCESS"


class InfestationTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AbatementOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    SERVED = "SERVED"
    REINSPECTION_SCHEDULED = "REINSPECTION_SCHEDULED"
    ESCALATED = "ESCALATED"
    CITY_ABATED = "CITY_ABATED"
    COMPLIED = "COMPLIED"
    CLOSED = "CLOSED"


class NoticeType(str, Enum):
    ABATEMENT_ORDER = "ABATEMENT_ORDER"
    EDUCATIONAL_ADVISORY = "EDUCATIONAL_ADVISORY"
    FINAL_WARNING = "FINAL_WARNING"
    LIEN_INTENT = "LIEN_INTENT"


class DeliveryMethod(str, Enum):
    FIRST_CLASS_MAIL = "FIRST_CLASS_MAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PERSONAL_SERVICE = "PERSONAL_SERVICE"
    POSTING = "POSTING"


class NoticeStatus(str, Enum):
    PENDING_SERVICE = "PENDING_SERVICE"
    SERVED = "SERVED"
    UNDELIVERABLE = "UNDELIVERABLE"


class ServiceOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    REFUSED = "REFUSED"
    UNDELIVERABLE = "UNDELIVERABLE"


class BaitType(str, Enum):
    ANTICOAGULANT = "ANTICOAGULANT"
    SNAP_TRAP = "SNAP_TRAP"
    GLUE_BOARD = "GLUE_BOARD"
    BAIT_BLOCK = "BAIT_BLOCK"


class BaitStationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DAMAGED = "DAMAGED"
    REMOVED = "REMOVED"


class StationCondition(str, Enum):
    INTACT = "INTACT"
    DAMAGED = "DAMAGED"
    MISSING = "MISSING"


class BillingStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class LienStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    RELEASED = "RELEASED"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"
    CASH = "CASH"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD 2.4)
# --------------------------------------------------------------------------


class Zone(TypedDict):
    id: str
    name: str
    code: str
    population_density_per_sqkm: int
    posture: str
    rodent_index: float
    open_complaint_count: int
    chronic_property_count: int
    active_station_count: int
    last_index_recomputed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PropertyOwner(TypedDict):
    id: str
    full_name: str
    email: str
    mailing_address: str
    notice_preference: str
    hardship_certified: bool
    outstanding_balance_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    zone_id: str
    owner_id: str
    address_line: str
    parcel_number: str
    property_type: str
    unit_count: int
    provisional_chronic_score: float
    chronic_score: float
    chronic_flag: bool
    open_order_count: int
    lien_encumbered: bool
    last_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Officer(TypedDict):
    id: str
    full_name: str
    badge_number: str
    rank: str
    certification_expires_at: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    property_id: str
    zone_id: str
    complaint_type: str
    reporter_type: str
    reporter_name: Optional[str]
    reporter_phone: Optional[str]
    description: str
    reported_severity: str
    severity: str
    status: str
    priority_score: float
    response_due_at: str
    closure_reason: Optional[str]
    triaged_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    complaint_id: Optional[str]
    abatement_order_id: Optional[str]
    property_id: str
    officer_id: str
    kind: str
    scheduled_start: str
    scheduled_end: str
    status: str
    result: Optional[str]
    notes: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementOrder(TypedDict):
    id: str
    property_id: str
    inspection_id: str
    issued_by_officer_id: str
    status: str
    required_actions: List[str]
    infestation_tier_at_issue: str
    escalation_level: int
    compliance_deadline: Optional[str]
    served_at: Optional[str]
    extension_count: int
    extension_days_total: int
    education_advisory_served: bool
    actual_labor_hours: Optional[float]
    actual_materials_cents: Optional[int]
    abated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnerNotice(TypedDict):
    id: str
    abatement_order_id: str
    notice_type: str
    delivery_method: str
    recipient_address: str
    status: str
    service_outcome: Optional[str]
    sent_at: str
    served_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BaitStation(TypedDict):
    id: str
    property_id: str
    zone_id: str
    station_code: str
    bait_type: str
    status: str
    installed_at: str
    last_reading_at: Optional[str]
    reading_count: int
    cumulative_take_pct: int
    created_at: str
    updated_at: str
    version: int


class CostRecoveryInvoice(TypedDict):
    id: str
    abatement_order_id: str
    property_id: str
    owner_id: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    billing_status: str
    lien_status: str
    estimated_total_cents: int
    final_total_cents: Optional[int]
    labor_line_cents: Optional[int]
    materials_line_cents: Optional[int]
    penalty_line_cents: Optional[int]
    education_credit_cents: Optional[int]
    admin_fee_cents: Optional[int]
    hardship_discount_cents: Optional[int]
    amount_paid_cents: int
    balance_due_cents: int
    due_at: Optional[str]
    paid_at: Optional[str]
    lien_filed_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observation records: id + created_at only (PRD 2.4)
# --------------------------------------------------------------------------


class Assessment(TypedDict):
    id: str
    inspection_id: str
    harborage_score: int
    attractant_score: int
    sanitation_score: int
    burrow_count: int
    evidence_photo_count: int
    recommended_actions: List[str]
    infestation_index: float
    infestation_tier: str
    created_at: str


class SurveillanceReading(TypedDict):
    id: str
    bait_station_id: str
    reading_at: str
    take_pct: int
    activity_sign_count: int
    station_condition: str
    rebaited: bool
    created_at: str
