from decimal import Decimal, ROUND_HALF_UP


def compute_bonus_tier(on_time_rate: float, acceptance_rate: float, rating: float) -> str:
    score = Decimal("0.6") * Decimal(str(on_time_rate)) \
            + Decimal("0.3") * Decimal(str(acceptance_rate)) \
            + Decimal("0.1") * (Decimal(str(rating)) / Decimal("5"))
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if score >= Decimal("0.900"):
        return "PLATINUM"
    if score >= Decimal("0.800"):
        return "GOLD"
    if score >= Decimal("0.700"):
        return "SILVER"
    return "BRONZE"
