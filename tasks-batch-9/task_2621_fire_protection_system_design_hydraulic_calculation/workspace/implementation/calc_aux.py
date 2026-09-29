"""Auxiliary system demand derivation (PRD 3.5)."""
from decimal import Decimal

from utils import _dec, rhu

SYSTEM_TYPES = [
    "STANDPIPE_CLASS_I",
    "STANDPIPE_CLASS_II",
    "COOKING",
    "IN_RACK",
    "FOAM_DELUGE",
    "HAZMAT_DELUGE",
]
AGENT_TYPES = ["WET_CHEMICAL", "AFFF", "HIGH_EXPANSION_FOAM", "NONE"]
INTERLOCK_TYPES = ("COOKING", "HAZMAT_DELUGE")
QUALIFYING_IN_RACK_COMMODITIES = ("CLASS_IV", "GROUP_A_PLASTIC")

CLASS_I_FIRST_RISER_GPM = Decimal("500.0")
CLASS_I_ADDITIONAL_RISER_GPM = Decimal("250.0")
CLASS_I_CAP_GPM = Decimal("1000.0")
CLASS_I_HIGH_RISE_CAP_GPM = Decimal("1250.0")
HIGH_RISE_HEIGHT_FT = Decimal("150")
CLASS_II_FIRST_RISER_GPM = Decimal("100.0")
CLASS_II_ADDITIONAL_RISER_GPM = Decimal("75.0")
CLASS_II_CAP_GPM = Decimal("400.0")
COOKING_HOOD_BASE_GPM = Decimal("40.0")
COOKING_PER_APPLIANCE_GPM = Decimal("15.0")
COOKING_WATER_WASH_GPM = Decimal("60.0")
IN_RACK_PER_HEAD_GPM = Decimal("30.0")
IN_RACK_FLOOR_GPM = Decimal("150.0")
IN_RACK_CAP_GPM = Decimal("480.0")
FOAM_DENSITY = Decimal("0.16")
FOAM_FLOOR_GPM = Decimal("250.0")
HAZMAT_DENSITY = Decimal("0.30")
HAZMAT_FLOOR_GPM = Decimal("300.0")


def interlock_required(system_type):
    return system_type in INTERLOCK_TYPES


def demand_gpm(system_type, row, project):
    """The demand this system contributes to the project ledger, 1 decimal place."""
    if system_type == "STANDPIPE_CLASS_I":
        risers = Decimal(int(row["riser_count"]))
        value = CLASS_I_FIRST_RISER_GPM + CLASS_I_ADDITIONAL_RISER_GPM * (risers - 1)
        cap = (
            CLASS_I_CAP_GPM
            if _dec(project["building_height_ft"]) <= HIGH_RISE_HEIGHT_FT
            else CLASS_I_HIGH_RISE_CAP_GPM
        )
        if value > cap:
            value = cap
    elif system_type == "STANDPIPE_CLASS_II":
        risers = Decimal(int(row["riser_count"]))
        value = CLASS_II_FIRST_RISER_GPM + CLASS_II_ADDITIONAL_RISER_GPM * (risers - 1)
        if value > CLASS_II_CAP_GPM:
            value = CLASS_II_CAP_GPM
    elif system_type == "COOKING":
        value = COOKING_HOOD_BASE_GPM + COOKING_PER_APPLIANCE_GPM * Decimal(
            int(row["appliance_count"])
        )
        if row.get("water_wash_enabled"):
            value = value + COOKING_WATER_WASH_GPM
    elif system_type == "IN_RACK":
        value = IN_RACK_PER_HEAD_GPM * Decimal(int(row["in_rack_head_count"]))
        if value < IN_RACK_FLOOR_GPM:
            value = IN_RACK_FLOOR_GPM
        if value > IN_RACK_CAP_GPM:
            value = IN_RACK_CAP_GPM
    elif system_type == "FOAM_DELUGE":
        value = _dec(rhu(FOAM_DENSITY * _dec(row["protected_area_sqft"]), 1))
        if value < FOAM_FLOOR_GPM:
            value = FOAM_FLOOR_GPM
    else:
        value = _dec(rhu(HAZMAT_DENSITY * _dec(row["protected_area_sqft"]), 1))
        if value < HAZMAT_FLOOR_GPM:
            value = HAZMAT_FLOOR_GPM
    return rhu(value, 1)
