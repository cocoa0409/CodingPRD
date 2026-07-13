"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    HARBORMASTER = "Harbormaster"
    FINANCE_CLERK = "FinanceClerk"
    BOATER = "Boater"


# --- Status / value enums ---
class BerthType(str, Enum):
    SLIP = "SLIP"
    MOORING = "MOORING"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class Residency(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class BerthStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PumpoutStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVERDUE = "OVERDUE"
    NA = "NA"


class PermitStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    TRANSFERRED = "TRANSFERRED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"


class PermitSource(str, Enum):
    DIRECT = "DIRECT"
    WAITLIST = "WAITLIST"
    LOTTERY = "LOTTERY"
    TRANSFER = "TRANSFER"


class DerelictStatus(str, Enum):
    OPEN = "OPEN"
    NOTICE_SERVED = "NOTICE_SERVED"
    RESOLVED = "RESOLVED"
    IMPOUNDED = "IMPOUNDED"


class RampPassType(str, Enum):
    DAY = "DAY"
    SEASONAL = "SEASONAL"


class RampPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LotteryRoundStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"
    CLOSED = "CLOSED"


class LotteryEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    WON = "WON"
    LOST = "LOST"
    CLAIMED = "CLAIMED"
    FORFEITED = "FORFEITED"


class InvoiceType(str, Enum):
    PERMIT = "PERMIT"
    RAMP_PASS = "RAMP_PASS"
    DERELICT = "DERELICT"
    TRANSFER = "TRANSFER"


class InvoiceStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"
    WAIVED = "WAIVED"


# --- Entity TypedDicts ---
# All carry id/created_at/updated_at/version EXCEPT PumpOutRecord (append-only).
class Marina(TypedDict):
    id: str
    name: str
    season_start_date: str
    season_end_date: str
    liveaboard_cap: int
    pumpout_interval_days: int
    available_slip_count: int
    occupied_slip_count: int
    available_mooring_count: int
    occupied_mooring_count: int
    liveaboard_count: int
    waitlist_length: int
    created_at: str
    updated_at: str
    version: int


class Berth(TypedDict):
    id: str
    marina_id: str
    berth_type: str
    size_class: str
    max_length_ft: int
    resident_only: bool
    status: str
    current_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Boater(TypedDict):
    id: str
    full_name: str
    email: str
    residency_status: str
    street_address: Optional[str]
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    boater_id: str
    name: str
    length_ft: int
    registration_number: str
    registration_expiry_date: str
    has_holding_tank: bool
    last_pumpout_date: Optional[str]
    registration_status: str
    pumpout_status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    marina_id: str
    boater_id: str
    vessel_id: str
    berth_id: Optional[str]
    requested_berth_type: str
    requested_size_class: str
    season_year: int
    season_start_date: str
    season_end_date: str
    is_liveaboard: bool
    source: str
    fee_basis: str
    priority_tier: int
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    activated_on_date: Optional[str]
    offer_expires_at: Optional[str]
    invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PumpOutRecord(TypedDict):
    # Append-only: id + created_at only (PRD §2.4).
    id: str
    vessel_id: str
    pumpout_date: str
    recorded_by_role: str
    created_at: str


class DerelictReport(TypedDict):
    id: str
    vessel_id: str
    reason: str
    status: str
    notice_served_date: Optional[str]
    closed_date: Optional[str]
    estimated_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RampPass(TypedDict):
    id: str
    boater_id: str
    vessel_id: str
    pass_type: str
    valid_from_date: str
    valid_to_date: str
    fee_basis: str
    fee_cents: int
    invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LotteryRound(TypedDict):
    id: str
    marina_id: str
    season_year: int
    berth_type: str
    entry_open_date: str
    entry_close_date: str
    berth_ids: List[str]
    status: str
    drawn_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryEntry(TypedDict):
    id: str
    round_id: str
    boater_id: str
    vessel_id: str
    draw_number: int
    priority_tier: int
    awarded_berth_id: Optional[str]
    claim_deadline: Optional[str]
    permit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    boater_id: str
    invoice_type: str
    reference_id: str
    amount_due_cents: int
    amount_paid_cents: int
    amount_refunded_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
