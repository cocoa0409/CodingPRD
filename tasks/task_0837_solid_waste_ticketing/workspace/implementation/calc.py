"""Calculation rules for the Solid-Waste Ticketing API (PRD §2.6, §2.9, §3.4, §3.9)."""
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu(x, places=0):
    """Round half up to `places` decimal places (PRD §2.6)."""
    x = D(x)
    if places == 0:
        q = Decimal(1)
    else:
        q = Decimal(1).scaleb(-places)  # e.g. places=2 -> 0.01
    return x.quantize(q, rounding=ROUND_HALF_UP)


# ---- tipping_fee constants (SCAFFOLD calc tipping_fee / PRD §3.4) ----
# tiers: list of (lo, hi, cents_per_ton); hi=None means +inf
RATE_TIERS = {
    "MSW": [(D(0), D(5), D(4500)), (D(5), None, D(3800))],
    "CONSTRUCTION_DEBRIS": [(D(0), None, D(5200))],
    "GREEN_WASTE": [(D(0), None, D(2000))],
    "CLEAN_WOOD": [(D(0), None, D(1800))],
    "TIRE": [(D(0), None, D(9000))],
    "ASBESTOS": [(D(0), None, D(15000))],
}
SPECIAL_SURCHARGE_CENTS = {"TIRE": D(5000), "ASBESTOS": D(20000)}
DIVERTED_MATERIALS = {"GREEN_WASTE", "CLEAN_WOOD"}
MINIMUM_FEE_CENTS = D(2500)
HOST_FEE_PCT = D("0.0875")


def weight_fee_cents(material, tons):
    """Marginal tiered weight fee, rounded to whole cents FIRST (PRD §3.4)."""
    tons = D(tons)
    raw = D(0)
    for (lo, hi, rate) in RATE_TIERS[material]:
        if tons > lo:
            top = tons if hi is None else min(tons, hi)
            span = top - lo
            raw += span * rate
    return rhu(raw, 0)


def tipping_fee_cents(material, tons, variant, gas_status):
    """Final/provisional tipping fee in whole cents with pinned rounding order."""
    wf = weight_fee_cents(material, tons)
    gas_mult = D("1.10") if (variant == "final" and gas_status == "ELEVATED") else D("1.00")
    gas_fee = rhu(wf * gas_mult, 0)                       # round AFTER multiplier
    surcharge = SPECIAL_SURCHARGE_CENTS.get(material, D(0))
    rebate = rhu(wf * D("0.12"), 0) if material in DIVERTED_MATERIALS else D(0)
    subtotal = gas_fee + surcharge - rebate
    fee = max(subtotal, MINIMUM_FEE_CENTS)               # nested max LAST
    return int(fee)


def posted_airspace_cy(net_weight_tons, is_diverted):
    """round(net * 1.5, 2) for landfilled material, 0 for diverted (PRD §3.6)."""
    if is_diverted:
        return D(0)
    return rhu(D(net_weight_tons) * D("1.5"), 2)


def invoice_total_cents(line_fees):
    """Per-line host-fee-inclusive charge rounded, THEN summed (PRD §3.9)."""
    total = 0
    for fee in line_fees:
        total += int(rhu(D(fee) * (Decimal(1) + HOST_FEE_PCT), 0))
    return total


def gas_status_for(ppm):
    """Three-way threshold on ppm (PRD §2.9). Inclusive >=."""
    if ppm >= 500:
        return "EXCEEDANCE"
    if ppm >= 200:
        return "ELEVATED"
    return "NORMAL"


def acceptance_posture(gas_status, remaining, total):
    """Strict priority order (PRD §2.9)."""
    remaining = D(remaining)
    total = D(total)
    if gas_status == "EXCEEDANCE":
        return "CLOSED"
    if remaining <= 0:
        return "CLOSED"
    if remaining <= total * D("0.10"):
        return "RESTRICTED"
    return "OPEN"


def diversion_rate(net_weights, diverted_flags):
    """Ratio of diverted tonnage to total tonnage, 4dp round-half-up, 0 if denom 0."""
    total = D(0)
    diverted = D(0)
    for nw, is_div in zip(net_weights, diverted_flags):
        total += D(nw)
        if is_div:
            diverted += D(nw)
    if total <= 0:
        return D(0)
    return rhu(diverted / total, 4)
