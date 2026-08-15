"""Calculation rules (scaffold §1.3): holdover_time, invoice_charges,
collection_percentage, tank_selector, ops checkpoint helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import util
from services import derived

# ---- holdover_time constants ----
HOLDOVER_MIN_FLOOR = 5
TEMP_FACTOR_COLD = Decimal("0.8")
TEMP_CUTOFF_CELSIUS = Decimal("-10")
RATE_FACTOR = {
    "LIGHT": Decimal("1.0"),
    "MODERATE": Decimal("0.75"),
    "HEAVY": Decimal("0.5"),
}
HOLDOVER_TABLE = {
    "TYPE_I": {
        "ANY": {"NONE": 45, "SNOW": 25, "FREEZING_FOG": 15, "FREEZING_RAIN": 9, "MIXED": 12}
    },
    "TYPE_IV": {
        100: {"NONE": 120, "SNOW": 60, "FREEZING_FOG": 40, "FREEZING_RAIN": 25, "MIXED": 30},
        75: {"NONE": 80, "SNOW": 35, "FREEZING_FOG": 25, "FREEZING_RAIN": 15, "MIXED": 18},
        50: {"NONE": 45, "SNOW": 20, "FREEZING_FOG": 12, "FREEZING_RAIN": 7, "MIXED": 9},
    },
}

# ---- invoice constants ----
PAD_FEE = {"SMALL": 20000, "MEDIUM": 35000, "LARGE": 60000}
RATE = {"TYPE_I": 90, "TYPE_IV": 140}
TIER_1_END = 5000
TIER_2_END = 20000
TIER_MULT = {"TIER_1": Decimal("1.0"), "TIER_2": Decimal("0.92"), "TIER_3": Decimal("0.85")}

SIZE_TO_ESTIMATED = {"SMALL": 200, "MEDIUM": 500, "LARGE": 1200}
SIZE_ORDER = {"SMALL": 0, "MEDIUM": 1, "LARGE": 2}
REQUIRED_CREW = {"LEVEL_1": 4, "LEVEL_2": 8, "LEVEL_3": 14}
REPORTABLE_SPILL_L = 100
PRIORITY_ORDER = {"EMERGENCY": 0, "SCHEDULED": 1, "FLEXIBLE": 2}
EXPIRE_EPOCHS = 2


def compute_holdover(tank, station_id, oat_celsius):
    """Return (holdover_minutes:int, holdover_variant:str)."""
    fluid_type = tank["fluid_type"]
    concentration_pct = tank["concentration_pct"]
    event = derived.active_weather_event(station_id)
    if event is None:
        precip_key = "NONE"
        rate = None
    else:
        precip_key = event["precip_type"]
        rate = event["precip_rate"]
    if fluid_type == "TYPE_I":
        base = HOLDOVER_TABLE["TYPE_I"]["ANY"][precip_key]
    else:
        base = HOLDOVER_TABLE["TYPE_IV"][concentration_pct][precip_key]
    oat = Decimal(str(oat_celsius))
    temp_factor = TEMP_FACTOR_COLD if oat <= TEMP_CUTOFF_CELSIUS else Decimal("1.0")
    result = Decimal(base) * temp_factor
    if event is not None and rate in ("MODERATE", "HEAVY"):
        variant = "RATE_ADJUSTED"
        result = result * RATE_FACTOR[rate]
    else:
        variant = "TABLE"
    minutes = int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if minutes < HOLDOVER_MIN_FLOOR:
        minutes = HOLDOVER_MIN_FLOOR
    return minutes, variant


def collection_pct_and_flag(collected_liters, actual_liters, min_collection_pct):
    pct = (Decimal(str(collected_liters)) / Decimal(str(actual_liters)) * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    flag = "OK" if pct >= Decimal(str(min_collection_pct)) else "BELOW_MINIMUM"
    return float(pct), flag


def select_tank(station_id, fluid_type, estimated_liters):
    """Tank selector: eligible = same station, matching fluid_type, not EMPTY,
    available_liters >= estimated_liters. Rank available DESC, created_at ASC."""
    eligible = []
    for tank in db.fluid_tanks.values():
        if tank["station_id"] != station_id:
            continue
        if tank["fluid_type"] != fluid_type:
            continue
        derived.recompute_tank(tank)
        if tank["status"] == "EMPTY":
            continue
        if Decimal(str(tank["available_liters"])) < Decimal(str(estimated_liters)):
            continue
        eligible.append(tank)
    if not eligible:
        return None
    eligible.sort(key=lambda t: t["_created_dt"])
    eligible.sort(key=lambda t: Decimal(str(t["available_liters"])), reverse=True)
    return eligible[0]


def queue_sort_key(req):
    return (
        PRIORITY_ORDER[req["priority"]],
        req["_departure_dt"],
        req["_created_dt"],
    )


def month_key_now():
    now = db.get_clock()
    return now.strftime("%Y-%m")


def lazy_month_reset(airline):
    """Reset monthly_billed_liters to 0 when the calendar month rolls."""
    key = month_key_now()
    if airline.get("month_key") != key:
        airline["month_key"] = key
        airline["monthly_billed_liters"] = 0


def compute_invoice_charges(operation, airline, station):
    """Return dict with pad_fee_cents, fluid_charge_cents, storm_surcharge_cents,
    total_cents. Caller must have already lazy-reset the airline month."""
    pad = db.pads[operation["pad_id"]]
    tank = db.fluid_tanks[operation["tank_id"]]
    pad_fee = PAD_FEE[pad["max_size_class"]]
    # Marginal-tier fluid charge across monthly tiers.
    base_liters = int(airline["monthly_billed_liters"])
    rate = Decimal(str(RATE[tank["fluid_type"]]))

    def tier_of(position):
        # position: 0-based cumulative monthly liter position (Decimal-safe)
        if position < Decimal(TIER_1_END):
            return "TIER_1"
        if position < Decimal(TIER_2_END):
            return "TIER_2"
        return "TIER_3"

    # Distribute actual_liters across monthly tiers starting at base_liters.
    # Each segment (within one tier) is rounded half-up to integer cents, then
    # summed.
    fluid_charge = Decimal("0")
    position = Decimal(base_liters)  # next cumulative monthly index
    liters_left = Decimal(str(operation["actual_liters"]))
    while liters_left > 0:
        tier = tier_of(position)
        if tier == "TIER_1":
            boundary = Decimal(TIER_1_END)
        elif tier == "TIER_2":
            boundary = Decimal(TIER_2_END)
        else:
            boundary = None
        if boundary is None:
            segment = liters_left
        else:
            segment = min(liters_left, boundary - position)
        if segment <= 0:
            break
        segment_cents = (segment * rate * TIER_MULT[tier]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        fluid_charge += segment_cents
        liters_left -= segment
        position += segment
    fluid_charge_cents = int(fluid_charge)
    # Storm surcharge snapshot: was an ACTIVE LEVEL_2/LEVEL_3 event present at
    # the moment the operation transitioned to AWAITING_INSPECTION?
    surcharge = 0
    if operation.get("_storm_surcharge_applies"):
        raw = (
            (Decimal(pad_fee) + Decimal(fluid_charge_cents))
            * Decimal(str(station["storm_surcharge_pct"]))
            / Decimal("100")
        )
        surcharge = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = pad_fee + fluid_charge_cents + surcharge
    return {
        "pad_fee_cents": pad_fee,
        "fluid_charge_cents": fluid_charge_cents,
        "storm_surcharge_cents": surcharge,
        "total_cents": total,
    }
