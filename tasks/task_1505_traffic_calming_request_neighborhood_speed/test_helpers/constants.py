"""Domain thresholds — numeric constants stated in the PRD (§2.4, §2.6, §3)."""
from decimal import Decimal

# --- Logical clock (PRD §2.4) ---
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# --- Petition (PRD §3.2) ---
PETITION_RATIO = Decimal("0.60")
PETITION_WINDOW_DAYS = 90

# --- Speed study (PRD §3.3) ---
MIN_OBSERVATION_DAYS = 3
STUDY_GAP_DAYS = 7
SCORE_ELIGIBILITY_THRESHOLD = 60
SCORE_CAP = 100

# --- Funding waterfall (PRD §2.6, §3.4) ---
CONTINGENCY_RATE = Decimal("0.075")

# --- Ballot (PRD §3.6) ---
QUORUM_RATIO = Decimal("0.25")
APPROVAL_RATIO_PERCENT = 60

# --- Installation / effectiveness / removal (PRD §3.7, §3.8) ---
POST_STUDY_MIN_DAYS = 30
REMOVAL_MIN_AGE_DAYS = 365
P85_REDUCTION_TARGET = 3.0
MEAN_REDUCTION_TARGET = 2.0


def round_half_up_int(value: Decimal) -> int:
    """Round a non-negative Decimal half-up to a whole integer (PRD §2.6)."""
    return int((value + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))


def contingency_cents(base_cents: int) -> int:
    """Per-request / per-plan contingency, rounded half-up to a whole cent
    before any summation (PRD §2.6)."""
    return round_half_up_int(Decimal(base_cents) * CONTINGENCY_RATE)


def allocated_cents_for(base_cents: int) -> int:
    """Provisional or final allocation: base + half-up contingency (PRD §3.4/§3.5)."""
    return base_cents + contingency_cents(base_cents)
