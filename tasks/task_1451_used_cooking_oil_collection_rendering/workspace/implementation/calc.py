"""Calculation rules (SCAFFOLD calculations table / PRD sections 2.6, 3.5-3.9).

All gallon math at 2dp half-up, yield rate at 4dp half-up, money in integer
cents with per-line rounding before summation. Decimal everywhere; never float
arithmetic for money.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import parse_dt, store
from errors import err

MISSED_PICKUP_SUSPEND_THRESHOLD = 3
MISSED_PICKUP_WINDOW_DAYS = 90
TANK_TOLERANCE_GAL = Decimal("0.5")
YIELD_COEFF = Decimal("0.92")
MIN_PAYOUT_CENTS = 100
COOLING_OFF_DAYS = 14
COMPLAINT_REOPEN_WINDOW_DAYS = 7

GRADE_FACTOR = {
    "A": Decimal("1.00"),
    "B": Decimal("0.90"),
    "C": Decimal("0.75"),
    "REJECT": Decimal("0.00"),
}
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "REJECT": 3}


def D(v):
    """Exact Decimal view of a JSON number."""
    return Decimal(str(v))


def r2(v):
    """Round half-up to 2 decimal places; returned as a JSON-safe float."""
    return float(D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r4(v):
    """Round half-up to 4 decimal places; returned as a JSON-safe float."""
    return float(D(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def c0(v):
    """Round half-up to integer cents."""
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(d):
    """JSON-safe view of a Decimal rate: int when integral, else float."""
    d = D(d)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Quality grading (PRD 3.6): lower bound inclusive, upper bound exclusive.
# ---------------------------------------------------------------------------
def moisture_dim(pct):
    p = D(pct)
    if p < D("5.0"):
        return "A"
    if p < D("15.0"):
        return "B"
    if p < D("25.0"):
        return "C"
    return "REJECT"


def impurity_dim(pct):
    p = D(pct)
    if p < D("2.0"):
        return "A"
    if p < D("6.0"):
        return "B"
    if p < D("10.0"):
        return "C"
    return "REJECT"


def worse(g1, g2):
    return g1 if _GRADE_ORDER[g1] >= _GRADE_ORDER[g2] else g2


def assign_grade(lab_moisture_pct, lab_impurity_pct):
    return worse(moisture_dim(lab_moisture_pct), impurity_dim(lab_impurity_pct))


# ---------------------------------------------------------------------------
# Pickup netting (PRD 3.5 / 3.7)
# ---------------------------------------------------------------------------
def net_provisional(pump_gallons, field_moisture_pct):
    return r2(D(pump_gallons) * (Decimal("1") - D(field_moisture_pct) / Decimal("100")))


def net_final(pump_gallons, lab_moisture_pct):
    return r2(D(pump_gallons) * (Decimal("1") - D(lab_moisture_pct) / Decimal("100")))


def graded_sample_for(visit_id):
    """The visit's GRADED sample used for final netting: latest updated wins."""
    graded = [
        s for s in store.samples.values()
        if s["pickup_visit_id"] == visit_id and s["status"] == "GRADED"
    ]
    if not graded:
        return None
    graded.sort(key=lambda s: (s["updated_at"], s["_seq"]))
    return graded[-1]


# ---------------------------------------------------------------------------
# Market index pricing (PRD 3.7)
# ---------------------------------------------------------------------------
def provisional_index_price(index_code, scheduled_date):
    """Latest PUBLISHED quote with week_start <= scheduled_date.

    Ties: greatest week_start, then greatest published_at, then created_at ASC.
    """
    cands = [
        q for q in store.quotes.values()
        if q["index_code"] == index_code
        and q["status"] == "PUBLISHED"
        and q["week_start"] <= scheduled_date
    ]
    if not cands:
        raise err(
            "ERR_QUOTE_NOT_PUBLISHED",
            "No published quote of %s covers %s" % (index_code, scheduled_date),
        )
    best_week = max(q["week_start"] for q in cands)
    cands = [q for q in cands if q["week_start"] == best_week]
    best_pub = max(q["published_at"] or "" for q in cands)
    cands = [q for q in cands if (q["published_at"] or "") == best_pub]
    cands.sort(key=lambda q: (q["created_at"], q["_seq"]))
    return cands[0]["price_cents_per_gal"]


def final_index_price(index_code, period_start, period_end):
    """Mean of PUBLISHED in-period week prices, half-up to integer cents/gal."""
    cands = [
        q for q in store.quotes.values()
        if q["index_code"] == index_code
        and q["status"] == "PUBLISHED"
        and period_start <= q["week_start"] < period_end
    ]
    if not cands:
        raise err(
            "ERR_QUOTE_NOT_PUBLISHED",
            "No published quote of %s inside [%s, %s)" % (index_code, period_start, period_end),
        )
    mean = sum(D(q["price_cents_per_gal"]) for q in cands) / D(len(cands))
    return c0(mean)


def quote_coverage_ok(index_code, scheduled_date):
    return any(
        q["index_code"] == index_code
        and q["status"] == "PUBLISHED"
        and q["week_start"] <= scheduled_date
        for q in store.quotes.values()
    )


# ---------------------------------------------------------------------------
# Settlement line amounts (PRD 3.7): per-line half-up rounding, then sum.
# ---------------------------------------------------------------------------
def line_amount(contract, index_price, grade, gallons_billed):
    """Return (rate_cents_per_gal, line_amount_cents) for one line."""
    if contract["pricing_mode"] == "REBATE":
        raw_rate = D(index_price) * GRADE_FACTOR[grade]
        rate = min(D(contract["cap_cents_per_gal"]), max(D(contract["floor_cents_per_gal"]), raw_rate))
        amount = c0(D(gallons_billed) * rate)
        return num(rate), amount
    # SERVICE_FEE: customer pays the company; rate is null.
    overage_gal = max(Decimal("0"), D(gallons_billed) - D(contract["overage_threshold_gal"]))
    overage_cents = c0(overage_gal * D(contract["overage_rate_cents_per_gal"]))
    amount = -(contract["service_fee_cents"] + overage_cents)
    return None, amount


# ---------------------------------------------------------------------------
# Route projections and tank conservation (PRD 2.9, 3.4)
# ---------------------------------------------------------------------------
def projected_fill(container_ids):
    total = Decimal("0")
    for cid in container_ids:
        c = store.containers[cid]
        total += min(D(c["capacity_gallons"]), D(c["est_fill_rate_gal_per_week"]))
    return r2(total)


def collected_gallons(manifest_id):
    total = Decimal("0")
    for v in store.visits.values():
        if v["manifest_id"] == manifest_id and v["status"] == "COMPLETED":
            total += D(v["pump_gallons"])
    return r2(total)


def tank_conservation_ok(manifest, end_level_gallons, spill_loss_gallons):
    expected = (
        D(manifest["start_level_gallons"])
        + D(collected_gallons(manifest["id"]))
        - D(spill_loss_gallons)
    )
    return abs(D(end_level_gallons) - expected) <= TANK_TOLERANCE_GAL


# ---------------------------------------------------------------------------
# Customer derived aggregates (PRD 3.1, 2.10) — live-computed on read.
# ---------------------------------------------------------------------------
def missed_pickup_count(customer_id):
    window_start = store.clock - timedelta(days=MISSED_PICKUP_WINDOW_DAYS)
    count = 0
    for v in store.visits.values():
        if v["status"] != "SKIPPED" or not v.get("skipped_at"):
            continue
        cont = store.containers.get(v["container_id"])
        if cont is None or cont["customer_id"] != customer_id:
            continue
        skipped_at = parse_dt(v["skipped_at"])
        if window_start < skipped_at <= store.clock:
            count += 1
    return count


def rebate_balance_cents(customer_id):
    return sum(
        s["final_total_cents"]
        for s in store.settlements.values()
        if s["customer_id"] == customer_id and s["status"] == "FINALIZED"
    )


# ---------------------------------------------------------------------------
# Rendering batch yield (PRD 3.9)
# ---------------------------------------------------------------------------
def weighted_moisture_pct(manifest_id):
    num_sum = Decimal("0")
    den_sum = Decimal("0")
    for v in store.visits.values():
        if v["manifest_id"] != manifest_id or v["status"] != "COMPLETED":
            continue
        sample = graded_sample_for(v["id"])
        eff = D(sample["lab_moisture_pct"]) if sample else D(v["field_moisture_pct"])
        num_sum += D(v["pump_gallons"]) * eff
        den_sum += D(v["pump_gallons"])
    if den_sum == 0:
        return 0.0
    return r2(num_sum / den_sum)


def est_yield_gallons(input_gallons, weighted_moisture):
    return r2(D(input_gallons) * (Decimal("1") - D(weighted_moisture) / Decimal("100")) * YIELD_COEFF)


def yield_rate(actual_output_gallons, input_gallons):
    return r4(D(actual_output_gallons) / D(input_gallons))


def sale_revenue_cents(actual_output_gallons, sale_price_cents_per_gal):
    return c0(D(actual_output_gallons) * D(sale_price_cents_per_gal))


# ---------------------------------------------------------------------------
# Pricing contract selection (PRD 3.7): the settlement's pricing contract is
# the customer's contract whose half-open term contains period_start (any
# status — a terminated contract still prices its historical settlements);
# falling back to the customer's most recent contract.
# ---------------------------------------------------------------------------
def pricing_contract_for(customer_id, period_start):
    from helpers import fresh_contract

    cands = [c for c in store.contracts.values() if c["customer_id"] == customer_id]
    if not cands:
        return None
    for c in cands:
        fresh_contract(c)
    containing = [
        c for c in cands if c["term_start"] <= period_start < c["term_end"]
    ]
    pool = containing if containing else cands
    pool.sort(key=lambda c: (c["term_start"], c["created_at"], c["_seq"]))
    return pool[-1]
