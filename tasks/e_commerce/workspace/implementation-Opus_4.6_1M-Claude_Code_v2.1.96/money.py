from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

TWO_PLACES = Decimal("0.01")


def to_decimal(value):
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def round2(value):
    return float(Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


def compute_commission(total_amount, current_gmv):
    total = to_decimal(total_amount)
    gmv = to_decimal(current_gmv)

    tiers = [
        (Decimal("10000"), Decimal("0.08")),
        (Decimal("50000"), Decimal("0.05")),
        (Decimal("Infinity"), Decimal("0.03")),
    ]

    commission = Decimal("0")
    remaining = total
    cumulative = gmv

    for ceiling, rate in tiers:
        if cumulative >= ceiling:
            continue
        tier_room = ceiling - cumulative
        applied = min(remaining, tier_room)
        commission += applied * rate
        cumulative += applied
        remaining -= applied
        if remaining <= 0:
            break

    commission = commission.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    rate = (commission / total * Decimal("100")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if total > 0 else Decimal("0")
    return float(commission), float(rate)
