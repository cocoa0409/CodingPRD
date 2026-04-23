from decimal import Decimal, ROUND_HALF_UP


def compute_tiered_commission(subtotal_cents):
    subtotal = Decimal(subtotal_cents)
    tier1_cap = Decimal(20000)
    tier2_cap = Decimal(50000)
    tier1_rate = Decimal("0.15")
    tier2_rate = Decimal("0.18")
    tier3_rate = Decimal("0.22")

    tier1_amount = min(subtotal, tier1_cap)
    tier2_amount = max(Decimal(0), min(subtotal, tier2_cap) - tier1_cap)
    tier3_amount = max(Decimal(0), subtotal - tier2_cap)

    total = tier1_amount * tier1_rate + tier2_amount * tier2_rate + tier3_amount * tier3_rate
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_flat_commission(subtotal_cents, rate):
    subtotal = Decimal(subtotal_cents)
    rate_d = Decimal(str(rate))
    total = subtotal * rate_d
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_commission(subtotal_cents, commission_rate_override=None):
    if commission_rate_override is not None:
        return compute_flat_commission(subtotal_cents, commission_rate_override)
    return compute_tiered_commission(subtotal_cents)
