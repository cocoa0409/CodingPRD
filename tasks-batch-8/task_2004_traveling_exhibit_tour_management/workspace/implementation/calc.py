"""Calculation rules — SCAFFOLD Table 3 / PRD §3. All money is integer cents;
every percentage application rounds half-up at exactly the pinned step.
Decimal is used throughout, never float.
"""

from decimal import Decimal, ROUND_HALF_UP

import db

# participation_fee constants
TIER1_MAX = 10000
TIER2_MAX = 50000
TIER2_PCT = Decimal("0.10")
TIER3_PCT = Decimal("0.25")
CANCEL_PENALTY_PCT = Decimal("0.30")

# condition_score constants
W_SURFACE = Decimal("0.4")
W_STRUCTURAL = Decimal("0.6")
SEAL_BREACH_CAP = 40
DAMAGE_THRESHOLD = 70

# damage_claim_payout constants
LINE_COVERAGE_PCT = Decimal("0.80")
CLAIM_CAP_PCT = Decimal("0.90")

# marketing_kit_cost constants
BASE_CENTS = 150000
PER_LANG_CENTS = 45000
BULK_LANG_MIN = 3
BULK_DISCOUNT_PCT = Decimal("0.15")
PER_LOGO_CENTS = 20000

# supervision: venue not climate_controlled OR crate_count exceeds this
# ceiling. The scaffold names CLIMATE_EXEMPT_CRATE_MAX but defines no value
# (noted scaffold gap; PRD renders it only as "the climate-exempt crate
# ceiling"). Any value >= 3 satisfies every documented scenario.
CLIMATE_EXEMPT_CRATE_MAX = 10


def rhu(value):
    """Round half-up to whole units (cents / score points)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def participation_fee(base_fee_cents, sponsorship_credit_cents, venue_cap_cents,
                      attendance):
    """Tiered uplift, then credit capped by min(credit, cap, fee), then subtract.
    Evaluation order is pinned by the PRD."""
    if attendance <= TIER1_MAX:
        uplift = 0
    elif attendance <= TIER2_MAX:
        uplift = rhu(Decimal(base_fee_cents) * TIER2_PCT)
    else:
        uplift = rhu(Decimal(base_fee_cents) * TIER3_PCT)
    fee_before_credit = base_fee_cents + uplift
    credit = min(sponsorship_credit_cents, venue_cap_cents, fee_before_credit)
    return fee_before_credit - credit


def cancel_penalty_fee(provisional_fee_cents):
    """FINAL_CANCEL variant: 30% of the provisional fee, rounded half-up."""
    return rhu(Decimal(provisional_fee_cents) * CANCEL_PENALTY_PCT)


def condition_composite(surface_score, structural_score, seal_intact):
    weighted = rhu(Decimal(surface_score) * W_SURFACE
                   + Decimal(structural_score) * W_STRUCTURAL)
    if not seal_intact:
        return min(SEAL_BREACH_CAP, weighted)
    return weighted


def damage_payout(line_items, claimed_amount_cents):
    """Round each line first, then sum, then cap — order pinned."""
    subtotal = sum(rhu(Decimal(li["amount_cents"]) * LINE_COVERAGE_PCT)
                   for li in line_items)
    cap = rhu(Decimal(claimed_amount_cents) * CLAIM_CAP_PCT)
    return min(subtotal, cap)


def marketing_kit_cost(language_count, sponsor_logo_slots):
    lang_cost = language_count * PER_LANG_CENTS
    if language_count > BULK_LANG_MIN:
        lang_cost = rhu(Decimal(lang_cost) * (Decimal("1") - BULK_DISCOUNT_PCT))
    return BASE_CENTS + lang_cost + sponsor_logo_slots * PER_LOGO_CENTS


def supervision_required(venue, tour):
    return (not venue["climate_controlled"]) or \
           (tour["crate_count"] > CLIMATE_EXEMPT_CRATE_MAX)


def cert_covers_leg(cert, tour, leg):
    """Four-clause coverage rule (PRD §3.5). `leg` is a shipment dict or None;
    with no leg the window clauses cannot be evaluated and are skipped."""
    if cert["status"] not in ("ISSUED", "ACTIVE"):
        return False
    if cert["coverage_cents"] < tour["declared_value_cents"]:
        return False
    if leg is not None:
        eff_from = db.parse_dt(cert["effective_from"])
        eff_to = db.parse_dt(cert["effective_to"])
        depart = db.parse_dt(leg["depart_at"])
        arrive = db.parse_dt(leg["arrive_at"])
        if not (eff_from <= depart):
            return False
        if not (eff_to > arrive):  # end-exclusive window
            return False
    return True


def assign_route_seqs(tour_id):
    """seq = position in (install_start ASC, created_at ASC) order over ALL
    stops of the tour regardless of status. Recomputed on every booking so
    out-of-order bookings renumber earlier stops (per route_sequence rule)."""
    tour_stops = [s for s in db.stops.values() if s["tour_id"] == tour_id]
    tour_stops.sort(key=lambda s: (db.parse_dt(s["install_start"]),
                                   s["created_at"]))
    for i, stop in enumerate(tour_stops, 1):
        if stop["seq"] != i:
            stop["seq"] = i
            db.touch(stop)
