"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FLEET_OPS = "FleetOps"
    FINANCE_OPS = "FinanceOps"
    OWNER = "Owner"


class ProgramPosture(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WINDING_DOWN = "WINDING_DOWN"
    CLOSED = "CLOSED"


class AircraftStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    GROUNDED = "GROUNDED"


class OwnerStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class ShareStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    LISTED = "LISTED"
    IN_EXIT = "IN_EXIT"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONALLY_BILLED = "PROVISIONALLY_BILLED"
    FINALLY_BILLED = "FINALLY_BILLED"


class NoticeTier(str, Enum):
    TIER_24H = "TIER_24H"
    TIER_72H = "TIER_72H"
    TIER_7D = "TIER_7D"


class InterchangeDirection(str, Enum):
    NONE = "NONE"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    DISPUTED = "DISPUTED"
    SETTLED_AFTER_DISPUTE = "SETTLED_AFTER_DISPUTE"


class LineKind(str, Enum):
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    OCCUPIED_HOURS = "OCCUPIED_HOURS"
    PEAK_SURCHARGE = "PEAK_SURCHARGE"
    INTERCHANGE_ADJUSTMENT = "INTERCHANGE_ADJUSTMENT"
    MAINTENANCE_ALLOCATION = "MAINTENANCE_ALLOCATION"
    DEPRECIATION_PASSTHROUGH = "DEPRECIATION_PASSTHROUGH"


class ListingStatus(str, Enum):
    LISTED = "LISTED"
    UNDER_OFFER = "UNDER_OFFER"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScheduleMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    DOUBLE_DECLINING = "DOUBLE_DECLINING"


class ExitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALUED = "VALUED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# --- Entities carrying id + created_at + updated_at + version (PRD §2.5) ---


class Program(TypedDict, total=False):
    id: str
    program_code: str
    currency: str
    program_posture: str
    contract_year_start_month: int
    peak_day_calendar: list
    created_at: str
    updated_at: str
    version: int


class AircraftClass(TypedDict, total=False):
    id: str
    class_code: str
    program_id: str
    hourly_rate_cents: int
    interchange_upgrade_multiplier_bp: int
    monthly_fee_base_cents: int
    seats: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    tail_number: str
    program_id: str
    class_id: str
    aircraft_status: str
    total_hours_flown: float
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict, total=False):
    id: str
    legal_name: str
    program_id: str
    owner_standing: str
    deposit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Share(TypedDict, total=False):
    id: str
    owner_id: str
    class_id: str
    fraction_numerator: int
    fraction_denominator: int
    annual_entitlement_hours: float
    hours_remaining_cy: float
    contract_year_index: int
    share_status: str
    purchase_price_cents: int
    created_at: str
    updated_at: str
    version: int


class BookingRequest(TypedDict, total=False):
    id: str
    share_id: str
    requested_class_id: str
    scheduled_departure_utc: str
    estimated_block_hours: float
    notice_tier: str
    booking_status: str
    billing_status: str
    assigned_aircraft_id: Optional[str]
    interchange_direction: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    owner_id: str
    billing_period: str
    invoice_status: str
    management_fee_cents: int
    occupied_hours_fee_cents: int
    total_due_cents: int
    tax_adjustment_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferListing(TypedDict, total=False):
    id: str
    share_id: str
    asking_price_cents: int
    listing_status: str
    buyer_owner_id: Optional[str]
    program_repurchase_flag: bool
    created_at: str
    updated_at: str
    version: int


class MaintenanceEvent(TypedDict, total=False):
    id: str
    aircraft_id: str
    window_start_utc: str
    window_end_utc: str
    event_status: str
    cost_cents: int
    unscheduled_flag: bool
    created_at: str
    updated_at: str
    version: int


class ExitRequest(TypedDict, total=False):
    id: str
    share_id: str
    exit_status: str
    buyout_amount_cents: Optional[int]
    early_exit_penalty_cents: Optional[int]
    settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: ONLY id + created_at, NO updated_at / version (PRD §2.5) ---


class FlightLeg(TypedDict, total=False):
    id: str
    booking_id: str
    aircraft_id: str
    actual_block_hours: float
    peak_day_flag: bool
    completed_at: str
    created_at: str


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    line_kind: str
    booking_id: Optional[str]
    share_id: str
    quantity_hours: float
    amount_cents: int
    created_at: str


class DepreciationSchedule(TypedDict, total=False):
    id: str
    share_id: str
    schedule_method: str
    recovery_years: int
    basis_cents: int
    accumulated_depreciation_cents: int
    current_year_allowance_cents: int
    created_at: str
