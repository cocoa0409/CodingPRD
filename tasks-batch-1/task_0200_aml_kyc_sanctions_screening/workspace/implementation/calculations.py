"""Calculation rules (PRD §3.2-§3.10, SCAFFOLD §1.3).

All weighted scores use Decimal with ROUND_HALF_UP to 2dp. Monetary amounts are
integer cents. Datetime arithmetic is in whole UTC days.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock

# ---- risk_scoring (PRD §3.2) ----
W_GEO = 4
W_PROD = 3
W_PEP = 5
W_MEDIA = 3
PEP_MEDIA_SURCHARGE = 12
PROHIBITED_THRESHOLD = 84
HIGH_THRESHOLD = 60
MEDIUM_THRESHOLD = 35

# ---- transaction_monitoring (PRD §3.6) ----
CTR_LIMIT_CENTS = 1000000
STRUCT_LOW = 900000
STRUCT_HIGH = 1000000
RAPID_FRACTION = Decimal("0.90")
HIGH_RISK_COUNTRIES = {"IR", "KP", "SY", "CU"}

# ---- alert_severity (PRD §3.7) ----
RULE_BASE = {
    "STRUCTURING": Decimal("40"),
    "RAPID_MOVEMENT": Decimal("35"),
    "HIGH_RISK_GEO": Decimal("25"),
    "CTR_THRESHOLD": Decimal("20"),
}
RISK_MULT = {
    "LOW": Decimal("1.0"),
    "MEDIUM": Decimal("1.5"),
    "HIGH": Decimal("2.0"),
    "PROHIBITED": Decimal("2.0"),
}
NULL_RATING_MULT = Decimal("1.0")

# ---- case_priority (PRD §3.8) ----
CRIT_THRESHOLD = Decimal("70")
HIGH_PRI_THRESHOLD = Decimal("50")
MED_PRI_THRESHOLD = Decimal("30")

# ---- confirm floor (PRD §3.5) ----
CONFIRM_FLOOR = Decimal("0.95")

# ---- review_cadence (PRD §3.3) ----
REVIEW_HIGH_DAYS = 90
REVIEW_MEDIUM_DAYS = 180
REVIEW_LOW_DAYS = 365

# ---- filing_deadline (PRD §3.9) ----
SAR_DEADLINE_DAYS = 30
CTR_DEADLINE_DAYS = 15


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_number(d):
    """Decimal -> JSON-friendly number; emit int if integral else float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# risk_scoring
# ---------------------------------------------------------------------------
def risk_scoring(geography_factor, product_factor, pep_factor, adverse_media_factor):
    """Return (total_score_number, risk_band). pep_factor already adjusted by
    the FINAL-variant pre-formula bump (applied by caller)."""
    base = (
        geography_factor * W_GEO
        + product_factor * W_PROD
        + pep_factor * W_PEP
        + adverse_media_factor * W_MEDIA
    )
    surcharge = PEP_MEDIA_SURCHARGE if max(pep_factor, adverse_media_factor) == 5 else 0
    total = _round2(Decimal(base + surcharge))
    if total >= PROHIBITED_THRESHOLD:
        band = "PROHIBITED"
    elif total >= HIGH_THRESHOLD:
        band = "HIGH"
    elif total >= MEDIUM_THRESHOLD:
        band = "MEDIUM"
    else:
        band = "LOW"
    return _to_number(total), band


# ---------------------------------------------------------------------------
# alert_severity
# ---------------------------------------------------------------------------
def alert_severity(rule_code, risk_rating):
    base = RULE_BASE[rule_code]
    mult = RISK_MULT.get(risk_rating, NULL_RATING_MULT) if risk_rating else NULL_RATING_MULT
    return _to_number(_round2(base * mult))


# ---------------------------------------------------------------------------
# case_priority
# ---------------------------------------------------------------------------
def case_priority(max_severity):
    """max_severity: Decimal or None (no linked alerts)."""
    if max_severity is None:
        return "LOW"
    if max_severity >= CRIT_THRESHOLD:
        return "CRITICAL"
    if max_severity >= HIGH_PRI_THRESHOLD:
        return "HIGH"
    if max_severity >= MED_PRI_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# review_cadence
# ---------------------------------------------------------------------------
def review_due_at(created_at_iso, risk_rating):
    if risk_rating == "HIGH":
        days = REVIEW_HIGH_DAYS
    elif risk_rating == "MEDIUM":
        days = REVIEW_MEDIUM_DAYS
    else:
        days = REVIEW_LOW_DAYS
    base = clock.parse_iso8601(created_at_iso)
    return clock.format_iso8601(base + timedelta(days=days))


# ---------------------------------------------------------------------------
# filing_deadline
# ---------------------------------------------------------------------------
def filing_deadline(filing_type, case_created_at_iso, ctr_anchor_iso):
    """ctr_anchor_iso is the earliest qualifying CTR txn posted_at, or None."""
    if filing_type == "SAR":
        base = clock.parse_iso8601(case_created_at_iso)
        return clock.format_iso8601(base + timedelta(days=SAR_DEADLINE_DAYS))
    # CTR
    anchor_iso = ctr_anchor_iso if ctr_anchor_iso is not None else case_created_at_iso
    base = clock.parse_iso8601(anchor_iso)
    return clock.format_iso8601(base + timedelta(days=CTR_DEADLINE_DAYS))


# ---------------------------------------------------------------------------
# transaction_monitoring
# ---------------------------------------------------------------------------
def evaluate_monitoring(direction, amount_cents, counterparty_country,
                        window_cash_in_after, prior_cumulative_credited):
    """Return triggered_rule (str) or None per the fixed precedence (PRD §3.6).

    window_cash_in_after: same-UTC-day CASH_IN total INCLUDING this txn (only
        meaningful for CASH_IN; caller passes the post-addition value).
    prior_cumulative_credited: cumulative_credited_cents BEFORE this txn.
    """
    if direction == "CASH_IN" and window_cash_in_after > CTR_LIMIT_CENTS:
        return "CTR_THRESHOLD"
    if direction == "CASH_IN" and STRUCT_LOW <= amount_cents <= STRUCT_HIGH:
        return "STRUCTURING"
    if counterparty_country in HIGH_RISK_COUNTRIES:
        return "HIGH_RISK_GEO"
    if direction in ("CASH_OUT", "WIRE_OUT"):
        threshold = int(
            (RAPID_FRACTION * Decimal(prior_cumulative_credited)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if amount_cents >= threshold:
            return "RAPID_MOVEMENT"
    return None


def same_utc_day(iso_a, iso_b):
    a = clock.parse_iso8601(iso_a)
    b = clock.parse_iso8601(iso_b)
    return a.date() == b.date()
