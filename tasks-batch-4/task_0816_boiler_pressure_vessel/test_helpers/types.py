"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields follow the Boiler & Pressure-Vessel Inspection PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    JURISDICTION_ADMIN = "JurisdictionAdmin"
    OWNER = "Owner"
    INSPECTOR = "Inspector"


# --- Value enums -------------------------------------------------------------
class VesselClass(str, Enum):
    POWER_BOILER = "POWER_BOILER"
    HEATING_BOILER = "HEATING_BOILER"
    PRESSURE_VESSEL = "PRESSURE_VESSEL"


class InspectorType(str, Enum):
    JURISDICTION = "JURISDICTION"
    INSURANCE = "INSURANCE"


class InspectionType(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"
    SPECIAL = "SPECIAL"


class DeficiencySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    CRITICAL = "CRITICAL"


# --- Status enums ------------------------------------------------------------
class InspectorStatus(str, Enum):
    PENDING = "PENDING"
    COMMISSIONED = "COMMISSIONED"
    SUSPENDED = "SUSPENDED"


class VesselRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    RETIRED = "RETIRED"


class VesselServiceStatus(str, Enum):
    NOT_IN_SERVICE = "NOT_IN_SERVICE"
    IN_SERVICE = "IN_SERVICE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class InsurancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    PASSED_WITH_DEFICIENCIES = "PASSED_WITH_DEFICIENCIES"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REPAIR = "UNDER_REPAIR"
    REINSPECTION = "REINSPECTION"
    CLEARED = "CLEARED"
    WITHDRAWN = "WITHDRAWN"


class RepairOrderStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class FeeInvoiceStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    admin_fee_pct: float
    interval_months_override: Optional[int]
    collected_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class InsuranceCompany(TypedDict):
    id: str
    name: str
    nb_accreditation_number: str
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    name: str
    commission_number: str
    inspector_type: str
    insurance_company_id: Optional[str]
    commissioning_jurisdiction_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    owner_id: str
    jurisdiction_id: str
    manufacturer: str
    national_board_number: str
    vessel_class: str
    mawp_psig: int
    installed_at: str
    jurisdiction_number: Optional[str]
    registration_status: str
    service_status: str
    current_certificate_id: Optional[str]
    open_deficiency_count: int
    open_critical_deficiency_count: int
    risk_score_standard: Optional[int]
    risk_score_forecast: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    vessel_id: str
    insurance_company_id: str
    coverage_start: str
    coverage_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    vessel_id: str
    inspector_id: str
    inspection_type: str
    is_special: bool
    scheduled_start: str
    scheduled_end: str
    status: str
    provisional_fee_cents: int
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class NationalBoardReport(TypedDict):
    id: str
    inspection_id: str
    report_number: str
    filed_by_inspector_id: str
    findings_summary: str
    created_at: str


class Deficiency(TypedDict):
    id: str
    inspection_id: str
    vessel_id: str
    repair_order_id: Optional[str]
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    vessel_id: str
    deficiency_ids: List[str]
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    vessel_id: str
    inspection_id: str
    fee_invoice_id: str
    supersedes_certificate_id: Optional[str]
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    vessel_id: str
    inspection_id: str
    certificate_id: Optional[str]
    amount_cents: int
    amount_paid_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    vessel_id: str
    triggered_inspection_id: Optional[str]
    severity: str
    occurred_at: str
    narrative: str
    created_at: str
    updated_at: str
    version: int
