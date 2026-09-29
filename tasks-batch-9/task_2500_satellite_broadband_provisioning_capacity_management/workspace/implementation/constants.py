"""Every named constant the PRD fixes."""

from decimal import Decimal


ROLES = (
    "ProvisioningAgent",
    "NetworkOpsEngineer",
    "ComplianceOfficer",
    "LogisticsCoordinator",
    "Subscriber",
)

API_PREFIX = "/satellite-broadband"

# --- cell slots / waitlist -------------------------------------------------
WAITLIST_CAP_PER_CELL = 3
RESERVATION_HOLD_HOURS = 72

# --- beam megabits --------------------------------------------------------
TIER_WEIGHT = {
    "PRIORITY_1": Decimal("1.0"),
    "PRIORITY_2": Decimal("0.7"),
    "BEST_EFFORT": Decimal("0.4"),
}
DEPRIORITIZED_WEIGHT = Decimal("0.25")
CONSTRAINED_FRACTION = Decimal("0.75")
DEFAULT_OVERSUBSCRIPTION_LIMIT = Decimal("4.0")

# --- waitlist ranking -----------------------------------------------------
PLAN_TIER_RANK = {"PRIORITY_1": 3, "PRIORITY_2": 2, "BEST_EFFORT": 1}
WAIT_DAY_CAP = 365

# --- disclosure -----------------------------------------------------------
DISCLOSURE_ACK_WINDOW_DAYS = 14

# --- roaming --------------------------------------------------------------
ROAMING_MAX_INFO_ROUNDS = 3
ROAMING_COOLDOWN_HOURS = 24

# --- hardware -------------------------------------------------------------
TERMINAL_DAMAGE_FEE_CENTS = 15000

# --- outage credits -------------------------------------------------------
MINUTES_PER_BILLING_MONTH = Decimal(43200)
SLA_MIN_OUTAGE_MINUTES = 30
CAUSE_MULTIPLIER = {
    "WEATHER_RAIN_FADE": Decimal("0.5"),
    "EQUIPMENT_FAILURE": Decimal("1.0"),
    "SPECTRUM_INTERFERENCE": Decimal("1.0"),
    "PLANNED_MAINTENANCE": Decimal("0.0"),
}
SEVERITY_FACTOR = {"FULL_OUTAGE": Decimal("1.0"), "DEGRADATION": Decimal("0.5")}
CREDIT_CAP_FRACTION = Decimal("0.5")

# --- cycle charges --------------------------------------------------------
DISCOUNT_BAND_1_CENTS = 10000
DISCOUNT_BAND_2_CENTS = 25000
DISCOUNT_BAND_1_PCT = Decimal("0.05")
DISCOUNT_BAND_2_PCT = Decimal("0.10")

# --- enumerations ---------------------------------------------------------
FREQUENCY_BANDS = ("KA_FORWARD", "KU_FORWARD", "KA_RETURN")
LICENSE_STATES = ("PENDING_COORDINATION", "ACTIVE", "SUSPENDED", "REFUSED", "EXPIRED")
COORDINATION_STATES = ("UNCOORDINATED", "COORDINATED", "REFUSED")
COORDINATION_OUTCOMES = ("GRANTED", "GRANTED_PROVISIONAL", "REFUSED")
ENFORCEMENT_ACTIONS = ("SUSPEND", "REINSTATE")
BEAM_STATES = ("ACTIVE", "SUSPENDED")
CAPACITY_STATES = ("NORMAL", "CONSTRAINED", "SATURATED")
AVAILABILITY_STATES = ("AVAILABLE", "WAITLIST_ONLY", "CLOSED")
PRIORITY_TIERS = ("PRIORITY_1", "PRIORITY_2", "BEST_EFFORT")
ACCOUNT_STATES = ("PROSPECT", "WAITLISTED", "ACTIVE", "SUSPENDED", "CLOSED")
ORDER_STATES = (
    "PENDING_DETERMINATION",
    "RESERVED",
    "WAITLISTED",
    "ACTIVATED",
    "EXPIRED",
    "CANCELLED",
)
TERMINAL_STATES = (
    "SHIPPED",
    "DELIVERED",
    "INSTALLED",
    "TRANSFER_PENDING",
    "RMA_PENDING",
    "RETURN_INITIATED",
    "RETURNED",
    "REPLACED",
)
SCAN_VERDICTS = ("PASS", "MARGINAL", "FAIL")
RETURN_EVENTS = ("INITIATE", "RECEIVE")
RETURN_CONDITIONS = ("GOOD", "DAMAGED")
SERVICE_STATES = ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "TERMINATED")
AUTHORIZATION_STATES = (
    "UNAUTHORIZED",
    "AUTHORIZED_FIXED",
    "AUTHORIZED_IN_MOTION",
    "DEAUTHORIZED",
)
PRIORITY_STATES = ("PRIORITY", "DEPRIORITIZED")
DISCLOSURE_ACK_STATES = ("PENDING_ACK", "ACKNOWLEDGED", "EXPIRED")
AUTHORIZATION_MODES = ("FIXED", "IN_MOTION")
ROAMING_MODES = ("PORTABILITY_MOVE", "ROAM_TEMPORARY", "IN_MOTION")
ROAMING_STATES = ("REQUESTED", "NEEDS_INFO", "APPROVED", "DENIED", "REVOKED")
OUTAGE_CAUSES = (
    "WEATHER_RAIN_FADE",
    "EQUIPMENT_FAILURE",
    "SPECTRUM_INTERFERENCE",
    "PLANNED_MAINTENANCE",
)
OUTAGE_SEVERITIES = ("FULL_OUTAGE", "DEGRADATION")
EVENT_STATES = ("OPEN", "RESOLVED")
CREDIT_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
CREDIT_DECISIONS = ("APPROVE", "REJECT")
ROAMING_DECISIONS = ("APPROVE", "DENY")

# slot-occupying / sold-set memberships (PRD 2.8)
SLOT_OCCUPYING_STATES = ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED")
SOLD_SET_STATES = ("PENDING_ACTIVATION", "ACTIVE")
AUTHORIZED_STATES = ("AUTHORIZED_FIXED", "AUTHORIZED_IN_MOTION")
