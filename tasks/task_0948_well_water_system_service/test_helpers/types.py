"""Domain types for the Well & Water-System Service API.

Entity shapes, status enumerations and the role enumeration, all named exactly
as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    ESTIMATOR = "Estimator"
    TECHNICIAN = "Technician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER_CONTACT = "CustomerContact"


class MembershipTier(str, Enum):
    NONE = "NONE"
    SELECT = "SELECT"
    PREMIER = "PREMIER"


class JurisdictionCode(str, Enum):
    JUR_ALPHA = "JUR_ALPHA"
    JUR_BRAVO = "JUR_BRAVO"
    JUR_CHARLIE = "JUR_CHARLIE"
    JUR_DELTA = "JUR_DELTA"


class ServiceZone(str, Enum):
    ZONE_1 = "ZONE_1"
    ZONE_2 = "ZONE_2"
    ZONE_3 = "ZONE_3"
    OUT_OF_AREA = "OUT_OF_AREA"


class WellType(str, Enum):
    DRILLED = "DRILLED"
    DRIVEN = "DRIVEN"
    DUG = "DUG"


class DutyCycleClass(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class PotabilityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    SAFE = "SAFE"
    ADVISORY = "ADVISORY"
    UNSAFE = "UNSAFE"


class AdvisoryReason(str, Enum):
    PRESUMPTIVE_COLIFORM = "PRESUMPTIVE_COLIFORM"
    CONFIRMED_COLIFORM = "CONFIRMED_COLIFORM"
    RETEST_WINDOW_LAPSED = "RETEST_WINDOW_LAPSED"
    CHEMICAL_EXCEEDANCE = "CHEMICAL_EXCEEDANCE"


class TreatmentMedia(str, Enum):
    NONE = "NONE"
    SEDIMENT = "SEDIMENT"
    CARBON = "CARBON"
    SOFTENER_RESIN = "SOFTENER_RESIN"


class SharedWellAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TechnicianTier(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class PartCategory(str, Enum):
    PUMP = "PUMP"
    PRESSURE_TANK = "PRESSURE_TANK"
    FILTRATION = "FILTRATION"
    CONTROL = "CONTROL"
    CONSUMABLE = "CONSUMABLE"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PanelType(str, Enum):
    BACTERIOLOGICAL = "BACTERIOLOGICAL"
    CHEMICAL = "CHEMICAL"


class WaterTestResultStatus(str, Enum):
    COLLECTED = "COLLECTED"
    ANALYZED_NEGATIVE = "ANALYZED_NEGATIVE"
    ANALYZED_PRESUMPTIVE_POSITIVE = "ANALYZED_PRESUMPTIVE_POSITIVE"
    ANALYZED_CHEMICAL_EXCEEDANCE = "ANALYZED_CHEMICAL_EXCEEDANCE"
    INVALID_HOLD_TIME = "INVALID_HOLD_TIME"
    CONFIRMED_POSITIVE = "CONFIRMED_POSITIVE"
    CLEARED_NEGATIVE = "CLEARED_NEGATIVE"


class RecommendationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SelectedCapacity(str, Enum):
    CAP_24000 = "CAP_24000"
    CAP_32000 = "CAP_32000"
    CAP_48000 = "CAP_48000"
    CAP_64000 = "CAP_64000"
    CAP_80000 = "CAP_80000"
    DUAL_TANK_64000 = "DUAL_TANK_64000"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    SENT = "SENT"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class QuoteScope(str, Enum):
    NEW_WELL = "NEW_WELL"
    PUMP_REPLACEMENT = "PUMP_REPLACEMENT"
    PRESSURE_TANK = "PRESSURE_TANK"
    TREATMENT_INSTALL = "TREATMENT_INSTALL"
    REPAIR = "REPAIR"
    MAINTENANCE = "MAINTENANCE"


class QuoteLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SUPERSEDED_BY_YIELD = "SUPERSEDED_BY_YIELD"
    REMOVED = "REMOVED"


class QuoteLineOrigin(str, Enum):
    ESTIMATOR = "ESTIMATOR"
    PERMIT_MANDATED_ALTERNATE = "PERMIT_MANDATED_ALTERNATE"


class DispatchStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    DIAGNOSED = "DIAGNOSED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class AuthorizationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PRE_AUTHORIZED = "PRE_AUTHORIZED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"


class CauseClass(str, Enum):
    PUMP_FAILURE = "PUMP_FAILURE"
    WELL_DRY = "WELL_DRY"
    PRESSURE_TANK_FAILURE = "PRESSURE_TANK_FAILURE"
    CONTROL_FAILURE = "CONTROL_FAILURE"
    TREATMENT_FAILURE = "TREATMENT_FAILURE"
    NON_WELL_CAUSE = "NON_WELL_CAUSE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    PENDING_INVOICE = "PENDING_INVOICE"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class Pipeline(str, Enum):
    SCHEDULED = "SCHEDULED"
    EMERGENCY = "EMERGENCY"


class CallbackEligibility(str, Enum):
    NONE = "NONE"
    ELIGIBLE = "ELIGIBLE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class ConsumptionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CoverageClass(str, Enum):
    PART = "PART"
    LABOR = "LABOR"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ComplaintClass(str, Enum):
    PART = "PART"
    LABOR = "LABOR"


class CallbackClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED_WARRANTY = "APPROVED_WARRANTY"
    REJECTED_OUT_OF_WARRANTY = "REJECTED_OUT_OF_WARRANTY"
    REJECTED_NOT_DEFECT = "REJECTED_NOT_DEFECT"
    RESOLVED_REPAIRED = "RESOLVED_REPAIRED"


class AdjudicationDecision(str, Enum):
    REVIEW = "REVIEW"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class JurisdictionTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVERDUE = "OVERDUE"


class VisitKind(str, Enum):
    SALT_AND_FILTER = "SALT_AND_FILTER"
    FILTER_ONLY = "FILTER_ONLY"
    SALT_ONLY = "SALT_ONLY"
    SERVICE_ONLY = "SERVICE_ONLY"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    VOID = "VOID"


class InvoiceVariant(str, Enum):
    QUOTED_PINNED = "QUOTED_PINNED"
    ACTUAL_FINAL = "ACTUAL_FINAL"


class InvoiceLineType(str, Enum):
    PARTS = "PARTS"
    LABOR = "LABOR"
    DISPATCH_SURCHARGE = "DISPATCH_SURCHARGE"
    TRIP_FEE = "TRIP_FEE"
    PERMIT_FEE = "PERMIT_FEE"
    WARRANTY_CREDIT = "WARRANTY_CREDIT"
    LOYALTY_DISCOUNT = "LOYALTY_DISCOUNT"
    TAX = "TAX"


# --- Entity shapes -----------------------------------------------------------
# Nineteen of the twenty-one entity kinds carry id + created_at + updated_at +
# version.  MaintenanceVisit and InvoiceLine carry only id and created_at.


class Account(TypedDict):
    id: str
    legal_name: str
    billing_jurisdiction_code: str
    contact_email: str
    membership_tier: str
    balance_cents: int
    lifetime_invoiced_cents: int
    lifetime_paid_cents: int
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    account_id: str
    address_line: str
    jurisdiction_code: str
    distance_miles: float
    household_size: int
    has_vulnerable_occupant: bool
    service_zone: str
    created_at: str
    updated_at: str
    version: int


class WellProfile(TypedDict):
    id: str
    property_id: str
    jurisdiction_code: str
    well_type: str
    depth_feet: float
    pressure_tank_drawdown_gallons: float
    duty_cycle_ratio: float
    duty_cycle_class: str
    measured_yield_gpm: Optional[float]
    hardness_gpg: Optional[float]
    potability_status: str
    advisory_reason: Optional[str]
    treatment_media: str
    last_inspection_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    """Append-only: carries id and created_at only, with no version."""

    id: str
    maintenance_plan_id: str
    work_order_id: str
    visit_kind: str
    performed_at: str
    filter_changed: bool
    salt_added_lbs: float
    created_at: str


class InvoiceLine(TypedDict):
    """Append-only: carries id and created_at only, with no version."""

    id: str
    invoice_id: str
    sequence_no: int
    line_type: str
    description: str
    amount_cents: int
    parts_consumption_entry_id: Optional[str]
    created_at: str


ENTITIES_WITHOUT_VERSION: List[str] = ["MaintenanceVisit", "InvoiceLine"]
