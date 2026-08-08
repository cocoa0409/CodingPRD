"""Measurement (baseline / delivered / performance) and payout (per-dispatch
tiered + settlement total) calculations. PRD §3.6 and §3.7."""
from decimal import Decimal

from errors import err
from store import db, parse_iso
from common import rhu
from models import get

# Constants (SCAFFOLD calculations)
BASELINE_LOOKBACK = 5
BASELINE_TOP_N = 3
WEATHER_ADJUST_FACTOR = Decimal("1.10")
OVERPERFORM_THRESHOLD = Decimal("1.10")
BONUS_MULTIPLIER = Decimal("1.15")


def event_duration_hours(event):
    start = parse_iso(event["window_start"])
    end = parse_iso(event["window_end"])
    seconds = (end - start).total_seconds()
    return Decimal(str(seconds)) / Decimal("3600")


def _mean(values):
    if not values:
        return Decimal("0")
    total = Decimal("0")
    for v in values:
        total += Decimal(str(v))
    return total / Decimal(len(values))


def measure_dispatch(dispatch, event, duration_hours):
    """Compute measurement fields for one dispatch. Returns a dict; does not
    mutate (caller applies atomically). Raises ERR_BASELINE_DATA_MISSING."""
    device_id = None
    enr = get("enrollments", dispatch["enrollment_id"])
    if enr is not None:
        device_id = enr["device_id"]

    # Baseline pool: device's BASELINE_WINDOW readings with null dispatch_event_id.
    pool = [r for r in db.data["meter_readings"].values()
            if r["device_id"] == device_id
            and r["reading_type"] == "BASELINE_WINDOW"
            and r.get("dispatch_event_id") is None]
    # Order interval_start DESC, tie-break created_at ASC (insertion order).
    pool = sorted(pool, key=lambda r: r["_seq"])
    pool = sorted(pool, key=lambda r: parse_iso(r["interval_start"]), reverse=True)
    lookback = pool[:BASELINE_LOOKBACK]
    if len(lookback) < BASELINE_TOP_N:
        raise err("ERR_BASELINE_DATA_MISSING",
                  "Device %s has fewer than %d baseline readings." % (device_id, BASELINE_TOP_N))

    if event["baseline_method_snapshot"] == "TEN_OF_TEN":
        ranked = sorted(lookback, key=lambda r: parse_iso(r["interval_start"]), reverse=True)
        ranked = sorted(ranked, key=lambda r: Decimal(str(r["kw_load"])), reverse=True)
        top = ranked[:BASELINE_TOP_N]
        baseline = _mean([r["kw_load"] for r in top])
    else:  # WEATHER_REGRESSION
        baseline = _mean([r["kw_load"] for r in lookback]) * WEATHER_ADJUST_FACTOR
    baseline_kw = rhu(baseline, 3)

    # Event-window load.
    evt = [r for r in db.data["meter_readings"].values()
           if r["device_id"] == device_id
           and r["reading_type"] == "EVENT_WINDOW"
           and r.get("dispatch_event_id") == event["id"]]
    avg_event_load = _mean([r["kw_load"] for r in evt])  # 0 when empty

    actual = baseline_kw - avg_event_load
    if actual < 0:
        actual = Decimal("0")
    delivered = rhu(actual * duration_hours, 3)

    assigned = Decimal(str(dispatch["assigned_reduction_kw"]))
    if assigned > 0:
        performance_ratio = rhu(actual / assigned, 4)
    else:
        performance_ratio = Decimal("0")

    return {
        "baseline_kw": float(baseline_kw),
        "avg_event_load_kw": float(avg_event_load),
        "actual_reduction_kw": float(actual),
        "delivered_kwh": float(delivered),
        "performance_ratio": float(performance_ratio),
    }


def dispatch_line_payout(dispatch, program, duration_hours):
    """Per-dispatch tiered payout -> whole cents, floored at 0 (PRD §3.7)."""
    delivered = Decimal(str(dispatch["delivered_kwh"]))
    assigned = Decimal(str(dispatch["assigned_reduction_kw"]))
    ratio = Decimal(str(dispatch["performance_ratio"]))
    R = Decimal(program["incentive_rate_cents_per_kwh"])
    P = Decimal(program["penalty_rate_cents_per_kwh"])
    F = Decimal(str(program["performance_floor_pct"]))

    assigned_kwh = assigned * duration_hours
    penalty = Decimal("0")
    if ratio >= OVERPERFORM_THRESHOLD:
        incentive = delivered * R * BONUS_MULTIPLIER
    elif ratio >= F:
        incentive = delivered * R
    else:
        incentive = delivered * R
        shortfall = assigned_kwh - delivered
        if shortfall < 0:
            shortfall = Decimal("0")
        penalty = shortfall * P
    net = incentive - penalty
    cents = rhu(net, 0)
    if cents < 0:
        cents = Decimal("0")
    return int(cents)


def settlement_totals(settlement, event, program, eligible):
    """Return (total_delivered_kwh, net_payment_cents). `eligible` are the
    event's COMPLETED dispatches (net_payment_cents already computed)."""
    duration_hours = event_duration_hours(event)
    total_delivered = rhu(sum(Decimal(str(d["delivered_kwh"])) for d in eligible)
                          if eligible else Decimal("0"), 3)

    if settlement["method_snapshot"] == "PAY_FOR_PERFORMANCE":
        net = sum(d["net_payment_cents"] for d in eligible)
    else:  # CAPACITY_PAYMENT
        cap_rate = Decimal(program["capacity_incentive_cents_per_kw"])
        P = Decimal(program["penalty_rate_cents_per_kwh"])
        capacity = sum((Decimal(str(d["assigned_reduction_kw"])) for d in eligible),
                       Decimal("0")) * cap_rate
        shortfall_total = Decimal("0")
        for d in eligible:
            s = Decimal(str(d["assigned_reduction_kw"])) * duration_hours - Decimal(str(d["delivered_kwh"]))
            if s < 0:
                s = Decimal("0")
            shortfall_total += s
        shortfall = shortfall_total * P
        net = rhu(capacity - shortfall, 0)
        if net < 0:
            net = Decimal("0")
        net = int(net)
    return float(total_delivered), int(net)
