"""The calculation layer.

One function per rule declared in SCAFFOLD.calculations, implemented to the
letter of PRD sections 2.7, 2.9, 3.3, 3.5, 3.6, 3.7 and 3.9.  All money and
gallon arithmetic runs on decimal.Decimal; the rounding order of the shortfall
fee and of the equipment exposure is pinned per PRD 2.7.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core import D, ceil_int, db, floor_div_units, round_half_up

# --- constants (SCAFFOLD.calculations[].constants) --------------------------
OUNCES_PER_GALLON = Decimal(128)
HORIZON_DAYS = Decimal(14)
TIER_FACTOR = {"SMALL": Decimal("1.00"), "MEDIUM": Decimal("1.15"), "LARGE": Decimal("1.30")}
CRITICAL_COVER_DAYS = Decimal(3)
LOW_COVER_DAYS = Decimal(7)

MONTH_DAYS = 30
DEPRECIATION_PER_MONTH = Decimal("0.01")
ESCALATION_PER_MONTH = Decimal("0.005")
RECALL_EXPOSURE_FLOOR_CENTS = 450000

SYMPTOM_WEIGHT = {"NO_POUR": 60, "OFF_RATIO": 40, "LEAK": 55, "CO2_LOW": 30, "ICE_FAULT": 25}
POSTURE_ADD = {"OPEN": 0, "RESTRICTED": 15, "FROZEN": 30}
OVERDUE_ADD_PER_TASK = 5
OVERDUE_ADD_CAP = 20
CALIBRATION_ADD = 10
SCORE_CAP = 100
CRITICAL_AT = 85
URGENT_AT = 60

HARDNESS_BASELINE_GPG = Decimal(10)
HARDNESS_DERATE_PER_GPG = Decimal("0.02")
GRACE_HOURS = 72

FROZEN_OVERDUE_AT = 3
RESTRICTED_OVERDUE_AT = 1

ALERT_RANK = {"CRITICAL": 0, "LOW": 1}

REPORT_WINDOW_DAYS = 30

STOP_BUFFER_MINUTES = 0
TRAVEL_BUFFER_MINUTES = 30

BRIX_TARGET_RATIO = Decimal("5.00")
BRIX_TOLERANCE = Decimal("0.15")

FORECAST_UNIT_STATUSES = ("IN_SERVICE", "SERVICE_HOLD")
EXPOSURE_UNIT_STATUSES = ("IN_SERVICE", "SERVICE_HOLD", "RECALL_STAGED")
REPORT_UNIT_STATUSES = ("IN_SERVICE", "SERVICE_HOLD", "RECALL_STAGED")


# ---------------------------------------------------------------------------
# calculations.outlet_service_posture
# ---------------------------------------------------------------------------
def outlet_service_posture(outlet):
    """Evaluated top to bottom; the first matching clause wins.  FROZEN is
    tested before RESTRICTED, so a held outlet with zero overdue tasks is
    still FROZEN (PRD 2.10)."""
    if outlet["open_compliance_hold_count"] >= 1 or outlet["overdue_task_count"] >= FROZEN_OVERDUE_AT:
        return "FROZEN"
    if outlet["overdue_task_count"] >= RESTRICTED_OVERDUE_AT:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# calculations.brix_calibration_outcome
# ---------------------------------------------------------------------------
def brix_calibration_outcome(measured_ratio):
    deviation = abs(D(measured_ratio) - BRIX_TARGET_RATIO)
    return "PASS" if deviation <= BRIX_TOLERANCE else "FAIL"


# ---------------------------------------------------------------------------
# calculations.maintenance_due_evaluation
# ---------------------------------------------------------------------------
def effective_gallon_interval(gallon_interval, water_hardness_gpg):
    """Derated once, at task creation, and stored (PRD 3.5)."""
    if gallon_interval is None:
        return None
    excess = D(water_hardness_gpg) - HARDNESS_BASELINE_GPG
    if excess < 0:
        excess = Decimal(0)
    factor = Decimal(1) - HARDNESS_DERATE_PER_GPG * excess
    return round_half_up(D(gallon_interval) * factor, 2)


def maintenance_due_evaluation(task, unit, clock):
    """Returns (breach_kind, next_status).  The GALLON breach is weighed first
    and outranks any calendar reasoning; it skips the grace band entirely."""
    eff = task.get("effective_gallon_interval")
    gallons_since_change = D(unit["lifetime_dispensed_gallons"]) - D(unit["gallons_at_last_filter_change"])
    if eff is not None and gallons_since_change >= D(eff):
        return "GALLON", "OVERDUE"
    due_at = task["_due_at"]
    if clock >= due_at + timedelta(hours=GRACE_HOURS):
        return "DATE", "OVERDUE"
    if clock >= due_at:
        return "DATE", "DUE"
    return None, task["status"]


# ---------------------------------------------------------------------------
# calculations.service_call_severity
# ---------------------------------------------------------------------------
def service_call_severity(symptom_code, outlet, unit):
    base = SYMPTOM_WEIGHT[symptom_code]
    posture_add = POSTURE_ADD[outlet["service_posture"]]
    overdue_add = min(OVERDUE_ADD_CAP, OVERDUE_ADD_PER_TASK * outlet["overdue_task_count"])
    calib_add = CALIBRATION_ADD if unit["calibration_status"] == "OUT_OF_SPEC" else 0
    score = min(SCORE_CAP, base + posture_add + overdue_add + calib_add)
    if score >= CRITICAL_AT:
        band = "CRITICAL"
    elif score >= URGENT_AT:
        band = "URGENT"
    else:
        band = "ROUTINE"
    return score, band


# ---------------------------------------------------------------------------
# calculations.outlet_supply_forecast
# ---------------------------------------------------------------------------
def _outlet_unit_ids(outlet_id, statuses):
    return {
        unit["id"]
        for unit in db.units.values()
        if unit["outlet_id"] == outlet_id and unit["status"] in statuses
    }


def trailing_daily_ounces(position, window_days, clock):
    """Step 1 - half-open telemetry window [clock - window_days, clock)."""
    unit_ids = _outlet_unit_ids(position["outlet_id"], FORECAST_UNIT_STATUSES)
    window_start = clock - timedelta(days=window_days)
    total = Decimal(0)
    for reading in db.readings.values():
        if reading["supply_item_id"] != position["supply_item_id"]:
            continue
        if reading["dispenser_unit_id"] not in unit_ids:
            continue
        at = reading["_reading_at"]
        if at >= window_start and at < clock:
            total += D(reading["dispensed_ounces"])
    return total / Decimal(window_days)


def alert_band(on_hand_units, ounces_per_unit, daily_ounces):
    """Step 5 - alert band from days of cover on hand, compared unrounded."""
    if daily_ounces == 0:
        coverage = None  # unlimited cover
    else:
        coverage = (Decimal(on_hand_units) * D(ounces_per_unit)) / daily_ounces
    if on_hand_units == 0 or (coverage is not None and coverage < CRITICAL_COVER_DAYS):
        return "CRITICAL"
    if coverage is not None and coverage < LOW_COVER_DAYS:
        return "LOW"
    return "NONE"


def outlet_supply_forecast(position, item, outlet, variant, window_days, clock):
    daily_ounces = trailing_daily_ounces(position, window_days, clock)

    # Step 2 - variant specific 14 day horizon
    projected = daily_ounces * HORIZON_DAYS
    if variant == "THROUGHPUT_PROJECTED":
        projected = projected * TIER_FACTOR[outlet["throughput_tier"]]

    # Step 3 - net requirement in units
    raw_units = projected / D(item["ounces_per_unit"])
    net = raw_units - Decimal(position["on_hand_units"])
    if net < 0:
        net = Decimal(0)
    forecast_units = round_half_up(net, 2)

    # Step 4 - promotional suppression, applied AFTER step 3 and overwriting it
    promo_suppressed = False
    if item["promotional"]:
        start = item.get("_promo_start")
        end = item.get("_promo_end")
        inside = start is not None and end is not None and start <= clock < end
        if not inside:
            forecast_units = Decimal("0.00")
            promo_suppressed = True

    requested_units = ceil_int(forecast_units)

    # Step 5 - alert band
    level = alert_band(position["on_hand_units"], item["ounces_per_unit"], daily_ounces)

    return {
        "daily_ounces": daily_ounces,
        "forecast_units": forecast_units,
        "requested_units": requested_units,
        "promo_suppressed": promo_suppressed,
        "alert_level": level,
    }


# ---------------------------------------------------------------------------
# calculations.equipment_recall_exposure
# ---------------------------------------------------------------------------
def months_in_service(unit, clock):
    """Whole 30-day months, truncated downward (PRD 2.7)."""
    return (clock - unit["_installed_at"]) // timedelta(days=MONTH_DAYS)


def equipment_recall_exposure(agreement, clock, variant):
    total = 0
    for unit in db.units.values():
        if unit["agreement_id"] != agreement["id"]:
            continue
        if unit["status"] not in EXPOSURE_UNIT_STATUSES:
            continue
        months = months_in_service(unit, clock)
        value = Decimal(agreement["equipment_value_cents"])
        if variant == "BOOK_VALUE":
            multiplier = Decimal(1) - DEPRECIATION_PER_MONTH * Decimal(months)
            if multiplier < 0:
                multiplier = Decimal(0)
        else:  # REPLACEMENT_RISK
            multiplier = Decimal(1) + ESCALATION_PER_MONTH * Decimal(months)
        # round per unit BEFORE summation (pinned order, PRD 2.7)
        total += int(round_half_up(value * multiplier, 0))
    return total


# ---------------------------------------------------------------------------
# calculations.agreement_shortfall_fee
# ---------------------------------------------------------------------------
def _quarter_end(quarter_start):
    month = quarter_start.month + 3
    year = quarter_start.year
    if month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def assessed_quarters(period_start, period_end):
    """A quarter enters the assessment when its own start instant lies inside
    the half-open request period [period_start, period_end)."""
    starts = []
    for year in range(period_start.year - 1, period_end.year + 2):
        for month in (1, 4, 7, 10):
            quarter_start = datetime(year, month, 1, tzinfo=timezone.utc)
            if period_start <= quarter_start < period_end:
                starts.append(quarter_start)
    return sorted(starts)


def agreement_shortfall_fee(agreement, period_start, period_end):
    unit_ids = {u["id"] for u in db.units.values() if u["agreement_id"] == agreement["id"]}
    quarter_commitment = D(agreement["annual_commitment_gallons"]) / Decimal(4)  # exact, never rounded
    fee_per_gallon = Decimal(agreement["shortfall_fee_cents_per_gallon"])

    shortfall_sum = Decimal(0)
    fee_cents_sum = 0
    quarters = []
    for quarter_start in assessed_quarters(period_start, period_end):
        quarter_end = _quarter_end(quarter_start)
        ounces = Decimal(0)
        for reading in db.readings.values():
            if reading["dispenser_unit_id"] not in unit_ids:
                continue
            at = reading["_reading_at"]
            if at >= quarter_start and at < quarter_end:
                ounces += D(reading["dispensed_ounces"])
        dispensed_gallons = ounces / OUNCES_PER_GALLON
        shortfall = quarter_commitment - dispensed_gallons
        if shortfall < 0:
            shortfall = Decimal(0)
        # ROUND HERE: per quarter, to whole cents, before summing
        quarter_fee = int(round_half_up(shortfall * fee_per_gallon, 0))
        shortfall_sum += shortfall
        fee_cents_sum += quarter_fee
        quarters.append((quarter_start, shortfall, quarter_fee))

    return {
        "assessed_shortfall_gallons": round_half_up(shortfall_sum, 2),
        "assessed_fee_cents": fee_cents_sum,
        "quarters": quarters,
    }


# ---------------------------------------------------------------------------
# calculations.stop_window_overlap  (half-open, zero buffer)
# ---------------------------------------------------------------------------
def stop_window_overlap(route_id, new_start, new_end, exclude_stop_id=None):
    for stop in db.stops.values():
        if stop["route_id"] != route_id:
            continue
        if exclude_stop_id is not None and stop["id"] == exclude_stop_id:
            continue
        if stop["status"] not in ("PENDING", "ARRIVED"):
            continue
        if stop["_window_start"] < new_end and new_start < stop["_window_end"]:
            return True
    return False


# ---------------------------------------------------------------------------
# calculations.van_window_overlap  (closed interval, 30 minute pad both sides)
# ---------------------------------------------------------------------------
def van_window_overlap(van_code, new_start, new_end, exclude_call_id=None):
    low = new_start - timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    high = new_end + timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for call in db.calls.values():
        if exclude_call_id is not None and call["id"] == exclude_call_id:
            continue
        if call["van_code"] != van_code:
            continue
        if call["status"] not in ("DISPATCHED", "ON_SITE"):
            continue
        other_start = call.get("_window_start")
        other_end = call.get("_window_end")
        if other_start is None or other_end is None:
            continue
        if other_start <= high and low <= other_end:
            return True
    return False


# ---------------------------------------------------------------------------
# calculations.route_allocation_waterfall (ordering + grant math)
# ---------------------------------------------------------------------------
def allocation_candidates(positions, stop):
    """Eligibility filter, then the pinned processing order:
    CRITICAL before LOW, larger requested_units first, older position first."""
    eligible = [
        p
        for p in positions
        if p["outlet_id"] == stop["outlet_id"]
        and p["alert_level"] in ("LOW", "CRITICAL")
        and p["planned_route_stop_id"] is None
        and p["promo_suppressed"] is False
        and p["requested_units"] >= 1
    ]
    return sorted(
        eligible,
        key=lambda p: (ALERT_RANK[p["alert_level"]], -p["requested_units"], p["created_at"], p["_seq"]),
    )


def grant_for(requested_units, remaining_pool, remaining_capacity, case_pack_units):
    cap = min(requested_units, remaining_pool, remaining_capacity)
    if cap < 0:
        cap = 0
    return floor_div_units(cap, case_pack_units)


# ---------------------------------------------------------------------------
# calculations.brand_mix_report
# ---------------------------------------------------------------------------
def brand_mix_report(outlet, clock):
    period_end = clock
    period_start = clock - timedelta(days=REPORT_WINDOW_DAYS)
    unit_ids = _outlet_unit_ids(outlet["id"], REPORT_UNIT_STATUSES)

    totals = {}
    for reading in db.readings.values():
        if reading["dispenser_unit_id"] not in unit_ids:
            continue
        at = reading["_reading_at"]
        if not (period_start <= at < period_end):
            continue
        totals[reading["supply_item_id"]] = totals.get(reading["supply_item_id"], Decimal(0)) + D(
            reading["dispensed_ounces"]
        )

    items = []
    for item_id, ounces in totals.items():
        item = db.supply_items.get(item_id)
        if item is None:
            continue
        items.append((item, ounces))
    items.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_seq"]))

    total_ounces = sum((ounces for _item, ounces in items), Decimal(0))

    lines = []
    if items and total_ounces > 0:
        raw_shares = []
        for item, ounces in items:
            raw = ounces / total_ounces * Decimal(100)
            floored = (raw * 10).to_integral_value(rounding="ROUND_FLOOR") / Decimal(10)
            raw_shares.append((item, ounces, floored, raw - floored))
        floor_sum = sum((entry[2] for entry in raw_shares), Decimal(0))
        leftover_tenths = int(round_half_up((Decimal(100) - floor_sum) * 10, 0))
        order = sorted(
            range(len(raw_shares)),
            key=lambda i: (-raw_shares[i][3], raw_shares[i][0]["created_at"], raw_shares[i][0]["_seq"]),
        )
        awarded = {}
        for idx in order[: max(0, leftover_tenths)]:
            awarded[idx] = Decimal("0.1")
        for idx, (item, ounces, floored, _rem) in enumerate(raw_shares):
            share = floored + awarded.get(idx, Decimal(0))
            lines.append(
                {
                    "supply_item_id": item["id"],
                    "sku_code": item["sku_code"],
                    "brand_name": item["brand_name"],
                    "total_ounces": float(ounces),
                    "share_pct": float(share.quantize(Decimal("0.1"))),
                }
            )

    top_brand_name = None
    if items and total_ounces > 0:
        best = sorted(items, key=lambda pair: (-pair[1], pair[0]["created_at"], pair[0]["_seq"]))[0]
        top_brand_name = best[0]["brand_name"]

    promo_skus = []
    if outlet["service_posture"] != "FROZEN":
        promo_items = [
            item
            for item in db.supply_items.values()
            if item["promotional"]
            and item.get("_promo_start") is not None
            and item.get("_promo_end") is not None
            and item["_promo_start"] <= clock < item["_promo_end"]
        ]
        promo_items.sort(key=lambda item: (item["created_at"], item["_seq"]))
        promo_skus = [item["sku_code"] for item in promo_items]

    return {
        "period_start": period_start,
        "period_end": period_end,
        "total_ounces": float(total_ounces),
        "lines": lines,
        "top_brand_name": top_brand_name,
        "promo_available_skus": promo_skus,
    }
