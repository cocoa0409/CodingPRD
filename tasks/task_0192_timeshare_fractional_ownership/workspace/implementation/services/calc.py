"""Calculation rules: points cost, fee proration, special assessment, late charges, exchange credits."""
from decimal import Decimal

from services.util import round_half_up, parse_iso, use_year_start, whole_days_between

# --- Constants (from SCAFFOLD calculations) ---
SEASON_MULT = {
    "PLATINUM": Decimal("1.50"),
    "GOLD": Decimal("1.00"),
    "SILVER": Decimal("0.60"),
}
EARLY_BIRD_DAYS = 180
EARLY_BIRD_DISCOUNT = Decimal("0.10")
DAYS_IN_YEAR = 365
LATE_RATE = Decimal("0.05")
CREDIT_DIVISOR = {"RCI": 100, "II": 120}


def inventory_points_value(resort, season):
    """points_value = round_half_up(points_per_week_base * SEASON_MULT[season])."""
    base = Decimal(str(resort["points_per_week_base"])) * SEASON_MULT[season]
    return round_half_up(base)


def reservation_base_cost(resort, unit):
    """base = round_half_up(points_per_week_base * season multiplier), rounded BEFORE discount."""
    return round_half_up(
        Decimal(str(resort["points_per_week_base"])) * SEASON_MULT[unit["season"]]
    )


def lead_time_discounted(base, resort, use_year):
    """Apply early-bird discount if lead_days >= 180. Floor the discounted result."""
    current = parse_iso(resort["current_utc"])
    target_start = use_year_start(use_year)
    lead_days = whole_days_between(current, target_start)
    if lead_days >= EARLY_BIRD_DAYS:
        # discounted = floor(base * (1 - EARLY_BIRD_DISCOUNT))
        discounted = Decimal(base) * (Decimal(1) - EARLY_BIRD_DISCOUNT)
        return int(discounted.to_integral_value(rounding="ROUND_FLOOR"))
    return base


def borrow_surcharge(shortfall, resort):
    """surcharge = ceil(shortfall * borrow_surcharge_pct)."""
    pct = Decimal(str(resort["borrow_surcharge_pct"]))
    val = Decimal(shortfall) * pct
    return int(val.to_integral_value(rounding="ROUND_CEILING"))


def annual_full_fee(resort, points_basis):
    """annual_full = ceil(points_basis / 1000 * annual_fee_cents_per_1000_points)."""
    rate = Decimal(str(resort["annual_fee_cents_per_1000_points"]))
    val = Decimal(points_basis) / Decimal(1000) * rate
    return int(val.to_integral_value(rounding="ROUND_CEILING"))


def resale_seller_share(annual_full, transfer_day_of_year):
    """seller_share = floor(annual_full * transfer_day_of_year / 365)."""
    val = Decimal(annual_full) * Decimal(transfer_day_of_year) / Decimal(DAYS_IN_YEAR)
    return int(val.to_integral_value(rounding="ROUND_FLOOR"))


def special_assessment_shares(total_amount_cents, contracts_with_basis):
    """Distribute total_amount_cents across contracts by points basis.

    contracts_with_basis: list of (contract, basis) in the order they should be
    considered for tie-breaking (caller passes Contract.created_at ASC order).
    Returns {contract_id: assessed_cents}. Round-down then largest-remainder.
    """
    total_basis = sum(basis for _, basis in contracts_with_basis)
    floor_shares = {}
    remainders = []  # (remainder_fraction, seq_index, contract_id)
    if total_basis == 0:
        # Degenerate: nothing to allocate proportionally; assign all to first.
        for i, (c, _) in enumerate(contracts_with_basis):
            floor_shares[c["id"]] = 0
        # Hand out all cents one each in order until exhausted.
        remaining = total_amount_cents
        for c, _ in contracts_with_basis:
            if remaining <= 0:
                break
            floor_shares[c["id"]] += 1
            remaining -= 1
        return floor_shares

    for i, (c, basis) in enumerate(contracts_with_basis):
        raw = Decimal(total_amount_cents) * Decimal(basis) / Decimal(total_basis)
        floor_share = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
        floor_shares[c["id"]] = floor_share
        frac = raw - Decimal(floor_share)
        remainders.append((frac, i, c["id"]))

    distributed = sum(floor_shares.values())
    remainder_cents = total_amount_cents - distributed
    # Order by (raw - floor) DESC, tie-break by created_at ASC (== seq index ASC).
    remainders.sort(key=lambda t: (-t[0], t[1]))
    for k in range(remainder_cents):
        cid = remainders[k][2]
        floor_shares[cid] += 1
    return floor_shares


def late_charge_delta(invoice, basis):
    """Compute the late-charge delta for one invoice for one escalation period."""
    if basis == "SIMPLE":
        val = Decimal(invoice["amount_cents"]) * LATE_RATE
    else:  # COMPOUNDING
        running = Decimal(invoice["amount_cents"] + invoice["late_charge_cents"])
        val = running * LATE_RATE
    return int(val.to_integral_value(rounding="ROUND_FLOOR"))


def exchange_credits(points_cost, network):
    divisor = CREDIT_DIVISOR[network]
    return points_cost // divisor
