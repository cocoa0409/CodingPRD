"""In-memory store and the server-held logical clock.

The store is EMPTY on every boot. Nothing is seeded, preloaded or hardcoded:
every row is created by a client through a declared endpoint.
"""
from decimal import Decimal

from flask import g

from util import fmt_dt, new_id, parse_dt

# ---------------------------------------------------------------------------
# Domain constants (PRD section 2.5 / 2.8 / 3.x)
# ---------------------------------------------------------------------------
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"
GLOBAL_MIN_ATTESTATION_AGE_YEARS = 18
CUSTOMER_BLOCK_STRIKE_THRESHOLD = 3
CUSTOMER_BLOCK_DAYS = 30
CAPTURE_RETENTION_DAYS = 2555
COURIER_ATTEMPT_DWELL_MINUTES = 20
CERT_MIN_TRAINING_SCORE = 80
CERT_REMEDIAL_TRAINING_SCORE = 90
TRAINING_FRESHNESS_DAYS = 90
MAX_REVISION_ROUNDS = 3
CERT_SUSPENSION_SCORE_THRESHOLD = Decimal("70.00")
COURIER_SUSPENSION_SCORE_THRESHOLD = Decimal("40.00")
POSTURE_RESTRICT_SCORE = Decimal("25.00")
POSTURE_SUSPEND_SCORE = Decimal("60.00")
POSTURE_RESTRICT_OPEN_CASES = 3
POSTURE_SUSPEND_CRITICAL_CASES = 2
CAP_VERIFIED_CREDIT = Decimal("0.50")

REFUSAL_SEVERITY_MAP = {
    "UNDERAGE_RECIPIENT": "CRITICAL",
    "ID_MISMATCH": "MAJOR",
    "NO_ACCEPTABLE_ID": "MINOR",
    "INTOXICATED_RECIPIENT": "MAJOR",
}
COMPLIANCE_REFUSAL_REASONS = (
    "UNDERAGE_RECIPIENT",
    "ID_MISMATCH",
    "NO_ACCEPTABLE_ID",
    "INTOXICATED_RECIPIENT",
)
SEVERITY_POINTS = {"MINOR": 5, "MAJOR": 15, "CRITICAL": 40}
TIER_MULTIPLIER = {
    "STANDARD": Decimal("1.00"),
    "PREFERRED": Decimal("0.80"),
    "PROBATIONARY": Decimal("1.50"),
}
COURIER_CASE_PENALTY = {
    "MINOR": Decimal("8.00"),
    "MAJOR": Decimal("18.00"),
    "CRITICAL": Decimal("35.00"),
}
SHOPPER_FAIL_PENALTY = Decimal("25.00")
HANDOVER_BONUS_PER = Decimal("1.00")
HANDOVER_BONUS_CAP = Decimal("10.00")

IDENTITY_SIGNAL_ORDER = (
    "GOVERNMENT_ID_DB",
    "CREDIT_BUREAU",
    "MOBILE_CARRIER",
    "WATCHLIST_NEGATIVE",
)
IDENTITY_SIGNAL_WEIGHTS = {
    "GOVERNMENT_ID_DB": Decimal("0.50"),
    "CREDIT_BUREAU": Decimal("0.25"),
    "MOBILE_CARRIER": Decimal("0.15"),
    "WATCHLIST_NEGATIVE": Decimal("0.10"),
}
IDENTITY_DOB_MISMATCH_PENALTY = Decimal("0.20")
IDENTITY_MATCH_BAND = Decimal("0.8500")
IDENTITY_PARTIAL_BAND = Decimal("0.6000")

RESTRICTION_CLASSES = (
    "ALCOHOL",
    "TOBACCO_VAPE",
    "CANNABIS",
    "PHARMACY_OTC_RESTRICTED",
    "AEROSOL_SOLVENT",
)
PRODUCT_RESTRICTION_TYPES = RESTRICTION_CLASSES + ("NONE",)
DOCUMENT_TYPES = (
    "DRIVERS_LICENSE",
    "PASSPORT",
    "STATE_ID",
    "MILITARY_ID",
    "TRIBAL_ID",
)
OPEN_CASE_STATES = ("OPEN", "UNDER_INVESTIGATION", "PENDING_PARTNER_RESPONSE")
DECIDED_CASE_STATES = ("SUBSTANTIATED", "CLOSED_VERIFIED")
OPEN_ATTEMPT_STATES = ("INITIATED", "ID_VERIFIED", "ID_REJECTED")
DISPATCHABLE_COMPLIANCE_STATES = ("AUTO_CLEARED", "PREVERIFIED", "COMPLIANCE_CLEARED")

COLLECTIONS = (
    "jurisdictions",
    "policies",
    "products",
    "customers",
    "identity_checks",
    "orders",
    "order_lines",
    "partners",
    "couriers",
    "certifications",
    "attempts",
    "captures",
    "shopper_tests",
    "cases",
    "plans",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_dt(DEFAULT_LOGICAL_CLOCK_UTC)
        self.clock_raw = DEFAULT_LOGICAL_CLOCK_UTC
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical-clock instant. Never the host wall clock (PRD 2.5)."""
    return db.clock


def now_str():
    return fmt_dt(db.clock)


def sort_key(row):
    """Deterministic `created_at` ASC ordering with an insertion-order tiebreak."""
    return (row["created_at"], row["_seq"])


def decided_sort_key(row):
    """`decided_at` ASC then `created_at` ASC (PRD 3.4 / 3.5 pinned orderings)."""
    return (row.get("decided_at") or "", row["created_at"], row["_seq"])


def recorded_sort_key(row):
    """`recorded_at` ASC then `created_at` ASC."""
    return (row.get("recorded_at") or "", row["created_at"], row["_seq"])


def delivered_sort_key(row):
    """`delivered_at` ASC then `created_at` ASC."""
    return (row.get("delivered_at") or "", row["created_at"], row["_seq"])


def new_row(with_common=True, **fields):
    row = {"id": new_id(), "created_at": now_str(), "_seq": db.next_seq()}
    if with_common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump `version` and refresh `updated_at`.

    PRD 2.4: a derived field recomputed as a side effect counts as a mutation of
    the row that owns it. A row mutated several times inside one request advances
    its version exactly once -- the endpoint contracts speak of "+1 per request".
    """
    if row is None or "version" not in row:
        return
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    key = row["id"]
    if key in seen:
        return
    seen.add(key)
    row["version"] += 1
    row["updated_at"] = now_str()
