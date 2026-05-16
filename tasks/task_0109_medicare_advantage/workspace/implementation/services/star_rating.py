"""Star rating weighted composite."""
from decimal import ROUND_HALF_UP, Decimal


W_CLINICAL = Decimal("0.50")
W_EXPERIENCE = Decimal("0.30")
W_SERVICE = Decimal("0.20")


def composite(clinical: float, experience: float, service: float) -> float:
    """Compute the weighted composite, preserved to 4 decimal places."""
    c = Decimal(str(clinical)) * W_CLINICAL
    e = Decimal(str(experience)) * W_EXPERIENCE
    s = Decimal(str(service)) * W_SERVICE
    total = (c + e + s).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(total)


def band(composite_raw: float) -> float:
    """Map composite to half-star rating using strictly >= thresholds."""
    if composite_raw >= 90:
        return 5.0
    if composite_raw >= 80:
        return 4.5
    if composite_raw >= 70:
        return 4.0
    if composite_raw >= 60:
        return 3.5
    if composite_raw >= 50:
        return 3.0
    if composite_raw >= 40:
        return 2.5
    if composite_raw >= 30:
        return 2.0
    if composite_raw >= 20:
        return 1.5
    return 1.0
