"""Manifest line-item mass math."""
from decimal import Decimal, ROUND_HALF_UP

from db import store


DENSITIES = {
    "BATH_DUMP": Decimal("1.2"),
    "SLUDGE_PRESS": Decimal("1.5"),
    "RINSE_CONCENTRATE": Decimal("1.2"),
}


def line_mass_kg(source_type, volume_liters):
    """round_half_up(volume_liters * density, 3)."""
    mass = Decimal(str(volume_liters)) * DENSITIES[source_type]
    return mass.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def recompute_manifest_total(manifest):
    """total_mass_kg = sum of line item mass_kg (3 decimals, round_half_up)."""
    total = Decimal("0")
    for li in store.manifest_line_items.values():
        if li["manifest_id"] == manifest["id"]:
            total += Decimal(str(li["mass_kg"]))
    manifest["total_mass_kg"] = total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
