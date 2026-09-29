"""In-memory data store.

Everything lives in plain dicts keyed by id. The store is EMPTY on every boot —
no entity is ever seeded, preloaded or hardcoded; tests build all state through
the declared API surface.
"""

from util import DEFAULT_CLOCK, new_id


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.customers = {}
        self.contacts = {}
        self.contracts = {}
        self.rows = {}
        self.cabinets = {}
        self.circuits = {}
        self.ports = {}
        self.cc_orders = {}
        self.tickets = {}
        self.visits = {}
        self.decoms = {}
        self.invoice_lines = {}


store = Store()


def now():
    """The logical clock — PRD §2.4."""
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def base_row(common_fields=True):
    """id + created_at, plus updated_at/version for every entity except
    InvoiceLine (PRD §2.4: an invoice line carries only id and created_at)."""
    ts = now()
    row = {"id": new_id(), "created_at": ts}
    if common_fields:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(entity):
    """A mutation — including a recomputation of a derived field — refreshes
    updated_at and increments version (PRD §2.4, §2.8)."""
    if "version" in entity:
        entity["updated_at"] = now()
        entity["version"] = entity["version"] + 1
    return entity


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ROLES = (
    "CustomerAdmin",
    "ProvisioningEngineer",
    "FacilityManager",
    "SecurityOfficer",
    "BillingOperator",
)

CUSTOMER_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
CONTRACT_STATUSES = (
    "DRAFT",
    "PENDING_ACTIVATION",
    "ACTIVE",
    "SUSPENDED",
    "WIND_DOWN",
    "TERMINATED",
)
BILLING_MODES = ("METERED_PLUS_COMMIT", "COMMITTED_ONLY")
REDUNDANCY_REQUIREMENTS = ("N", "N_PLUS_1", "TWO_N")
ROW_STATUSES = ("OPEN", "DENSITY_CAPPED", "COOLING_CONSTRAINED", "DECOMMISSIONING")
CABINET_STATUSES = (
    "AVAILABLE",
    "RESERVED",
    "CAPACITY_HELD",
    "INSTALLED",
    "ACTIVE",
    "DECOMMISSIONING",
    "RELEASED",
)
FOOTPRINT_TYPES = ("CABINET", "CAGE_SLOT", "MEET_ME")
CIRCUIT_STATUSES = ("DESIGNED", "APPROVED", "BLOCKED", "ENERGIZED", "DE_ENERGIZED", "REMOVED")
FEED_SIDES = ("A", "B")
REDUNDANCY_ROLES = ("PRIMARY", "REDUNDANT")
PHASES = ("SINGLE", "THREE")
MEDIA_TYPES = ("SMF", "MMF", "CAT6A", "COAX")
PORT_STATUSES = ("FREE", "RESERVED", "ASSIGNED", "QUARANTINED")
CC_STATUSES = (
    "SUBMITTED",
    "ROUTE_PROPOSED",
    "CHANGES_REQUESTED",
    "APPROVED",
    "INSTALLED",
    "ACTIVE",
    "DECOMMISSIONED",
    "ABORTED",
)
ACCESS_LEVELS = ("ESCORTED_ONLY", "UNESCORTED")
AUTH_SCOPES = ("REMOTE_HANDS", "SITE_ACCESS")
BIOMETRIC_STATES = ("NOT_ENROLLED", "ENROLLED", "REVOKED")
VISIT_PURPOSES = ("MAINTENANCE", "CARRIER_INSTALL", "AUDIT", "REMOTE_HANDS_ESCORT")
VISIT_STATUSES = ("SCHEDULED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED")
SEVERITIES = ("CRITICAL", "HIGH", "STANDARD")
AUTHORIZATION_STATES = ("PENDING_AUTHORIZATION", "AUTHORIZED", "DENIED", "REVOKED")
EXECUTION_STATES = ("QUEUED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
DECOM_STATUSES = (
    "REQUESTED",
    "APPROVED",
    "IN_PROGRESS",
    "READY_FOR_RELEASE",
    "CLOSED",
    "CANCELLED",
)
DECOM_STEPS = ("EQUIPMENT_REMOVAL", "CABLE_RECLAMATION")
LINE_TYPES = (
    "POWER_COMMIT",
    "POWER_OVERAGE",
    "CROSS_CONNECT_MRC",
    "CROSS_CONNECT_SURCHARGE",
    "CROSS_CONNECT_CREDIT",
    "REMOTE_HANDS",
    "SLA_CREDIT",
    "REVERSAL",
)

# Cabinet statuses that occupy a slot in their row (PRD §3.2).
OCCUPYING_CABINET_STATUSES = ("RESERVED", "CAPACITY_HELD", "INSTALLED", "ACTIVE", "DECOMMISSIONING")
# Cabinet statuses that count against committed_cabinet_count (PRD §2.5 rule 39).
COMMIT_CABINET_STATUSES = ("RESERVED", "CAPACITY_HELD", "INSTALLED", "ACTIVE")
# Cabinet statuses accepted as "operational" (PRD §2.5 rule 20).
OPERATIONAL_CABINET_STATUSES = ("INSTALLED", "ACTIVE")

# ---------------------------------------------------------------------------
# Business constants (scaffold §1.3)
# ---------------------------------------------------------------------------

NEC_DERATE_FACTOR = "0.80"
PHASE_FACTOR_SINGLE = "1.0"
PHASE_FACTOR_THREE = "1.732"
REDUNDANT_COOLING_FACTOR = "0.25"

COOLING_ALERT_RATIO = "0.90"
MEASURED_WINDOW_DAYS = 30

POWER_COMMIT_RATE_USD_PER_KW_MONTH = "175.00"
COMMIT_HOURS_PER_MONTH = "730"
DEEMED_LOAD_FACTOR = "0.65"
OVERAGE_TIER_1_LIMIT_KWH = "500"
OVERAGE_TIER_2_LIMIT_KWH = "2000"
OVERAGE_TIER_1_RATE = "0.180"
OVERAGE_TIER_2_RATE = "0.155"
OVERAGE_TIER_3_RATE = "0.135"

BILLING_INCREMENT_MINUTES = 15
REMOTE_HANDS_RATE_USD_PER_INCREMENT = "62.50"
AFTER_HOURS_MULTIPLIER = "1.35"
AFTER_HOURS_START_EXCLUSIVE_HOUR = 8
AFTER_HOURS_EVENING_HOUR = 20
SLA_BREACH_CREDIT_PCT = "0.25"

CC_MEDIA_MRC_USD = {
    "SMF": "300.00",
    "MMF": "250.00",
    "CAT6A": "175.00",
    "COAX": "225.00",
}
CC_VOLUME_TIER_1_MIN_USD = "500.00"
CC_VOLUME_TIER_2_MIN_USD = "800.00"
CC_VOLUME_DISCOUNT_TIER_1_PCT = "0.05"
CC_VOLUME_DISCOUNT_TIER_2_PCT = "0.10"
INFRA_SURCHARGE_PCT = "0.20"
CC_DECOMMISSION_CREDIT_PCT = "0.50"

BREAKER_HEADROOM_RATIO = "1.25"
DENSITY_TOLERANCE_RATIO = "1.10"
POWER_OVERPROVISION_CAP_RATIO = "1.10"
PORT_QUARANTINE_HOURS = 24
MAX_ROUTE_REVISIONS = 2

RESPONSE_TARGET_MINUTES = {"CRITICAL": 30, "HIGH": 120, "STANDARD": 480}
