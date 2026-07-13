"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Weights & Measures Device Inspection PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INSPECTOR = "Inspector"
    ESTABLISHMENT = "Establishment"


# --------------------------------------------------------------------------- #
# Status enums (PRD §3)
# --------------------------------------------------------------------------- #
class EstablishmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeviceType(str, Enum):
    SCALE = "SCALE"
    FUEL_PUMP = "FUEL_PUMP"
    SCANNER = "SCANNER"


class DeviceClass(str, Enum):
    CLASS_III = "CLASS_III"
    CLASS_IIIL = "CLASS_IIIL"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SEALED = "SEALED"
    CONDEMNED = "CONDEMNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class InspectionType(str, Enum):
    ACCURACY_TEST = "ACCURACY_TEST"
    PRICE_VERIFICATION = "PRICE_VERIFICATION"
    COMPLAINT_RETEST = "COMPLAINT_RETEST"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class SealStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class CondemnationStatus(str, Enum):
    ISSUED = "ISSUED"
    LIFTED = "LIFTED"


class ViolationType(str, Enum):
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
    PRICE_ERROR = "PRICE_ERROR"
    OPERATING_CONDEMNED = "OPERATING_CONDEMNED"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class FeeType(str, Enum):
    REGISTRATION = "REGISTRATION"


class FeeInvoiceStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# Entities with all four common properties (id, created_at, updated_at, version)
# per PRD §2.4.
# --------------------------------------------------------------------------- #
class Establishment(TypedDict):
    id: str
    name: str
    jurisdiction: str
    status: str
    balance_due_cents: int
    sealed_device_count: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    region: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    establishment_id: str
    device_type: str
    device_class: str
    serial_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    device_id: str
    inspector_id: str
    complaint_id: Optional[str]
    inspection_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    device_id: str
    complainant_name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Seal(TypedDict):
    id: str
    device_id: str
    inspection_id: str
    seal_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CondemnationOrder(TypedDict):
    id: str
    device_id: str
    inspection_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Penalty(TypedDict):
    id: str
    establishment_id: str
    device_id: str
    violation_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    establishment_id: str
    device_id: str
    fee_type: str
    base_amount_cents: int
    amount_due_cents: int
    proration_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only line items (PRD §2.4, §3.4): id + created_at ONLY.
# No updated_at, no version.
# --------------------------------------------------------------------------- #
class TestReading(TypedDict):
    id: str
    inspection_id: str
    applied_load: float
    indicated_value: float
    error_grams: float
    created_at: str


class ScannerAuditItem(TypedDict):
    id: str
    inspection_id: str
    item_sku: str
    posted_price_cents: int
    scanned_price_cents: int
    overcharge_cents: int
    created_at: str
