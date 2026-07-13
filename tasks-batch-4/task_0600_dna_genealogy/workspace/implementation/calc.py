"""Calculation rules (PRD §2.8, §3.1, §3.2, §3.5, §3.7, §3.8)."""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- constants -------------------------------------------------------------
TIER_FEE_CENTS = {"FREE": 0, "PLUS": 1999, "PRO": 7999}
TIER_TREE_PERSON_LIMIT = {"FREE": 3, "PLUS": 250, "PRO": 999999}
TIER_HEALTH_REPORTS = ("PLUS", "PRO")

BILLING_PERIOD_DAYS = 30
GRACE_PERIOD_DAYS = 14
REPORT_UNLOCK_FEE_CENTS = 300
PROCESSING_FEE_PCT = Decimal("0.029")
PROCESSING_FEE_MIN_CENTS = 30

KIT_PRICE_CENTS = 9900
MIN_DNA_YIELD_NG = 200.0
MAX_EXTRACTION_ATTEMPTS = 3
MIN_CALL_RATE = 0.98

CONSENT_COOLING_OFF_HOURS = 24
PURGE_GRACE_DAYS = 7

MINOR_POPULATION_FLOOR_PCT = Decimal("1.00")
HEALTH_TRAIT_MARKER_CEILING = 12

CM_PER_MARKER = Decimal("4.00")
MATCH_MIN_CM = Decimal("8.00")
MAX_CM_FOR_FULL_CONFIDENCE = Decimal("400.00")
W_CM = Decimal("0.70")
W_SEG = Decimal("0.30")
CHIP_MISMATCH_PENALTY = Decimal("0.05")
EXPECTED_SEGMENTS = {"PARENT_CHILD": 40, "SIBLING": 30, "CLOSE_COUSIN": 12, "DISTANT_COUSIN": 4}
RELATIONSHIP_LADDER = (
    ("PARENT_CHILD", Decimal("240.00")),
    ("SIBLING", Decimal("120.00")),
    ("CLOSE_COUSIN", Decimal("40.00")),
    ("DISTANT_COUSIN", Decimal("8.00")),
)


# ---- rounding helpers ------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div_seconds_to_days(delta_seconds):
    return math.floor(delta_seconds / 86400)


# ---- tier change charge (PRD §3.2) -----------------------------------------
def tier_change_charge(old_tier, new_tier, current_period_end, clock_now):
    """Returns (is_upgrade, charge_total_cents)."""
    old_fee = TIER_FEE_CENTS[old_tier]
    new_fee = TIER_FEE_CENTS[new_tier]
    if new_fee <= old_fee:
        return False, 0  # downgrade (same tier counts as a downgrade): free, deferred

    base_delta_cents = new_fee - old_fee
    remaining_days = floor_div_seconds_to_days((current_period_end - clock_now).total_seconds())
    prorated_cents = math.floor(
        (dec(base_delta_cents) * dec(remaining_days)) / dec(BILLING_PERIOD_DAYS)
    )

    # The loyalty rate is selected ONCE, from the prorated subtotal.
    if prorated_cents >= 5000:
        discount_pct = Decimal("0.10")
    elif prorated_cents >= 2000:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0.00")

    discount_cents = round_half_up_cents(dec(prorated_cents) * discount_pct)
    discounted_cents = prorated_cents - discount_cents

    processing_fee_cents = max(
        PROCESSING_FEE_MIN_CENTS,
        round_half_up_cents(dec(discounted_cents) * PROCESSING_FEE_PCT),
    )
    charge_total_cents = discounted_cents + processing_fee_cents
    return True, charge_total_cents


# ---- cancellation refund (PRD §3.1) ----------------------------------------
def subscription_close_refund(tier, current_period_end, clock_now, published_report_count):
    unused_days = floor_div_seconds_to_days((current_period_end - clock_now).total_seconds())
    if unused_days < 0:
        unused_days = 0
    base_refund_cents = round_half_up_cents(
        (dec(TIER_FEE_CENTS[tier]) * dec(unused_days)) / dec(BILLING_PERIOD_DAYS)
    )
    if published_report_count == 0:
        return base_refund_cents  # CLEAN_PERIOD
    return max(0, base_refund_cents - REPORT_UNLOCK_FEE_CENTS * published_report_count)


# ---- ethnicity composition (PRD §3.7) --------------------------------------
def _compose(entries):
    """Steps 1-3 over the in-scope entries. Returns (shares_by_pop, residual_population)."""
    in_scope = list(entries)
    if not in_scope:
        return {}, None

    raw_total = sum(int(e["raw_score"]) for e in in_scope)
    shares = {}
    for e in sorted(in_scope, key=lambda x: str(x["population"])):
        if raw_total == 0:
            shares[e["population"]] = Decimal("0.00")
        else:
            shares[e["population"]] = round_half_up(
                (dec(int(e["raw_score"])) / dec(raw_total)) * dec(100), 2
            )

    residual = round_half_up(Decimal("100.00") - sum(shares.values()), 2)
    residual_population = None
    if residual != Decimal("0.00"):
        winner = sorted(in_scope, key=lambda x: (-int(x["raw_score"]), str(x["population"])))[0]
        pop = winner["population"]
        shares[pop] = round_half_up(shares[pop] + residual, 2)
        residual_population = pop
    return shares, residual_population


def ethnicity_composition(population_scores, variant):
    """Returns (composition_list, residual_population)."""
    entries = list(population_scores or [])
    in_scope = entries
    if variant == "FINAL":
        provisional_shares, _ = _compose(entries)
        in_scope = [
            e
            for e in entries
            if provisional_shares.get(e["population"], Decimal("0.00")) >= MINOR_POPULATION_FLOOR_PCT
        ]

    shares, residual_population = _compose(in_scope)
    composition = [
        {"population": pop, "share_pct": float(shares[pop])} for pop in sorted(shares.keys())
    ]
    return composition, residual_population


# ---- health traits (PRD §3.7) ----------------------------------------------
def health_trait_count(genotype_markers):
    return sum(1 for m in (genotype_markers or []) if int(m) <= HEALTH_TRAIT_MARKER_CEILING)


# ---- shared segment scan (PRD §3.8) ----------------------------------------
def shared_segment_scan(markers_a, markers_b):
    shared = sorted(set(int(m) for m in (markers_a or [])) & set(int(m) for m in (markers_b or [])))
    shared_cm = round_half_up(CM_PER_MARKER * dec(len(shared)), 2)

    segment_count = 0
    previous = None
    for m in shared:
        if previous is None or m != previous + 1:
            segment_count += 1
        previous = m
    return shared_cm, segment_count


def predicted_relationship(shared_cm):
    for name, threshold in RELATIONSHIP_LADDER:
        if shared_cm >= threshold:
            return name
    return None


def relative_match_confidence(shared_cm, segment_count, relationship, chip_mismatch):
    cm_factor = min(Decimal("1.0"), dec(shared_cm) / MAX_CM_FOR_FULL_CONFIDENCE)
    segment_factor = min(
        Decimal("1.0"), dec(segment_count) / dec(EXPECTED_SEGMENTS[relationship])
    )
    chip_penalty = CHIP_MISMATCH_PENALTY if chip_mismatch else Decimal("0.0")
    raw = W_CM * cm_factor + W_SEG * segment_factor - chip_penalty
    if raw < 0:
        raw = Decimal("0.0")
    return round_half_up(raw, 4)


# ---- batch pass rate (PRD §3.5) --------------------------------------------
def lab_batch_pass_rate(call_rates):
    total = len(call_rates)
    passed = sum(1 for c in call_rates if float(c) >= MIN_CALL_RATE)
    return float(round_half_up(dec(passed) / dec(total), 4))
