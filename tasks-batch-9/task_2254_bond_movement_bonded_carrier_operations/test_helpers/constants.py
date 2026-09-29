"""Domain constants for the In-Bond Movement & Bonded Carrier API.

Values here are taken from the PRD: enumerations, the logical-clock default,
the fixed coefficients of the obligation formula, the transit-day allowances,
the sanction weights and decay buckets, and the mitigation credit table.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_BONDED_CARRIER = "BondedCarrier"
ROLE_CBP_OFFICER = "CBPOfficer"
ROLE_FPF_OFFICER = "FPFOfficer"
ROLE_SURETY_AGENT = "SuretyAgent"

ALL_ROLES = [
    ROLE_BONDED_CARRIER,
    ROLE_CBP_OFFICER,
    ROLE_FPF_OFFICER,
    ROLE_SURETY_AGENT,
]

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
#: The clock starts here on a fresh database.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

#: "Wherever this document speaks of 'a day' of elapsed time it means exactly
#: 86,400 seconds."
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
CUSTODIAL_STATUSES = ["ACTIVE", "SUSPENDED", "REVOKED"]

BOND_TYPES = ["SINGLE_TRANSACTION", "CONTINUOUS"]
BOND_STATUSES = ["ACTIVE", "SATURATED", "SUSPENDED", "EXPIRED"]

PORT_REGIONS = ["NE", "MW", "SE", "PSW", "NW"]

IN_BOND_TYPES = ["IT", "TE", "IE"]

TRANSIT_STATUSES = [
    "FILED",
    "IN_TRANSIT",
    "OVERDUE",
    "ARRIVED",
    "EXPORTED",
    "CLOSED",
    "CANCELLED",
]
CUSTODY_STATUSES = ["BONDED", "EXAM_HOLD", "GENERAL_ORDER", "RELEASED", "SEIZED"]

LEDGER_ENTRY_TYPES = [
    "OBLIGATE",
    "RELEASE",
    "INCREASE_LD",
    "RELEASE_LD",
    "MITIGATE",
]

SEAL_EVENT_TYPES = [
    "APPLIED",
    "VERIFIED_INTACT",
    "BROKEN_AUTHORIZED",
    "BROKEN_UNAUTHORIZED",
    "REPLACED",
]

HOLD_TYPES = ["EXAM_NII", "EXAM_PHYSICAL", "EXAM_INTENSIVE", "DOCUMENT", "PGA"]
#: Hold types that must carry both scheduled window fields.
SCHEDULED_HOLD_TYPES = ["EXAM_NII", "EXAM_PHYSICAL", "EXAM_INTENSIVE"]
#: Hold types that must omit both scheduled window fields.
UNSCHEDULED_HOLD_TYPES = ["DOCUMENT", "PGA"]
HOLD_STATUSES = ["OPEN", "RELEASED"]

AMENDMENT_TYPES = ["DIVERSION", "EXTENSION"]
AMENDMENT_STATUSES = ["SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED"]

REPORT_TYPES = ["ARRIVAL", "EXPORT"]
REPORT_STATUSES = ["ACCEPTED", "PENDING_PROOF", "REJECTED", "SUPERSEDED"]

CLAIM_TYPES = [
    "LATE_ARRIVAL",
    "NON_ARRIVAL",
    "SEAL_VIOLATION",
    "UNAUTHORIZED_DIVERSION",
    "NO_PROOF_OF_EXPORT",
]
CLAIM_STATUSES = ["ISSUED", "PETITIONED", "MITIGATED", "PAID", "CANCELLED"]

PETITION_STATUSES = [
    "SUBMITTED",
    "SUPPLEMENT_REQUESTED",
    "GRANTED",
    "PARTIALLY_GRANTED",
    "DENIED",
    "SUPERSEDED",
]

MITIGATION_FACTORS = [
    "FIRST_VIOLATION",
    "PROMPT_ARRIVAL_REPORT",
    "CARGO_SECURED_INTACT",
    "CBP_ADMIN_DELAY",
    "EXTRAORDINARY_CIRCUMSTANCE",
]

PETITION_DECISIONS = ["GRANT", "PARTIAL_GRANT", "DENY", "REQUEST_SUPPLEMENT"]
CLAIM_DISPOSITIONS = ["PAY", "CANCEL"]
AMENDMENT_DECISIONS = ["APPROVE", "DENY"]

# ---------------------------------------------------------------------------
# Obligation formula (PRD 3.2)
# ---------------------------------------------------------------------------
OBLIGATION_CARGO_RATE = 0.0325
OBLIGATION_WEIGHT_RATE = 0.0125
OBLIGATION_PACKAGE_RATE = 0.1275
OBLIGATION_FLOOR = 25.00

# ---------------------------------------------------------------------------
# Transit allowances (PRD 3.2)
# ---------------------------------------------------------------------------
BASE_TRANSIT_DAYS = {"IT": 30, "TE": 30, "IE": 15}
INTERPORT_SURCHARGE_DAYS = 5
TRANSIT_DAYS_CAP = 60
THROTTLE_MIN_DAYS = 5
#: Bond expiry must cover the deadline plus this margin.
BOND_COVERAGE_MARGIN_DAYS = 3

# ---------------------------------------------------------------------------
# Deadlines and windows
# ---------------------------------------------------------------------------
GENERAL_ORDER_DAYS = 15
GO_GRACE_DAYS = 5
EXTENSION_GRACE_DAYS = 2
EXTENSION_CUMULATIVE_CAP_DAYS = 30
OVERDUE_REVIVAL_MAX_DAYS = 2

# ---------------------------------------------------------------------------
# Liquidated damages (PRD 3.7)
# ---------------------------------------------------------------------------
CLAIM_SEVERITY = {
    "LATE_ARRIVAL": 1.0,
    "NO_PROOF_OF_EXPORT": 2.0,
    "SEAL_VIOLATION": 3.0,
    "UNAUTHORIZED_DIVERSION": 3.0,
    "NON_ARRIVAL": 4.0,
}
CLAIM_RATE_PER_DAY = 250.00
CLAIM_MINIMUM = 1000.00

# ---------------------------------------------------------------------------
# Sanction points (PRD 3.7)
# ---------------------------------------------------------------------------
SANCTION_WEIGHT = {
    "LATE_ARRIVAL": 2.0,
    "NO_PROOF_OF_EXPORT": 3.0,
    "SEAL_VIOLATION": 4.0,
    "UNAUTHORIZED_DIVERSION": 4.0,
    "NON_ARRIVAL": 6.0,
}
#: (inclusive upper bound in days since issuance, multiplier)
SANCTION_DECAY_BUCKETS = [(90, 1.0), (180, 0.75), (365, 0.5)]
SANCTION_POINTS_CAP = 12.0
THROTTLE_THRESHOLD = 6.0
SUSPENSION_THRESHOLD = 10.0

# ---------------------------------------------------------------------------
# Mitigation waterfall (PRD 3.7)
# ---------------------------------------------------------------------------
MITIGATION_CREDIT = {
    "FIRST_VIOLATION": 0.20,
    "PROMPT_ARRIVAL_REPORT": 0.15,
    "CARGO_SECURED_INTACT": 0.10,
    "CBP_ADMIN_DELAY": 0.25,
    "EXTRAORDINARY_CIRCUMSTANCE": 0.30,
}
PRIOR_VIOLATION_DEBIT = 0.05
MITIGATION_CAP_ROUND_1 = 0.50
MITIGATION_CAP_ROUND_2 = 0.75
PRIOR_VIOLATION_LOOKBACK_DAYS = 365

PROCESSING_FEE_LOW = 100.00
PROCESSING_FEE_MID = 250.00
PROCESSING_FEE_MID_THRESHOLD = 2000.00
PROCESSING_FEE_HIGH_THRESHOLD = 10000.00
PROCESSING_FEE_HIGH_RATE = 0.025

MAX_PETITION_ROUND = 2

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
