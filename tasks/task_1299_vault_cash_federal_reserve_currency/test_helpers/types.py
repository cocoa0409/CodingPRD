"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.5: VaultSite, StaffMember, Carrier, AtmMachine, SeasonalWindow, FedOrder,
CashShipment, FitnessBatch, CounterfeitCase, Reconciliation, and AtmForecast carry
id + created_at + updated_at + version. DenominationLine and CashLedgerEntry carry
only id and created_at — both updated_at and version are absent on those two types.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class SiteType(str, Enum):
    CENTRAL = "CENTRAL"
    BRANCH = "BRANCH"


class VaultPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    FROZEN = "FROZEN"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AtmCashPosture(str, Enum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class AtmServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FedOrderDirection(str, Enum):
    ORDER = "ORDER"
    DEPOSIT = "DEPOSIT"


class FedOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class CashShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    EXCEPTION = "EXCEPTION"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class FitnessBatchStatus(str, Enum):
    OPEN = "OPEN"
    SORTED = "SORTED"
    SETTLED = "SETTLED"


class CounterfeitCaseStatus(str, Enum):
    DETECTED = "DETECTED"
    SEIZED = "SEIZED"
    REPORTED = "REPORTED"
    SETTLED_WITH_FED = "SETTLED_WITH_FED"
    RELEASED = "RELEASED"


class LedgerEntryType(str, Enum):
    OPENING_BALANCE = "OPENING_BALANCE"
    FED_RECEIPT = "FED_RECEIPT"
    FED_DEPOSIT = "FED_DEPOSIT"
    SHIPMENT_IN = "SHIPMENT_IN"
    SHIPMENT_OUT = "SHIPMENT_OUT"
    ATM_LOAD = "ATM_LOAD"
    ATM_RESIDUAL_RETURN = "ATM_RESIDUAL_RETURN"
    FITNESS_RECLASS = "FITNESS_RECLASS"
    COUNTERFEIT_SEIZURE = "COUNTERFEIT_SEIZURE"
    COUNTERFEIT_RELEASE = "COUNTERFEIT_RELEASE"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerBucket(str, Enum):
    FIT = "FIT"
    UNFIT = "UNFIT"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    BALANCED = "BALANCED"
    VARIANCE_PENDING = "VARIANCE_PENDING"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class AtmForecastVariant(str, Enum):
    TRAILING = "TRAILING"
    SEASONAL = "SEASONAL"


class AtmForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOADED = "LOADED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    CASH_OPERATIONS_ADMIN = "CashOperationsAdmin"
    VAULT_CUSTODIAN = "VaultCustodian"
    FED_COORDINATOR = "FedCoordinator"
    CARRIER_DISPATCHER = "CarrierDispatcher"
    ATM_ANALYST = "AtmAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full audit-field entities (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class VaultSite(TypedDict, total=False):
    id: str
    name: str
    site_type: str
    vault_limit_cents: int
    insurance_coverage_cents: int
    dock_capacity: int
    opening_fit_cents: int
    opening_unfit_cents: int
    on_hand_fit_cents: int
    on_hand_unfit_cents: int
    reserved_out_cents: int
    in_transit_inbound_cents: int
    pending_inbound_order_cents: int
    on_hand_total_cents: int
    insurance_headroom_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    home_site_id: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    name: str
    liability_cap_per_truck_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AtmMachine(TypedDict, total=False):
    id: str
    site_id: str
    terminal_code: str
    cash_capacity_cents: int
    opening_balance_cents: int
    current_balance_cents: int
    cash_posture: str
    service_status: str
    current_forecast_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonalWindow(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    start_date: str
    end_date: str
    multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class FedOrder(TypedDict, total=False):
    id: str
    site_id: str
    direction: str
    business_date: str
    face_total_cents: int
    fee_total_cents: int
    grand_total_cents: int
    advice_count: int
    settled_basis_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CashShipment(TypedDict, total=False):
    id: str
    fed_order_id: Optional[str]
    carrier_id: str
    origin_site_id: Optional[str]
    destination_site_id: Optional[str]
    declared_value_cents: int
    counted_value_cents: Optional[int]
    scheduled_departure_at: str
    scheduled_arrival_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FitnessBatch(TypedDict, total=False):
    id: str
    site_id: str
    input_unfit_cents: int
    fit_recovered_cents: int
    unfit_remaining_cents: int
    counterfeit_face_cents: int
    shrink_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CounterfeitCase(TypedDict, total=False):
    id: str
    site_id: str
    fitness_batch_id: Optional[str]
    denomination_cents: int
    note_count: int
    face_value_cents: int
    seized_by_staff_id: Optional[str]
    seized_at: Optional[str]
    reported_by_staff_id: Optional[str]
    reported_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    site_id: str
    business_date: str
    opening_balance_cents: int
    counted_on_hand_cents: Optional[int]
    counted_by_staff_id: Optional[str]
    provisional_expected_cents: int
    final_expected_cents: int
    variance_cents: Optional[int]
    approved_by_staff_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AtmForecast(TypedDict, total=False):
    id: str
    atm_id: str
    forecast_date: str
    w1_cents: int
    w2_cents: int
    w3_cents: int
    variant_applied: str
    projected_base_cents: int
    projected_final_cents: int
    recommended_load_cents: int
    residual_target_cents: int
    actual_withdrawals_cents: Optional[int]
    residual_balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — ONLY id + created_at (no updated_at, no version)
# ---------------------------------------------------------------------------

class DenominationLine(TypedDict, total=False):
    id: str
    created_at: str
    fed_order_id: str
    denomination_cents: int
    strap_count: int
    line_cents: int
    fee_cents: int


class CashLedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    site_id: str
    business_date: str
    entry_type: str
    signed_amount_cents: int
    bucket: str
    note: str
