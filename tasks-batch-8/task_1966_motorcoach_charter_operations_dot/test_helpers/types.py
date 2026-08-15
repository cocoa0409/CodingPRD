"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    QUOTE_AGENT = "QuoteAgent"
    DISPATCH_MANAGER = "DispatchManager"
    FLEET_MANAGER = "FleetManager"
    SAFETY_OFFICER = "SafetyOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status / classification enums (PRD §3)
# ---------------------------------------------------------------------------

class CreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COLLECTIONS = "COLLECTIONS"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_TRIP = "IN_TRIP"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class VehicleClass(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    EXECUTIVE = "EXECUTIVE"


class CdlClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class DriverStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"
    OFF_DUTY = "OFF_DUTY"
    SUSPENDED = "SUSPENDED"


class HosCycleType(str, Enum):
    CYCLE_70_8 = "CYCLE_70_8"
    CYCLE_60_7 = "CYCLE_60_7"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PricingVariant(str, Enum):
    MILEAGE_PRIMARY = "MILEAGE_PRIMARY"
    HOURLY_PRIMARY = "HOURLY_PRIMARY"


class OrderStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class CancelledBy(str, Enum):
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


class TripLogType(str, Enum):
    DRIVING = "DRIVING"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"
    OFF_DUTY = "OFF_DUTY"
    SLEEPER_BERTH = "SLEEPER_BERTH"


class IncidentType(str, Enum):
    ACCIDENT = "ACCIDENT"
    BREAKDOWN = "BREAKDOWN"
    TRAFFIC_VIOLATION = "TRAFFIC_VIOLATION"
    CUSTOMER_COMPLAINT = "CUSTOMER_COMPLAINT"
    HOS_VIOLATION = "HOS_VIOLATION"
    CARGO_DAMAGE = "CARGO_DAMAGE"
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class MaintenanceType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    DOT_INSPECTION = "DOT_INSPECTION"
    REPAIR = "REPAIR"
    RECALL = "RECALL"
    TIRE_REPLACE = "TIRE_REPLACE"
    BRAKE_SERVICE = "BRAKE_SERVICE"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class BreakdownStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPATCHED = "DISPATCHED"
    REPLACEMENT_EN_ROUTE = "REPLACEMENT_EN_ROUTE"
    REPLACED = "REPLACED"
    RESOLVED_IN_PLACE = "RESOLVED_IN_PLACE"
    CANCELLED = "CANCELLED"


class CertificateType(str, Enum):
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    AUTO_LIABILITY = "AUTO_LIABILITY"
    UMBRELLA = "UMBRELLA"
    WORKERS_COMP = "WORKERS_COMP"


class CertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuditType(str, Enum):
    DOT_COMPLIANCE = "DOT_COMPLIANCE"
    SAFETY_RATING = "SAFETY_RATING"
    INSURANCE_VERIFICATION = "INSURANCE_VERIFICATION"
    FULL_OPERATIONAL = "FULL_OPERATIONAL"


class AuditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class AuditRating(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Sub-records (trip logs, incident reports, maintenance records) carry ONLY
# id + created_at (PRD §2.4).

class CustomerAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    contact_phone: str
    billing_address: str
    tax_exempt: bool
    credit_status: str
    safety_audit_score: float
    total_completed_trips: int
    lifetime_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    unit_number: str
    make_model: str
    year: int
    seating_capacity: int
    ada_accessible: bool
    vehicle_class: str
    status: str
    dot_inspection_expiry: str
    last_inspection_date: Optional[str]
    odometer_miles: int
    maintenance_due_miles: int
    insurance_policy_number: str
    insurance_expiry: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    full_name: str
    cdl_number: str
    cdl_class: str
    endorsements: List[str]
    hire_date: str
    status: str
    hos_cycle_type: str
    current_driving_hours_today: float
    current_on_duty_hours_today: float
    current_cycle_hours: float
    last_rest_start: Optional[str]
    consecutive_driving_minutes: int
    safety_score: float
    created_at: str
    updated_at: str
    version: int


class CharterQuote(TypedDict, total=False):
    id: str
    customer_id: str
    trip_date: str
    return_date: str
    origin: str
    destination: str
    passenger_count: int
    estimated_miles: int
    estimated_hours: float
    requires_overnight: bool
    requires_relief_driver: bool
    ada_required: bool
    vehicle_class_requested: str
    status: str
    mileage_rate_cents: int
    hourly_rate_cents: int
    overnight_fee_cents: int
    relief_driver_fee_cents: int
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    deposit_cents: int
    quote_expiry: str
    pricing_variant: str
    special_requests: str
    created_at: str
    updated_at: str
    version: int


class CharterOrder(TypedDict, total=False):
    id: str
    quote_id: str
    customer_id: str
    status: str
    assigned_vehicle_id: Optional[str]
    assigned_driver_id: Optional[str]
    relief_driver_id: Optional[str]
    actual_miles: int
    actual_hours: float
    extra_hours: float
    extra_hours_charge_cents: int
    fuel_surcharge_cents: int
    deposit_cents: int
    deposit_paid_cents: int
    deposit_paid_at: Optional[str]
    cancellation_fee_cents: int
    refund_cents: int
    final_subtotal_cents: int
    final_tax_cents: int
    final_invoice_cents: int
    balance_due_cents: int
    itinerary_changes: List[dict]
    cancelled_by: Optional[str]
    cancellation_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TripLog(TypedDict, total=False):
    """Sub-record: carries only id + created_at (PRD §2.4)."""
    id: str
    order_id: str
    driver_id: str
    log_type: str
    start_time: str
    end_time: str
    start_location: str
    end_location: str
    miles_driven: int
    hos_violation: bool
    violation_details: str
    created_at: str


class IncidentReport(TypedDict, total=False):
    """Sub-record: carries only id + created_at (PRD §2.4)."""
    id: str
    order_id: str
    driver_id: str
    vehicle_id: str
    incident_type: str
    severity: str
    description: str
    occurred_at: str
    reported_by: str
    dot_recordable: bool
    resolution_status: str
    resolution_notes: Optional[str]
    safety_score_impact: float
    created_at: str


class MaintenanceRecord(TypedDict, total=False):
    """Sub-record: carries only id + created_at (PRD §2.4)."""
    id: str
    vehicle_id: str
    maintenance_type: str
    status: str
    scheduled_date: str
    completed_date: Optional[str]
    odometer_at_service: int
    description: str
    technician: str
    cost_cents: int
    next_due_miles: int
    dot_inspection_passed: Optional[bool]
    defects_found: List[str]
    created_at: str


class BreakdownEvent(TypedDict, total=False):
    id: str
    order_id: str
    vehicle_id: str
    driver_id: str
    location: str
    description: str
    status: str
    replacement_vehicle_id: Optional[str]
    replacement_driver_id: Optional[str]
    delay_minutes: int
    resolution_notes: Optional[str]
    customer_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    order_id: str
    venue_name: str
    venue_address: str
    certificate_type: str
    coverage_amount_cents: int
    status: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    certificate_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyAuditRequest(TypedDict, total=False):
    id: str
    customer_id: str
    audit_type: str
    status: str
    requested_date: str
    completed_date: Optional[str]
    auditor_notes: Optional[str]
    findings: List[str]
    overall_rating: Optional[str]
    created_at: str
    updated_at: str
    version: int
