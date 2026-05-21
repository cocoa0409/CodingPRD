"""Domain types: entity TypedDicts, status enums, role enum.

Two entities are immutable append-only records per PRD §2.4:
"Two entities — `FuelCardTransaction` and `TelematicsEvent` — are
immutable append-only records: they carry `id` and `created_at` only,
and both `updated_at` and `version` are absent because there is no
in-place edit path that could refresh them."

Their TypedDicts therefore omit `updated_at` and `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    TAX_ADMIN = "TaxAdmin"
    CLAIM_ADJUSTER = "ClaimAdjuster"
    VENDOR_OPS = "VendorOps"
    LESSEE = "Lessee"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class LesseeAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    IN_SHOP = "IN_SHOP"
    GROUNDED = "GROUNDED"
    RETIRED = "RETIRED"


class VehicleClass(str, Enum):
    CLASS_3 = "CLASS_3"
    CLASS_5 = "CLASS_5"
    CLASS_7 = "CLASS_7"
    CLASS_8 = "CLASS_8"


class LeaseState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    IN_RETURN = "IN_RETURN"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class FuelCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class FuelCardTxnStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    IFTA_INCLUDED = "IFTA_INCLUDED"


class TelematicsIngestStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_STALE = "REJECTED_STALE"


class MaintenanceTicketKind(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"


class MaintenanceTicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_SHOP = "IN_SHOP"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CollisionClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OverageSettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class IFTAFilingStatus(str, Enum):
    OPEN = "OPEN"
    READY = "READY"
    CLOSED = "CLOSED"


class USJurisdiction(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"
    IL = "IL"
    FL = "FL"
    OH = "OH"
    PA = "PA"
    GA = "GA"
    WA = "WA"
    AZ = "AZ"


# ===========================================================================
# Entity TypedDicts — common-fields entities carry id, created_at,
# updated_at, version. Append-only entities (FuelCardTransaction,
# TelematicsEvent) carry only id + created_at + entity-specific fields.
# ===========================================================================
class Lessee(TypedDict, total=False):
    id: str
    legal_name: str
    dot_number: str
    base_jurisdiction: str
    account_status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    vehicle_class: str
    model_year: int
    odometer_baseline_miles: int
    odometer_current_miles: int
    vehicle_status: str
    current_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    lessee_id: str
    vehicle_id: str
    term_start_date: str
    term_end_date: str
    monthly_mileage_allowance: int
    overage_rate_cents_per_mile: int
    tiered_overage_enabled: bool
    lease_state: str
    cumulative_overage_miles: int
    collision_open_count: int
    created_at: str
    updated_at: str
    version: int


class FuelCard(TypedDict, total=False):
    id: str
    lease_agreement_id: str
    card_pan_last4: str
    monthly_limit_cents: int
    card_status: str
    current_period_spend_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only — PRD §2.4 — carries only id + created_at
class FuelCardTransaction(TypedDict, total=False):
    id: str
    fuel_card_id: str
    posted_at: str
    jurisdiction: str
    gallons: float
    amount_cents: int
    txn_status: str
    ifta_eligible: bool
    created_at: str


# Append-only — PRD §2.4 — carries only id + created_at
class TelematicsEvent(TypedDict, total=False):
    id: str
    vehicle_id: str
    event_ts: str
    odometer_reading: int
    harsh_event_count: int
    fault_code: str
    ingest_status: str
    created_at: str


class MaintenanceTicket(TypedDict, total=False):
    id: str
    vehicle_id: str
    ticket_kind: str
    opened_at_odometer: int
    estimate_cents: int
    actual_cents: int
    ticket_status: str
    created_at: str
    updated_at: str
    version: int


class CollisionClaim(TypedDict, total=False):
    id: str
    lease_agreement_id: str
    vehicle_id: str
    incident_ts: str
    estimate_cents: int
    revised_estimate_cents: int
    lessee_deductible_cents: int
    claim_status: str
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class OverageSettlement(TypedDict, total=False):
    id: str
    lease_agreement_id: str
    period_year: int
    period_month: int
    provisional_overage_miles: int
    final_overage_miles: int
    provisional_balance_cents: int
    balance_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class IFTAQuarter(TypedDict, total=False):
    id: str
    lessee_id: str
    year: int
    quarter: int
    filing_status: str
    total_taxable_gallons: float
    total_tax_cents: int
    created_at: str
    updated_at: str
    version: int


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "LesseeAccountStatus",
    "VehicleStatus",
    "VehicleClass",
    "LeaseState",
    "FuelCardStatus",
    "FuelCardTxnStatus",
    "TelematicsIngestStatus",
    "MaintenanceTicketKind",
    "MaintenanceTicketStatus",
    "CollisionClaimStatus",
    "OverageSettlementStatus",
    "IFTAFilingStatus",
    "USJurisdiction",
    # Entities
    "Lessee",
    "Vehicle",
    "LeaseAgreement",
    "FuelCard",
    "FuelCardTransaction",
    "TelematicsEvent",
    "MaintenanceTicket",
    "CollisionClaim",
    "OverageSettlement",
    "IFTAQuarter",
]
