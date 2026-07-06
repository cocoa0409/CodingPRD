"""Calculation rules (PRD 3.9 media value, 3.10 ROI, 3.11 billing).

All monetary amounts are integer cents; rounding is round-half-up. ROI rounds to
four decimal places round-half-up. Real intermediate arithmetic uses Decimal to
avoid float drift, then rounds at the points the PRD specifies.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# --- media_value constants (PRD 3.9 / scaffold) -----------------------------
OUTLET_TIER_UNITS = {"NATIONAL": 500000, "REGIONAL": 200000, "TRADE": 80000, "BLOG": 20000}
SENTIMENT_WEIGHT = {"POSITIVE": "1.0", "NEUTRAL": "0.5", "NEGATIVE": "0.25"}
PROMINENCE_WEIGHT = {"FEATURE": "1.0", "MENTION": "0.6", "PASSING": "0.3"}
ACCOUNT_TIER_MULT = {"STANDARD": "1.0", "PREMIUM": "1.25", "ENTERPRISE": "1.5"}
REACH_CAP = Decimal("3.0")

# --- campaign_roi constants -------------------------------------------------
ROI_FLOOR_CENTS = 100000


def _round_cents(real):
    return int(real.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def media_value_raw(outlet, coverage_rec, client):
    """Compute the shared raw media value as a Decimal (PRD 3.9).

    raw = base_units
          * min(reach_factor, REACH_CAP)
          * authority_factor
          * sentiment_w
          * prominence_w
          * tier_mult
    The factors are multiplied in this order.
    """
    base_units = Decimal(OUTLET_TIER_UNITS[outlet["tier"]])
    reach_factor = Decimal(1) + (Decimal(outlet["monthly_unique_visitors"]) / Decimal(1_000_000))
    reach_factor = min(reach_factor, REACH_CAP)
    authority_factor = Decimal(1) + (Decimal(outlet["domain_authority"]) / Decimal(100))
    sentiment_w = Decimal(SENTIMENT_WEIGHT[coverage_rec["sentiment"]])
    prominence_w = Decimal(PROMINENCE_WEIGHT[coverage_rec["prominence"]])
    tier_mult = Decimal(ACCOUNT_TIER_MULT[client["account_tier"]])

    raw = (base_units
           * reach_factor
           * authority_factor
           * sentiment_w
           * prominence_w
           * tier_mult)
    return raw


def media_value_estimated(outlet, coverage_rec, client):
    """Estimated variant: 0.8 provisional haircut, then round-half-up (PRD 3.9)."""
    raw = media_value_raw(outlet, coverage_rec, client)
    return _round_cents(raw * Decimal("0.8"))


def media_value_verified(outlet, coverage_rec, client):
    """Verified variant: full raw, round-half-up (PRD 3.9)."""
    raw = media_value_raw(outlet, coverage_rec, client)
    return _round_cents(raw)


# ----------------------------------------------------------------------------
# retainer_billing (PRD 3.11)
# ----------------------------------------------------------------------------
def _entry_overage_reals(period, statuses):
    """Yield each included entry's real overage cents (Decimal), in waterfall order.

    Entries are processed in ascending created_at order; the entry id is never
    used for ordering. We use the insertion sequence `_seq` (monotonic with
    creation) as the stable tiebreaker for the created_at sort.
    """
    cap = Decimal(str(period["hours_cap"]))
    rate = Decimal(period["overage_rate_cents"])

    entries = [te for te in db.time_entries.values()
               if te["retainer_period_id"] == period["id"] and te["status"] in statuses]
    entries.sort(key=lambda te: (te["created_at"], te["_seq"]))

    running_prior = Decimal(0)
    for te in entries:
        hours = Decimal(str(te["billable_hours"]))
        in_cap_remaining = max(Decimal(0), cap - running_prior)
        entry_overage_hours = max(Decimal(0), hours - in_cap_remaining)
        entry_overage_real = entry_overage_hours * rate
        running_prior += hours
        yield te, entry_overage_real


def entry_provisional_cost_cents(period, entry):
    """Per-entry provisional cost = round-half-up of this entry's real overage.

    Computed within the waterfall over {SUBMITTED, APPROVED} entries so the
    in-cap allocation reflects earlier included entries (PRD 3.11).
    """
    for te, real in _entry_overage_reals(period, {"SUBMITTED", "APPROVED"}):
        if te["id"] == entry["id"]:
            return _round_cents(real)
    # Entry not in the included set (e.g. VOID): contributes 0.
    return 0


def provisional_total_cents(period):
    """Provisional total: round per entry, then sum (PRD 3.11), over SUBMITTED+APPROVED."""
    total = 0
    for _te, real in _entry_overage_reals(period, {"SUBMITTED", "APPROVED"}):
        total += _round_cents(real)
    return total


def final_total_cents(period):
    """Final total: sum the real overage amounts over APPROVED entries, then round once."""
    total = Decimal(0)
    for _te, real in _entry_overage_reals(period, {"APPROVED"}):
        total += real
    return _round_cents(total)


def hours_consumed(period):
    """Conserved quantity: sum billable_hours of non-void (SUBMITTED+APPROVED) entries."""
    total = Decimal(0)
    for te in db.time_entries.values():
        if te["retainer_period_id"] == period["id"] and te["status"] in ("SUBMITTED", "APPROVED"):
            total += Decimal(str(te["billable_hours"]))
    # Preserve numeric type: return as float if fractional, else int.
    if total == total.to_integral_value():
        return int(total)
    return float(total)


# ----------------------------------------------------------------------------
# campaign_roi (PRD 3.10) — pinned evaluation order
# ----------------------------------------------------------------------------
def campaign_earned_cents(campaign):
    """STEP 1: sum media_value_cents of VERIFIED coverage on this campaign."""
    total = 0
    for cov in db.coverage.values():
        if cov["campaign_id"] == campaign["id"] and cov["status"] == "VERIFIED":
            total += cov["media_value_cents"]
    return total


def campaign_cost_basis_cents(campaign):
    """STEP 2: sum cost_cents of APPROVED time entries on this campaign."""
    total = 0
    for te in db.time_entries.values():
        if te.get("campaign_id") == campaign["id"] and te["status"] == "APPROVED":
            total += te["cost_cents"]
    return total


def campaign_roi_ratio(earned, cost):
    """STEPS 3-4: denom = max(cost, floor); roi = (earned-cost)/denom (4dp HU).

    If earned == 0 -> null.
    """
    if earned == 0:
        return None
    denom = max(cost, ROI_FLOOR_CENTS)
    ratio = (Decimal(earned) - Decimal(cost)) / Decimal(denom)
    return float(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
