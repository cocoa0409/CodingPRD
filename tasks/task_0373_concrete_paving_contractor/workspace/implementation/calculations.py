"""Calculation rules (PRD §3, scaffold §1.3). Uses Decimal for money; round-half-up."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from util import D, money

# ---- constants (scaffold §1.3) ----
WASTE_FACTOR = D("0.10")
CUBIC_FEET_PER_YARD = 27
INCHES_PER_FOOT = 12
TICKET_INCREMENT_CY = D("0.25")

RATE_TIER1 = D("9.00")
RATE_TIER2 = D("7.50")
RATE_TIER3 = D("6.00")
MIX_RATE_PER_CY = D("145.00")
FINISH_MULT = {"BROOM": D("1.00"), "EXPOSED_AGGREGATE": D("1.20"), "STAMPED": D("1.35")}
REINF_RATE = {"NONE": D("0.00"), "MESH": D("0.60"), "REBAR": D("1.25")}

RETAINAGE_PCT = D("0.10")
CURE_HOURS = {"STANDARD": 168, "HIGH_EARLY": 72, "FIBER": 168}

W_CURE = 30
W_WEATHER = 25
W_CLAIM = 15
W_NO_REINF = 10


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _adj_cy(seg):
    """Waste-adjusted raw cubic yards for a single segment (Decimal)."""
    raw = (D(seg["area_sqft"]) * (D(seg["thickness_in"]) / D(INCHES_PER_FOOT))
           / D(CUBIC_FEET_PER_YARD))
    return raw * (D(1) + WASTE_FACTOR)


def estimate_cubic_yards(segments):
    """PROVISIONAL variant: sum waste-adjusted volumes first, then ceil to whole yard."""
    total = sum((_adj_cy(s) for s in segments), Decimal(0))
    return int(math.ceil(total))


def total_sqft(segments):
    """Sum of area_sqft over segments, rounded to 2 dp."""
    s = sum((D(seg["area_sqft"]) for seg in segments), Decimal(0))
    return float(_round2(s))


def order_cubic_yards(segments):
    """ORDER variant: ceil each segment to 0.25-yd, sum, then ceil to whole yard."""
    total = Decimal(0)
    for s in segments:
        adj = _adj_cy(s)
        # ceil to the next 0.25-yd ticket increment
        ticket = (adj * 4).to_integral_value(rounding=ROUND_CEILING) / D(4)
        total += ticket
    return int(math.ceil(total))


def estimate_total(segments, provisional_cy):
    """Tiered labor + finish multiplier + reinforcement add, then material subtotal.

    Returns (labor_subtotal, material_subtotal, estimate_total) all as 2dp floats.
    """
    sqft_total = sum((D(s["area_sqft"]) for s in segments), Decimal(0))

    # marginal tiered labor base
    remaining = sqft_total
    labor_base = Decimal(0)
    t1 = min(remaining, D(500))
    labor_base += t1 * RATE_TIER1
    remaining -= t1
    if remaining > 0:
        t2 = min(remaining, D(1000))
        labor_base += t2 * RATE_TIER2
        remaining -= t2
    if remaining > 0:
        labor_base += remaining * RATE_TIER3

    finish_mult = max((FINISH_MULT[s["finish_grade"]] for s in segments), default=D("1.00"))
    reinf_add = sum((REINF_RATE[s["reinforcement"]] * D(s["area_sqft"]) for s in segments), Decimal(0))

    labor_subtotal = _round2(labor_base * finish_mult + reinf_add)
    material_subtotal = _round2(D(provisional_cy) * MIX_RATE_PER_CY)
    # round-per-line-item THEN sum
    total = labor_subtotal + material_subtotal
    return float(labor_subtotal), float(material_subtotal), float(total)


def provisional_contract_value(base_contract_amount, change_orders):
    """base + sum of delta_amount for COs in {UNDER_REVIEW, APPROVED}."""
    total = D(base_contract_amount)
    for co in change_orders:
        if co["status"] in ("UNDER_REVIEW", "APPROVED"):
            total += D(co["delta_amount"])
    return float(_round2(total))


def committed_contract_value(base_contract_amount, change_orders):
    """base + sum of APPROVED deltas applied in created_at ASC order (tie-break: seq)."""
    approved = [co for co in change_orders if co["status"] == "APPROVED"]
    approved.sort(key=lambda co: (co["created_at"], co["_seq"]))
    value = D(base_contract_amount)
    for co in approved:
        value += D(co["delta_amount"])
    return float(_round2(value))


def draw_cap(draw_type, committed_value):
    """FINAL -> full committed; DEPOSIT/PROGRESS -> committed * (1 - retainage), 2dp."""
    if draw_type == "FINAL":
        return float(_round2(D(committed_value)))
    return float(_round2(D(committed_value) * (D(1) - RETAINAGE_PCT)))


def cure_window_end(pour_completed_at, mix_type):
    return pour_completed_at + timedelta(hours=CURE_HOURS[mix_type])


def warranty_risk_score(project, segments, material_orders, warranties):
    """Additive, then clamped to [0,100] (PRD §3.7)."""
    score = 0

    # find the poured material order (the one with pour_completed_at set)
    poured = None
    for m in material_orders:
        if m["pour_completed_at"] is not None:
            poured = m
            break

    if poured is not None and poured["pour_completed_at"] is not None and poured["cure_window_end"] is not None:
        span_hours = (poured["cure_window_end"] - poured["pour_completed_at"]).total_seconds() / 3600.0
        required = CURE_HOURS[poured["mix_type"]]
        if span_hours < required:
            score += W_CURE

    # weather violation flag set on any order that was force-started over a bad reading
    if any(m.get("weather_violation") for m in material_orders):
        score += W_WEATHER

    total_claims = sum(w["defect_claims_count"] for w in warranties)
    score += W_CLAIM * total_claims

    if any(s["reinforcement"] == "NONE" for s in segments):
        score += W_NO_REINF

    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score
