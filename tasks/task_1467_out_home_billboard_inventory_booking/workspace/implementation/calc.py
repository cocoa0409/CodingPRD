"""Calculation rules (SCAFFOLD table 3 / PRD 2.6, 3.5, 3.8, 3.9)."""
from datetime import timedelta

from util import D, rhu, rhu_places, ceil_div

TIER_1_FLOOR_CENTS = 5000000
TIER_1_PCT = D("0.05")
TIER_2_FLOOR_CENTS = 15000000
TIER_2_PCT = D("0.10")
HOLDOVER_RATE_PCT = D("1.10")
ILLUMINATION_FACTOR = D("1.12")
ILLUMINATION_CREDIT_PCT = D("0.15")
AUDIENCE_GUARANTEE_RATIO = D("0.90")


def billing_weeks(start_date, end_date):
    """ceil((end - start + 1 day) / 7); dates inclusive."""
    days = (end_date - start_date).days + 1
    return ceil_div(days, 7)


def flight_gross_cost(face, rate_card, start_date, end_date, loop_slots):
    """flight_gross_cost: round the weekly rate once, then multiply by weeks."""
    weeks = billing_weeks(start_date, end_date)
    base = D(rate_card["base_weekly_cents"])
    if face["daily_traffic_count"] >= rate_card["traffic_tier_2_threshold"]:
        traffic_mult = 1 + D(rate_card["traffic_tier_2_uplift_pct"])
    elif face["daily_traffic_count"] >= rate_card["traffic_tier_1_threshold"]:
        traffic_mult = 1 + D(rate_card["traffic_tier_1_uplift_pct"])
    else:
        traffic_mult = D(1)
    ill_mult = (1 + D(rate_card["illumination_premium_pct"])) \
        if face["illuminated"] else D(1)
    if face["display_type"] == "DIGITAL":
        slot_share = D(loop_slots) / D(face["loop_slots_total"])
    else:
        slot_share = D(1)
    pinned_weekly_cents = rhu(base * traffic_mult * ill_mult * slot_share)
    gross_cents = pinned_weekly_cents * weeks
    return weeks, pinned_weekly_cents, gross_cents


def volume_tier(contracted_cents):
    if contracted_cents >= TIER_2_FLOOR_CENTS:
        return TIER_2_PCT
    if contracted_cents >= TIER_1_FLOOR_CENTS:
        return TIER_1_PCT
    return D(0)


def per_flight_net(flight):
    """round_half_up((gross + holdover) * (1 - flight.discount_pct))."""
    return rhu(D(flight["gross_cents"] + flight["holdover_charge_cents"])
               * (1 - D(flight["discount_pct"])))


def estimated_impressions(face, weeks, loop_slots):
    """Per-week round_half_up, then sum (rounding order pinned, PRD 3.8)."""
    factor = ILLUMINATION_FACTOR if face["illuminated"] else D("1.0")
    if face["display_type"] == "DIGITAL":
        slot_share = D(loop_slots) / D(face["loop_slots_total"])
    else:
        slot_share = D(1)
    per_week = rhu(D(face["daily_traffic_count"]) * 7 * factor * slot_share)
    return per_week * weeks


def replay_delivered(flight):
    """delivered_impressions: chronological replay with AUDIENCE_MEASURED
    precedence per period (PRD 3.8)."""
    entries = flight["impression_entries"]
    groups = {}
    for e in entries:
        groups.setdefault((e["period_start"], e["period_end"]), []).append(e)
    total = 0
    for key in sorted(groups.keys()):
        es = sorted(groups[key], key=lambda e: e["_seq"])
        measured = [e for e in es if e["source"] == "AUDIENCE_MEASURED"]
        if measured:
            total += sum(e["impressions"] for e in measured)
        else:
            total += es[-1]["impressions"]
    flight["delivered_impressions"] = total
    est = flight["estimated_impressions"]
    if not entries or est == 0:
        flight["delivery_ratio"] = 0
    else:
        ratio = rhu_places(D(total) / D(est), 4)
        flight["delivery_ratio"] = float(ratio)


def holdover_charge(flight, today):
    """HOLDOVER -> COMPLETED pricing (PRD 3.7)."""
    days = (today - flight["end_date"]).days
    if days <= 0:
        return 0, 0
    weeks = ceil_div(days, 7)
    charge = weeks * rhu(D(flight["pinned_weekly_cents"]) * HOLDOVER_RATE_PCT)
    return weeks, charge


def cancellation_fee(gross_cents, days_before):
    """Tiered schedule: >=28d -> 10%; 14..27 -> 25%; <14 -> 50% (PRD 3.5)."""
    if days_before >= 28:
        pct = D("0.10")
    elif days_before >= 14:
        pct = D("0.25")
    else:
        pct = D("0.50")
    return rhu(D(gross_cents) * pct)


def _cap(credit, gross_cents):
    """Credits never exceed gross_cents (cap after rounding, PRD 3.9)."""
    return min(credit, gross_cents)


def mg_missed_posting(flight):
    return _cap(rhu(D(flight["pinned_weekly_cents"]) * flight["missed_days"] / 7),
                flight["gross_cents"])


def mg_illumination_outage(flight, outage_days):
    return _cap(rhu(D(flight["pinned_weekly_cents"]) * ILLUMINATION_CREDIT_PCT
                    * outage_days / 7), flight["gross_cents"])


def mg_permit_suspension(flight, suspension_days):
    return _cap(rhu(D(flight["pinned_weekly_cents"]) * suspension_days / 7),
                flight["gross_cents"])


def under_delivery_credit(flight):
    """Returns credit cents when a shortfall exists at completion, else None."""
    est = flight["estimated_impressions"]
    if est <= 0:
        return None
    guarantee = AUDIENCE_GUARANTEE_RATIO * D(est)
    delivered = D(flight["delivered_impressions"])
    if not delivered < guarantee:
        return None
    base = rhu(D(flight["gross_cents"]) * (1 - D(flight["discount_pct"])))
    credit = rhu(D(base) * (guarantee - delivered) / guarantee)
    return _cap(credit, flight["gross_cents"])


def interval_intersect_days(a_start, a_end, b_start, b_end):
    """Inclusive date-interval intersection length in days (0 when disjoint)."""
    lo = max(a_start, a_end) if a_start > a_end else a_start
    s = max(a_start, b_start)
    e = min(a_end, b_end)
    if e < s:
        return 0
    return (e - s).days + 1
