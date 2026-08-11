"""Pure calculations: storage days, weights, pricing, matching, waterfalls."""

from decimal import Decimal

import store
from util import (
    BATCH_CUTOFF_HOUR_UTC, CLOCK, CONSOLIDATION_DISCOUNT_PCT, CONSOLIDATION_MIN_ITEMS,
    FORWARD_BRACKET_1_CENTS, FORWARD_BRACKET_1_MAX_LB, FORWARD_BRACKET_2_CENTS,
    FORWARD_BRACKET_2_MAX_LB, FORWARD_BRACKET_3_CENTS, FORWARD_BRACKET_3_MAX_LB,
    FORWARD_BRACKET_4_CENTS, LOYALTY_TIER_1_MIN_CENTS, LOYALTY_TIER_1_PCT,
    LOYALTY_TIER_2_MIN_CENTS, LOYALTY_TIER_2_PCT, SERVICE_MULTIPLIER, ceil_int, dec,
    normalize_name, num_out, round_half_up, whole_days_between,
)


# ------------------------------------------------------------------ storage days
def custody_end(item):
    if item["storage_status"] in ("RELEASED", "DESTROYED") and item.get("released_at"):
        return item["released_at"]
    return CLOCK.now


def total_custody_days(item):
    return whole_days_between(item["received_at"], custody_end(item))


def storage_counters(item):
    """
    PRD 3.12.  free + billable == total custody days, always (invariant
    storage_day_time_partition).  SOP pieces are unconditionally exempt.
    """
    total = total_custody_days(item)
    if item["item_class"] == "SOP":
        return total, 0
    b = store.box(item["box_id"])
    tier = store.tier_of_box(b) if b else None
    included = tier["included_storage_days"] if tier else 0
    free = min(total, included)
    return free, total - free


# ------------------------------------------------------------------ package acceptance
def dimensional_weight(item, rule):
    product = dec(item["length_in"]) * dec(item["width_in"]) * dec(item["height_in"])
    return ceil_int(product / dec(rule["dim_divisor"]))


def billable_weight(item, rule):
    dim = dimensional_weight(item, rule)
    actual = dec(item["actual_weight_lb"])
    value = actual if actual >= dec(dim) else dec(dim)
    return num_out(value)


def is_oversize(item, rule):
    girth = 2 * (dec(item["width_in"]) + dec(item["height_in"]))
    lpg = dec(item["length_in"]) + girth
    return (lpg > dec(rule["max_length_plus_girth_in"])
            or dec(item["actual_weight_lb"]) > dec(rule["max_actual_weight_lb"]))


def acceptance_fee(item, rule, billable_lb):
    if item["item_class"] == "SOP":
        return 0
    return round_half_up(dec(rule["acceptance_fee_cents"])
                         + dec(billable_lb) * dec(rule["base_rate_cents_per_lb"]))


# ------------------------------------------------------------------ forwarding
def weight_bracket_cents(billable_lb):
    w = dec(billable_lb)
    if w <= FORWARD_BRACKET_1_MAX_LB:
        return FORWARD_BRACKET_1_CENTS
    if w <= FORWARD_BRACKET_2_MAX_LB:
        return FORWARD_BRACKET_2_CENTS
    if w <= FORWARD_BRACKET_3_MAX_LB:
        return FORWARD_BRACKET_3_CENTS
    return FORWARD_BRACKET_4_CENTS


def forward_pricing(items, service_level):
    """
    PRD 2.6 pinned order: each piece is priced, rounded to a whole cent, and
    only THEN added into base_price_cents.  Summing unrounded products and
    rounding once is a different (incorrect) integer.
    """
    multiplier = SERVICE_MULTIPLIER[service_level]
    base = 0
    weight = Decimal("0")
    for it in sorted(items, key=lambda r: (r["created_at"], r["id"])):
        base += round_half_up(dec(weight_bracket_cents(it["billable_weight_lb"])) * multiplier)
        weight += dec(it["billable_weight_lb"])
    if len(items) >= CONSOLIDATION_MIN_ITEMS:
        discount = round_half_up(dec(base) * CONSOLIDATION_DISCOUNT_PCT)
    else:
        discount = 0
    return base, discount, base - discount, num_out(weight)


# ------------------------------------------------------------------ payee matching
def payee_match(box_id, payee_name):
    """PRD 3.9; the alias set is never consulted when the exact set is non-empty."""
    target = normalize_name(payee_name)
    candidates = [r for r in store.recipients_of_box(box_id)
                  if r["roster_status"] in ("PENDING", "AUTHORIZED", "SUSPENDED")]
    exact = [r for r in candidates if normalize_name(r["legal_name"]) == target]
    if exact:
        return exact[0], "EXACT_LEGAL"
    alias = [r for r in candidates
             if any(normalize_name(a) == target for a in (r.get("dba_aliases") or []))]
    if alias:
        return alias[0], "ALIAS"
    return None, "NONE"


def cutoff_passed():
    return CLOCK.hour() >= BATCH_CUTOFF_HOUR_UTC


# ------------------------------------------------------------------ billing
def loyalty_discount(subtotal_cents):
    if subtotal_cents >= LOYALTY_TIER_2_MIN_CENTS:
        pct = LOYALTY_TIER_2_PCT
    elif subtotal_cents >= LOYALTY_TIER_1_MIN_CENTS:
        pct = LOYALTY_TIER_1_PCT
    else:
        return 0
    return round_half_up(dec(subtotal_cents) * pct)


def outstanding_overage(box_id):
    total = 0
    for c in store.cycles_of_box(box_id):
        if c["status"] != "OPEN":
            continue
        for e in store.entries_of_cycle(c["id"]):
            if e["tranche"] == "OVERAGE":
                total += e["amount_cents"]
    return total
