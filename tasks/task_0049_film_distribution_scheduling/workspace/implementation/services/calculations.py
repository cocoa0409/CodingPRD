"""Pure calculation rules from §1.3 of the scaffold."""

from decimal import Decimal, ROUND_HALF_UP


# Constants
IMAX_SETUP_MINUTES = 5
THREEEDEE_SETUP_MINUTES = 3
TWODEE_SETUP_MINUTES = 0

PLATFORM_COMMISSION_BPS = 800
TAX_BPS = 600
PROMO_DISTRIBUTOR_BPS_OVERRIDE = 5000

LOW_ATTENDANCE_THRESHOLD_BPS = 1500

ROLLING_WINDOW_THRESHOLD = 10
CUMULATIVE_THRESHOLD = 30
WINDOW_MINUTES = 60

PER_BUYER_HARD_CAP = 20
COMPETING_PEAK_CAP = 1


def round_half_up_int(numerator, denominator):
    """Compute round_half_up(numerator / denominator) to nearest integer."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_setup_minutes(film_format):
    if film_format == "IMAX":
        return IMAX_SETUP_MINUTES
    if film_format == "3D":
        return THREEEDEE_SETUP_MINUTES
    return TWODEE_SETUP_MINUTES


def compute_block_and_end_minutes(film, screen, start_minute):
    base = film["duration_minutes"] + screen["trailer_minutes"] + screen["ad_minutes"]
    block = base + format_setup_minutes(film["format"])
    end = start_minute + block
    return block, end


def compute_settlement_split(tickets, distributor_default_bps):
    """Compute split per §3.9 (POSTING variant).

    tickets: list of dicts each having paid_amount_cents and optional promo_code.
    Returns dict with gross_cents, platform_commission_cents, tax_cents,
    distributor_amount_cents, cinema_amount_cents.
    """
    # Step 1: per-ticket platform commission rounded half-up
    per_ticket_platform = []
    for t in tickets:
        amt = t.get("paid_amount_cents", 0)
        fee = round_half_up_int(amt * PLATFORM_COMMISSION_BPS, 10000)
        per_ticket_platform.append(fee)
    # Step 3: sum
    platform_commission_cents = sum(per_ticket_platform)
    # Step 2: gross
    gross_cents = sum(t.get("paid_amount_cents", 0) for t in tickets)
    # Step 4
    net_after_platform = gross_cents - platform_commission_cents
    # Step 5: tax computed on net_after_platform, single round
    tax_cents = round_half_up_int(net_after_platform * TAX_BPS, 10000)
    # Step 6
    net_after_tax = net_after_platform - tax_cents
    # promo eligibility: any non-empty promo_code in evaluation set
    promo_active = any(
        (t.get("promo_code") not in (None, "")) for t in tickets
    )
    effective_bps = PROMO_DISTRIBUTOR_BPS_OVERRIDE if promo_active else distributor_default_bps
    distributor_amount_cents = round_half_up_int(net_after_tax * effective_bps, 10000)
    # Step 7: cinema = remainder
    cinema_amount_cents = net_after_tax - distributor_amount_cents
    return {
        "gross_cents": gross_cents,
        "platform_commission_cents": platform_commission_cents,
        "tax_cents": tax_cents,
        "distributor_amount_cents": distributor_amount_cents,
        "cinema_amount_cents": cinema_amount_cents,
    }


def compute_reversal_split(ticket, distributor_default_bps):
    """Reversal variant: evaluation set is exactly one ticket; gross enters as -paid_amount_cents.

    Per spec §3.9: "a reversal subtracts exactly that ticket's rounded share of the platform
    commission rather than recomputing a fresh slice of a hypothetical net total."
    """
    # Compute positive-side allocations first, then negate every component.
    amt = ticket.get("paid_amount_cents", 0)
    pos_platform = round_half_up_int(amt * PLATFORM_COMMISSION_BPS, 10000)
    pos_net_after_platform = amt - pos_platform
    pos_tax = round_half_up_int(pos_net_after_platform * TAX_BPS, 10000)
    pos_net_after_tax = pos_net_after_platform - pos_tax
    promo_active = (ticket.get("promo_code") not in (None, ""))
    effective_bps = PROMO_DISTRIBUTOR_BPS_OVERRIDE if promo_active else distributor_default_bps
    pos_distrib = round_half_up_int(pos_net_after_tax * effective_bps, 10000)
    pos_cinema = pos_net_after_tax - pos_distrib

    return {
        "gross_cents": -amt,
        "platform_commission_cents": -pos_platform,
        "tax_cents": -pos_tax,
        "distributor_amount_cents": -pos_distrib,
        "cinema_amount_cents": -pos_cinema,
    }


def attendance_rate_bps(gross_box_office_cents, seat_capacity, ticket_price_cents):
    """Floor (integer) division as per spec §3.7."""
    max_revenue_cents = seat_capacity * ticket_price_cents
    if max_revenue_cents <= 0:
        return 0
    return (gross_box_office_cents * 10000) // max_revenue_cents


def attendance_is_low(gross_box_office_cents, seat_capacity, ticket_price_cents):
    bps = attendance_rate_bps(gross_box_office_cents, seat_capacity, ticket_price_cents)
    return bps < LOW_ATTENDANCE_THRESHOLD_BPS
