"""Enrollment pricing (calc enrollment_pricing, PRD §3.4 single, §3.6 bundle)."""
import math

from services.common import round_half_up_cents


def single_course_gross(list_price_cents, coupon):
    """Return gross_price_cents for a single-course enrollment.

    coupon may be None. PERCENT: discount = round_half_up(base * value/100).
    FLAT: discount = min(value, base). gross = max(base - discount, 0).
    """
    base = list_price_cents
    if coupon is None:
        return base
    if coupon["discount_type"] == "PERCENT":
        discount = round_half_up_cents(base * coupon["discount_value"] / 100)
    else:  # FLAT
        discount = min(coupon["discount_value"], base)
    return max(base - discount, 0)


def instructor_share(gross_cents, revenue_share_pct):
    """round_half_up(gross * revenue_share_pct)."""
    return round_half_up_cents(gross_cents * revenue_share_pct)


def allocate_bundle(bundle_price_cents, members):
    """Largest-remainder allocation of the flat bundle price across member
    courses by list-price weight.

    `members` is the ordered list of member course records (with list_price_cents,
    created_at, _seq). Returns a dict course_id -> allocated gross cents that sums
    EXACTLY to bundle_price_cents.

    raw_i = bundle_price * (list_i / sum_list); floor_i = floor(raw_i);
    remainder = bundle_price - sum(floor_i); distribute one cent at a time to the
    courses with the largest fractional part (raw_i - floor_i), ties broken by
    Course.created_at ASC (we use _seq, monotonic with created_at).
    """
    sum_list = sum(c["list_price_cents"] for c in members)
    allocations = {}
    fractionals = []
    floor_total = 0
    for c in members:
        if sum_list > 0:
            raw = bundle_price_cents * (c["list_price_cents"] / sum_list)
        else:
            raw = 0.0
        fl = math.floor(raw)
        frac = raw - fl
        allocations[c["id"]] = fl
        floor_total += fl
        fractionals.append((c, frac))

    remainder = bundle_price_cents - floor_total
    # Sort by largest fractional part desc; tie-break by created_at ASC (_seq asc).
    fractionals.sort(key=lambda t: (-t[1], t[0].get("_seq", 0)))
    for i in range(remainder):
        c = fractionals[i][0]
        allocations[c["id"]] += 1
    return allocations
