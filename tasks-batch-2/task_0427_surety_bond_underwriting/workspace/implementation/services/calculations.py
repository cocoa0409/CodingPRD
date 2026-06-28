"""Monetary and rating calculations (scaffold §1.3, PRD §2.6-§2.9, §3).

Every quantity is integer cents. All divisions round half up exactly once at the
stored-value step, with rounding order pinned per the PRD where it matters.
"""

from decimal import Decimal

from helpers import round_half_up
from clock import clock, parse_iso8601, months_between

# --- premium_rating constants (PRD §3.3 / scaffold §1.3) ---
RATE_TABLE = {
    "PREFERRED":   {"BID": 100, "PERFORMANCE": 150, "PAYMENT": 150, "LICENSE_PERMIT": 80,  "FIDELITY": 120},
    "STANDARD":    {"BID": 150, "PERFORMANCE": 225, "PAYMENT": 225, "LICENSE_PERMIT": 120, "FIDELITY": 180},
    "SUBSTANDARD": {"BID": 250, "PERFORMANCE": 375, "PAYMENT": 375, "LICENSE_PERMIT": 200, "FIDELITY": 300},
}
LARGE_RISK_SURCHARGE_BPS = 50
MAX_RATE_BPS = 400

# --- credit_tier_derivation constants ---
PREFERRED_MIN_SCORE = 720
STANDARD_MIN_SCORE = 620

# --- premium_earning constant ---
SHORT_RATE_PENALTY_PCT = Decimal("0.10")


def derive_credit_tier(credit_score, working_capital_cents):
    """PRD §3.2: PREFERRED if score>=720 and wc>=0; STANDARD if score>=620 and
    wc>=0; SUBSTANDARD otherwise (negative working capital or score<620)."""
    if credit_score >= PREFERRED_MIN_SCORE and working_capital_cents >= 0:
        return "PREFERRED"
    if credit_score >= STANDARD_MIN_SCORE and working_capital_cents >= 0:
        return "STANDARD"
    return "SUBSTANDARD"


def premium_rating(credit_tier, bond_type, requested_penal_sum_cents, single_limit_cents):
    """PRD §3.3: select base rate from credit_tier x bond_type; add a flat 50 bps
    large-risk surcharge when requested*2 >= single_limit; clamp rate to <= 400;
    then quoted_premium_cents = round_half_up(penal_sum * rate / 10000).

    Returns (quoted_premium_rate_bps, quoted_premium_cents).
    """
    base_rate_bps = RATE_TABLE[credit_tier][bond_type]
    surcharge_bps = LARGE_RISK_SURCHARGE_BPS if requested_penal_sum_cents * 2 >= single_limit_cents else 0
    rate_bps = min(MAX_RATE_BPS, base_rate_bps + surcharge_bps)
    premium_cents = round_half_up(
        Decimal(requested_penal_sum_cents) * Decimal(rate_bps) / Decimal(10000))
    return rate_bps, premium_cents


def elapsed_months(created_at_iso, term_months):
    """Whole months from the bond's created_at to the current logical clock,
    clamped to [0, term_months] (PRD §3.5)."""
    start = parse_iso8601(created_at_iso)
    now = clock.now()
    m = months_between(start, now)
    if m < 0:
        m = 0
    if m > term_months:
        m = term_months
    return m


def earned_premium_pro_rata(written_premium_cents, term_months, elapsed):
    """PRD §3.5 PRO_RATA: written * elapsed / term, round half up once."""
    if term_months == 0:
        return 0
    return round_half_up(
        Decimal(written_premium_cents) * Decimal(elapsed) / Decimal(term_months))


def earned_premium_short_rate(written_premium_cents, term_months, elapsed, remaining):
    """PRD §3.5 SHORT_RATE: pro-rata earned + 10% of the unearned portion, summed
    then rounded half up once (sum-then-round, not round-per-part)."""
    if term_months == 0:
        return 0
    pro_rata = Decimal(written_premium_cents) * Decimal(elapsed) / Decimal(term_months)
    unearned = Decimal(written_premium_cents) * Decimal(remaining) / Decimal(term_months)
    total = pro_rata + unearned * SHORT_RATE_PENALTY_PCT
    return round_half_up(total)


def rider_additional_premium(penal_sum_delta_cents, premium_rate_bps, remaining):
    """PRD §3.5 INCREASE rider: round the per-MONTH figure first, THEN multiply by
    remaining months (round-then-multiply, never sum-then-round)."""
    monthly = round_half_up(
        Decimal(penal_sum_delta_cents) * Decimal(premium_rate_bps) / Decimal(10000) / Decimal(12))
    return monthly * remaining


def cession_amount(penal_sum_cents, cession_pct_bps):
    """PRD §3.5: round_half_up(penal_sum * cession_pct_bps / 10000)."""
    return round_half_up(
        Decimal(penal_sum_cents) * Decimal(cession_pct_bps) / Decimal(10000))
