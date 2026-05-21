"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — entities split into two shapes:

    "Most entities are identified by a server-minted id and additionally
    carry created_at, updated_at, and version. Two entities are
    deliberate exceptions: Title rows carry only id and issued_at — they
    have no updated_at and no version. Similarly, FeeLedgerEntry rows
    carry only id and occurred_at; they are append-only, never edited,
    and have no updated_at and no version."

Common-fields entities (id, created_at, updated_at, version):
    Owner, Vehicle, LienRecord, EmissionsInspection, RealIDApplication,
    Plate, TransferApplication.

Lean entities:
    Title (id, issued_at)
    FeeLedgerEntry (id, occurred_at)
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    VIN_VERIFIER = "VinVerifier"
    TAX_ASSESSOR = "TaxAssessor"
    PLATE_ISSUER = "PlateIssuer"
    SALVAGE_OFFICER = "SalvageOfficer"
    EMISSIONS_INSPECTOR = "EmissionsInspector"
    LIEN_CLERK = "LienClerk"
    REAL_ID_REVIEWER = "RealIDReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 state machines
# ---------------------------------------------------------------------------
class RealIDStatus(str, Enum):
    NOT_APPLIED = "NOT_APPLIED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class VinVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    HOLD = "HOLD"


class TitleStatus(str, Enum):
    CLEAN = "CLEAN"
    SALVAGE_PENDING_REBUILD = "SALVAGE_PENDING_REBUILD"
    REBUILT = "REBUILT"
    NON_REPAIRABLE = "NON_REPAIRABLE"


class LienStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class FuelType(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    HYBRID = "HYBRID"
    ELECTRIC = "ELECTRIC"


class TitleBrand(str, Enum):
    CLEAN = "CLEAN"
    SALVAGE = "SALVAGE"
    REBUILT = "REBUILT"
    FLOOD = "FLOOD"
    LEMON = "LEMON"


class LienRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class EmissionsInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EmissionsOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class RealIDApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DOC_REVIEW = "DOC_REVIEW"
    APPROVED = "APPROVED"
    DOC_REJECTED = "DOC_REJECTED"
    REVOKED = "REVOKED"


class PlateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SURRENDERED = "SURRENDERED"


class PlateSurrenderReason(str, Enum):
    SALVAGE_TRIGGERED = "SALVAGE_TRIGGERED"
    OWNER_REQUEST = "OWNER_REQUEST"
    LIEN_DEFAULT = "LIEN_DEFAULT"
    TRANSFER_COMPLETE = "TRANSFER_COMPLETE"


class TransferApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    VIN_VERIFIED = "VIN_VERIFIED"
    SALVAGE_REVIEW = "SALVAGE_REVIEW"
    SALVAGE_APPROVED = "SALVAGE_APPROVED"
    EMISSIONS_PENDING = "EMISSIONS_PENDING"
    EMISSIONS_PASSED = "EMISSIONS_PASSED"
    TAX_ASSESSED = "TAX_ASSESSED"
    PLATE_ISSUED = "PLATE_ISSUED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class TransferApplicationType(str, Enum):
    INITIAL_REGISTRATION = "INITIAL_REGISTRATION"
    TITLE_TRANSFER = "TITLE_TRANSFER"


class RejectionReason(str, Enum):
    EMISSIONS_FAILED = "EMISSIONS_FAILED"
    NON_REPAIRABLE_SALVAGE = "NON_REPAIRABLE_SALVAGE"
    UNPAID_TIMEOUT = "UNPAID_TIMEOUT"
    OWNER_HOLDS = "OWNER_HOLDS"
    WITHDRAWN = "WITHDRAWN"


class SalvageDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class SalvageSeverity(str, Enum):
    PARTIAL = "PARTIAL"
    TOTAL = "TOTAL"


class FeeLedgerKind(str, Enum):
    SALES_TAX = "SALES_TAX"
    REG_FEE = "REG_FEE"
    PROCESSING_FEE = "PROCESSING_FEE"
    REFUND_TAX = "REFUND_TAX"
    REFUND_REG = "REFUND_REG"
    REFUND_PROCESSING = "REFUND_PROCESSING"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities (id, created_at, updated_at,
# version) per PRD §2.4
# ---------------------------------------------------------------------------
class Owner(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    residency_state: str
    real_id_status: str
    real_id_score: Optional[float]
    real_id_expires_at: Optional[str]
    is_resident: bool
    outstanding_holds_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    make: str
    model: str
    model_year: int
    curb_weight_lbs: int
    fuel_type: str
    vin_verification_status: str
    vin_verified_at: Optional[str]
    title_status: str
    lien_status: str
    current_title_id: Optional[str]
    emissions_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LienRecord(TypedDict, total=False):
    id: str
    title_id: str
    lienholder_name: str
    principal_amount: float
    status: str
    released_at: Optional[str]
    release_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmissionsInspection(TypedDict, total=False):
    id: str
    vehicle_id: str
    station_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    result_recorded_at: Optional[str]
    odometer_reading: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RealIDApplication(TypedDict, total=False):
    id: str
    owner_id: str
    status: str
    documents_proof_of_identity: bool
    documents_proof_of_residency: bool
    documents_proof_of_ssn: bool
    revision_count: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Plate(TypedDict, total=False):
    id: str
    plate_number: str
    vehicle_id: str
    status: str
    activated_at: Optional[str]
    suspended_at: Optional[str]
    surrender_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict, total=False):
    id: str
    vehicle_id: str
    applicant_owner_id: str
    application_type: str
    status: str
    salvage_branch_taken: bool
    trade_in_value: float
    declared_sale_price: float
    fee_subtotal: Optional[float]
    processing_fee: Optional[float]
    total_due: Optional[float]
    paid_at: Optional[str]
    plate_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — PRD §2.4: Title, FeeLedgerEntry carry only id + their
# respective creation timestamps; no updated_at, no version.
# ---------------------------------------------------------------------------
class Title(TypedDict, total=False):
    id: str
    vehicle_id: str
    owner_id: str
    brand: str
    issued_at: str
    superseded_at: Optional[str]
    is_active: bool
    source_application_id: Optional[str]


class FeeLedgerEntry(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    amount_cents: int
    occurred_at: str


__all__ = [
    "UserRole",
    "RealIDStatus",
    "VinVerificationStatus",
    "TitleStatus",
    "LienStatus",
    "FuelType",
    "TitleBrand",
    "LienRecordStatus",
    "EmissionsInspectionStatus",
    "EmissionsOutcome",
    "RealIDApplicationStatus",
    "PlateStatus",
    "PlateSurrenderReason",
    "TransferApplicationStatus",
    "TransferApplicationType",
    "RejectionReason",
    "SalvageDecision",
    "SalvageSeverity",
    "FeeLedgerKind",
    "Owner",
    "Vehicle",
    "LienRecord",
    "EmissionsInspection",
    "RealIDApplication",
    "Plate",
    "TransferApplication",
    "Title",
    "FeeLedgerEntry",
]
