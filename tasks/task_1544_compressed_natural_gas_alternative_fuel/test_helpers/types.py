"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class StationStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class UptimePosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"


class AccessMode(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    DUAL = "DUAL"


class CompressorCondition(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"


class DispenserStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    CALIBRATION_HOLD = "CALIBRATION_HOLD"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FuelType(str, Enum):
    CNG = "CNG"
    RNG = "RNG"


class CalibrationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SessionStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AccessType(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class VoidReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    MANAGER_VOID = "MANAGER_VOID"
    TIMEOUT = "TIMEOUT"
    STATION_OUTAGE = "STATION_OUTAGE"
    INSPECTION_FAIL = "INSPECTION_FAIL"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class WindowType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"
    EMERGENCY = "EMERGENCY"


class BackupStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVATED = "ACTIVATED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    APPROVED = "APPROVED"


class InspectionType(str, Enum):
    ANNUAL_COMPREHENSIVE = "ANNUAL_COMPREHENSIVE"
    ODORIZATION_CHECK = "ODORIZATION_CHECK"
    PRESSURE_VESSEL = "PRESSURE_VESSEL"


class InspectionResult(str, Enum):
    PASS = "PASS"
    PASS_WITH_DEFICIENCIES = "PASS_WITH_DEFICIENCIES"
    FAIL = "FAIL"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    NETWORK_OPERATOR = "NetworkOperator"
    STATION_MANAGER = "StationManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FLEET_ACCOUNT_MANAGER = "FleetAccountManager"
    FLEET_DRIVER = "FleetDriver"
    ANONYMOUS = "Anonymous"


# --- Entity TypedDicts -------------------------------------------------------
# Resources carrying the full common-field set (id, created_at, updated_at,
# version) per PRD §2.4; calibration records and monthly settlements are
# immutable and carry only id + created_at.


class Station(TypedDict):
    id: str
    station_name: str
    station_code: str
    access_mode: str
    backup_capacity_gge: int
    uptime_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Compressor(TypedDict):
    id: str
    station_id: str
    compressor_code: str
    capacity_scf_per_minute: int
    condition: str
    created_at: str
    updated_at: str
    version: int


class Dispenser(TypedDict):
    id: str
    station_id: str
    dispenser_code: str
    fuel_type: str
    status: str
    correction_factor: float
    last_calibration_at: str
    calibration_due_at: str
    created_at: str
    updated_at: str
    version: int


class CalibrationRecord(TypedDict):
    # Immutable record: only id + created_at among the common fields (PRD §2.4).
    id: str
    dispenser_id: str
    measured_error_pct: float
    result: str
    applied_correction_factor: Optional[float]
    performed_at: str
    created_at: str


class PricingPolicy(TypedDict):
    id: str
    station_id: str
    access_scope: str
    fuel_type: str
    price_per_gge_cents: int
    tier_threshold_gge: Optional[float]
    tier_price_cents: Optional[int]
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    account_name: str
    billing_email: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetCard(TypedDict):
    id: str
    fleet_account_id: str
    card_number: str
    vehicle_plate: str
    daily_gge_limit: float
    status: str
    current_day_gge: float
    current_day_date: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict):
    id: str
    fleet_account_id: str
    station_id: str
    committed_monthly_gge: float
    contract_price_per_gge_cents: int
    shortfall_tier1_rate_cents: int
    shortfall_tier2_rate_cents: int
    start_month: str
    end_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlySettlement(TypedDict):
    # Immutable record: only id + created_at among the common fields (PRD §2.4).
    id: str
    supply_contract_id: str
    month: str
    delivered_gge: float
    shortfall_gge: float
    penalty_cents: int
    settled_at: str
    created_at: str


class FuelingSession(TypedDict):
    id: str
    access_type: str
    station_id: str
    dispenser_id: str
    fleet_card_id: Optional[str]
    fleet_account_id: Optional[str]
    client_ref: str
    estimated_gge: float
    unit_price_cents: int
    hold_amount_cents: int
    metered_mass_kg: Optional[float]
    correction_factor_applied: Optional[float]
    provisional_gge: Optional[float]
    settled_gge: Optional[float]
    total_amount_cents: Optional[int]
    status: str
    void_reason: Optional[str]
    authorized_at: str
    completed_at: Optional[str]
    voided_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    station_id: str
    compressor_id: Optional[str]
    starts_at: str
    ends_at: str
    window_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BackupFuelingArrangement(TypedDict):
    id: str
    station_id: str
    partner_station_code: str
    available_from: str
    available_until: str
    committed_gge: int
    used_gge: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict):
    id: str
    station_id: str
    inspection_type: str
    scheduled_for: str
    status: str
    result: Optional[str]
    findings: Optional[str]
    performed_by: Optional[str]
    approved_by: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxCreditClaim(TypedDict):
    id: str
    station_id: str
    period_start: str
    period_end: str
    status: str
    eligible_gge_provisional: float
    claim_amount_provisional_cents: int
    eligible_gge_final: Optional[float]
    claim_amount_final_cents: Optional[int]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
