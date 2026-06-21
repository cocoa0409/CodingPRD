"""Calculation rules (SCAFFOLD §1.3, PRD §2.10 / §3.4 / §3.6 / §3.7 / §3.8)."""
import math
from decimal import Decimal, ROUND_HALF_UP

import clock

# ---- risk_score constants ----
NAME_HIT_WEIGHT = 50
COMPANY_HIT_WEIGHT = 30
NO_PHOTO_ID_WEIGHT = 15

# ---- delivery handling ----
SURCHARGE_RATE = Decimal("0.075")

# ---- contractor billing tiers ----
FREE_MINUTES = 60
TIER2_SPAN = 180          # minutes 61..240
TIER2_RATE_CENTS = 200    # per started hour in tier 2
TIER3_RATE_CENTS = 500    # per started hour beyond 240 minutes


def normalize(value):
    """Lowercase + trim for case-insensitive watchlist matching."""
    if value is None:
        return ""
    return value.strip().lower()


def matching_active_entries(visit, all_watchlist_entries):
    """Set M: active WatchlistEntry rows for visit.site_id matching the visit.

    NAME entries match visitor_full_name; COMPANY entries match visitor_company.
    """
    name_norm = normalize(visit.get("visitor_full_name"))
    company_norm = normalize(visit.get("visitor_company"))
    matched = []
    for e in all_watchlist_entries:
        if e.get("site_id") != visit.get("site_id"):
            continue
        if not e.get("active", True):
            continue
        if e["match_type"] == "NAME" and e["match_value_normalized"] == name_norm:
            matched.append(e)
        elif e["match_type"] == "COMPANY" and e["match_value_normalized"] == company_norm:
            matched.append(e)
    return matched


def risk_score(visit, all_watchlist_entries):
    """Weighted score, clamped to [0,100] (SCAFFOLD risk_score calc / PRD §3.4)."""
    name_norm = normalize(visit.get("visitor_full_name"))
    company_norm = normalize(visit.get("visitor_company"))

    name_hit = 0
    company_hit = 0
    for e in all_watchlist_entries:
        if e.get("site_id") != visit.get("site_id"):
            continue
        if not e.get("active", True):
            continue
        if e["match_type"] == "NAME" and e["match_value_normalized"] == name_norm:
            name_hit = 1
        elif e["match_type"] == "COMPANY" and e["match_value_normalized"] == company_norm:
            company_hit = 1

    no_photo_id = 1 if not visit.get("id_scanned", False) else 0
    raw = (NAME_HIT_WEIGHT * name_hit
           + COMPANY_HIT_WEIGHT * company_hit
           + NO_PHOTO_ID_WEIGHT * no_photo_id)
    return max(0, min(100, raw))


def screening_decision(visit, all_watchlist_entries):
    """Severity dominance: DENY > REVIEW > CLEAR (SCAFFOLD screening_decision / PRD §3.4)."""
    matched = matching_active_entries(visit, all_watchlist_entries)
    if any(e["severity"] == "DENY" for e in matched):
        return "DENY"
    if any(e["severity"] == "REVIEW" for e in matched):
        return "REVIEW"
    return "CLEAR"


def visit_duration_minutes(sign_in_at_iso, sign_out_at_iso):
    """Ceiling minutes between sign_in_at and sign_out_at (SCAFFOLD visit_duration / PRD §3.6).

    Boundary: 0 elapsed seconds -> 0 minutes (not 1).
    """
    start = clock.parse_iso(sign_in_at_iso)
    end = clock.parse_iso(sign_out_at_iso)
    elapsed_seconds = (end - start).total_seconds()
    if elapsed_seconds <= 0:
        return 0
    return math.ceil(elapsed_seconds / 60.0)


def delivery_handling_invoice(parcel_fees_cents):
    """Per-parcel surcharge, round_half_up per parcel, THEN sum (SCAFFOLD / PRD §3.8)."""
    total = 0
    multiplier = Decimal("1") + SURCHARGE_RATE
    for fee in parcel_fees_cents:
        surcharged = Decimal(int(fee)) * multiplier
        rounded = int(surcharged.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += rounded
    return total


def _per_visit_parking_fee(minutes):
    """Three-tier parking fee for one visit's duration (SCAFFOLD contractor_billing_total / PRD §3.7)."""
    if minutes <= FREE_MINUTES:
        return 0
    if minutes <= FREE_MINUTES + TIER2_SPAN:  # <= 240
        started_hours = math.ceil((minutes - FREE_MINUTES) / 60.0)
        return started_hours * TIER2_RATE_CENTS
    # minutes > 240
    tier2_fee = (TIER2_SPAN // 60) * TIER2_RATE_CENTS  # full tier-2 = 3 * 200
    extra_started_hours = math.ceil((minutes - FREE_MINUTES - TIER2_SPAN) / 60.0)
    return tier2_fee + extra_started_hours * TIER3_RATE_CENTS


def contractor_billing_total(covered_signed_out_visits):
    """Sum per-visit parking fees across covered SIGNED_OUT visits.

    Visits are processed in sign_out_at ASC, tie-break created_at ASC (PRD §3.7).
    """
    ordered = sorted(
        covered_signed_out_visits,
        key=lambda v: (v.get("sign_out_at"), v.get("created_at")),
    )
    total = 0
    for v in ordered:
        minutes = v.get("visit_duration_minutes") or 0
        total += _per_visit_parking_fee(minutes)
    return total, len(ordered)
