"""Domain services: serialization (computed fields), calculations (PRD §3),
cascading side effects, and logical-clock transitions (PRD §2.7)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db
from util import parse_dt, parse_date

# ---------------------------------------------------------------------------
# Constants (PRD §2.5, §3)
# ---------------------------------------------------------------------------

MIX_COST_CENTS_PER_LITRE = 85
MIX_SHELF_HOURS = 72
TUNNEL_BUFFER_MINUTES = 30
MIN_REMAINING_SHELF_DAYS = 30
ABUSE_THRESHOLD_C = Decimal("-18.0")
HEAT_SHOCK_THRESHOLD_C = Decimal("-12.0")
STANDARD_FREE_MINUTES = 30
STANDARD_LOW_TIER_MAX_MINUTES = 120
STANDARD_RATE_LOW_CENTS_PER_MIN = 200
STANDARD_RATE_HIGH_CENTS_PER_MIN = 350
CARRIER_RATE_CENTS_PER_MIN = 150
CARRIER_DEDUCTIBLE_CENTS = 5000
CARRIER_CAP_PCT = Decimal("0.80")
HEAT_SHOCK_LIMIT_UM = {"NOVELTY": Decimal("120"), "BULK": Decimal("150")}
CLEAN_DURATION_MINUTES = {"RINSE": 30, "WASH": 90, "ALLERGEN_CIP": 240}
APPEAL_WINDOW_DAYS = 14
LAB_CYCLE_CAP = 3


def D(value):
    """Exact Decimal from a JSON number."""
    return Decimal(str(value))


def _ceil_div(numer, denom):
    return int((Decimal(int(numer)) / Decimal(int(denom))).to_integral_value(
        rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Computed fields and serialization
# ---------------------------------------------------------------------------

def litres_remaining(batch):
    """mix_litres_conservation: produced - consumed - wasted."""
    return batch["litres_produced"] - batch["litres_consumed"] - batch["litres_wasted"]


def lot_pallets(lot):
    """Per-lot ceiling FIRST (PRD §3.7): ceil((available+reserved)/units_per_pallet)."""
    product = db.get("products", lot["product_id"])
    upp = int(product["units_per_pallet"]) if product else 1
    return _ceil_div(lot["units_available"] + lot["units_reserved"], upp)


def _lot_covers_day(lot, day):
    """Occupancy window: produced_date <= day < best_before_date (half-open days)."""
    produced_day = parse_dt(lot["produced_at"]).date()
    best_before_day = parse_dt(lot["best_before"]).date()
    return produced_day <= day < best_before_day


def zone_occupied_pallets(zone_id, day):
    """Sum AFTER per-lot rounding, over lots AVAILABLE/QUARANTINED covering day."""
    total = 0
    for lot in db.all_of("lots"):
        if (
            lot["zone_id"] == zone_id
            and lot["status"] in ("AVAILABLE", "QUARANTINED")
            and _lot_covers_day(lot, day)
        ):
            total += lot_pallets(lot)
    return total


def fulfillment_pct(contract):
    """round_half_up(delivered / committed * 100, 2)."""
    pct = (
        Decimal(int(contract["delivered_units"]))
        * Decimal(100)
        / Decimal(int(contract["committed_units"]))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(pct)


def serialize(collection, ent):
    """Public view: strip internals, convert Decimals, attach computed fields."""
    out = {}
    for key, value in ent.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            value = float(value)
        out[key] = value
    if collection == "mix_batches":
        out["litres_remaining"] = float(litres_remaining(ent))
    elif collection == "lots":
        out["pallets"] = lot_pallets(ent)
    elif collection == "contracts":
        out["fulfillment_pct"] = fulfillment_pct(ent)
    elif collection == "zones":
        out["occupied_pallets"] = zone_occupied_pallets(ent["id"], db.now().date())
    return out


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def changeover_clean_level(line, to_product):
    """changeover_matrix (PRD §3.4): allergen containment, then flavor family."""
    from_product_id = line["last_product_id"]
    if from_product_id is None:
        level = "RINSE"
    else:
        from_allergens = line["last_allergens"] or []
        if not set(from_allergens) <= set(to_product["allergens"]):
            level = "ALLERGEN_CIP"
        else:
            from_product = db.get("products", from_product_id)
            from_family = from_product["flavor_family"] if from_product else None
            if from_family is not None and from_family != to_product["flavor_family"]:
                level = "WASH"
            else:
                level = "RINSE"
    return level, CLEAN_DURATION_MINUTES[level]


def tunnel_window_conflicts(tunnel_id, new_start, new_end):
    """Half-open occupancy with a trailing 30-minute cleanup buffer (PRD §3.5).

    Conflict iff new.start_at < existing.end_at + buffer AND
    existing.start_at < new.end_at. Exact adjacency at the buffered end is
    allowed (>= boundary). CANCELED/EXPIRED bookings occupy nothing."""
    buffer = timedelta(minutes=TUNNEL_BUFFER_MINUTES)
    for existing in db.all_of("bookings"):
        if existing["tunnel_id"] != tunnel_id:
            continue
        if existing["status"] not in ("BOOKED", "COMPLETED"):
            continue
        ex_start = parse_dt(existing["start_at"])
        ex_buffered_end = parse_dt(existing["end_at"]) + buffer
        if new_start < ex_buffered_end and ex_start < new_end:
            return True
    return False


def tunnel_throughput_ok(tunnel, planned_units, new_start, new_end):
    """planned_units <= max_units_per_hour * window hours (<= boundary)."""
    seconds = D((new_end - new_start).total_seconds())
    return Decimal(int(planned_units)) * Decimal(3600) <= Decimal(
        int(tunnel["max_units_per_hour"])
    ) * seconds


def zone_capacity_ok_for_new_lot(zone, product, actual_units, produced_dt):
    """Day-granular aggregate capacity over the new lot's occupancy window."""
    new_pallets = _ceil_div(actual_units, int(product["units_per_pallet"]))
    best_before_dt = produced_dt + timedelta(days=int(product["shelf_life_days"]))
    day = produced_dt.date()
    last_day = best_before_dt.date()
    capacity = int(zone["pallet_capacity"])
    while day < last_day:
        if zone_occupied_pallets(zone["id"], day) + new_pallets > capacity:
            return False
        day += timedelta(days=1)
    return True


def overrun_mix_usage(product, actual_units, mix_metered_litres):
    """Dual-variant run completion costing (PRD §3.6).

    Returns (mix_litres_theoretical 2dp, overrun_actual_pct 2dp,
    mix_cost_variance_cents int)."""
    fill = D(product["fill_volume_ml_per_unit"])
    target = D(product["target_overrun_pct"])
    units = D(actual_units)
    metered = D(mix_metered_litres)
    theoretical = (units * fill / (Decimal(1) + target / Decimal(100)) / Decimal(1000)
                   ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    overrun_actual = (((units * fill / (metered * Decimal(1000))) - Decimal(1))
                      * Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    theoretical_cost = int((theoretical * MIX_COST_CENTS_PER_LITRE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    actual_cost = int((metered * MIX_COST_CENTS_PER_LITRE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    return float(theoretical), float(overrun_actual), theoretical_cost - actual_cost


def temperature_replay(shipment):
    """Replay in-window readings (PRD §3.9).

    Returns (abuse_minutes int, peak_temp_c float|None, heat_shock_events int).
    Window: dispatched_at <= recorded_at <= closed_at (inclusive both ends);
    sorted by recorded_at ASC, ties by created_at ASC (insertion order)."""
    dispatched_at = parse_dt(shipment["dispatched_at"])
    closed_at = parse_dt(shipment["closed_at"])
    readings = [
        r for r in db.all_of("readings")
        if r["shipment_id"] == shipment["id"]
    ]
    in_window = [
        r for r in readings
        if dispatched_at <= parse_dt(r["recorded_at"]) <= closed_at
    ]
    in_window.sort(key=lambda r: (parse_dt(r["recorded_at"]), r["_seq"]))
    if not in_window:
        return 0, None, 0
    temps = [D(r["temp_c"]) for r in in_window]
    abuse_minutes = 0
    for i in range(len(in_window) - 1):
        if temps[i] > ABUSE_THRESHOLD_C:
            delta = parse_dt(in_window[i + 1]["recorded_at"]) - parse_dt(
                in_window[i]["recorded_at"])
            abuse_minutes += int(delta.total_seconds() // 60)
    last = in_window[-1]
    last_at = parse_dt(last["recorded_at"])
    if last_at < closed_at and temps[-1] > ABUSE_THRESHOLD_C:
        abuse_minutes += int((closed_at - last_at).total_seconds() // 60)
    peak = max(temps)
    peak_temp_c = float(peak.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    heat_shock_events = 0
    for i in range(len(in_window) - 1):
        if temps[i] <= HEAT_SHOCK_THRESHOLD_C and temps[i + 1] > HEAT_SHOCK_THRESHOLD_C:
            heat_shock_events += 1
    return abuse_minutes, peak_temp_c, heat_shock_events


def claim_payouts(abuse_minutes, declared_value_cents):
    """Both variants computed at open-review (PRD §3.9); approve selects one.

    Evaluation order pinned: tiers -> deductible -> cap."""
    declared = int(declared_value_cents)
    m = int(abuse_minutes)
    # STANDARD: marginal tiers on abuse minutes, capped at declared value.
    if m <= STANDARD_FREE_MINUTES:
        standard = 0
    elif m <= STANDARD_LOW_TIER_MAX_MINUTES:
        standard = (m - STANDARD_FREE_MINUTES) * STANDARD_RATE_LOW_CENTS_PER_MIN
    else:
        standard = (
            (STANDARD_LOW_TIER_MAX_MINUTES - STANDARD_FREE_MINUTES)
            * STANDARD_RATE_LOW_CENTS_PER_MIN
            + (m - STANDARD_LOW_TIER_MAX_MINUTES) * STANDARD_RATE_HIGH_CENTS_PER_MIN
        )
    standard = min(standard, declared)
    # CARRIER: flat per-minute from minute 1, minus deductible, floor 0,
    # capped at 80% of declared value.
    if m == 0:
        carrier = 0
    else:
        raw = m * CARRIER_RATE_CENTS_PER_MIN - CARRIER_DEDUCTIBLE_CENTS
        carrier = max(0, raw)
        cap = int(Decimal(declared) * CARRIER_CAP_PCT)
        carrier = min(carrier, cap)
    return standard, carrier


def shortfall_penalty_cents(contract):
    """contract_fulfillment penalty (PRD §3.2): delivered -> pct -> tier -> penalty."""
    delivered = int(contract["delivered_units"])
    committed = int(contract["committed_units"])
    if delivered >= committed:
        return 0
    pct = fulfillment_pct(contract)
    if pct >= 90:
        rate = Decimal("0.10")
    elif pct >= 50:
        rate = Decimal("0.20")
    else:
        rate = Decimal("0.35")
    penalty = Decimal(committed - delivered) * Decimal(
        int(contract["unit_price_cents"])) * rate
    return int(penalty.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Cascading side effects
# ---------------------------------------------------------------------------

def release_allocations_for_lot(lot, reason, regress_loaded):
    """Release every ACTIVE allocation on a lot (complaint cascade / reject /
    expiry). Lot unit counters are mutated here; the caller touches the lot.
    Each released allocation and each mutated shipment is touched."""
    for alloc in db.all_of("allocations"):
        if alloc["lot_id"] != lot["id"] or alloc["status"] != "ACTIVE":
            continue
        units = int(alloc["units"])
        alloc["status"] = "RELEASED"
        if reason is not None:
            alloc["release_reason"] = reason
        db.touch(alloc)
        lot["units_reserved"] -= units
        lot["units_available"] += units
        shipment = db.get("shipments", alloc["shipment_id"])
        if shipment is not None:
            shipment["allocated_units"] -= units
            if regress_loaded and shipment["status"] == "LOADED":
                # A LOADED shipment losing an allocation regresses to PLANNED.
                shipment["status"] = "PLANNED"
            db.touch(shipment)


def quarantine_lot_cascade(lot, quarantined_by):
    """AVAILABLE -> QUARANTINED plus allocation-release cascade (PRD §3.7/§3.10)."""
    lot["quarantined_by"] = quarantined_by
    release_allocations_for_lot(lot, "COMPLAINT_CASCADE", regress_loaded=True)
    lot["status"] = "QUARANTINED"
    db.touch(lot)


# ---------------------------------------------------------------------------
# Logical-clock transitions (PRD §2.7)
# ---------------------------------------------------------------------------

def process_clock_transitions():
    """Fire all time-based transitions whose trigger instant has been reached."""
    now = db.now()
    # RELEASED mix batches expire at expires_at; unconsumed litres written off.
    for batch in db.all_of("mix_batches"):
        if batch["status"] == "RELEASED" and parse_dt(batch["expires_at"]) <= now:
            batch["status"] = "EXPIRED"
            batch["litres_wasted"] = batch["litres_produced"] - batch["litres_consumed"]
            db.touch(batch)
    # AVAILABLE lots expire at best_before; ACTIVE allocations system-released
    # (release_reason stays null for system expiry).
    for lot in db.all_of("lots"):
        if lot["status"] == "AVAILABLE" and parse_dt(lot["best_before"]) <= now:
            lot["status"] = "EXPIRED"
            release_allocations_for_lot(lot, None, regress_loaded=False)
            db.touch(lot)
    # BOOKED tunnel bookings expire strictly past end_at while the owning run
    # is neither IN_PRODUCTION nor ON_HOLD.
    for booking in db.all_of("bookings"):
        if booking["status"] != "BOOKED":
            continue
        if now > parse_dt(booking["end_at"]):
            run = db.get("runs", booking["run_id"])
            if run is not None and run["status"] not in ("IN_PRODUCTION", "ON_HOLD"):
                booking["status"] = "EXPIRED"
                db.touch(booking)
    # APPROVED contracts activate when the logical UTC date reaches start_date.
    today = now.date()
    for contract in db.all_of("contracts"):
        if contract["status"] == "APPROVED" and parse_date(
            contract["start_date"]
        ) <= today:
            contract["status"] = "ACTIVE"
            db.touch(contract)
