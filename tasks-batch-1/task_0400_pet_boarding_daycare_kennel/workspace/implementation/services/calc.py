"""Calculation rules (scaffold §1.3 / PRD §3).

All money is integer cents; round half up applied exactly once at the points
each formula specifies.
"""
from services.common import round_half_up, D, days_between

# --- deposit_amount constants (PRD §3.5) ---
BASE_BY_SERVICE = {"DAYCARE": 1500, "OVERNIGHT": 4000}
SIZE_MULT = {"TOY": 0.8, "SMALL": 1.0, "MEDIUM": 1.2, "LARGE": 1.5}
POLICY_FACTOR = {"STANDARD": 0.30, "STRICT": 0.50, "NONE": 0.0}

# --- reservation_total constants (PRD §3.8) ---
OVERNIGHT_NIGHTLY = {"TOY": 3500, "SMALL": 4000, "MEDIUM": 5000, "LARGE": 6500}
DAYCARE_DAY = {"TOY": 2500, "SMALL": 3000, "MEDIUM": 3500, "LARGE": 4500}
ADDON_PRICE_BATH = {"TOY": 1500, "SMALL": 2000, "MEDIUM": 2500, "LARGE": 3500}
ADDON_PRICE_PLAYTIME = {"TOY": 1000, "SMALL": 1000, "MEDIUM": 1500, "LARGE": 2000}

# --- group_compatibility_score constants (PRD §3.6) ---
W_SIZE = 2
W_TEMP = 3
SIZE_RANK = {"TOY": 0, "SMALL": 1, "MEDIUM": 2, "LARGE": 3}
STRICT_MAX = 4
LENIENT_MAX = 9


def temp_penalty(a, b):
    """Symmetric temperament pairing penalty."""
    pair = frozenset([a, b])
    if a == "REACTIVE" and b == "REACTIVE":
        return 5
    if pair == frozenset(["REACTIVE", "PLAYFUL"]):
        return 3
    if pair == frozenset(["REACTIVE", "CALM"]):
        return 1
    if a == "PLAYFUL" and b == "PLAYFUL":
        return 1
    if pair == frozenset(["PLAYFUL", "CALM"]):
        return 0
    # CALM x CALM
    return 0


def deposit_amount(service_type, size_class, nights, deposit_policy):
    """Tiered deposit. round_half_up applied once after all multiplications."""
    base = BASE_BY_SERVICE[service_type]
    size_mult = SIZE_MULT[size_class]
    units = max(nights, 1) if service_type == "OVERNIGHT" else 1
    raw = D(base) * D(size_mult) * D(units)
    policy_factor = POLICY_FACTOR[deposit_policy]
    deposit = round_half_up(raw * D(policy_factor))
    return deposit


def cancellation_refund(path, deposit_paid_cents, start_date, current_date):
    """Lead-time threshold tiers.

    path: "NO_SHOW" or "CANCEL".
    lead_days = start_date - current_date.
    """
    if path == "NO_SHOW":
        return 0
    lead_days = days_between(start_date, current_date)
    if lead_days >= 7:
        return deposit_paid_cents
    elif lead_days >= 2:
        return round_half_up(D(deposit_paid_cents) * D(0.50))
    else:
        return 0


def addon_price(kind, size_class):
    if kind == "BATH":
        return ADDON_PRICE_BATH[size_class]
    return ADDON_PRICE_PLAYTIME[size_class]


def reservation_total(service_type, size_class, nights, delivered_addon_prices,
                      redeemed_credit):
    """Final bill, fixed evaluation order (PRD §3.8):
    (1) subtotal -> (2) tier from subtotal -> (3) discount -> (4) total.
    """
    if service_type == "OVERNIGHT":
        lodging = OVERNIGHT_NIGHTLY[size_class] * max(nights, 1)
    else:
        lodging = DAYCARE_DAY[size_class]
    addons_sum = sum(delivered_addon_prices)
    subtotal = lodging + addons_sum
    if subtotal >= 30000:
        tier_rate = 0.10
    elif subtotal >= 15000:
        tier_rate = 0.05
    else:
        tier_rate = 0.0
    discount = round_half_up(D(subtotal) * D(tier_rate))
    package_offset = DAYCARE_DAY[size_class] if redeemed_credit else 0
    total = max(subtotal - discount - package_offset, 0)
    return total


def group_compatibility_score(candidate_size, candidate_temp, existing_pets):
    """Sum of pair scores against each existing pet.

    existing_pets: list of (size_class, temperament), ordered oldest-first.
    """
    group_score = 0
    for e_size, e_temp in existing_pets:
        size_gap = abs(SIZE_RANK[candidate_size] - SIZE_RANK[e_size])
        tp = temp_penalty(candidate_temp, e_temp)
        pair_score = W_SIZE * size_gap + W_TEMP * tp
        group_score += pair_score
    return group_score


def group_ceiling(candidate_temp):
    return STRICT_MAX if candidate_temp == "REACTIVE" else LENIENT_MAX
