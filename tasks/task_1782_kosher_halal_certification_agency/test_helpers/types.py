"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    FIELD_SUPERVISOR = "FieldSupervisor"
    CERTIFICATE_OFFICER = "CertificateOfficer"
    CLIENT_CONTACT = "ClientContact"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPLICANT = "APPLICANT"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class CertificationScheme(str, Enum):
    KOSHER = "KOSHER"
    HALAL = "HALAL"
    DUAL = "DUAL"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FacilityStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FacilityRole(str, Enum):
    OWNED = "OWNED"
    CO_PACKER = "CO_PACKER"


class DedicationStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    DEDICATED = "DEDICATED"
    SHARED = "SHARED"


class KosherizationState(str, Enum):
    NONE = "NONE"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    COMPROMISED = "COMPROMISED"


class IngredientStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGE_PENDING = "CHANGE_PENDING"


class SourceCategory(str, Enum):
    ANIMAL = "ANIMAL"
    PLANT = "PLANT"
    MICROBIAL = "MICROBIAL"
    MINERAL = "MINERAL"
    SYNTHETIC = "SYNTHETIC"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CERTIFIABLE = "CERTIFIABLE"
    REVIEW_HOLD = "REVIEW_HOLD"
    WITHDRAWN = "WITHDRAWN"


class ProductIngredientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_REAPPROVAL = "PENDING_REAPPROVAL"
    BLOCKED = "BLOCKED"
    REMOVED = "REMOVED"


class VisitType(str, Enum):
    INITIAL = "INITIAL"
    ROUTINE = "ROUTINE"
    UNANNOUNCED = "UNANNOUNCED"
    SPECIAL_HOLIDAY = "SPECIAL_HOLIDAY"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_ACCESS = "NO_ACCESS"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"


class FindingOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_NO_ACCESS = "AUTO_NO_ACCESS"


class BillingCycle(str, Enum):
    ANNIVERSARY = "ANNIVERSARY"
    CALENDAR_YEAR = "CALENDAR_YEAR"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class InvoiceType(str, Enum):
    ANNUAL_CERTIFICATION = "ANNUAL_CERTIFICATION"
    PRODUCT_ADDITION = "PRODUCT_ADDITION"
    RENEWAL = "RENEWAL"
    REINSTATEMENT = "REINSTATEMENT"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class TermType(str, Enum):
    ANNUAL = "ANNUAL"
    SEASONAL = "SEASONAL"


class ScopeStatus(str, Enum):
    FULL = "FULL"
    PARTIAL_FROZEN = "PARTIAL_FROZEN"


class CertificateProductStatus(str, Enum):
    INCLUDED = "INCLUDED"
    FROZEN = "FROZEN"
    REMOVED = "REMOVED"


class HolidayCode(str, Enum):
    PASSOVER = "PASSOVER"
    ROSH_HASHANAH = "ROSH_HASHANAH"
    RAMADAN = "RAMADAN"
    EID_AL_FITR = "EID_AL_FITR"


class WindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class AgencyClient(TypedDict, total=False):
    id: str
    legal_name: str
    certification_scheme: str
    contact_email: str
    status: str
    open_nc_score: int
    risk_tier: str
    total_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    address: str
    facility_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentLine(TypedDict, total=False):
    id: str
    facility_id: str
    designation: str
    dedication_status: str
    kosherization_state: str
    kosherized_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    manufacturer: str
    source_category: str
    has_species_documentation: bool
    change_summary: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    client_id: str
    brand: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductIngredient(TypedDict, total=False):
    id: str
    product_id: str
    ingredient_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupervisionVisit(TypedDict, total=False):
    id: str
    facility_id: str
    visit_type: str
    inspector_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    id: str
    visit_id: str
    facility_id: str
    severity: str
    description: str
    remediation_deadline: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificationAgreement(TypedDict, total=False):
    id: str
    client_id: str
    scheme: str
    billing_cycle: str
    term_start_date: str
    term_end_date: str
    per_product_fee_cents: int
    annual_fee_snapshot_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    client_id: str
    agreement_id: Optional[str]
    related_certificate_id: Optional[str]
    invoice_type: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    due_date: str
    paid_recorded_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    client_id: str
    scheme: str
    term_type: str
    holiday_window_id: Optional[str]
    facility_ids: List[str]
    renews_certificate_id: Optional[str]
    status: str
    scope_status: str
    active_product_count: int
    issued_at: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificateProduct(TypedDict, total=False):
    id: str
    certificate_id: str
    product_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HolidayProductionWindow(TypedDict, total=False):
    id: str
    facility_id: str
    holiday_code: str
    window_start: str
    window_end: str
    assigned_supervisor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
