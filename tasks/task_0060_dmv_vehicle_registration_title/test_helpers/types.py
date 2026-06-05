"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CLERK_AGENT = "ClerkAgent"
    INSPECTION_STATION = "InspectionStation"
    OWNER = "Owner"
    DMV_ADMIN = "DmvAdmin"


class CredentialType(str, Enum):
    STANDARD = "STANDARD"
    REAL_ID = "REAL_ID"


class RealIdStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    UPGRADED = "UPGRADED"


class VinStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class TitleStatus(str, Enum):
    NONE = "NONE"
    CLEAR = "CLEAR"
    REBUILT = "REBUILT"


class VehicleClass(str, Enum):
    PASSENGER = "PASSENGER"
    TRUCK = "TRUCK"
    MOTORCYCLE = "MOTORCYCLE"


class VinOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NHTSA_FLAG = "NHTSA_FLAG"


class TitleApplicationType(str, Enum):
    INITIAL = "INITIAL"
    TRANSFER = "TRANSFER"


class TitleApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SALVAGE_HOLD = "SALVAGE_HOLD"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"


class TitleBrand(str, Enum):
    CLEAR = "CLEAR"
    REBUILT = "REBUILT"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LienStatus(str, Enum):
    FILED = "FILED"
    PERFECTED = "PERFECTED"
    RELEASED = "RELEASED"


class FeeAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class RegistrationType(str, Enum):
    INITIAL = "INITIAL"
    TRANSFER = "TRANSFER"


class RegistrationStatus(str, Enum):
    PENDING_FEES = "PENDING_FEES"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PlateType(str, Enum):
    PHYSICAL = "PHYSICAL"
    ELECTRONIC = "ELECTRONIC"


class PlateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    SURRENDERED = "SURRENDERED"


class RealIdApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --- Entity TypedDicts ---
# Entities carrying the full common-field set (id + created_at + updated_at + version).

class Owner(TypedDict):
    id: str
    full_name: str
    residence_county_code: str
    credential_type: str
    identity_documents_verified: bool
    real_id_status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    owner_id: str
    vin: str
    model_year: int
    purchase_price_cents: int
    msrp_cents: int
    vehicle_class: str
    vin_status: str
    title_status: str
    is_salvage_branded: bool
    active_lien_count: int
    created_at: str
    updated_at: str
    version: int


class TitleApplication(TypedDict):
    id: str
    vehicle_id: str
    applicant_owner_id: str
    application_type: str
    status: str
    requires_salvage_path: bool
    issued_title_brand: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvageInspection(TypedDict):
    id: str
    title_application_id: str
    station_id: str
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    vehicle_id: str
    lien_holder_name: str
    principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionsInspection(TypedDict):
    id: str
    vehicle_id: str
    station_id: str
    result: str
    inspected_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    registration_id: str
    use_tax_cents: int
    registration_fee_cents: int
    real_id_surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    vehicle_id: str
    owner_id: str
    registration_type: str
    bundle_real_id: bool
    status: str
    term_start: Optional[str]
    term_end: Optional[str]
    plate_assigned: bool
    created_at: str
    updated_at: str
    version: int


class LicensePlate(TypedDict):
    id: str
    registration_id: str
    plate_number: str
    plate_type: str
    issued_at: str
    surrendered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RealIdApplication(TypedDict):
    id: str
    owner_id: str
    status: str
    documents_complete: bool
    created_at: str
    updated_at: str
    version: int


# Write-once inspection record: carries ONLY id + created_at (no updated_at, no version).
class VinVerification(TypedDict):
    id: str
    vehicle_id: str
    submitted_vin: str
    outcome: str
    created_at: str
