"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SHIPPER = "Shipper"
    CARRIER = "Carrier"
    DRIVER = "Driver"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class ReeferUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    RETIRED = "RETIRED"


class ShipmentStatus(str, Enum):
    TENDERED = "TENDERED"
    ACCEPTED = "ACCEPTED"
    PRECOOLED = "PRECOOLED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CargoClass(str, Enum):
    FOOD = "FOOD"
    PHARMA = "PHARMA"
    GENERAL = "GENERAL"


class LoadIntegrityPosture(str, Enum):
    INTACT = "INTACT"
    AT_RISK = "AT_RISK"
    COMPROMISED = "COMPROMISED"


class Impairment(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    TOTAL_LOSS = "TOTAL_LOSS"


class SpoilageStatus(str, Enum):
    SOUND = "SOUND"
    IMPAIRED = "IMPAIRED"
    SPOILED = "SPOILED"


class ReadingKind(str, Enum):
    TEMP = "TEMP"
    DOOR_OPEN = "DOOR_OPEN"
    PRECOOL = "PRECOOL"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class StopKind(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Carrier(TypedDict):
    id: str
    legal_name: str
    fsma_registered: bool
    sanitary_training_current: bool
    liability_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class ReeferUnit(TypedDict):
    id: str
    carrier_id: str
    asset_tag: str
    compartment_count: int
    status: str
    last_sanitation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TempLane(TypedDict):
    id: str
    code: str
    setpoint_min_c: float
    setpoint_max_c: float
    regulated: bool
    tolerance_degree_minutes: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    shipper_user_id: str
    carrier_id: str
    reefer_unit_id: Optional[str]
    cargo_class: str
    status: str
    load_integrity_posture: str
    precool_verified: bool
    total_detention_fee_cents: int
    total_lumper_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Compartment(TypedDict):
    id: str
    shipment_id: str
    temp_lane_id: str
    ordinal: int
    door_open_events: int
    degree_minutes_out: float
    impairment: str
    created_at: str
    updated_at: str
    version: int


class ProductLot(TypedDict):
    id: str
    compartment_id: str
    sku: str
    pallet_count: int
    declared_value_cents: int
    spoilage_status: str
    created_at: str
    updated_at: str
    version: int


class SpoilageClaim(TypedDict):
    id: str
    shipment_id: str
    filed_by_user_id: str
    status: str
    claimed_value_cents: int
    approved_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class StopEvent(TypedDict):
    id: str
    shipment_id: str
    kind: str
    appointment_min: int
    arrived_min: Optional[int]
    departed_min: Optional[int]
    pallets_handled: int
    compartments_touched: int
    status: str
    detention_fee_cents: int
    lumper_fee_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only telemetry event; ONLY id + created_at
class SensorReading(TypedDict):
    id: str
    compartment_id: str
    kind: str
    temp_c: Optional[float]
    offset_min: int
    excursion_flagged: bool
    created_at: str
