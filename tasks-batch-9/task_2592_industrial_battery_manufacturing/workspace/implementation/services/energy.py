"""Formation energy, tariff banding and emission grams (PRD 3.5, calculation 1)."""
from decimal import Decimal

from util import band_hours, hours_between, q, q0
from services.constants import (
    BAY_UTILIZATION_FACTOR,
    EMISSION_FACTOR_G_PER_KWH,
)


def theoretical_kwh(lot, design, charge_factor):
    watt_hours = (
        Decimal(lot["quantity"])
        * Decimal(design["cells_per_battery"])
        * design["nominal_capacity_ah"]
        * design["cell_nominal_voltage_v"]
        * charge_factor
    )
    return watt_hours / Decimal("1000")


def nameplate_kwh(bay, start, end):
    return bay["rated_power_kw"] * hours_between(start, end) * BAY_UTILIZATION_FACTOR


def estimated_energy(lot, design, bay, charge_factor, start, end):
    return q(min(theoretical_kwh(lot, design, charge_factor), nameplate_kwh(bay, start, end)), 2)


def price_energy(plant, energy, peak_hours, offpeak_hours):
    """Split energy across the bands, then price each band and round per band."""
    total = peak_hours + offpeak_hours
    if total == 0:
        kwh_peak = Decimal("0.00")
    else:
        kwh_peak = q(energy * peak_hours / total, 2)
    kwh_offpeak = q(energy - kwh_peak, 2)
    cents = q0(kwh_peak * plant["peak_tariff_cents_per_kwh"]) + q0(
        kwh_offpeak * plant["offpeak_tariff_cents_per_kwh"]
    )
    return kwh_peak, kwh_offpeak, cents


def emission_grams(energy, chemistry):
    return q(energy * EMISSION_FACTOR_G_PER_KWH[chemistry], 2)


def provisional_pricing(plant, lot, design, bay, charge_factor, start, end):
    energy = estimated_energy(lot, design, bay, charge_factor, start, end)
    peak, offpeak = band_hours(start, end)
    _, _, cents = price_energy(plant, energy, peak, offpeak)
    return {
        "estimated_energy_kwh": energy,
        "scheduled_peak_hours": peak,
        "scheduled_offpeak_hours": offpeak,
        "provisional_charge_cents": cents,
        "reserved_emission_g": emission_grams(energy, lot["chemistry"]),
    }


def final_pricing(plant, lot, energy, start, end):
    peak, offpeak = band_hours(start, end)
    _, _, cents = price_energy(plant, energy, peak, offpeak)
    return {
        "actual_peak_hours": peak,
        "actual_offpeak_hours": offpeak,
        "final_charge_cents": cents,
        "consumed_emission_g": emission_grams(energy, lot["chemistry"]),
    }
