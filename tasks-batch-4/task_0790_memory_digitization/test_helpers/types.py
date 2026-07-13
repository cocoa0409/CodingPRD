"""Domain types: entity TypedDicts, status enums, role enum.

All names use the vocabulary of the Memory Digitization PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    INTAKE_TECH = "IntakeTech"
    LAB_TECH = "LabTech"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    ADMIN = "Admin"


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class PlanTier(str, Enum):
    STANDARD_KIT = "STANDARD_KIT"
    FAMILY_KIT = "FAMILY_KIT"
    CLOSET_KIT = "CLOSET_KIT"


class Turnaround(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class OutputType(str, Enum):
    CLOUD = "CLOUD"
    USB = "USB"
    DVD = "DVD"


class OrderFulfillmentStatus(str, Enum):
    QUOTED = "QUOTED"
    AWAITING_MEDIA = "AWAITING_MEDIA"
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    READY = "READY"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class MachineKind(str, Enum):
    TAPE_DECK = "TAPE_DECK"
    FILM_SCANNER = "FILM_SCANNER"
    PHOTO_SCANNER = "PHOTO_SCANNER"
    AUDIO_DECK = "AUDIO_DECK"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOADED = "LOADED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MediaType(str, Enum):
    TAPE = "TAPE"
    FILM = "FILM"
    PHOTO = "PHOTO"
    AUDIO = "AUDIO"


class MediaItemStatus(str, Enum):
    LOGGED = "LOGGED"
    PREPPED = "PREPPED"
    SCANNING = "SCANNING"
    QC_PENDING = "QC_PENDING"
    QC_FAIL = "QC_FAIL"
    OUTPUT_READY = "OUTPUT_READY"
    WRITTEN_OFF = "WRITTEN_OFF"


class QCDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class OutputArtifactStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClaimType(str, Enum):
    LOST = "LOST"
    DAMAGED = "DAMAGED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    wallet_credit_cents: int
    risk_score: int
    approved_claim_count: int
    pending_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    plan_tier: str
    turnaround: str
    output_option: str
    lost_damage_protection: bool
    is_gift: bool
    gift_recipient_email: Optional[str]
    promo_code: Optional[str]
    declared_tape_count: int
    declared_film_count: int
    declared_photo_count: int
    declared_audio_count: int
    fulfillment_status: str
    payment_status: str
    estimate_total_cents: int
    final_total_cents: Optional[int]
    captured_total_cents: int
    refunded_total_cents: int
    received_item_count: int
    written_off_count: int
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    name: str
    kind: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict):
    id: str
    label: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    machine_id: str
    scheduled_start: str
    scheduled_end: str
    capacity: int
    status: str
    loaded_count: int
    created_at: str
    updated_at: str
    version: int


class MediaItem(TypedDict):
    id: str
    order_id: str
    batch_id: Optional[str]
    bin_id: str
    media_type: str
    barcode: Optional[str]
    status: str
    qc_attempts: int
    digitized_minutes: Optional[float]
    page_count: Optional[int]
    stored_at: str
    retention_until: str
    created_at: str
    updated_at: str
    version: int


class OutputArtifact(TypedDict):
    id: str
    order_id: str
    output_type: str
    status: str
    download_token: str
    download_count: int
    expires_at: str
    item_count_snapshot: int
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    order_id: str
    media_item_id: str
    claim_type: str
    declared_value_cents: Optional[int]
    status: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable audit records, only id + created_at
class QCReview(TypedDict):
    id: str
    media_item_id: str
    decision: str
    attempt_number: int
    notes: Optional[str]
    created_at: str


class DownloadEvent(TypedDict):
    id: str
    output_artifact_id: str
    sequence_number: int
    downloaded_at: str
    created_at: str
