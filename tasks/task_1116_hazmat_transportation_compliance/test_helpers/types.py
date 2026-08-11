"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CARRIER_ADMIN = "CarrierAdmin"
    SHIPPER_COMPLIANCE_OFFICER = "ShipperComplianceOfficer"
    REGULATOR = "Regulator"


class CarrierStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED_ACTIVE = "APPROVED_ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class RegistrationTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class SecurityPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    UNDER_REVISION = "UNDER_REVISION"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class HazardClass(str, Enum):
    CLASS_1_1 = "CLASS_1_1"
    CLASS_1_2 = "CLASS_1_2"
    CLASS_1_3 = "CLASS_1_3"
    CLASS_2_1 = "CLASS_2_1"
    CLASS_2_2 = "CLASS_2_2"
    CLASS_2_3 = "CLASS_2_3"
    CLASS_3 = "CLASS_3"
    CLASS_4_1 = "CLASS_4_1"
    CLASS_4_2 = "CLASS_4_2"
    CLASS_4_3 = "CLASS_4_3"
    CLASS_5_1 = "CLASS_5_1"
    CLASS_5_2 = "CLASS_5_2"
    CLASS_6_1 = "CLASS_6_1"
    CLASS_6_2 = "CLASS_6_2"
    CLASS_7 = "CLASS_7"
    CLASS_8 = "CLASS_8"
    CLASS_9 = "CLASS_9"


class PackingGroup(str, Enum):
    PG_I = "PG_I"
    PG_II = "PG_II"
    PG_III = "PG_III"
    PG_NONE = "PG_NONE"


class PlacardTable(str, Enum):
    TABLE_1 = "TABLE_1"
    TABLE_2 = "TABLE_2"


class TransportCategory(str, Enum):
    EXPLOSIVE = "EXPLOSIVE"
    FLAMMABLE_LIQUID = "FLAMMABLE_LIQUID"
    OXIDIZER = "OXIDIZER"
    RADIOACTIVE = "RADIOACTIVE"
    INHALATION_TOXIC = "INHALATION_TOXIC"
    CORROSIVE = "CORROSIVE"
    MISC = "MISC"


class SegregationGroup(str, Enum):
    SG_NONE = "SG_NONE"
    SG_ACID = "SG_ACID"
    SG_ALKALI = "SG_ALKALI"
    SG_OXIDIZER = "SG_OXIDIZER"
    SG_FLAMMABLE = "SG_FLAMMABLE"


class PackagingSpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class QualificationPosture(str, Enum):
    SUSPENDED = "SUSPENDED"
    ENDORSEMENT_EXPIRED = "ENDORSEMENT_EXPIRED"
    TRAINING_LAPSED = "TRAINING_LAPSED"
    QUALIFIED = "QUALIFIED"


class TrainingType(str, Enum):
    INITIAL = "INITIAL"
    RECURRENT = "RECURRENT"


class VehicleClass(str, Enum):
    VAN = "VAN"
    FLATBED = "FLATBED"
    TANKER = "TANKER"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    PACKAGING_VERIFIED = "PACKAGING_VERIFIED"
    DOCUMENTED = "DOCUMENTED"
    REJECTED = "REJECTED"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ShippingPaperStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    LOCKED_IN_TRANSIT = "LOCKED_IN_TRANSIT"
    VOIDED = "VOIDED"


class VehicleLoadStatus(str, Enum):
    STAGING = "STAGING"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    VOIDED = "VOIDED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CATASTROPHIC = "CATASTROPHIC"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    PHONE_REPORTED = "PHONE_REPORTED"
    WRITTEN_FILED = "WRITTEN_FILED"
    CLOSED = "CLOSED"


class InvoiceKind(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"
    REINSTATEMENT = "REINSTATEMENT"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts ---
# Common resources carry id + created_at + updated_at + version (PRD §2.5).
# TrainingRecord and LoadItem carry ONLY id + created_at (PRD §2.5).

class Carrier(TypedDict, total=False):
    id: str
    legal_name: str
    usdot_number: str
    fleet_size_declared: int
    verified_fleet_size: Optional[int]
    hazmat_categories: List[str]
    accepts_dangerous_placard_substitution: bool
    registration_status: str
    registration_tier: str
    registration_expires_at: Optional[str]
    security_plan_required: bool
    outstanding_balance_cents: int
    credit_balance_cents: int
    safety_rating: int
    created_at: str
    updated_at: str
    version: int


class SecurityPlan(TypedDict, total=False):
    id: str
    carrier_id: str
    plan_name: str
    coverage_categories: List[str]
    effective_from: str
    effective_to: str
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazmatMaterial(TypedDict, total=False):
    id: str
    un_na_number: str
    proper_shipping_name: str
    hazard_class: str
    packing_group: str
    placard_table: str
    transport_category: str
    reportable_quantity_lbs: float
    is_inhalation_hazard: bool
    segregation_group: str
    erg_guide_number: str
    requires_security_plan: bool
    created_at: str
    updated_at: str
    version: int


class PackagingSpec(TypedDict, total=False):
    id: str
    spec_code: str
    authorized_hazard_classes: List[str]
    max_packing_group: str
    max_net_quantity_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    carrier_id: str
    full_name: str
    cdl_number: str
    hazmat_endorsement_expires_at: str
    status: str
    qualification_posture: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    driver_id: str
    training_type: str
    completed_at: str
    expires_at: str
    certificate_code: str
    created_at: str


class Vehicle(TypedDict, total=False):
    id: str
    carrier_id: str
    plate_number: str
    vehicle_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    carrier_id: str
    material_id: str
    packaging_spec_id: str
    driver_id: Optional[str]
    declared_shipping_name: str
    normalized_shipping_name: Optional[str]
    quantity_kg: float
    declared_value_cents: int
    status: str
    classified_by_user_id: Optional[str]
    pinned_security_plan_id: Optional[str]
    pinned_security_plan_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShippingPaper(TypedDict, total=False):
    id: str
    shipment_id: str
    emergency_contact_phone: str
    er_response_guide_number: str
    emergency_response_summary: str
    shipper_certification_signed: bool
    certified_by_user_id: Optional[str]
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VehicleLoad(TypedDict, total=False):
    id: str
    vehicle_id: str
    route_id: str
    planned_departure_at: str
    planned_arrival_at: str
    total_table2_weight_kg: float
    required_placards: List[str]
    handling_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadItem(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    load_id: str
    shipment_id: str
    position_code: str
    created_at: str


class Route(TypedDict, total=False):
    id: str
    route_code: str
    allowed_hazard_classes: List[str]
    is_restricted_corridor: bool
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    shipment_id: str
    carrier_id: str
    occurred_at: str
    severity: str
    confirmed_severity: Optional[str]
    phone_report_required: bool
    phone_deadline: str
    written_report_deadline: str
    phone_reported_at: Optional[str]
    written_filed_at: Optional[str]
    is_phone_late: bool
    is_written_late: bool
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrationInvoice(TypedDict, total=False):
    id: str
    carrier_id: str
    kind: str
    assessment_year: int
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    total_due_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
