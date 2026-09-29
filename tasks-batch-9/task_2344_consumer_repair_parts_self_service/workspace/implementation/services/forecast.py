"""long_tail_demand_forecast (PRD 3.11). Pinned evaluation order, no persistence."""
from fractions import Fraction

import db
from util import as_number, ceil_frac, days, round_half_up_places, whole_months_between

VARIANTS = ("TRAILING_ONLY", "PIPELINE_WEIGHTED")

TRAILING_WINDOW_DAYS = 180
TRAILING_WINDOW_MONTHS = 6
MANDATE_BUFFER_RATIO = Fraction(1, 4)

BAND_MULTIPLIER = {
    "CURRENT": Fraction(1),
    "LEGACY": Fraction(135, 100),
    "LONG_TAIL": Fraction(180, 100),
}


def _joined_lines(part_id, model_id):
    for line in db.ordered(db.db.lines.all()):
        if line["part_id"] != part_id:
            continue
        order = db.db.orders.get(line["order_id"])
        if order is None or order.get("model_id") != model_id:
            continue
        yield line, order


def mandated_months_remaining(model_id):
    at = db.now()
    latest = None
    for obligation in db.db.obligations.all():
        if obligation["model_id"] != model_id or obligation["status"] == "CLOSED":
            continue
        deadline = obligation.get("parts_available_until")
        if deadline is None:
            continue
        if latest is None or deadline > latest:
            latest = deadline
    if latest is None or latest <= at:
        return 0
    return whole_months_between(at, latest)


def forecast(part, model, horizon_months, variant):
    at = db.now()
    window_start = at - days(TRAILING_WINDOW_DAYS)

    trailing_units = 0
    pipeline_units = 0
    for line, order in _joined_lines(part["id"], model["id"]):
        status = order["fulfillment_status"]
        if status in ("DELIVERED", "CLOSED"):
            confirmed = order.get("confirmed_at")
            if confirmed is not None and window_start <= confirmed < at:
                trailing_units += line["quantity"]
        if status in ("PENDING_DISCLOSURE", "CONFIRMED"):
            pipeline_units += line["quantity"]

    base_monthly = Fraction(trailing_units, TRAILING_WINDOW_MONTHS)

    eop = model.get("end_of_production_date")
    months_since_eop = 0 if eop is None else whole_months_between(eop, at)
    if months_since_eop < 12:
        band = "CURRENT"
    elif months_since_eop <= 60:
        band = "LEGACY"
    else:
        band = "LONG_TAIL"
    multiplier = BAND_MULTIPLIER[band]

    if variant == "PIPELINE_WEIGHTED":
        demand_monthly = (
            Fraction(6, 10) * base_monthly
            + Fraction(4, 10) * Fraction(pipeline_units, horizon_months)
        )
    else:
        demand_monthly = base_monthly

    projected = demand_monthly * horizon_months * multiplier

    if projected < 50:
        safety_pct = Fraction(30, 100)
    elif projected < 500:
        safety_pct = Fraction(20, 100)
    else:
        safety_pct = Fraction(12, 100)

    months_remaining = mandated_months_remaining(model["id"])
    mandated_buffer = ceil_frac(demand_monthly * months_remaining * MANDATE_BUFFER_RATIO)

    recommended = ceil_frac(projected * (Fraction(1) + safety_pct)) + mandated_buffer

    return {
        "variant": variant,
        "trailing_units": trailing_units,
        "pipeline_units": pipeline_units,
        "base_monthly_units": as_number(base_monthly),
        "obsolescence_band": band,
        "band_multiplier": as_number(multiplier),
        "projected_units": round_half_up_places(projected, 2),
        "safety_stock_pct": as_number(safety_pct),
        "mandated_buffer_units": mandated_buffer,
        "recommended_stock_units": recommended,
    }
