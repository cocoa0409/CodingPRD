"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.2, 3.6, 3.8, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

# fraud_score constants
FAKE_WEIGHT = Decimal("0.7")
ANOMALY_WEIGHT = Decimal("0.3")
EXPECTED_ENGAGEMENT_CEILING = Decimal("0.05")
FRAUD_BLOCK_THRESHOLD = 60

# negotiation / revision caps
MAX_NEGOTIATION_ROUNDS = 4
MAX_REVISION_ROUNDS = 2

# campaign window buffer
CAMPAIGN_BUFFER_DAYS = 7

# payout breakdown tiers
TIER1_CAP_CENTS = 100000
TIER2_CAP_CENTS = 500000
TIER1_RATE = Decimal("0.20")
TIER2_RATE = Decimal("0.15")
TIER3_RATE = Decimal("0.10")
BACKUP_WITHHOLDING_RATE = Decimal("0.24")

# 1099 threshold
TAX_1099_THRESHOLD_CENTS = 60000

FTC_TOKENS = ["#ad", "#sponsored"]


def _round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def fraud_score(avg_engagement_rate, fake_follower_pct):
    """Composite fraud score 0..100 (integer), round_half_up (PRD 3.2)."""
    fake = Decimal(str(fake_follower_pct))
    eng = Decimal(str(avg_engagement_rate))

    # engagement_anomaly = max(0, ceiling - eng) / ceiling, clamped [0,1]
    diff = EXPECTED_ENGAGEMENT_CEILING - eng
    if diff < 0:
        diff = Decimal(0)
    anomaly = diff / EXPECTED_ENGAGEMENT_CEILING
    if anomaly < 0:
        anomaly = Decimal(0)
    if anomaly > 1:
        anomaly = Decimal(1)

    raw = (fake * 100 * FAKE_WEIGHT) + (anomaly * 100 * ANOMALY_WEIGHT)
    if raw < 0:
        raw = Decimal(0)
    if raw > 100:
        raw = Decimal(100)
    return int(_round_half_up(raw, 0))


def detect_ftc(caption):
    """True iff caption is non-null AND (case-insensitive) contains an FTC token."""
    if caption is None:
        return False
    low = caption.lower()
    return any(tok in low for tok in FTC_TOKENS)


def payout_breakdown(gross_cents, has_w9):
    """Return (gross, platform_fee, tax_withholding, net) as ints (PRD 3.9).

    Marginal tiered platform fee, rounded once at the end. Backup withholding
    24% of (gross - platform_fee) when no W-9, rounded once.
    """
    gross = Decimal(gross_cents)
    tier1 = min(gross, Decimal(TIER1_CAP_CENTS)) * TIER1_RATE
    tier2 = max(Decimal(0), min(gross, Decimal(TIER2_CAP_CENTS)) - Decimal(TIER1_CAP_CENTS)) * TIER2_RATE
    tier3 = max(Decimal(0), gross - Decimal(TIER2_CAP_CENTS)) * TIER3_RATE
    platform_fee = int(_round_half_up(tier1 + tier2 + tier3, 0))

    if not has_w9:
        tax_withholding = int(_round_half_up(
            (gross - Decimal(platform_fee)) * BACKUP_WITHHOLDING_RATE, 0))
    else:
        tax_withholding = 0

    net = gross_cents - platform_fee - tax_withholding
    return gross_cents, platform_fee, tax_withholding, net


def perf_metrics(cost_basis_cents, impressions, engagements, sale_revenue_cents):
    """CPM/CPE/ROAS (PRD 3.8).

    cpm = (cost/100) / (impressions/1000) round 2
    cpe = (cost/100) / engagements round 2
    roas = sale_revenue / cost round 4
    Division-by-zero yields None (no events of that kind / no cost basis).
    """
    cost = Decimal(cost_basis_cents)

    if impressions > 0:
        cpm = _round_half_up((cost / Decimal(100)) / (Decimal(impressions) / Decimal(1000)), 2)
        cpm = float(cpm)
    else:
        cpm = None

    if engagements > 0:
        cpe = _round_half_up((cost / Decimal(100)) / Decimal(engagements), 2)
        cpe = float(cpe)
    else:
        cpe = None

    if cost_basis_cents > 0:
        roas = _round_half_up(Decimal(sale_revenue_cents) / cost, 4)
        roas = float(roas)
    else:
        roas = None

    return cpm, cpe, roas
