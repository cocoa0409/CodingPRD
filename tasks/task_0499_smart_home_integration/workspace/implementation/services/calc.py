"""Calculation rules (scaffold §1.3, PRD §3.2/§3.4/§3.9).

All monetary amounts are integer cents; round-half-up at each rounding step.
"""
from decimal import Decimal, ROUND_HALF_UP

# --- proposal_total constants (scaffold §1.3 / PRD §3.2) ---
VOLUME_T1_CENTS = 500000
VOLUME_T2_CENTS = 2000000
VOLUME_T1_RATE = Decimal("0.05")
VOLUME_T2_RATE = Decimal("0.10")
LOYALTY_COMMERCIAL_RATE = Decimal("0.02")
DISCOUNT_CAP_RATE = Decimal("0.12")
RESIDENTIAL_TAX_RATE = Decimal("0.0825")
COMMERCIAL_TAX_RATE = Decimal("0.00")

LABOR_RATE_CENTS = {
    "RESIDENTIAL": {"NORTH": 12000, "SOUTH": 10000, "EAST": 13000, "WEST": 11000},
    "COMMERCIAL": {"NORTH": 15000, "SOUTH": 13000, "EAST": 16000, "WEST": 14000},
}


def round_half_up(value):
    """Round a Decimal to whole cents using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def proposal_total(line_items, billing_tier, region_code, labor_hours_estimate):
    """Pinned-order proposal pricing (PRD §3.2).

    Returns dict with equipment_subtotal_cents, discount_cents, labor_cost_cents,
    tax_cents, grand_total_cents.
    """
    # 1) equipment subtotal: sum over non-removed line items of qty * unit price
    subtotal = 0
    for li in line_items:
        if not li.get("removed"):
            subtotal += li["qty"] * li["unit_price_cents"]

    # 2) discount rate: volume tier on subtotal + loyalty (commercial) capped at 0.12
    if subtotal < VOLUME_T1_CENTS:
        volume_rate = Decimal("0.00")
    elif subtotal < VOLUME_T2_CENTS:
        volume_rate = VOLUME_T1_RATE
    else:
        volume_rate = VOLUME_T2_RATE
    discount_rate = volume_rate
    if billing_tier == "COMMERCIAL":
        discount_rate += LOYALTY_COMMERCIAL_RATE
    if discount_rate > DISCOUNT_CAP_RATE:
        discount_rate = DISCOUNT_CAP_RATE
    discount_cents = round_half_up(Decimal(subtotal) * discount_rate)

    # 3) labor cost: hours * region/tier labor rate
    labor_rate = LABOR_RATE_CENTS[billing_tier][region_code]
    labor_cost_cents = round_half_up(Decimal(str(labor_hours_estimate)) * Decimal(labor_rate))

    # 4) tax on (subtotal - discount); labor not taxed
    taxable_base = subtotal - discount_cents
    tax_rate = COMMERCIAL_TAX_RATE if billing_tier == "COMMERCIAL" else RESIDENTIAL_TAX_RATE
    tax_cents = round_half_up(Decimal(taxable_base) * tax_rate)

    # 5) grand total = (subtotal - discount) + labor + tax
    grand_total_cents = (subtotal - discount_cents) + labor_cost_cents + tax_cents

    return {
        "equipment_subtotal_cents": subtotal,
        "discount_cents": discount_cents,
        "labor_cost_cents": labor_cost_cents,
        "tax_cents": tax_cents,
        "grand_total_cents": grand_total_cents,
    }


def contract_balance(prepaid_hours, consumed_hours, hourly_rate_cents):
    """PRD §3.9: remaining = prepaid - consumed; <=0 -> 0; else round-half-up
    (remaining * rate), floored at 0."""
    remaining = Decimal(str(prepaid_hours)) - Decimal(str(consumed_hours))
    if remaining <= 0:
        return 0
    return round_half_up(remaining * Decimal(hourly_rate_cents))


def labor_cost_only(labor_hours_estimate, billing_tier, region_code):
    labor_rate = LABOR_RATE_CENTS[billing_tier][region_code]
    return round_half_up(Decimal(str(labor_hours_estimate)) * Decimal(labor_rate))


# --- IP / subnet helpers (scaffold §1.3 ip_pool_size, mgmt_ip_allocation) ---
def _parse_cidr(cidr):
    """Return (network_int, prefix)."""
    addr, prefix_s = cidr.split("/")
    prefix = int(prefix_s)
    parts = [int(p) for p in addr.split(".")]
    base = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    # Network address = base masked to prefix.
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix > 0 else 0
    network = base & mask
    return network, prefix


def ip_pool_size(cidr):
    """(2^(32-prefix)) - 2 (exclude network + broadcast)."""
    _, prefix = _parse_cidr(cidr)
    size = (2 ** (32 - prefix)) - 2
    return max(0, size)


def _int_to_ip(n):
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def allocate_mgmt_ip(cidr, taken_ips):
    """Lowest free host address in subnet, ascending; skip taken; None if none."""
    network, prefix = _parse_cidr(cidr)
    pool = ip_pool_size(cidr)
    taken = set(taken_ips)
    for offset in range(1, pool + 1):  # offset 0 is the network address
        candidate = _int_to_ip(network + offset)
        if candidate not in taken:
            return candidate
    return None


# --- semver comparison (PRD §3.10 firmware) ---
def _semver_tuple(v):
    return tuple(int(x) for x in v.split("."))


def semver_gt(target, current):
    """True iff target strictly greater than current by semver, or current is None."""
    if current is None:
        return True
    return _semver_tuple(target) > _semver_tuple(current)
