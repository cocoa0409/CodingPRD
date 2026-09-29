"""Exact-rational arithmetic. Cents everywhere, basis points, round half up (PRD 2.8)."""

import math
from fractions import Fraction

import store

BPS = Fraction(10000)

MODEL_REFERENCE_GUESTS = 2
MODEL_REFERENCE_NIGHTS = 4

PLACEMENT_POINTS = {
    "FIRST_QUOTE": 25,
    "RATE_DETAILS": 15,
    "CHECKOUT": 8,
    "CONFIRMATION_ONLY": 3,
    "ABSENT": 0,
}

TOTAL_WEIGHT = 40
ITEMIZED_WEIGHT = 25
COVERAGE_BONUS_MAX = 10
NO_TOTAL_PENALTY = 30
NO_ITEMIZATION_PENALTY = 20
CONFIRMED_UNDISCLOSED_PENALTY = 5

FLAG_SCORE_FLOOR = 60
CONFIRMATION_SCORE_FLOOR = 80
POSTURE_NON_COMPLIANT_BELOW = 60
POSTURE_AT_RISK_BELOW = 80

COMMISSION_TIERS = ((19999, 1500), (34999, 1800))
COMMISSION_TOP_BPS = 2100


def rhu(value):
    """Round half up to a whole integer. Exact for Fraction / int inputs."""
    frac = value if isinstance(value, Fraction) else Fraction(value)
    if frac >= 0:
        return int(math.floor(frac + Fraction(1, 2)))
    return int(math.ceil(frac - Fraction(1, 2)))


def bps_of(amount, rate_bps):
    """amount * rate_bps / 10000 as an exact rational."""
    return Fraction(amount) * Fraction(rate_bps) / BPS


# ------------------------------------------------------- fee expansion (3.2)

def per_night_value(fee, room_rate_cents, guests):
    """Unrounded per-night value, or None for a PER_STAY fee (no per-night value)."""
    basis = fee["basis"]
    if basis == "PER_NIGHT":
        return Fraction(fee["amount_cents"])
    if basis == "PER_PERSON_PER_NIGHT":
        return Fraction(fee["amount_cents"]) * guests
    if basis == "PERCENT_OF_ROOM":
        return Fraction(room_rate_cents) * Fraction(fee["percent_bps"]) / BPS
    return None


def stay_value(fee, room_rate_cents, guests, nights):
    """Unrounded whole-stay value."""
    if fee["basis"] == "PER_STAY":
        return Fraction(fee["amount_cents"])
    return per_night_value(fee, room_rate_cents, guests) * nights


def reference_per_night_rounded(fee, room_rate_cents, guests, nights):
    """Per-night rounding order used by the program rollup and the revenue model:
    a PER_STAY fee contributes amount_cents / nights rounded half up."""
    if fee["basis"] == "PER_STAY":
        return rhu(Fraction(fee["amount_cents"], nights))
    return rhu(per_night_value(fee, room_rate_cents, guests))


# ---------------------------------------------- fee program rollups (3.2)

def total_mandatory_fee_cents_per_night(program, prop):
    total = 0
    for fee in store.mandatory_fees_of_program(program["id"]):
        total += reference_per_night_rounded(
            fee, prop["base_room_rate_cents"], MODEL_REFERENCE_GUESTS,
            MODEL_REFERENCE_NIGHTS,
        )
    return total


def fee_has_value_bearing_inclusion(fee):
    for inclusion in store.inclusions_of_fee(fee["id"]):
        if inclusion["included_value_cents"] > 0:
            return True
    return False


def inclusion_coverage(program):
    """(numerator over 10000, float with four fractional digits)."""
    mandatory = store.mandatory_fees_of_program(program["id"])
    if not mandatory:
        return 0, 0.0
    covered = sum(1 for fee in mandatory if fee_has_value_bearing_inclusion(fee))
    numerator = rhu(Fraction(covered, len(mandatory)) * 10000)
    return numerator, numerator / 10000.0


# ------------------------------------------------ disclosure score (3.3)

def disclosure_score(profile):
    program = store.fee_programs.get(profile["fee_program_id"])
    channel = store.channels.get(profile["channel_id"])
    prop = store.properties.get(profile["property_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"]) if prop else None

    score = 0
    if profile["first_quote_shows_total"]:
        score += TOTAL_WEIGHT
    if profile["itemized_at_first_quote"]:
        score += ITEMIZED_WEIGHT
    score += PLACEMENT_POINTS.get(profile["disclosure_placement"], 0)

    coverage_num = program.get("_coverage_num", 0) if program else 0
    bonus = int(math.floor(Fraction(coverage_num, 10000) * 10))
    score += min(COVERAGE_BONUS_MAX, bonus)

    penalty = 0
    if channel is not None and jurisdiction is not None:
        if not channel["supports_total_price_display"] and jurisdiction["first_quote_total_required"]:
            penalty = max(penalty, NO_TOTAL_PENALTY)
        if not channel["supports_itemization"] and jurisdiction["itemization_required_on_folio"]:
            penalty = max(penalty, NO_ITEMIZATION_PENALTY)
    score -= penalty

    score -= CONFIRMED_UNDISCLOSED_PENALTY * profile["confirmed_undisclosed_count"]

    # The clamp is applied exactly once, last (PRD 2.8).
    return max(0, min(100, score))


def posture_for(minimum):
    if minimum is None:
        return "COMPLIANT"
    if minimum < POSTURE_NON_COMPLIANT_BELOW:
        return "NON_COMPLIANT"
    if minimum < POSTURE_AT_RISK_BELOW:
        return "AT_RISK"
    return "COMPLIANT"


# --------------------------------------------------------- tax helpers

def aggregate_tax(portions):
    """portions: list of (amount_cents, rate_bps). One rounding per distinct rate,
    summed in ascending rate order (PRD 3.4 step four)."""
    by_rate = {}
    for amount, rate in portions:
        by_rate[rate] = by_rate.get(rate, 0) + amount
    total = 0
    for rate in sorted(by_rate):
        total += rhu(bps_of(by_rate[rate], rate))
    return total


def rule_rate_bps(rule, jurisdiction):
    if rule is not None and rule.get("tax_rate_bps") is not None:
        return rule["tax_rate_bps"]
    return jurisdiction["occupancy_tax_rate_bps"]


# ---------------------------------------------------- quote arithmetic (3.4)

def quote_figures(prop, jurisdiction, program, room_rate_cents, guests, nights,
                  disclosed_fee_amounts):
    """The pinned five-step quote order. Per-night rounding, then x nights; a single
    rounding per distinct rate over the aggregate taxable base."""
    mandatory = store.mandatory_fees_of_program(program["id"])

    # Step one.
    room_total = room_rate_cents * nights

    # Step two: per-night rounding order.
    per_night_sum = 0
    per_stay_total = 0
    charged = []  # (fee, whole-stay charged cents under the quote variant)
    for fee in mandatory:
        if fee["basis"] == "PER_STAY":
            amount = fee["amount_cents"]
            per_stay_total += amount
            charged.append((fee, amount))
        else:
            rounded = rhu(per_night_value(fee, room_rate_cents, guests))
            per_night_sum += rounded
            charged.append((fee, rounded * nights))
    mandatory_fee_cents = per_night_sum * nights + per_stay_total

    # Step three: assemble the aggregate taxable base.
    portions = [(room_total, jurisdiction["occupancy_tax_rate_bps"])]
    for fee, amount in charged:
        rule = store.taxability_rule(prop["jurisdiction_id"], fee["code"])
        if rule is not None and rule["taxability"] == "EXEMPT":
            continue
        portions.append((amount, rule_rate_bps(rule, jurisdiction)))

    # Step four: one rounding over the aggregate, per distinct rate.
    tax_cents = aggregate_tax(portions)

    # Step five.
    total_cents = room_total + mandatory_fee_cents + tax_cents

    # The disclosure gap, over the same per-night-rounded whole-stay amounts.
    gap = 0
    disclosed = disclosed_fee_amounts or {}
    for fee, amount in charged:
        shown = disclosed.get(fee["code"], 0)
        difference = amount - shown
        if difference > 0:
            gap += difference

    return {
        "quoted_room_total_cents": room_total,
        "quoted_mandatory_fee_cents": mandatory_fee_cents,
        "quoted_tax_cents": tax_cents,
        "quoted_total_cents": total_cents,
        "quote_disclosure_gap_cents": gap,
    }


# ---------------------------------------------------- folio arithmetic (3.5)

def folio_line_amount(fee, room_rate_cents, guests, nights):
    """Stay-aggregation variant: unrounded whole stay, rounded half up once."""
    return rhu(stay_value(fee, room_rate_cents, guests, nights))


def line_taxability(rule):
    """(determination, taxed) for a charge line written at itemisation."""
    if rule is None or rule["taxability"] == "EXEMPT":
        return "EXEMPT", False
    if rule["taxability"] == "TAXABLE":
        return "TAXABLE", True
    return "TAXABLE_IF_MANDATORY_APPLIED", True


# ------------------------------------------------- revenue modelling (3.9)

def commission_bps(adr_cents):
    for threshold, bps in COMMISSION_TIERS:
        if adr_cents <= threshold:
            return bps
    return COMMISSION_TOP_BPS


def _split_fees(fees, prop, adr_cents, jurisdiction):
    """Rounded per-night amounts split into the taxable and the exempt bucket."""
    taxable = 0
    exempt = 0
    for fee in fees:
        amount = reference_per_night_rounded(
            fee, adr_cents, MODEL_REFERENCE_GUESTS, MODEL_REFERENCE_NIGHTS)
        rule = store.taxability_rule(prop["jurisdiction_id"], fee["code"])
        if rule is not None and rule["taxability"] == "EXEMPT":
            exempt += amount
        else:
            taxable += amount
    return taxable, exempt


def revenue_figures(prop, jurisdiction, program, scenario, variant, roll_in_codes):
    mandatory = store.mandatory_fees_of_program(program["id"])
    jur_rate = jurisdiction["occupancy_tax_rate_bps"]

    # --- baseline (always computed, identical under both variants) ---
    baseline_adr = prop["base_room_rate_cents"]
    baseline_bps = commission_bps(baseline_adr)
    baseline_commission = rhu(bps_of(baseline_adr, baseline_bps))
    base_taxable, base_exempt = _split_fees(mandatory, prop, baseline_adr, jurisdiction)
    baseline_tax = rhu(bps_of(baseline_adr + base_taxable, jur_rate))
    baseline_guest_total = baseline_adr + base_taxable + base_exempt + baseline_tax
    baseline_net = baseline_adr + base_taxable + base_exempt - baseline_commission

    # --- modelled side, in its pinned six-step order ---
    rolled = 0
    for fee in mandatory:
        if fee["code"] in roll_in_codes:
            rolled += reference_per_night_rounded(
                fee, baseline_adr, MODEL_REFERENCE_GUESTS, MODEL_REFERENCE_NIGHTS)

    if variant == "TAX_ABSORBED":
        modeled_adr = rhu(Fraction(baseline_adr + rolled) * BPS / (BPS + Fraction(jur_rate)))
    else:
        modeled_adr = baseline_adr + rolled

    applied_bps = commission_bps(modeled_adr)
    modeled_commission = rhu(bps_of(modeled_adr, applied_bps))

    surviving = [f for f in mandatory if f["code"] not in roll_in_codes]
    surv_taxable, surv_exempt = _split_fees(surviving, prop, modeled_adr, jurisdiction)
    modeled_tax = rhu(bps_of(modeled_adr + surv_taxable, jur_rate))
    modeled_guest_total = modeled_adr + surv_taxable + surv_exempt + modeled_tax
    modeled_net = modeled_adr + surv_taxable + surv_exempt - modeled_commission

    return {
        "baseline_adr_cents": baseline_adr,
        "baseline_commission_cents": baseline_commission,
        "baseline_tax_cents": baseline_tax,
        "baseline_guest_total_cents": baseline_guest_total,
        "baseline_net_revenue_cents": baseline_net,
        "modeled_adr_cents": modeled_adr,
        "applied_commission_bps": applied_bps,
        "modeled_commission_cents": modeled_commission,
        "modeled_tax_cents": modeled_tax,
        "modeled_guest_total_cents": modeled_guest_total,
        "modeled_net_revenue_cents": modeled_net,
        "modeled_adr_delta_cents": modeled_adr - baseline_adr,
        "modeled_commission_delta_cents": modeled_commission - baseline_commission,
        "modeled_tax_delta_cents": modeled_tax - baseline_tax,
        "modeled_guest_total_delta_cents": modeled_guest_total - baseline_guest_total,
        "modeled_net_revenue_delta_cents": modeled_net - baseline_net,
    }
