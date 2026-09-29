"""Literal constants of the Vehicle Distribution & Port Processing contract.

Everything here is transcribed from the PRD: route prefixes, enum members,
state names, declared defaults, thresholds and rounding rates.  Nothing in
this module computes anything -- expected figures live in the individual
tests so that a test never re-derives the number it is asserting.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------
API_PREFIX = "/vpc"

PATH_CLOCK_SET = f"{API_PREFIX}/_clock/set_current_utc"
PATH_CLOCK_READ = f"{API_PREFIX}/_clock"
PATH_CENTERS = f"{API_PREFIX}/processing-centers"
PATH_BERTHS = f"{API_PREFIX}/berths"
PATH_VESSELS = f"{API_PREFIX}/vessels"
PATH_VEHICLES = f"{API_PREFIX}/vehicles"
PATH_DAMAGE_SURVEYS = f"{API_PREFIX}/damage-surveys"
PATH_CARRIER_CLAIMS = f"{API_PREFIX}/carrier-claims"
PATH_REPAIR_ORDERS = f"{API_PREFIX}/repair-orders"
PATH_ACCESSORY_KITS = f"{API_PREFIX}/accessory-kits"
PATH_ACCESSORY_WORK_ORDERS = f"{API_PREFIX}/accessory-work-orders"
PATH_QUALITY_INSPECTIONS = f"{API_PREFIX}/quality-inspections"
PATH_HOLD_ORDERS = f"{API_PREFIX}/hold-orders"
PATH_DEALERS = f"{API_PREFIX}/dealers"
PATH_TRUCK_CARRIERS = f"{API_PREFIX}/truck-carriers"
PATH_RELEASE_ORDERS = f"{API_PREFIX}/release-orders"

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
#: The clock's value when it has never been set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
MODEL_LINES = ("LX500", "TX300", "EV900")
MODEL_LINE_LX500 = "LX500"
MODEL_LINE_TX300 = "TX300"
MODEL_LINE_EV900 = "EV900"

ROUTE_ZONES = ("A", "B", "C")
ROUTE_ZONE_A = "A"
ROUTE_ZONE_B = "B"
ROUTE_ZONE_C = "C"

DAMAGE_ZONE_GLASS = "GLASS"
DAMAGE_ZONE_BODY_PANEL = "BODY_PANEL"
DAMAGE_ZONE_INTERIOR = "INTERIOR"
DAMAGE_ZONE_UNDERBODY = "UNDERBODY"

#: Zone weights applied to a damage line's ``severity_points``.
DAMAGE_ZONE_WEIGHTS = {
    DAMAGE_ZONE_UNDERBODY: 1.8,
    DAMAGE_ZONE_GLASS: 1.5,
    DAMAGE_ZONE_BODY_PANEL: 1.2,
    DAMAGE_ZONE_INTERIOR: 1.0,
}

# Vessel discharge status
VESSEL_SCHEDULED = "SCHEDULED"
VESSEL_DISCHARGING = "DISCHARGING"
VESSEL_DISCHARGE_COMPLETE = "DISCHARGE_COMPLETE"

# Vehicle processing dimension
PROC_DISCHARGED = "DISCHARGED"
PROC_SURVEYED = "SURVEYED"
PROC_ACCESSORY_IN_PROGRESS = "ACCESSORY_IN_PROGRESS"
PROC_INSPECTION_PASSED = "INSPECTION_PASSED"
PROC_SHIPPING_READY = "SHIPPING_READY"
PROC_ALLOCATED = "ALLOCATED"
PROC_RELEASED = "RELEASED"
PROC_GATED_OUT = "GATED_OUT"

# Vehicle damage dimension
DAMAGE_NONE = "NONE"
DAMAGE_SURVEY_DAMAGE_OPEN = "SURVEY_DAMAGE_OPEN"
DAMAGE_REPAIR_AUTHORIZED = "REPAIR_AUTHORIZED"
DAMAGE_REPAIRED = "REPAIRED"

# Yard presence
YARD_IN_YARD = "IN_YARD"
YARD_DEPARTED = "DEPARTED"

# Yard posture
POSTURE_OPEN = "OPEN"
POSTURE_CONSTRAINED = "CONSTRAINED"
POSTURE_GRIDLOCK = "GRIDLOCK"

# Damage survey status
SURVEY_DRAFT = "DRAFT"
SURVEY_SUBMITTED = "SUBMITTED"
SURVEY_CLAIMED = "CLAIMED"

# Carrier claim status
CLAIM_FILED = "FILED"
CLAIM_ACCEPTED_PENDING_SETTLEMENT = "ACCEPTED_PENDING_SETTLEMENT"
CLAIM_DISPUTED = "DISPUTED"
CLAIM_DENIED = "DENIED"
CLAIM_SETTLED = "SETTLED"

# Carrier response outcomes
RESPONSE_ACCEPT = "ACCEPT"
RESPONSE_DISPUTE = "DISPUTE"
RESPONSE_DENY = "DENY"

# Recoverable basis
BASIS_SURVEY_BASED = "SURVEY_BASED"
BASIS_REPAIR_ACTUAL = "REPAIR_ACTUAL"

# Repair order status / tier
REPAIR_AUTHORIZED_STATUS = "AUTHORIZED"
REPAIR_ESCALATED_STATUS = "ESCALATED"
REPAIR_REJECTED_STATUS = "REJECTED"
REPAIR_COMPLETED_STATUS = "COMPLETED"
TIER_AUTO = "AUTO"
TIER_ESCALATED = "ESCALATED"
DECISION_AUTHORIZE = "AUTHORIZE"
DECISION_REJECT = "REJECT"

# Accessory work order status
WO_PLANNED = "PLANNED"
WO_KITTED = "KITTED"
WO_INSTALLED = "INSTALLED"
WO_VOIDED = "VOIDED"

# Quality inspection status / outcome
INSPECTION_OPEN = "OPEN"
INSPECTION_PASSED_STATUS = "PASSED"
INSPECTION_FAILED_STATUS = "FAILED"
OUTCOME_PASS = "PASS"
OUTCOME_FAIL = "FAIL"

# Hold order
HOLD_TYPE_RECALL = "RECALL"
HOLD_TYPE_STOP_SHIP = "STOP_SHIP"
HOLD_SCOPE_MODEL_LINE = "MODEL_LINE"
HOLD_SCOPE_SINGLE_VIN = "SINGLE_VIN"
HOLD_OPEN = "OPEN"
HOLD_LIFTED = "LIFTED"

# Truck carrier status
CARRIER_ACTIVE = "ACTIVE"
CARRIER_SUSPENDED = "SUSPENDED"

# Release order status
RO_ALLOCATED = "ALLOCATED"
RO_RELEASED = "RELEASED"
RO_GATED_OUT = "GATED_OUT"
RO_DELIVERED = "DELIVERED"
RO_CANCELLED = "CANCELLED"
RO_CANCELLED_BY_HOLD = "CANCELLED_BY_HOLD"

# --------------------------------------------------------------------------
# Declared defaults
# --------------------------------------------------------------------------
DEFAULT_FREE_STORAGE_DAYS = 5
DEFAULT_TURNAROUND_BUFFER_MINUTES = 120
DEFAULT_CARRIER_STATUS = CARRIER_ACTIVE
DEFAULT_PAGE_LIMIT = 10
DEFAULT_PAGE_OFFSET = 0
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --------------------------------------------------------------------------
# Thresholds and rates stated in the PRD
# --------------------------------------------------------------------------
YARD_GRIDLOCK_RATIO = 0.95
YARD_CONSTRAINED_RATIO = 0.80

SEVERITY_DAMAGE_OPEN_THRESHOLD = 25
SEVERITY_CLAIM_MANDATORY_THRESHOLD = 60
SEVERITY_INDEX_CAP = 100
BREADTH_POINTS_PER_EXTRA_LINE = 5

CLAIM_LINE_CAP_CENTS = 80_000
CLAIM_DEDUCTIBLE_CENTS = 25_000
CLAIM_REVISION_CEILING = 3

REPAIR_ESCALATION_THRESHOLD_CENTS = 150_000

PARTS_MARKUP_MULTIPLIER = 1.125
MINUTES_PER_HOUR = 60

ZONE_ACCESSORIAL_CENTS = {
    ROUTE_ZONE_A: 0,
    ROUTE_ZONE_B: 4_500,
    ROUTE_ZONE_C: 9_800,
}

FREIGHT_DISCOUNT_HIGH_THRESHOLD_CENTS = 120_000
FREIGHT_DISCOUNT_HIGH_RATE = 0.06
FREIGHT_DISCOUNT_LOW_THRESHOLD_CENTS = 60_000
FREIGHT_DISCOUNT_LOW_RATE = 0.03

SECONDS_PER_DAY = 86_400
PROVISIONAL_LOOKAHEAD_DAYS = 2

# --------------------------------------------------------------------------
# Baseline rate card used by the reference processing center
# --------------------------------------------------------------------------
CENTER_NAME = "Newport VPC"
CENTER_PORT_CODE = "USNPT"
CENTER_YARD_CAPACITY_SLOTS = 50
CENTER_DAILY_STORAGE_RATE_CENTS = 1_450
CENTER_LABOR_RATE_CENTS_PER_HOUR = 9_000
CENTER_FUEL_SURCHARGE_PCT = 0.0925

# --------------------------------------------------------------------------
# VIN helpers.  A ``vin`` must be exactly 17 characters and unique across all
# units, so tests mint them from a shared 11-character prefix plus a
# 6-character serial.
# --------------------------------------------------------------------------
VIN_PREFIX = "1VWSA7A3XFC"
VIN_LENGTH = 17


def vin(serial: str) -> str:
    """Build a 17-character VIN from a six-character serial suffix."""
    value = f"{VIN_PREFIX}{serial}"
    assert len(value) == VIN_LENGTH, f"VIN {value!r} is {len(value)} characters"
    return value


#: A VIN one character short of the required length.
SHORT_VIN = "1VWSA7A3XFC00010"

# --------------------------------------------------------------------------
# Identifiers that resolve to nothing.  These are well-formed UUIDs that are
# never minted by the server.
# --------------------------------------------------------------------------
MISSING_UUIDS = tuple(
    f"00000000-0000-4000-8000-00000000000{n}" for n in range(1, 10)
)
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
MISSING_KIT_UUID = "00000000-0000-4000-8000-0000000000aa"
MISSING_BERTH_UUID = "00000000-0000-4000-8000-0000000000bb"
MISSING_VEHICLE_UUID = "00000000-0000-4000-8000-0000000000cc"
MISSING_DEALER_UUID = "00000000-0000-4000-8000-0000000000dd"
