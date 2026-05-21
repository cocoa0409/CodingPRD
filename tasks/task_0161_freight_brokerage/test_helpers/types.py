"""Domain types: entity TypedDicts, status enums, role enum.

Derived directly from the PRD entity descriptions in §3 and the role
list in §2.1. Invoice and FactoringAdvance are append-only financial
records per PRD §2.4 — their TypedDicts deliberately omit `updated_at`
and `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER_OPS = "BrokerOps"
    CARRIER_OPS = "CarrierOps"
    SHIPPER_USER = "ShipperUser"
    CARRIER_USER = "CarrierUser"


# ---------------------------------------------------------------------------
# Equipment type and claim type enums — PRD §3.4, §3.9
# ---------------------------------------------------------------------------
class EquipmentType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class AccessorialChargeType(str, Enum):
    LAYOVER = "LAYOVER"
    TONU = "TONU"
    REWEIGH = "REWEIGH"
    LUMPER = "LUMPER"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    SHORTAGE = "SHORTAGE"
    OVERCHARGE = "OVERCHARGE"
    LATE_DELIVERY = "LATE_DELIVERY"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CarrierStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class QuoteRequestStatus(str, Enum):
    OPEN = "OPEN"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RateSource(str, Enum):
    SPOT = "SPOT"
    CONTRACT = "CONTRACT"


class RateContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class LoadStatus(str, Enum):
    TENDERED = "TENDERED"
    ACCEPTED = "ACCEPTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class AccessorialChargeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InvoiceFactoringStatus(str, Enum):
    NOT_FACTORED = "NOT_FACTORED"
    FACTORED = "FACTORED"
    RECOURSED = "RECOURSED"


class InvoiceSettlementStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class DisputeClaimStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    COUNTER_OFFERED = "COUNTER_OFFERED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Common-field bearers — id, created_at, updated_at, version per PRD §2.4
# ---------------------------------------------------------------------------
class Brokerage(TypedDict, total=False):
    id: str
    name: str
    mc_number: str
    factoring_reserve_pct: float
    detention_free_minutes: int
    detention_rate_cents_per_15min: int
    clock_now_iso: str
    created_at: str
    updated_at: str
    version: int


class Shipper(TypedDict, total=False):
    id: str
    brokerage_id: str
    company_name: str
    smartway_required: bool
    credit_limit_cents: int
    outstanding_invoiced_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    brokerage_id: str
    legal_name: str
    mc_number: str
    usdot_number: str
    insurance_expires_on: str
    smartway_certified: bool
    safety_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuoteRequest(TypedDict, total=False):
    id: str
    shipper_id: str
    brokerage_id: str
    origin_zip: str
    destination_zip: str
    equipment_type: str
    pickup_window_start: str
    pickup_window_end: str
    rate_contract_id: Optional[str]
    rate_source: Optional[str]
    quoted_linehaul_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RateContract(TypedDict, total=False):
    id: str
    brokerage_id: str
    shipper_id: str
    lane_origin_zip: str
    lane_destination_zip: str
    equipment_type: str
    flat_rate_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict, total=False):
    id: str
    shipper_id: str
    brokerage_id: str
    quote_request_id: str
    carrier_id: str
    rate_source: str
    linehaul_cents: int
    provisional_detention_cents: int
    final_detention_cents: Optional[int]
    accessorial_total_cents: int
    actual_arrive_at: Optional[str]
    actual_depart_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessorialCharge(TypedDict, total=False):
    id: str
    load_id: str
    brokerage_id: str
    charge_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeClaim(TypedDict, total=False):
    id: str
    invoice_id: str
    brokerage_id: str
    claim_type: str
    claimed_cents: int
    counter_offer_cents: Optional[int]
    settled_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: Invoice and FactoringAdvance carry only
# `id` and `created_at`. NO updated_at, NO version.
# ---------------------------------------------------------------------------
class Invoice(TypedDict, total=False):
    id: str
    load_id: str
    shipper_id: str
    brokerage_id: str
    linehaul_cents: int
    detention_cents: int
    accessorial_cents: int
    invoice_total_cents: int
    amount_paid_cents: int
    amount_credited_cents: int
    balance_due_cents: int
    factoring_status: str
    settlement_status: str
    created_at: str


class FactoringAdvance(TypedDict, total=False):
    id: str
    invoice_id: str
    brokerage_id: str
    invoice_total_at_advance_cents: int
    haircut_cents: int
    reserve_cents: int
    advanced_cents: int
    recourse_owed_cents: int
    created_at: str


__all__ = [
    "UserRole",
    "EquipmentType",
    "AccessorialChargeType",
    "ClaimType",
    "ShipperStatus",
    "CarrierStatus",
    "QuoteRequestStatus",
    "RateSource",
    "RateContractStatus",
    "LoadStatus",
    "AccessorialChargeStatus",
    "InvoiceFactoringStatus",
    "InvoiceSettlementStatus",
    "DisputeClaimStatus",
    "Brokerage",
    "Shipper",
    "Carrier",
    "QuoteRequest",
    "RateContract",
    "Load",
    "AccessorialCharge",
    "DisputeClaim",
    "Invoice",
    "FactoringAdvance",
]
