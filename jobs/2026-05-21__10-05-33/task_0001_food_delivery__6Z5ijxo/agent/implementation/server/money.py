from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(amount) -> int:
    if isinstance(amount, int):
        return amount
    d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
