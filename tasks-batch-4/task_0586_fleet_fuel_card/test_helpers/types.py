"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FLEET_MANAGER = "FleetManager"
    MERCHANT = "Merchant"
    FRAUD_ANALYST = "FraudAnalyst"
    TELEMATICS_GATEWAY = "TelematicsGateway"


# --------------------------------------------------------------------------- #
# Status enums (PRD §3.1–§3.9)
# --------------------------------------------------------------------------- #

class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FuelCardStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class CardAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ENDED = "ENDED"


class PostingStatus(str, Enum):
    """The money axis of a Transaction (PRD §3.5)."""
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    """The fraud-review axis of a Transaction, independent of posting (PRD §3.5–§3.6)."""
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class FuelProduct(str, Enum):
    UNLEADED = "UNLEADED"
    PREMIUM = "PREMIUM"
    DIESEL = "DIESEL"
    DEF = "DEF"


class FraudAlertStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class FraudRuleCode(str, Enum):
    OVER_TANK_FILL = "OVER_TANK_FILL"
    OUTSIDE_HOURS = "OUTSIDE_HOURS"
    PRODUCT_MISMATCH = "PRODUCT_MISMATCH"


class FaultSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class FaultStatus(str, Enum):
    OPEN = "OPEN"
    MAINTENANCE_SCHEDULED = "MAINTENANCE_SCHEDULED"
    MAINTENANCE_COMPLETE = "MAINTENANCE_COMPLETE"
    CLEARED = "CLEARED"


class IftaReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"


class MpgMethod(str, Enum):
    SEGMENT = "SEGMENT"
    ROLLING = "ROLLING"


# --------------------------------------------------------------------------- #
# Entity shapes.
#
# PRD §2.5: every primary resource carries id, created_at, updated_at, version.
# --------------------------------------------------------------------------- #

class FleetAccount(TypedDict):
    id: str
    company_name: str
    status: str
    base_jurisdiction: str
    credit_limit_cents: int
    rebate_tiers: List[dict]
    outstanding_holds_cents: int
    settled_spend_cents: int
    available_credit_cents: int
    rebate_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    fleet_account_id: str
    plate: str
    tank_capacity_gallons: float
    starting_odometer: float
    current_odometer: float
    expected_mpg_min: float
    expected_mpg_max: float
    home_jurisdiction: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    fleet_account_id: str
    full_name: str
    pin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelCard(TypedDict):
    id: str
    fleet_account_id: str
    last4: str
    status: str
    allowed_products: List[str]
    daily_dollar_limit_cents: int
    per_txn_gallon_limit: float
    allowed_start_hour: int
    allowed_end_hour: int
    created_at: str
    updated_at: str
    version: int


class CardAssignment(TypedDict):
    id: str
    card_id: str
    vehicle_id: str
    driver_id: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    card_id: str
    vehicle_id: str
    driver_id: str
    product: str
    gallons: float
    unit_price_cents: int
    odometer: float
    jurisdiction: str
    gross_amount_cents: int
    hold_amount_cents: int
    segment_miles: float
    mpg_snapshot: float
    mpg_exception: bool
    purchased_at: str
    posting_status: str
    review_status: str
    provisional_rebate_cents: int
    final_rebate_cents: int
    created_at: str
    updated_at: str
    version: int


class FraudAlert(TypedDict):
    id: str
    transaction_id: str
    card_id: str
    rule_code: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TelematicsFault(TypedDict):
    id: str
    vehicle_id: str
    fault_code: str
    severity: str
    status: str
    maintenance_window_start: Optional[str]
    maintenance_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IftaReport(TypedDict):
    id: str
    fleet_account_id: str
    quarter: str
    period_start: str
    period_end: str
    jurisdiction_lines: List[dict]
    total_tax_cents: int
    status: str
    filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
