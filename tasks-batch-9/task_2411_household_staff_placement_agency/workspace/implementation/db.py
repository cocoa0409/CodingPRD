"""In-memory data store and logical clock.

Every collection is a plain dict keyed by the row's UUID `id`.  Nothing is ever
written to disk, and the store starts completely empty on every boot: the
implementation encodes the system, never the data.
"""

import itertools
import uuid

from flask import g

from timeutil import format_instant, parse_timestamp

# ---------------------------------------------------------------------------
# Global constants (PRD 2.12)
# ---------------------------------------------------------------------------
MILESTONE_WEIGHTS_BPS = {"ENGAGEMENT": 3000, "TRIAL_CLEARED": 3000, "START_DATE": 4000}
MILESTONE_SEQUENCE = ["ENGAGEMENT", "TRIAL_CLEARED", "START_DATE"]
NET_TERMS_DAYS = 14
PRESENTATION_MIN_SCORE = 70
PLACEMENT_MIN_SCORE = 80
MIN_VERIFIED_REFERENCES = 2
MIN_CHAIN_MONTHS_SENIOR = 24
MIN_CHAIN_MONTHS_STANDARD = 12
MIN_CHAIN_MONTHS_VETTING_GATE = 12
TRIAL_BUFFER_MINUTES = 120
CANDIDATE_WEEKLY_TRIAL_CAP = 2
MAX_SCOPING_ROUNDS = 3
MAX_NEGOTIATION_ROUNDS = 4
CREDIT_HOLD_LIMIT_CENTS = 5000000
COOLING_OFF_DAYS = 30
NON_SOLICITATION_TERM_DAYS = 730
PENALTY_FLOOR_CENTS = 750000
PENALTY_CAP_CENTS = 7500000
ADMIN_RETENTION_TIER_BPS = [(1000000, 500), (3000000, 750), (None, 1000)]
POACHING_RATE_TIERS_BPS = [(2000000, 10000), (5000000, 7500), (None, 5000)]
RELATIONSHIP_WEIGHTS = {"PRINCIPAL_EMPLOYER": 12, "AGENCY_SUPERVISOR": 8, "PEER": 4}
EXPERIENCE_POINTS_PER_YEAR = 3
EXPERIENCE_POINTS_CAP = 36
REFERENCE_POINTS_CAP = 24
COVERAGE_POINTS_CAP = 20
BACKGROUND_POINTS_CLEARED = 20
BACKGROUND_POINTS_ADJUDICATED_PASS = 10
DISPUTED_REFERENCE_PENALTY = 15
SENIOR_ROLE_TYPES = {"ESTATE_MANAGER", "CHEF"}
STANDARD_ROLE_TYPES = {"HOUSEKEEPER", "CHAUFFEUR"}

DEFAULT_CLOCK_LITERAL = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Enumerations (PRD section 3 entity descriptions)
# ---------------------------------------------------------------------------
ROLE_TYPES = ["ESTATE_MANAGER", "HOUSEKEEPER", "CHEF", "CHAUFFEUR"]
REGION_CODES = ["NY", "CA", "FL", "TX", "MA"]
CLIENT_STATUSES = ["PROSPECT", "ONBOARDED", "SUSPENDED"]
NDA_STATUSES = ["UNSIGNED", "SIGNED", "COUNTERSIGNED"]
FEE_SCHEDULE_STATUSES = ["ACTIVE", "RETIRED"]
SCHEDULE_PATTERNS = ["FIVE_TWO", "SIX_ONE", "ROTA_TWO_TWO", "ON_CALL"]
REQUISITION_STATUSES = ["DRAFT", "SCOPING", "SOURCING", "TRIALING", "OFFER_PENDING", "PLACED", "WITHDRAWN"]
VETTING_STATUSES = ["UNVETTED", "SCREENING", "REFERENCES_VERIFIED", "BACKGROUND_PENDING", "CLEARED", "REJECTED"]
AVAILABILITY_STATUSES = ["AVAILABLE", "ON_TRIAL", "OFFER_HELD", "PLACED", "COOLING_OFF", "INACTIVE"]
RELATIONSHIP_TYPES = ["PRINCIPAL_EMPLOYER", "AGENCY_SUPERVISOR", "PEER"]
REFERENCE_STATUSES = ["PENDING", "VERIFIED", "UNREACHABLE", "DISPUTED"]
BACKGROUND_SCOPE_ITEMS = ["IDENTITY", "CRIMINAL", "DMV", "CREDENTIAL", "SOCIAL_MEDIA"]
BACKGROUND_STATUSES = ["INITIATED", "CLEARED", "FLAGGED", "INCONCLUSIVE", "ADJUDICATED_PASS", "ADJUDICATED_FAIL"]
ENGAGEMENT_TYPES = ["TRIAL_DAY", "WORKING_INTERVIEW"]
TRIAL_STATUSES = ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED"]
CANCEL_REASONS = ["CLIENT_REQUEST", "CANDIDATE_WITHDRAWN", "VETTING_FAILED", "CLIENT_SUSPENDED"]
ACCOMMODATION_STATUSES = ["PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
RESPONDER_ROLES = ["AGENCY", "CLIENT", "CANDIDATE"]
PLACEMENT_STATUSES = [
    "PENDING_ACCEPTANCE", "ACTIVE", "GUARANTEE_EXPIRED", "TERMINATED_REPLACED",
    "TERMINATED_REFUNDED", "TERMINATED_NO_REMEDY", "VOIDED",
]
BILLING_STATUSES = ["UNBILLED", "PARTIALLY_BILLED", "FULLY_BILLED", "REVERSED", "REFUNDED"]
FEE_VARIANTS = ["PROVISIONAL", "FINAL"]
VOID_REASONS = ["SUPERSEDED_BY_NEW_OFFER", "CLIENT_WITHDRAWN"]
MILESTONE_TYPES = ["ENGAGEMENT", "TRIAL_CLEARED", "START_DATE"]
INVOICE_STATUSES = ["PENDING", "INVOICED", "OVERDUE", "PAID", "REVERSED", "VOIDED"]
LEDGER_ENTRY_TYPES = [
    "FEE_INVOICED", "FEE_PAYMENT", "FEE_REVERSAL", "REFUND_ISSUED",
    "PENALTY_ASSESSED", "PENALTY_SETTLED", "MANUAL_ADJUSTMENT",
]
LEDGER_REF_TYPES = ["NONE", "PLACEMENT", "FEE_MILESTONE", "REPLACEMENT_CLAIM", "NON_SOLICITATION_CASE"]
REMEDIES = ["REPLACEMENT", "REFUND"]
CLAIM_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED_REPLACEMENT",
    "APPROVED_REFUND", "DENIED", "SUPERSEDED",
]
CLAIM_ACTIONS = ["OPEN_REVIEW", "REQUEST_INFO", "APPROVE_REPLACEMENT", "APPROVE_REFUND", "DENY"]
EIN_STATUSES = ["NOT_APPLIED", "APPLIED", "ISSUED"]
HANDOFF_STATUSES = ["PREPARED", "ATTESTED"]
CASE_STATUSES = ["ALLEGED", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED", "SETTLED"]
CASE_DISPOSITIONS = ["SUBSTANTIATE", "UNSUBSTANTIATE"]

# ---------------------------------------------------------------------------
# Terminal states (PRD 2.9)
# ---------------------------------------------------------------------------
TERMINAL_REQUISITION = {"PLACED", "WITHDRAWN"}
TERMINAL_FEE_SCHEDULE = {"RETIRED"}
TERMINAL_REFERENCE = {"VERIFIED", "UNREACHABLE", "DISPUTED"}
TERMINAL_BACKGROUND = {"ADJUDICATED_PASS", "ADJUDICATED_FAIL"}
TERMINAL_TRIAL = {"PASSED", "FAILED", "CANCELLED"}
TERMINAL_ACCOMMODATION = {"ACCEPTED", "REJECTED", "SUPERSEDED"}
TERMINAL_PLACEMENT = {"VOIDED", "TERMINATED_REPLACED", "TERMINATED_REFUNDED", "GUARANTEE_EXPIRED"}
TERMINAL_BILLING = {"REFUNDED"}
TERMINAL_MILESTONE = {"PAID", "REVERSED", "VOIDED"}
TERMINAL_CLAIM = {"APPROVED_REPLACEMENT", "APPROVED_REFUND", "DENIED", "SUPERSEDED"}
TERMINAL_HANDOFF = {"ATTESTED"}
TERMINAL_CASE = {"UNSUBSTANTIATED", "SETTLED"}

ACTIVE_TRIAL_STATUSES = {"SCHEDULED", "IN_PROGRESS"}
WEEKLY_CAP_STATUSES = {"SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED"}
OPEN_CLAIM_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"}
COUNTED_PLACEMENT_STATUSES = {
    "ACTIVE", "GUARANTEE_EXPIRED", "TERMINATED_REPLACED",
    "TERMINATED_REFUNDED", "TERMINATED_NO_REMEDY",
}
FROZEN_INVOICE_STATUSES = {"INVOICED", "OVERDUE", "PAID", "REVERSED"}


class Store:
    """Every collection lives here; nothing is persisted anywhere else."""

    def __init__(self):
        self.clients = {}
        self.fee_schedules = {}
        self.requisitions = {}
        self.candidates = {}
        self.reference_checks = {}
        self.background_verifications = {}
        self.trial_engagements = {}
        self.accommodation_terms = {}
        self.placements = {}
        self.fee_milestones = {}
        self.replacement_claims = {}
        self.payroll_handoffs = {}
        self.non_solicitation_cases = {}
        self.ledger_entries = {}
        self._counter = itertools.count(1)
        # Logical clock: the literal text the caller supplied plus its parsed form.
        self.clock_literal = DEFAULT_CLOCK_LITERAL
        self.clock = parse_timestamp(DEFAULT_CLOCK_LITERAL)

    # -- identity ---------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._counter)

    # -- logical clock ----------------------------------------------------
    def now(self):
        return self.clock

    def now_str(self):
        return format_instant(self.clock)

    def today(self):
        return self.clock.date()


store = Store()


def reset():
    """Used only by the module itself; a fresh process always starts empty."""
    global store
    store = Store()


# ---------------------------------------------------------------------------
# Housekeeping helpers (PRD 2.4)
# ---------------------------------------------------------------------------
def _touched_set():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def stamp_new(row):
    """Populate id / created_at / updated_at / version for a freshly created row."""
    now = store.now_str()
    row["id"] = store.new_id()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = store.next_seq()
    # A row created during this request is never additionally version-bumped.
    _touched_set().add(id(row))
    return row


def stamp_ledger(row):
    """LedgerEntry carries only id and created_at (PRD 2.4)."""
    row["id"] = store.new_id()
    row["created_at"] = store.now_str()
    row["_seq"] = store.next_seq()
    _touched_set().add(id(row))
    return row


def touch(row):
    """Increment version by exactly one and refresh updated_at.

    A row mutated several times inside one request (for instance a household
    whose balance and status both move) is a single mutation of that row and so
    advances its version by exactly one.
    """
    if row is None:
        return
    marker = id(row)
    touched = _touched_set()
    if marker in touched:
        return
    touched.add(marker)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = store.now_str()


def serialize(row):
    """Strip internal bookkeeping keys before the row leaves the process."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    """Default ordering is created_at ascending (PRD 2.3); insertion order breaks
    ties because the logical clock is frequently identical across rows."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_by_sequence(rows):
    return sorted(rows, key=lambda r: r["sequence_no"])
