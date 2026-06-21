"""Calculation rules (PRD §2.7, §3.1, §3.4, §3.5, §3.6, §3.10, §3.12).

All money is integer cents; all weight is integer pounds. The only rounding in
the system is fuel surcharge (round-half-up to whole cents) and on_time_pct
(round-half-up to two decimals). Everything else is integer arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# Constants (scaffold §1.3).
ACCESSORIAL_ESTIMATE_CENTS = 5000
TOLERANCE_CENTS = 500

ACCESSORIAL_FLAT = {
    "DETENTION": 7500,
    "LIFTGATE": 3500,
    "RESIDENTIAL": 2500,
}
KNOWN_ACCESSORIALS = set(ACCESSORIAL_FLAT.keys()) | {"REWEIGH"}

REWEIGH_LIGHT_CENTS = 1500
REWEIGH_MID_CENTS = 4000
REWEIGH_HEAVY_CENTS = 9000
REWEIGH_MID_LB = 5000
REWEIGH_HEAVY_LB = 20000

# Scorecard grade thresholds (inclusive).
GRADE_A_ONTIME = 95
GRADE_A_CLAIM_MAX = Decimal("0.02")
GRADE_B_ONTIME = 90
GRADE_B_CLAIM_MAX = Decimal("0.05")
GRADE_C_ONTIME = 80


def _round_half_up_cents(value):
    """Round a Decimal to a whole integer number of cents, round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def linehaul_cents(rate, distance_miles):
    """Linehaul = max(per-mile-rate * distance, min charge floor) (PRD §3.4)."""
    raw = rate["base_rate_per_mile_cents"] * distance_miles
    return max(raw, rate["min_charge_cents"])


def fuel_cents(linehaul, fuel_surcharge_pct):
    """Fuel = round_half_up(linehaul * fuel_surcharge_pct) to whole cents (PRD §2.7)."""
    return _round_half_up_cents(Decimal(linehaul) * Decimal(str(fuel_surcharge_pct)))


def priced_cost(rate, distance_miles):
    """Rate-shop priced cost: linehaul + fuel (PRD §3.4). Floor applied first."""
    lh = linehaul_cents(rate, distance_miles)
    fu = fuel_cents(lh, rate["fuel_surcharge_pct"])
    return lh + fu


# ---- rate_shop_selection (PRD §3.4) ----

def rate_shop_selection(shipment, order, tender_minute):
    """Select the lowest-priced eligible ContractRate. Returns the chosen rate
    record, or None if the candidate set is empty.

    Eligibility: rate ACTIVE, rate.mode == shipment.mode, rate zones == order
    zones, effective window contains tender_minute (closed interval), carrier
    ACTIVE, carrier.mode == shipment.mode.
    Ranking: lowest priced_cents; tie-break higher on_time_pct (null -> -1);
    then earliest contract-rate created_at."""
    candidates = []
    for rate in db.contract_rates.values():
        if rate["status"] != "ACTIVE":
            continue
        if rate["mode"] != shipment["mode"]:
            continue
        if rate["origin_zone"] != order["origin_zone"]:
            continue
        if rate["dest_zone"] != order["dest_zone"]:
            continue
        if not (rate["effective_start_minute"] <= tender_minute <= rate["effective_end_minute"]):
            continue
        carrier = db.carriers.get(rate["carrier_id"])
        if carrier is None or carrier["status"] != "ACTIVE":
            continue
        if carrier["mode"] != shipment["mode"]:
            continue
        candidates.append((rate, carrier))

    if not candidates:
        return None

    def sort_key(item):
        rate, carrier = item
        cost = priced_cost(rate, shipment["distance_miles"])
        otp = on_time_pct(carrier)
        # null on_time_pct treated as -1, ranked last -> negate for ASC ordering.
        otp_rank = -1 if otp is None else otp
        return (
            cost,                       # lowest priced cost first
            -float(otp_rank),           # higher on_time_pct first
            rate["created_at"],         # earliest created_at first
            rate["_seq"],
        )

    best_rate, _best_carrier = min(candidates, key=sort_key)
    return best_rate


def offered_rate_cents(rate, shipment):
    return priced_cost(rate, shipment["distance_miles"])


# ---- freight_cost_quoted (PRD §3.5) ----

def freight_cost_quoted(shipment, rate):
    """Provisional cost = linehaul + fuel + flat 5000-cent accessorial reserve.
    Floor applied to linehaul before fuel (pinned order)."""
    lh = linehaul_cents(rate, shipment["distance_miles"])
    fu = fuel_cents(lh, rate["fuel_surcharge_pct"])
    return lh + fu + ACCESSORIAL_ESTIMATE_CENTS


# ---- accessorial_charge (PRD §3.10) ----

def accessorial_charge(code, weight_lbs):
    """Charge in cents for one accessorial code. Unknown codes are rejected by
    the caller before reaching here (validated against KNOWN_ACCESSORIALS)."""
    if code in ACCESSORIAL_FLAT:
        return ACCESSORIAL_FLAT[code]
    # REWEIGH — weight-tiered, inclusive lower boundary.
    if weight_lbs < REWEIGH_MID_LB:
        return REWEIGH_LIGHT_CENTS
    if weight_lbs < REWEIGH_HEAVY_LB:
        return REWEIGH_MID_CENTS
    return REWEIGH_HEAVY_CENTS


# ---- freight_cost_audited (PRD §3.10) ----

def freight_cost_audited(shipment, rate, invoice):
    """Returns (audited_cost_cents, variance_cents).

    audited = linehaul + fuel + sum(accessorial_charge over invoice codes).
    variance = invoiced_linehaul_cents + accessorial_total - audited."""
    lh = linehaul_cents(rate, shipment["distance_miles"])
    fu = fuel_cents(lh, rate["fuel_surcharge_pct"])
    accessorial_total = 0
    for code in invoice["invoiced_accessorial_codes"]:
        accessorial_total += accessorial_charge(code, shipment["weight_lbs"])
    audited = lh + fu + accessorial_total
    variance = invoice["invoiced_linehaul_cents"] + accessorial_total - audited
    return audited, variance


# ---- load_consolidation (PRD §3.6) ----

def consolidated_weight(load):
    """Sum weight_lbs over shipments on this load with execution_status != CANCELLED."""
    total = 0
    for s in db.shipments.values():
        if s.get("load_id") == load["id"] and s["execution_status"] != "CANCELLED":
            total += s["weight_lbs"]
    return total


# ---- carrier_scorecard (PRD §3.1) ----

def on_time_pct(carrier):
    """round_half_up(on_time_count / delivered_count * 100, 2) when delivered>0 else None."""
    delivered = carrier["delivered_count"]
    if delivered <= 0:
        return None
    raw = (Decimal(carrier["on_time_count"]) / Decimal(delivered)) * Decimal(100)
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def scorecard_grade(carrier):
    """A | B | C | PROBATION, top-down first-match (inclusive boundaries)."""
    delivered = carrier["delivered_count"]
    if delivered == 0:
        return "PROBATION"
    otp = on_time_pct(carrier)
    claim_ratio = Decimal(carrier["claim_count"]) / Decimal(delivered)
    otp_dec = Decimal(str(otp))
    if otp_dec >= GRADE_A_ONTIME and claim_ratio <= GRADE_A_CLAIM_MAX:
        return "A"
    if otp_dec >= GRADE_B_ONTIME and claim_ratio <= GRADE_B_CLAIM_MAX:
        return "B"
    if otp_dec >= GRADE_C_ONTIME:
        return "C"
    return "PROBATION"


# ---- claim_settlement (PRD §3.12) ----

def claim_settlement(claim, order):
    """min(claimed_amount, declared_value); OSD_OVERAGE settles to 0."""
    if claim["claim_type"] == "OSD_OVERAGE":
        return 0
    return min(claim["claimed_amount_cents"], order["declared_value_cents"])
