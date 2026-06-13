"""In-memory data store. Starts empty on every boot. No seeding."""
import itertools
import uuid
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """ISO 8601 UTC with millisecond precision, e.g. 2025-05-24T10:30:00.123Z (PRD §2.5)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id() -> str:
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


class Store:
    """Pure in-memory dict store keyed by id. Re-created fresh on every process boot."""

    def __init__(self):
        self.insurers = {}            # id -> Insurer dict
        self.occupation_classes = {}  # id -> OccupationClass dict
        self.policyholders = {}       # id -> Policyholder dict
        self.policies = {}            # id -> Policy dict
        self.claims = {}              # id -> Claim dict
        self.income_reports = {}      # id -> IncomeReport dict
        self.disability_proofs = {}   # id -> DisabilityProof dict
        self.benefit_periods = {}     # id -> BenefitPeriod dict
        self.offset_awards = {}       # id -> OffsetAward dict
        self.claim_ledgers = {}       # id -> ClaimLedger dict (one per claim)
        # Monotonic creation counter to provide a strict, stable creation order
        # for tie-breaks (created_at can collide at millisecond resolution).
        self._seq = itertools.count(1)

    def next_seq(self) -> int:
        return next(self._seq)


# Module-level singleton (per process). Re-created on every process boot.
store = Store()
