"""Calculation rules (scaffold §1.3 / PRD §3). All money is integer cents."""

from decimal import Decimal, ROUND_HALF_UP

# Ammo tier constants
TIER1_BALLS = 500
TIER2_BALLS = 1500
RATE1_CENTS = 10
RATE2_CENTS = 8
RATE3_CENTS = 6
CO2_CENTS = 700

TAX_RATE = Decimal("0.0825")
REFEREE_THRESHOLD = 12
ADULT_AGE = 18
MIN_LEAD_MINUTES = 60


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, ties away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ammo_cost(n):
    """Tiered marginal ammo cost in cents for n balls."""
    tier1 = min(n, TIER1_BALLS)
    tier2 = min(max(n - TIER1_BALLS, 0), TIER2_BALLS)
    tier3 = max(n - TIER1_BALLS - TIER2_BALLS, 0)
    return tier1 * RATE1_CENTS + tier2 * RATE2_CENTS + tier3 * RATE3_CENTS


def add_on_quote_cents(ammo_balls, co2_tanks, misc_cents):
    """QUOTE variant: no package context."""
    return ammo_cost(ammo_balls) + co2_tanks * CO2_CENTS + misc_cents


def add_on_settled_cents(ammo_balls, co2_tanks, misc_cents, included_ammo, discount_pct):
    """SETTLED variant: included allowance consumed first, then package discount
    on metered ammo only, rounded half up BEFORE subtraction."""
    billable_ammo = max(ammo_balls - included_ammo, 0)
    metered = ammo_cost(billable_ammo)
    gross = metered + co2_tanks * CO2_CENTS + misc_cents
    discount = round_half_up(Decimal(metered) * Decimal(str(discount_pct)))
    return gross - discount


def deposit_settlement(deposit_hold_cents, damage_fee_cents):
    """FINAL variant waterfall. Returns (refund, forfeit)."""
    forfeit = min(deposit_hold_cents, damage_fee_cents)
    refund = deposit_hold_cents - forfeit
    return refund, forfeit


def field_fee_cents(party_size, package):
    """Package-tier field fee; 0 when no package (PRD §3.3)."""
    if package is None:
        return 0
    extra_players = max(party_size - package["included_players"], 0)
    return package["base_fee_cents"] + extra_players * package["extra_player_fee_cents"]


def _taxed_line(line):
    """Line plus round-half-up per-line tax."""
    tax = round_half_up(Decimal(line) * TAX_RATE)
    return line + tax


def booking_invoice_cents(line_field, line_addon, line_forfeit):
    """Per-line tax then sum — rounding order pinned (PRD §3.8)."""
    return _taxed_line(line_field) + _taxed_line(line_addon) + _taxed_line(line_forfeit)
