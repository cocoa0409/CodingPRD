"""Royalty and pricing calculations (PRD §3.7 / SCAFFOLD §1.3).

All monetary results are integer cents, round-half-up unless stated. Decimal is
used throughout to avoid float drift; rounding boundaries are honored exactly.
"""
import math
from decimal import Decimal

from services.common import round_half_up, floor_cents

# ---- performance_pool_royalty constants ----
PRO_RATE = {"ASCAP": 12, "BMI": 11, "NONE": 0}
POOL_SHARE = Decimal("0.50")
DURATION_CAP = Decimal("3.0")

# ---- mechanical_statutory_royalty constants ----
BASE_PENNY_RATE = Decimal("12")
PER_MINUTE_RATE = Decimal("2")
STREAM_FACTOR = Decimal("0.01")

# ---- sync_quote_fee constants ----
MEDIA_MULT = {
    "FILM": Decimal("2.0"),
    "TV": Decimal("1.5"),
    "AD": Decimal("3.0"),
    "GAME": Decimal("1.25"),
}
TERR_WW_MULT = Decimal("2.5")
TERR_SMALL_DEAL_MULT = Decimal("1.2")
TERR_LARGE_DEAL_MULT = Decimal("1.0")
LARGE_DEAL_SUBTOTAL_CENTS = Decimal("500000")


def performance_pool_royalty(work, usage_event):
    """PRD §3.7 performance pool. Returns the pool total in integer cents,
    rounded half-up ONCE. NONE affiliation earns 0."""
    pro_affiliation = work["pro_affiliation"]
    pro_rate = Decimal(PRO_RATE[pro_affiliation])
    if pro_affiliation == "NONE":
        return 0
    duration_weight = min(
        Decimal(work["duration_seconds"]) / Decimal("180"),
        DURATION_CAP,
    )
    gross = Decimal(usage_event["gross_revenue_cents"])
    quantity = Decimal(usage_event["quantity"])
    raw = gross * POOL_SHARE + quantity * pro_rate * duration_weight
    return round_half_up(raw)


def mechanical_statutory_royalty(recording, usage_event):
    """PRD §3.7 mechanical statutory. Returns the pool total in integer cents,
    rounded half-up ONCE."""
    duration = recording["duration_seconds"]
    if duration <= 300:
        rate = BASE_PENNY_RATE
    else:
        started_minutes = math.ceil(duration / 60.0)
        rate = max(BASE_PENNY_RATE, PER_MINUTE_RATE * Decimal(started_minutes))
    quantity = Decimal(usage_event["quantity"])
    if recording["release_type"] == "PHYSICAL":
        raw = rate * quantity
    else:  # STREAMING
        raw = rate * quantity * STREAM_FACTOR
    return round_half_up(raw)


def sync_quote_fee(base_fee_cents, media_type, territory, term_months):
    """PRD §3.7 sync quote. Pinned eval order: media -> territory(from subtotal)
    -> term. Single final round over the full product."""
    media_mult = MEDIA_MULT[media_type]
    subtotal = Decimal(base_fee_cents) * media_mult  # step 1, no rounding
    # step 2: territory tier on subtotal magnitude
    if territory == "WW":
        terr_mult = TERR_WW_MULT
    elif subtotal >= LARGE_DEAL_SUBTOTAL_CENTS:
        terr_mult = TERR_LARGE_DEAL_MULT
    else:
        terr_mult = TERR_SMALL_DEAL_MULT
    # step 3: term tier
    if term_months >= 36:
        term_mult = Decimal("1.6")
    elif term_months >= 12:
        term_mult = Decimal("1.3")
    else:
        term_mult = Decimal("1.0")
    return round_half_up(subtotal * terr_mult * term_mult)


def allocate_to_holders(pool_total_cents, holders):
    """Distribute a rounded pool total to holders by split_bps. Per PRD §3.7
    each per-holder allocation is rounded half-up once:
        holder_cents = round_half_up(pool_total * split_bps / 10000)
    holders: list of dicts each with 'rightsholder_id' and 'split_bps'.
    Returns list of (rightsholder_id, amount_cents)."""
    result = []
    pool = Decimal(pool_total_cents)
    for h in holders:
        amount = round_half_up(pool * Decimal(h["split_bps"]) / Decimal("10000"))
        result.append((h["rightsholder_id"], amount))
    return result


def advance_recoupment(gross_earnings_cents, active_advances_sorted):
    """PRD §3.7 advance recoupment, oldest first.

    active_advances_sorted: list of advance records sorted by created_at ASC.
    Returns (recoupment_applied_cents, [(advance, take_amount), ...]) where each
    entry records how much was taken from that advance (only advances with a
    positive take are returned). Mutation of the advance records is the caller's
    responsibility (this function is pure)."""
    remaining_gross = gross_earnings_cents
    recoupment_applied = 0
    takes = []
    for adv in active_advances_sorted:
        outstanding = adv["principal_cents"] - adv["recouped_cents"]
        if outstanding <= 0:
            continue
        eligible = floor_cents(Decimal(remaining_gross) * Decimal(str(adv["recoupment_pct"])))
        take = min(outstanding, eligible)
        if take <= 0:
            continue
        recoupment_applied += take
        remaining_gross -= take
        takes.append((adv, take))
    return recoupment_applied, takes
