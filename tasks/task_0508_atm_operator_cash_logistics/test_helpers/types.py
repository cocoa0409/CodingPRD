"""Domain types: entity TypedDicts, status enums, role enum (ATM Cash Logistics API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VAULT_CONTROLLER = "VaultController"
    FIELD_TECH = "FieldTech"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums (PRD §2.5, §3) ---
class ATMOperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FAULTED = "FAULTED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ATMCashStatus(str, Enum):
    EMPTY = "EMPTY"
    AWAITING_LOAD = "AWAITING_LOAD"
    LOADED = "LOADED"
    LOW = "LOW"
    RECONCILING = "RECONCILING"


class CassetteBalanceStatus(str, Enum):
    BALANCED = "BALANCED"
    OVER = "OVER"
    SHORT = "SHORT"


class ReplenishmentOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    LOADED = "LOADED"
    SETTLED = "SETTLED"
    RECALLED = "RECALLED"


class TransactionKind(str, Enum):
    WITHDRAWAL = "WITHDRAWAL"
    BALANCE_INQUIRY = "BALANCE_INQUIRY"


class CashCountOutcome(str, Enum):
    BALANCED = "BALANCED"
    OVER = "OVER"
    SHORT = "SHORT"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class FaultKind(str, Enum):
    CASH_JAM = "CASH_JAM"
    CARD_READER = "CARD_READER"
    NETWORK = "NETWORK"
    DISPENSER = "DISPENSER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class SettlementRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"


class CommissionStatementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class FeeDisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CommissionBasis(str, Enum):
    GREATER_OF = "GREATER_OF"
    PCT_ONLY = "PCT_ONLY"
    FLAT_ONLY = "FLAT_ONLY"


class PayoutStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class JurisdictionCode(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FL = "FL"


# --- Entity TypedDicts (PRD §2.4) ---
# All entities below carry the full common-field set (id, created_at, updated_at, version)
# EXCEPT Transaction, which is an append-only event record (id + created_at only).

class Location(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    site_merchant_id: str
    route_id: str
    address: str
    created_at: str
    updated_at: str
    version: int


class SiteMerchant(TypedDict):
    id: str
    legal_name: str
    commission_pct_bps: int
    commission_flat_per_wd_cents: int
    commission_monthly_ceiling_cents: int
    commission_basis: str
    payout_status: str
    created_at: str
    updated_at: str
    version: int


class ArmoredRoute(TypedDict):
    id: str
    carrier_name: str
    vault_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vault(TypedDict):
    id: str
    name: str
    provisioned_cents: int
    balance_cents: int
    in_transit_cents: int
    in_machine_cents: int
    created_at: str
    updated_at: str
    version: int


class ATM(TypedDict):
    id: str
    serial_no: str
    location_id: str
    note_denomination_cents: int
    surcharge_cents: int
    operational_status: str
    cash_status: str
    monthly_wd_count: int
    loaded_cents: int
    dispensed_cents_since_load: int
    fee_disclosure_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cassette(TypedDict):
    id: str
    atm_id: str
    position: str
    loaded_cents: int
    dispensed_cents: int
    balance_status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict):
    id: str
    atm_id: str
    route_id: str
    vault_id: Optional[str]
    order_amount_cents: int
    forecast_basis: str
    service_window_start: str
    service_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only event record — NO updated_at, NO version (PRD §2.4).
class Transaction(TypedDict):
    id: str
    atm_id: str
    cassette_id: Optional[str]
    kind: str
    amount_cents: int
    surcharge_cents: int
    settlement_run_id: Optional[str]
    monthly_seq: Optional[int]
    created_at: str


class CashCount(TypedDict):
    id: str
    atm_id: str
    counted_cents: int
    expected_remaining_cents: int
    variance_cents: int
    outcome: str
    tolerance_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    atm_id: str
    fault_kind: str
    severity: str
    status: str
    reopen_count: int
    assigned_tech_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementRun(TypedDict):
    id: str
    atm_id: str
    window_start: str
    window_end: str
    withdrawal_count: int
    surcharge_revenue_cents: int
    interchange_revenue_cents: int
    network_fee_cents: int
    net_operator_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    settlement_run_id: str
    site_merchant_id: str
    pct_amount_cents: int
    flat_amount_cents: int
    commission_cents: int
    operator_keeps_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeDisclosure(TypedDict):
    id: str
    atm_id: str
    disclosed_surcharge_cents: int
    jurisdiction_code: str
    regulatory_cap_cents: int
    ack_text_present: bool
    status: str
    created_at: str
    updated_at: str
    version: int
