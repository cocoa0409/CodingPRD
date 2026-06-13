"""Calculation rules (PRD 2.7 + 3 / SCAFFOLD 1.3). Integer-cents arithmetic
with Decimal for the precision-sensitive steps. round_half_up for
percentage discounts and pace; ceil for the processing fee.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from errors import err, ERR_NO_ACTIVE_PRICING_TIER

# Constants (SCAFFOLD 1.3 / PRD 3.2, 3.3, 3.4)
PROCESSING_FEE_RATE = Decimal("0.029")
MAX_DISCOUNT_PCT = Decimal("0.20")
PROMO_TABLE = {"SPRING10": Decimal("0.10"), "WELCOME05": Decimal("0.05")}
CANCELLATION_FEE_RATE = Decimal("0.15")
DEFERRAL_FEE_CENTS = 1500
BIB_START_NUMBER = 100
OFFER_TTL_HOURS = 24


def round_half_up(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    """Round a Decimal up to the next whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def active_pricing_tier(tiers, reference_clock):
    """Return the active PricingTier for a list of tiers (all on one distance)
    at reference_clock: the tier with the greatest effective_from_utc that is
    <= reference_clock (inclusive). None if none qualifies.

    tiers: list of dicts each with key '_effective_from_dt' (aware datetime).
    reference_clock: aware datetime.
    """
    best = None
    for t in tiers:
        eff = t["_effective_from_dt"]
        if eff <= reference_clock:
            if best is None or eff > best["_effective_from_dt"]:
                best = t
    return best


def registration_amount_due(entry_type, party_size, promo_code, tiers, reference_clock):
    """Pinned tiered-pricing sequence (PRD 3.2). Returns
    (amount_cents, processing_fee_cents, discounted_base_cents).

    Raises ERR_NO_ACTIVE_PRICING_TIER when no tier is active and the entry is
    not CHARITY (CHARITY waives the entry fee, base = 0)."""
    # Step 1: base fee
    if entry_type == "CHARITY":
        base = 0
    else:
        tier = active_pricing_tier(tiers, reference_clock)
        if tier is None:
            raise err(ERR_NO_ACTIVE_PRICING_TIER,
                      "No active pricing tier for this distance at the reference clock")
        base = tier["base_price_cents"]

    # Step 2: group discount
    if party_size >= 4:
        group_pct = Decimal("0.10")
    elif party_size >= 2:
        group_pct = Decimal("0.05")
    else:
        group_pct = Decimal("0.00")

    # Step 3: promo discount
    promo_pct = PROMO_TABLE.get(promo_code, Decimal("0.00")) if promo_code else Decimal("0.00")

    # Step 4: combined, capped
    discount_pct = min(group_pct + promo_pct, MAX_DISCOUNT_PCT)

    # Step 5: discount cents, round half-up
    discount_cents = round_half_up(Decimal(base) * discount_pct)

    # Step 6: discounted base
    discounted_base = base - discount_cents

    # Step 7: processing fee, ceil
    processing_fee_cents = ceil_int(Decimal(discounted_base) * PROCESSING_FEE_RATE)

    # Step 8: total
    amount = discounted_base + processing_fee_cents
    return amount, processing_fee_cents, discounted_base


def registration_refund(status, amount_paid_cents, processing_fee_cents, organizer_initiated):
    """Refund on cancellation (PRD 3.4 / 3.9).

    Organizer-initiated => full refund of amount_paid (incl. processing fee).
    Participant-initiated: 0 for PENDING_PAYMENT/WAITLISTED; else
    net = paid - processing_fee; fee = round_half_up(net * 0.15); refund = net - fee.
    """
    if organizer_initiated:
        return amount_paid_cents
    if status in ("PENDING_PAYMENT", "WAITLISTED"):
        return 0
    net = amount_paid_cents - processing_fee_cents
    cancellation_fee = round_half_up(Decimal(net) * CANCELLATION_FEE_RATE)
    return net - cancellation_fee


def deferral_credit(amount_paid_cents, processing_fee_cents):
    """Deferral credit (PRD 3.4): max(net - DEFERRAL_FEE_CENTS, 0)."""
    net = amount_paid_cents - processing_fee_cents
    return max(net - DEFERRAL_FEE_CENTS, 0)


def fundraising_totals(pledges):
    """Return (provisional_pledged_cents, settled_pledged_cents) for a list of
    pledge dicts (already filtered to one registration). VOIDED excluded from both."""
    provisional = 0
    settled = 0
    for p in pledges:
        if p["status"] == "PLEDGED" or p["status"] == "SETTLED":
            provisional += p["amount_cents"]
        if p["status"] == "SETTLED":
            settled += p["amount_cents"]
    return provisional, settled


def timing_result(gun_start, mat_cross, finish, distance_km):
    """Compute (gun_time, chip_time, pace_seconds_per_km). Assumes clocks
    already validated for ordering."""
    gun_time = finish - gun_start
    chip_time = finish - mat_cross
    pace = round_half_up(Decimal(chip_time) / Decimal(str(distance_km)))
    return gun_time, chip_time, pace


def corral_letter(corral_index):
    """A, B, C, ... at the given 0-based index."""
    return chr(ord("A") + corral_index)
