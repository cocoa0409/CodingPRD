"""Calculation rules (SCAFFOLD §1.3). All money/basis-point math is Decimal with
round-half-up per component, in the pinned orders the PRD declares."""
from decimal import Decimal

from util import hamming64, levenshtein, rhu, whole_days_between

# registration_fee constants
TIER1_LIMIT = 50000
TIER1_FEE = 1000
TIER2_LIMIT = 200000
TIER2_FEE = 2000
TIER3_FEE = 3500
ENGRAVING_FEE = 1500
INSURANCE_RATE = Decimal("0.08")
PROCESSING_RATE = Decimal("0.03")

# duplicate_confidence constants
AUTO_FLAG_THRESHOLD_BP = 8500
W_SERIAL = Decimal("0.60")
W_MFR = Decimal("0.25")
W_MODEL = Decimal("0.15")

# match_score constants
NOTIFY_THRESHOLD_BP = 7000

# storage_fee_accrual constants
FREE_DAYS = 5
RATE_CENTS_PER_DAY = 150
CAP_PCT_OF_APPRAISED = Decimal("0.25")

# auction_settlement_waterfall constants
MIN_RESERVE_CENTS = 1000
RESERVE_PCT_OF_APPRAISED = Decimal("0.20")
STORAGE_CAP_PCT_OF_WINNING = Decimal("0.30")
COMMISSION_TIER1_LIMIT = 50000
COMMISSION_TIER1_RATE = Decimal("0.10")
COMMISSION_TIER2_RATE = Decimal("0.15")

# next_minimum_bid constants
MIN_INCREMENT_FLOOR_CENTS = 500
MIN_INCREMENT_PCT = Decimal("0.05")


def registration_fee(declared_value_cents, insurance_opt_in, engraving_opt_in):
    """Per-component rounding FIRST, then summation (pinned order, PRD §3.2)."""
    if declared_value_cents < TIER1_LIMIT:
        tier_base = TIER1_FEE
    elif declared_value_cents <= TIER2_LIMIT:
        tier_base = TIER2_FEE
    else:
        tier_base = TIER3_FEE
    insurance = rhu(INSURANCE_RATE * declared_value_cents) if insurance_opt_in else 0
    engraving = ENGRAVING_FEE if engraving_opt_in else 0
    processing = rhu(PROCESSING_RATE * (tier_base + insurance + engraving))
    return tier_base + insurance + engraving + processing


def _serial_points(a_norm, b_norm):
    if a_norm == b_norm:
        return Decimal("1")
    longer = max(len(a_norm), len(b_norm))
    if longer == 0:
        return Decimal("1")
    pts = Decimal("1") - Decimal(levenshtein(a_norm, b_norm)) / Decimal(longer)
    return pts if pts > 0 else Decimal("0")


def duplicate_confidence(bike_a, bike_b):
    """Weighted blend over canonical serials + descriptive fields (PRD §3.2)."""
    serial_pts = _serial_points(bike_a["serial_normalized"], bike_b["serial_normalized"])
    mfr_pts = Decimal("1") if (bike_a["manufacturer"] or "").lower() == (bike_b["manufacturer"] or "").lower() else Decimal("0")
    model_pts = Decimal("1") if (bike_a["model"] or "").lower() == (bike_b["model"] or "").lower() else Decimal("0")
    return rhu(10000 * (W_SERIAL * serial_pts + W_MFR * mfr_pts + W_MODEL * model_pts))


def match_scores(intake, bicycle, report):
    """Returns (screening_score, forensic_score) in integer basis points."""
    days = max(0, whole_days_between(report["occurred_at"], intake["found_at"]))

    serial_pts = _serial_points(intake["serial_normalized"], bicycle["serial_normalized"])

    if intake["manufacturer"] is None:
        mfr_pts = Decimal("0.5")
    else:
        mfr_pts = Decimal("1") if intake["manufacturer"].lower() == (bicycle["manufacturer"] or "").lower() else Decimal("0")

    if intake["primary_color"] is None:
        color_pts = Decimal("0.5")
    else:
        color_pts = Decimal("1") if intake["primary_color"].lower() == (bicycle["primary_color"] or "").lower() else Decimal("0")

    if intake["photo_hash"] is None or bicycle["photo_hash"] is None:
        photo_pts = Decimal("0")
    else:
        photo_pts = Decimal("1") - Decimal(hamming64(intake["photo_hash"], bicycle["photo_hash"])) / Decimal(64)

    if days <= 30:
        temporal_pts = Decimal("1")
    else:
        temporal_pts = Decimal("1") - Decimal(days - 30) / Decimal(335)
        if temporal_pts < 0:
            temporal_pts = Decimal("0")

    screening = rhu(10000 * (
        Decimal("0.50") * serial_pts
        + Decimal("0.20") * mfr_pts
        + Decimal("0.15") * color_pts
        + Decimal("0.15") * temporal_pts
    ))
    forensic = rhu(10000 * (
        Decimal("0.35") * serial_pts
        + Decimal("0.30") * photo_pts
        + Decimal("0.15") * mfr_pts
        + Decimal("0.10") * color_pts
        + Decimal("0.10") * temporal_pts
    ))
    return screening, forensic


def storage_fee_accrual(intake, cutoff):
    """First 5 days free; 150 cents/day after; capped at 25% of appraised value."""
    elapsed_days = whole_days_between(intake["created_at"], cutoff)
    chargeable_days = max(0, elapsed_days - FREE_DAYS)
    accrued = chargeable_days * RATE_CENTS_PER_DAY
    cap = rhu(CAP_PCT_OF_APPRAISED * intake["appraised_value_cents"])
    return min(accrued, cap)


def reserve_price(appraised_value_cents):
    return max(MIN_RESERVE_CENTS, rhu(RESERVE_PCT_OF_APPRAISED * appraised_value_cents))


def settlement_waterfall(gross, cutoff, intake):
    """Pinned six-step order (PRD §3.7). Returns (storage, commission, payout)."""
    storage = min(storage_fee_accrual(intake, cutoff), rhu(STORAGE_CAP_PCT_OF_WINNING * gross))
    base = gross - storage
    commission = (
        rhu(COMMISSION_TIER1_RATE * min(base, COMMISSION_TIER1_LIMIT))
        + rhu(COMMISSION_TIER2_RATE * max(0, base - COMMISSION_TIER1_LIMIT))
    )
    payout = gross - storage - commission
    return storage, commission, payout


def next_minimum_bid(reserve_price_cents, active_amounts):
    """No ACTIVE bid -> reserve; else leading + max(500, rhu(5% of leading)).
    Acceptance is inclusive (amount == minimum accepted)."""
    if not active_amounts:
        return reserve_price_cents
    leading = max(active_amounts)
    increment = max(MIN_INCREMENT_FLOOR_CENTS, rhu(MIN_INCREMENT_PCT * leading))
    return leading + increment
