"""Calculation rules (SCAFFOLD §1.3 / PRD §3.5-§3.7).

All money is integer cents. Divisions floor on the per-item computation, never on
a pre-aggregated total (PRD §2.5).
"""
import db


# ---------------------------------------------------------------------------
# resignation_refund (PRD §3.3)
#   gross_refund = floor(refundable_equity_cents * resignation_refund_pct / 100)
#   refund_owed  = max(0, gross_refund - outstanding_charge_balance)
# ---------------------------------------------------------------------------
def resignation_refund(refundable_equity_cents, resignation_refund_pct, charge_balance_cents):
    # floor toward zero on the percentage multiply (non-negative inputs -> // is floor)
    gross_refund = (refundable_equity_cents * resignation_refund_pct) // 100
    refund_owed = gross_refund - charge_balance_cents
    if refund_owed < 0:
        refund_owed = 0
    return refund_owed


# ---------------------------------------------------------------------------
# fb_shortfall (PRD §3.7)
#   effective_minimum = max(0, fb_minimum_cents - fb_credit_carried_cents)
#   fb_spend = sum(DINING chits in period, status in {POSTED, SETTLED})
#   shortfall = max(0, effective_minimum - fb_spend)
#   surplus   = max(0, fb_spend - effective_minimum)   (FORWARD_CARRYOVER only)
# ---------------------------------------------------------------------------
def fb_spend_for_period(membership_id, period):
    total = 0
    for c in db.chits.values():
        if (
            c["membership_id"] == membership_id
            and c.get("counts_toward_fb")
            and c["period_index"] == period
            and c["status"] in ("POSTED", "SETTLED")
        ):
            total += c["amount_cents"]
    return total


def fb_shortfall(fb_minimum_cents, fb_credit_carried_cents, fb_spend_cents):
    effective_minimum = fb_minimum_cents - fb_credit_carried_cents
    if effective_minimum < 0:
        effective_minimum = 0
    shortfall = effective_minimum - fb_spend_cents
    if shortfall < 0:
        shortfall = 0
    return effective_minimum, shortfall


def fb_surplus(effective_minimum, fb_spend_cents, fb_minimum_cents):
    """Surplus written to NEXT period's fb_credit_carried_cents (capped at one
    fb_minimum_cents). FORWARD_CARRYOVER variant only (PRD §3.7)."""
    surplus = fb_spend_cents - effective_minimum
    if surplus < 0:
        surplus = 0
    if surplus > fb_minimum_cents:
        surplus = fb_minimum_cents
    return surplus


# ---------------------------------------------------------------------------
# statement_total (PRD §3.7)
#   total_due = dues + fb_shortfall + chit_charges + assessment
#   chit_charges = sum(POSTED chits in period, all kinds)
#   assessment   = sum(AssessmentCharge for this member in period)
# ---------------------------------------------------------------------------
def chit_charges_for_period(membership_id, period):
    total = 0
    for c in db.chits.values():
        if (
            c["membership_id"] == membership_id
            and c["period_index"] == period
            and c["status"] == "POSTED"
        ):
            total += c["amount_cents"]
    return total


def assessment_charges_for_period(membership_id, period):
    total = 0
    for ac in db.assessment_charges.values():
        if ac["membership_id"] != membership_id:
            continue
        assessment = db.assessments.get(ac["assessment_id"])
        if assessment and assessment.get("levied_period_index") == period:
            total += ac["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# assessment_allocation (PRD §3.5)
#   EQUAL: base = floor(target / n); rem distributed +1 each to first `rem`
#          members in created_at ASC order.
#   DUES_WEIGHTED: raw = target * weight / sum(weights); base = floor(raw);
#          rem distributed +1 each to members with largest fractional part,
#          ties broken by created_at ASC.
#   Floor each share THEN distribute remainder. sum-then-round forbidden.
# ---------------------------------------------------------------------------
def allocate_equal(total_target_cents, eligible):
    """eligible: list of membership records already sorted created_at ASC.
    Returns dict membership_id -> share."""
    n = len(eligible)
    base = total_target_cents // n
    rem = total_target_cents - base * n
    shares = {}
    for idx, m in enumerate(eligible):
        share = base + (1 if idx < rem else 0)
        shares[m["id"]] = share
    return shares


def allocate_dues_weighted(total_target_cents, eligible):
    """eligible: list of membership records sorted created_at ASC.
    weight = category.monthly_dues_cents."""
    weights = []
    for m in eligible:
        cat = db.categories.get(m["category_id"])
        w = cat["monthly_dues_cents"] if cat else 0
        weights.append(w)
    total_weight = sum(weights)

    shares = {}
    fractional = []  # (frac_numerator, index) — larger numerator = larger fraction
    base_sum = 0
    for idx, m in enumerate(eligible):
        if total_weight > 0:
            numer = total_target_cents * weights[idx]
            base = numer // total_weight
            frac = numer - base * total_weight  # fractional part numerator (0..total_weight)
        else:
            # No weights at all: degenerate — split as evenly as EQUAL would.
            base = total_target_cents // len(eligible)
            frac = 0
        shares[m["id"]] = base
        base_sum += base
        fractional.append((frac, idx, m["id"]))

    rem = total_target_cents - base_sum
    # Distribute leftover one cent each to members with the largest fractional
    # remainder, ties broken by created_at ASC (eligible is already created_at ASC,
    # so index ascending breaks ties).
    fractional.sort(key=lambda t: (-t[0], t[1]))
    for i in range(rem):
        _, _, mid = fractional[i]
        shares[mid] += 1
    return shares
