"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry id + created_at + updated_at + version (PRD section 2.4
grants every resource the same four system-managed properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    DISPATCHER = "Dispatcher"
    TERMINAL_OPERATOR = "TerminalOperator"
    WASH_OPERATOR = "WashOperator"
    SAFETY_OFFICER = "SafetyOfficer"
    DRIVER = "Driver"
    CUSTOMER_REP = "CustomerRep"


class CompatibilityGroup(str, Enum):
    PETROLEUM = "PETROLEUM"
    SOLVENT = "SOLVENT"
    ACID = "ACID"
    CAUSTIC = "CAUSTIC"
    VEG_OIL = "VEG_OIL"
    FOOD_GRADE = "FOOD_GRADE"
    LATEX = "LATEX"


class HazmatClass(str, Enum):
    NONE = "NONE"
    CLASS_3_FLAMMABLE = "CLASS_3_FLAMMABLE"
    CLASS_8_CORROSIVE = "CLASS_8_CORROSIVE"
    CLASS_6_TOXIC = "CLASS_6_TOXIC"


class PackingGroup(str, Enum):
    NONE = "NONE"
    I = "I"
    II = "II"
    III = "III"


class WashLevel(str, Enum):
    NONE = "NONE"
    FLUSH = "FLUSH"
    DETERGENT_WASH = "DETERGENT_WASH"
    CHEMICAL_KOSHER = "CHEMICAL_KOSHER"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TrailerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"


class CertStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CERTIFIED = "CERTIFIED"
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    VARIANCE_REVIEW = "VARIANCE_REVIEW"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class MeterTicketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class DeliveryTicketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_VARIANCE = "CLOSED_VARIANCE"


class RetainSampleStatus(str, Enum):
    RETAINED = "RETAINED"
    DISPOSED = "DISPOSED"


class SpillPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    REPORTABLE = "REPORTABLE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    dedicated_program_enrolled: bool
    status: str
    exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    name: str
    compatibility_group: str
    hazmat_class: str
    packing_group: str
    density_lb_per_gal: float
    temp_coeff_per_degF: float
    placard_code: str
    created_at: str
    updated_at: str
    version: int


class CompatibilityRule(TypedDict, total=False):
    id: str
    prior_group: str
    next_group: str
    required_wash_level: str
    forbidden: bool
    created_at: str
    updated_at: str
    version: int


class TankTrailer(TypedDict, total=False):
    id: str
    unit_number: str
    capacity_gallons: int
    tare_weight_lb: int
    tare_steer_lb: int
    tare_drive_lb: int
    tare_trailer_lb: int
    steer_axle_rating_lb: int
    drive_axle_rating_lb: int
    trailer_axle_rating_lb: int
    gvwr_lb: int
    last_product_group: Optional[str]
    last_wash_cert_id: Optional[str]
    dedicated_customer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    full_name: str
    cdl_number: str
    tanker_endorsement: bool
    hazmat_endorsement: bool
    endorsement_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WashBay(TypedDict, total=False):
    id: str
    bay_code: str
    supported_wash_levels: List[str]
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class TankWashCertificate(TypedDict, total=False):
    id: str
    trailer_id: str
    wash_bay_id: str
    wash_level: str
    window_start: str
    window_end: str
    certified_at: Optional[str]
    expires_at: Optional[str]
    consumed_by_shipment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadingRack(TypedDict, total=False):
    id: str
    rack_code: str
    terminal_name: str
    authorized_groups: List[str]
    open_hour: int
    close_hour: int
    meter_id: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    customer_id: str
    product_id: str
    ordered_gallons: int
    route_miles: int
    rate_per_gal_cents: int
    trailer_id: Optional[str]
    driver_id: Optional[str]
    rack_id: Optional[str]
    wash_cert_id: Optional[str]
    rack_window_start: Optional[str]
    rack_window_end: Optional[str]
    weights_verified_at: Optional[str]
    placards_confirmed: bool
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    reconciled_at: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeterTicket(TypedDict, total=False):
    id: str
    shipment_id: str
    rack_id: str
    opened_at: str
    closed_at: Optional[str]
    meter_start_gal: Optional[float]
    meter_end_gal: Optional[float]
    observed_temp_F: Optional[float]
    observed_gallons: Optional[float]
    net60_gallons: Optional[float]
    closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict, total=False):
    id: str
    shipment_id: str
    opened_at: str
    closed_at: Optional[str]
    delivered_observed_gal: Optional[float]
    delivered_temp_F: Optional[float]
    delivered_net60_gal: Optional[float]
    loaded_net60_gal: Optional[float]
    allowed_loss_gal: Optional[float]
    variance_gallons: Optional[float]
    closed_by_driver_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetainSample(TypedDict, total=False):
    id: str
    shipment_id: str
    delivery_ticket_id: str
    quantity_ml: int
    taken_at: str
    retain_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpillResponsePlan(TypedDict, total=False):
    id: str
    customer_id: str
    product_id: str
    equipment_checklist: List[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpillIncident(TypedDict, total=False):
    id: str
    shipment_id: str
    reported_by_driver_id: str
    occurred_at: str
    reported_at: str
    gallons_spilled: float
    severity: str
    closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DedicatedTrailerAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    trailer_id: str
    committed_loads_per_month: int
    effective_from: str
    effective_to: str
    flagged_shipment_count: int
    last_settled_month: Optional[str]
    shortfall_events: int
    shortfall_fees_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
