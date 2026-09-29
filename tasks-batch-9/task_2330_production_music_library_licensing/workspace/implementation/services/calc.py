"""All nine calculation rules (SCAFFOLD §1.3 / PRD §3).

Every monetary figure is an integer number of cents; every rounding point is
named and uses ROUND_HALF_UP on Decimal values (never float).
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

ZERO = Decimal("0")
CENT = Decimal("1")
TWO_DP = Decimal("0.01")
ONE_DP = Decimal("0.1")

# -- license_fee_quote ------------------------------------------------------
MEDIA_FACTOR = {
    "BROADCAST_TV": Decimal("1.30"),
    "ONLINE_AD": Decimal("1.75"),
    "FILM": Decimal("2.20"),
    "CORPORATE": Decimal("0.85"),
    "GAME": Decimal("1.40"),
}
SCALE_FACTOR = {
    "LOCAL": Decimal("0.60"),
    "NATIONAL": Decimal("1.00"),
    "WORLDWIDE": Decimal("1.90"),
}
EXCLUSIVITY_FACTOR = Decimal("1.65")
RUSH_FACTOR = Decimal("1.20")
CUSTOM_EDIT_FEE_CENTS = 45000
STEMS_FEE_CENTS = 30000
ALT_LENGTH_FEE_CENTS = 12000

# -- cue_performance_credits ------------------------------------------------
USAGE_WEIGHT = {
    "THEME": Decimal("1.00"),
    "FEATURE": Decimal("0.65"),
    "BACKGROUND": Decimal("0.35"),
    "LOGO": Decimal("0.10"),
}
MARKET_WEIGHT = {
    "NETWORK": Decimal("1.00"),
    "CABLE": Decimal("0.65"),
    "LOCAL": Decimal("0.40"),
    "DIGITAL": Decimal("0.25"),
}
CREDIT_VALUE_CENTS = Decimal("1250")

# -- blanket ----------------------------------------------------------------
OVERAGE_RATE_CENTS_PER_MINUTE = 450
REPORT_GRACE_DAYS = 15
POOL_ADMIN_PCT = Decimal("15.00")

# -- statements -------------------------------------------------------------
MIN_PAYOUT_CENTS = 2500

# -- search -----------------------------------------------------------------
RECENCY_BOOST = Decimal("1.10")
RECENCY_BOOST_DAYS = 90

# -- infringement -----------------------------------------------------------
PLATFORM_RATE_CENTS_PER_SEC = {
    "UGC_VIDEO": Decimal("1000"),
    "BROADCAST": Decimal("4500"),
    "THEATRICAL": Decimal("9000"),
    "PODCAST": Decimal("1500"),
}
STATUTORY_CAP_CENTS = 15000000
NEGOTIATED_FLOOR_PCT = Decimal("30.00")
CLAIM_CONFIDENCE_MIN_PCT = Decimal("70.0")
NOTICE_CONFIDENCE_MIN_PCT = Decimal("85.0")


# ---------------------------------------------------------------------------
# rounding helpers
# ---------------------------------------------------------------------------
def cents(value):
    """round_half_up to a whole cent."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def dp2(value):
    """round_half_up to 2 decimals."""
    return Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def dp1(value):
    return Decimal(value).quantize(ONE_DP, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(Decimal(value).quantize(CENT, rounding=ROUND_FLOOR))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# license_fee_quote
# ---------------------------------------------------------------------------
def term_factor(term_months):
    if term_months <= 3:
        return Decimal("0.70")
    if term_months <= 12:
        return Decimal("1.00")
    if term_months <= 36:
        return Decimal("1.45")
    return Decimal("1.90")


def discount_pct(spend_basis_cents):
    if spend_basis_cents < 500000:
        return Decimal("0.00")
    if spend_basis_cents < 1500000:
        return Decimal("5.00")
    if spend_basis_cents < 3000000:
        return Decimal("10.00")
    return Decimal("15.00")


def license_fee(base_rate_cents, media_type, distribution_scale, term_months,
                exclusive, rush, custom_edit, stems, alt_length_count,
                committed_spend_cents):
    """Returns (fee_cents, spend_basis_cents, discount_pct, pre_discount_cents)."""
    core = (
        Decimal(base_rate_cents)
        * MEDIA_FACTOR[media_type]
        * SCALE_FACTOR[distribution_scale]
        * term_factor(term_months)
    )
    if exclusive:
        core = core * EXCLUSIVITY_FACTOR
    if rush:
        core = core * RUSH_FACTOR
    core_cents = cents(core)                                  # rounded exactly once
    addons = 0
    if custom_edit:
        addons += CUSTOM_EDIT_FEE_CENTS
    if stems:
        addons += STEMS_FEE_CENTS
    addons += ALT_LENGTH_FEE_CENTS * alt_length_count
    pre_discount = core_cents + addons
    basis = committed_spend_cents + pre_discount
    pct = discount_pct(basis)
    fee = pre_discount - cents(Decimal(pre_discount) * pct / Decimal(100))
    return fee, basis, pct, pre_discount


# ---------------------------------------------------------------------------
# cue_performance_credits
# ---------------------------------------------------------------------------
def cue_credits(duration_sec, usage_type, market_tier):
    raw = (Decimal(duration_sec) / Decimal(30)) * USAGE_WEIGHT[usage_type] * MARKET_WEIGHT[market_tier]
    return dp2(raw)


# ---------------------------------------------------------------------------
# performance_royalty_cents  (two roundings, never collapsed)
# ---------------------------------------------------------------------------
def performance_amounts(composer_credits, writer_share_pct):
    gross = cents(Decimal(composer_credits) * CREDIT_VALUE_CENTS)
    writer = cents(Decimal(gross) * Decimal(writer_share_pct) / Decimal(100))
    return gross, writer


# ---------------------------------------------------------------------------
# blanket_pool_distribution
# ---------------------------------------------------------------------------
def cadence_fraction(reporting_cadence):
    if reporting_cadence == "MONTHLY":
        return Decimal(1) / Decimal(12)
    return Decimal(1) / Decimal(4)


def pool_figures(annual_fee_cents, pool_share_pct, reporting_cadence, overage_increment_cents):
    fee_term = cents(
        Decimal(annual_fee_cents) * Decimal(pool_share_pct) / Decimal(100)
        * cadence_fraction(reporting_cadence)
    )
    overage_term = cents(Decimal(overage_increment_cents) * Decimal(pool_share_pct) / Decimal(100))
    pool = fee_term + overage_term
    admin = cents(Decimal(pool) * POOL_ADMIN_PCT / Decimal(100))
    return pool, admin, pool - admin


def allocate_pool(distributable_cents, works):
    """`works` is a list of (composition_id, credits Decimal, created_at).

    Largest-remainder allocation: floor share plus one cent to the head slice,
    ordered credits DESC, created_at ASC, id ASC.  The allocations always sum to
    `distributable_cents` exactly.
    """
    if not works:
        return []
    total_credits = sum((w[1] for w in works), Decimal("0"))
    ordered = sorted(works, key=lambda w: (-w[1], w[2], w[0]))
    if total_credits <= 0:
        return [
            {"composition_id": w[0], "credits": num(dp2(w[1])), "allocation_cents": 0}
            for w in ordered
        ]
    floors = []
    for w in ordered:
        share = Decimal(distributable_cents) * w[1] / total_credits
        floors.append(floor_int(share))
    remainder = distributable_cents - sum(floors)
    allocations = []
    for index, w in enumerate(ordered):
        extra = 1 if index < remainder else 0
        allocations.append(
            {
                "composition_id": w[0],
                "credits": num(dp2(w[1])),
                "allocation_cents": floors[index] + extra,
            }
        )
    return allocations


# ---------------------------------------------------------------------------
# statement_settlement
# ---------------------------------------------------------------------------
def statement_figures(gross_cents, outstanding_advance_cents, tax_withholding_pct):
    recouped = min(max(gross_cents, 0), outstanding_advance_cents)
    base = gross_cents - recouped
    withholding = cents(Decimal(base) * Decimal(tax_withholding_pct))
    net = gross_cents - recouped - withholding
    if gross_cents == 0:
        status = "NO_ACTIVITY"
    elif net < MIN_PAYOUT_CENTS:
        status = "HELD_BELOW_MINIMUM"
    else:
        status = "PAYABLE"
    return recouped, withholding, net, status


# ---------------------------------------------------------------------------
# infringement_statutory_amount
# ---------------------------------------------------------------------------
def confidence_factor(confidence_pct):
    pct = Decimal(confidence_pct)
    if pct >= Decimal("95.0"):
        return Decimal("1.00")
    if pct >= Decimal("85.0"):
        return Decimal("0.75")
    if pct >= Decimal("70.0"):
        return Decimal("0.50")
    return None


def statutory_amount(matched_seconds, source_platform, confidence_pct):
    factor = confidence_factor(confidence_pct)
    raw = cents(
        Decimal(matched_seconds) * PLATFORM_RATE_CENTS_PER_SEC[source_platform] * factor
    )
    return min(STATUTORY_CAP_CENTS, raw)


def settlement_floor(statutory_amount_cents):
    return cents(Decimal(statutory_amount_cents) * NEGOTIATED_FLOOR_PCT / Decimal(100))
