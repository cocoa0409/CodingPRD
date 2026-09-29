"""Motive-power fleet sizing and charger matching (PRD 3.8, calculation 7)."""
from decimal import Decimal

from errors import ApiError
from store import db
from util import ceil_dec, q
from services.constants import (
    CHEM_LITHIUM,
    DOD_CAP,
    RESERVE_MULTI_SHIFT,
    RESERVE_SINGLE_SHIFT,
    SIZING_CHARGE_FACTOR,
    TEMP_DERATE_BASE_C,
    TEMP_DERATE_MAX,
    TEMP_DERATE_PER_DEGREE,
)


def scaling_factors(payload):
    daily = q(payload["shift_energy_kwh_per_shift"] * Decimal(payload["shifts_per_day"]), 2)
    shortfall = TEMP_DERATE_BASE_C - payload["ambient_temp_c"]
    if shortfall < 0:
        shortfall = Decimal("0")
    derate = q(min(Decimal("1.0") + shortfall * TEMP_DERATE_PER_DEGREE, TEMP_DERATE_MAX), 4)
    reserve = RESERVE_MULTI_SHIFT if payload["shifts_per_day"] >= 2 else RESERVE_SINGLE_SHIFT
    return daily, derate, reserve


def required_ah_for(design, daily_energy, voltage, derate, reserve):
    dod = DOD_CAP[design["chemistry"]]
    raw = daily_energy * Decimal("1000") / voltage / dod * derate * reserve
    return ceil_dec(raw)


def charge_hours(design, charger):
    dod = DOD_CAP[design["chemistry"]]
    factor = SIZING_CHARGE_FACTOR[design["chemistry"]]
    return q(design["nominal_capacity_ah"] * dod * factor / charger["output_amps"], 2)


def eligible_designs(payload, daily_energy, derate, reserve):
    voltage = payload["required_voltage_v"]
    preference = payload.get("chemistry_preference") or "ANY"
    pool = []
    for design in db.cell_designs.values():
        if design.get("approval_state") != "APPROVED":
            continue
        if preference != "ANY" and design["chemistry"] != preference:
            continue
        if design["nominal_pack_voltage_v"] != voltage:
            continue
        if design["pack_weight_kg"] > payload["compartment_max_kg"]:
            continue
        needed = required_ah_for(design, daily_energy, voltage, derate, reserve)
        if design["nominal_capacity_ah"] < Decimal(needed):
            continue
        pool.append((design, needed))
    # capacity ASC, weight ASC, created_at ASC; never falls through to id.
    pool.sort(
        key=lambda item: (
            item[0]["nominal_capacity_ah"],
            item[0]["pack_weight_kg"],
            item[0]["created_at"],
            item[0]["_seq"],
        )
    )
    return pool


def feasible_chargers(design, payload):
    matches = []
    for charger in db.chargers.values():
        if charger.get("charger_status") != "AVAILABLE":
            continue
        if charger["chemistry_compatibility"] != design["chemistry"]:
            continue
        if charger["output_voltage_v"] != payload["required_voltage_v"]:
            continue
        hours = charge_hours(design, charger)
        if hours <= payload["charge_window_hours"]:
            matches.append((charger, hours))
    matches.sort(
        key=lambda item: (
            item[0]["price_cents"],
            item[0]["output_amps"],
            item[0]["created_at"],
            item[0]["_seq"],
        )
    )
    return matches


def size_fleet(payload):
    """Run the whole selector. Raises when nothing matches; nothing is persisted."""
    daily, derate, reserve = scaling_factors(payload)
    pool = eligible_designs(payload, daily, derate, reserve)
    evaluated = len(pool)
    if evaluated == 0:
        raise ApiError(
            "ERR_NO_ELIGIBLE_CELL_DESIGN",
            "No APPROVED cell design satisfies the voltage, weight and capacity envelope",
        )
    for design, needed in pool:
        matches = feasible_chargers(design, payload)
        if not matches:
            continue
        charger, hours = matches[0]
        lithium = design["chemistry"] == CHEM_LITHIUM
        if lithium:
            batteries = payload["forklift_count"]
            chargers = payload["forklift_count"]
        else:
            batteries = payload["forklift_count"] * (1 if payload["shifts_per_day"] == 1 else 2)
            chargers = ceil_dec(Decimal(batteries) / Decimal("2"))
        capital = batteries * int(design["list_price_cents"]) + chargers * int(charger["price_cents"])
        return {
            "daily_energy_kwh": daily,
            "temp_derate_factor": derate,
            "reserve_factor": reserve,
            "required_ah": needed,
            "evaluated_design_count": evaluated,
            "selected_cell_design_id": design["id"],
            "selected_charger_id": charger["id"],
            "selected_charge_hours": hours,
            "recommended_battery_count": batteries,
            "recommended_charger_count": chargers,
            "fleet_capital_cents": capital,
        }
    raise ApiError(
        "ERR_NO_CHARGER_MATCH",
        "No AVAILABLE charger can refill an eligible pack inside the charge window",
    )
