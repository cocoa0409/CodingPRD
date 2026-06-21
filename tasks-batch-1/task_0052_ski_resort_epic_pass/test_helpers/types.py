"""Domain types: entity TypedDicts, status enums, and the role enum.

Most resources (Resort, PassProduct, Pass, BuddyTicket, RefundRequest,
InterchangeAgreement) carry the full common set id/created_at/updated_at/version.
A LiftScan is an immutable audit row and carries only id + created_at — it has
neither an updated_at nor a version field.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────

class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    RESORT_OPS = "ResortOps"
    REFUND_ADMIN = "RefundAdmin"


# ─── Status / enum value sets ─────────────────────────────────

class ResortStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class HomeNetwork(str, Enum):
    EPIC = "EPIC"
    IKON = "IKON"


class PassTier(str, Enum):
    LOCAL = "LOCAL"
    EPIC_DAY = "EPIC_DAY"
    FULL_EPIC = "FULL_EPIC"


class PassStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class ScanResult(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    BLACKOUT = "BLACKOUT"
    TOKEN_MISMATCH = "TOKEN_MISMATCH"
    NOT_ACTIVE = "NOT_ACTIVE"
    NO_INTERCHANGE = "NO_INTERCHANGE"
    RESORT_SUSPENDED = "RESORT_SUSPENDED"
    ANTI_PASSBACK = "ANTI_PASSBACK"


class BuddyTicketStatus(str, Enum):
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    CANCELLED = "CANCELLED"


class RefundReason(str, Enum):
    INJURY = "INJURY"
    RELOCATION = "RELOCATION"
    DISSATISFIED = "DISSATISFIED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ─── Entity TypedDicts (common_fields: true) ──────────────────

class Resort(TypedDict):
    id: str
    name: str
    home_network: str
    status: str
    gate_count: int
    created_at: str
    updated_at: str
    version: int


class PassProduct(TypedDict):
    id: str
    tier: str
    price_cents: int
    blackout_dates: List[str]
    buddy_ticket_allotment: int
    buddy_ticket_price_cents: int
    ikon_interchange_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Pass(TypedDict):
    id: str
    pass_product_id: str
    holder_name: str
    magnetic_token: str
    status: str
    activated_on: Optional[str]
    scan_count: int
    buddy_tickets_remaining: int
    refund_basis_cents: int
    created_at: str
    updated_at: str
    version: int


class BuddyTicket(TypedDict):
    id: str
    pass_id: str
    resort_id: str
    guest_name: str
    valid_date: str
    price_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    pass_id: str
    reason: str
    scan_count_at_request: int
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InterchangeAgreement(TypedDict):
    id: str
    resort_id: str
    max_interchange_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) ────────────────

class LiftScan(TypedDict):
    id: str
    pass_id: str
    resort_id: str
    presented_token: str
    scan_at: str
    scan_date: str
    result: str
    denial_reason: Optional[str]
    created_at: str
    # NOTE: no updated_at, no version — LiftScan is an immutable audit row.
