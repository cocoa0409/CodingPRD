"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields vs lean entities:
    "A Park, a Lot, a Home, a Resident, a Lease, a RentIncreaseNotice,
    an EvictionCase, a HomeSaleTransfer, and a ConversionRequest all
    carry the full four-field envelope. The only exception is a
    UtilityBill: because a bill is materially immutable once written by
    the billing sweep ... a UtilityBill carries id and created_at but
    no updated_at and no version."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PARK_MANAGER = "ParkManager"
    RESIDENT = "Resident"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# State code — PRD §2.9
# ---------------------------------------------------------------------------
class StateCode(str, Enum):
    CA = "CA"
    FL = "FL"
    OR = "OR"
    AZ = "AZ"
    TX = "TX"


class ApportionmentMethod(str, Enum):
    SUB_METER = "SUB_METER"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class OwnershipMode(str, Enum):
    PARK_OWNED = "PARK_OWNED"
    RESIDENT_OWNED = "RESIDENT_OWNED"


# ---------------------------------------------------------------------------
# Lease — PRD §3.2, §3.3, §3.4, §3.7
# ---------------------------------------------------------------------------
class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    GRACE = "GRACE"
    TERMINATED = "TERMINATED"
    ASSUMED = "ASSUMED"


# ---------------------------------------------------------------------------
# RentIncreaseNotice — PRD §3.5
# ---------------------------------------------------------------------------
class RentIncreaseNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EFFECTIVE = "EFFECTIVE"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# EvictionCase — PRD §3.6
# ---------------------------------------------------------------------------
class EvictionCaseStatus(str, Enum):
    FILED = "FILED"
    IN_CURE = "IN_CURE"
    CURED = "CURED"
    FINALIZED_FOR_CAUSE = "FINALIZED_FOR_CAUSE"
    DISMISSED = "DISMISSED"


class ViolationType(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    RULE_VIOLATION = "RULE_VIOLATION"
    ILLEGAL_USE = "ILLEGAL_USE"


# ---------------------------------------------------------------------------
# HomeSaleTransfer — PRD §3.7
# ---------------------------------------------------------------------------
class HomeSaleTransferStatus(str, Enum):
    PENDING_PARK_APPROVAL = "PENDING_PARK_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# ConversionRequest — PRD §3.8
# ---------------------------------------------------------------------------
class ConversionRequestStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities (id, created_at,
# updated_at, version) per PRD §2.4
# ---------------------------------------------------------------------------
class Park(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    master_cpi_pct: float
    utility_apportionment_method: str
    billing_period_anchor_day: int
    ownership_pool_count: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    park_id: str
    lot_number: str
    ownership_mode: str
    base_rent_cents: int
    sub_meter_reading_kwh: float
    home_id: Optional[str]
    current_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Home(TypedDict, total=False):
    id: str
    park_id: str
    lot_id: Optional[str]
    owner_resident_id: Optional[str]
    vin: str
    assessed_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    violation_count_12mo: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    lot_id: str
    resident_id: str
    monthly_rent_cents: int
    start_date: str
    status: str
    outstanding_balance_cents: int
    predecessor_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentIncreaseNotice(TypedDict, total=False):
    id: str
    lease_id: str
    proposed_new_rent_cents: int
    effective_on: str
    capped_new_rent_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict, total=False):
    id: str
    lease_id: str
    violation_type: str
    filed_at: str
    cure_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeSaleTransfer(TypedDict, total=False):
    id: str
    home_id: str
    seller_resident_id: str
    buyer_resident_id: str
    sale_price_cents: int
    status: str
    new_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionRequest(TypedDict, total=False):
    id: str
    lot_id: str
    prospective_buyer_resident_id: str
    offer_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entity — PRD §2.4: UtilityBill carries ONLY id + created_at.
# ---------------------------------------------------------------------------
class UtilityBill(TypedDict, total=False):
    id: str
    lot_id: str
    lease_id: Optional[str]
    billing_period_start: str
    billing_period_end: str
    master_total_cents: int
    lot_share_cents: int
    rent_due_cents: int
    total_due_cents: int
    paid_at: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "StateCode",
    "ApportionmentMethod",
    "OwnershipMode",
    "LeaseStatus",
    "RentIncreaseNoticeStatus",
    "EvictionCaseStatus",
    "ViolationType",
    "HomeSaleTransferStatus",
    "ConversionRequestStatus",
    "Park",
    "Lot",
    "Home",
    "Resident",
    "Lease",
    "RentIncreaseNotice",
    "EvictionCase",
    "HomeSaleTransfer",
    "ConversionRequest",
    "UtilityBill",
]
