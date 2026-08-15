"""Calculation rules from SCAFFOLD section 1.3 / PRD section 3."""

from __future__ import annotations

import math
from decimal import Decimal

import db
from util import round_half_up_int, round_half_up_1dp


HANDLING_PCT = Decimal("0.06")
BASE_RATE_CENTS = 150
RUSH_MULTIPLIER = Decimal("1.25")
AT_RISK_THRESHOLD_PCT = Decimal("90.0")
LIQUIDATION_UNIT_CENTS = 2500
ATTIC_STOCK_PCT = Decimal("0.05")
DAILY_CAPACITY_HOURS = 8


# ---------------------------------------------------------------------------
# Prototype cost estimate (both variants, per-line round then sum)
# ---------------------------------------------------------------------------

def prototype_costs(bom_lines: list) -> tuple[int, int]:
    provisional_total = 0
    engineered_total = 0
    for line in bom_lines:
        qty = Decimal(line["quantity"])
        list_cost = Decimal(line["list_unit_cost_cents"])
        line_prov = round_half_up_int(qty * list_cost)
        provisional_total += line_prov
        negotiated = line.get("negotiated_unit_cost_cents")
        eng_basis = Decimal(negotiated) if negotiated is not None else list_cost
        line_eng = round_half_up_int(qty * eng_basis)
        engineered_total += line_eng
    return provisional_total, engineered_total


# ---------------------------------------------------------------------------
# Kit total cost (per-line round then sum) and component count
# ---------------------------------------------------------------------------

def kit_totals(config_lines: list) -> tuple[int, int]:
    total_components = 0
    kit_total = 0
    for line in config_lines:
        qty = int(line["quantity"])
        total_components += qty
        raw = Decimal(qty) * Decimal(int(line["unit_cost_cents"])) * (Decimal("1") + HANDLING_PCT)
        kit_total += round_half_up_int(raw)
    return total_components, kit_total


# ---------------------------------------------------------------------------
# Wave release charge (tiered + rush)
# ---------------------------------------------------------------------------

def wave_release_charge(kit_total_components: int, wave: dict) -> int:
    committed_after = wave["committed_units"] + kit_total_components
    capacity = wave["capacity_units"]
    utilization_after = (Decimal(committed_after) / Decimal(capacity)) * Decimal("100")
    if utilization_after < Decimal("70"):
        tier = Decimal("1.0")
    elif utilization_after < Decimal("90"):
        tier = Decimal("1.15")
    else:
        tier = Decimal("1.35")
    rush = RUSH_MULTIPLIER if wave["status"] == "IN_PRODUCTION" else Decimal("1.0")
    raw = Decimal(kit_total_components) * Decimal(BASE_RATE_CENTS) * tier * rush
    return round_half_up_int(raw)


# ---------------------------------------------------------------------------
# Wave utilization (1 decimal place; posture boundary inclusive at 90.0)
# ---------------------------------------------------------------------------

def recompute_wave_utilization(wave: dict) -> None:
    capacity = wave["capacity_units"]
    committed = wave["committed_units"]
    pct = (Decimal(committed) / Decimal(capacity)) * Decimal("100")
    pct_1dp = round_half_up_1dp(pct)
    wave["utilization_pct"] = pct_1dp
    wave["utilization_posture"] = (
        "AT_RISK" if Decimal(str(pct_1dp)) >= AT_RISK_THRESHOLD_PCT else "NORMAL"
    )


# ---------------------------------------------------------------------------
# Staging overlap (half-open intervals; adjacency allowed; HELD only)
# ---------------------------------------------------------------------------

def staging_conflict(bay_code: str, new_start, new_end) -> bool:
    for existing in db.reservations.values():
        if existing["staging_bay_code"] != bay_code:
            continue
        if existing["status"] != "HELD":
            continue
        ex_start = existing["_start_dt"]
        ex_end = existing["_end_dt"]
        if new_start < ex_end and ex_start < new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Crew daily capacity (aggregate; FAILED/COMPLETE excluded; equality allowed)
# ---------------------------------------------------------------------------

def crew_committed_hours(crew_code: str, delivery_date: str) -> int:
    total = 0
    for d in db.deliveries.values():
        if d["crew_code"] != crew_code or d["delivery_date"] != delivery_date:
            continue
        if d["status"] in ("SCHEDULED", "DISPATCHED", "DELIVERED"):
            total += d["estimated_install_hours"]
    return total


# ---------------------------------------------------------------------------
# Attic stock valuation
# ---------------------------------------------------------------------------

RECOVERY_RATES = {
    "RETURN_VENDOR": Decimal("0.80"),
    "SCRAP": Decimal("0.05"),
    "DONATE": Decimal("0.00"),
}


def attic_recovery_value(ledger: dict, program: dict, disposition_type: str) -> int:
    qty = ledger["quantity_on_hand"]
    if qty == 0:
        return 0
    rate = RECOVERY_RATES[disposition_type]
    if program.get("attic_valuation_method", "PROGRAM_AVERAGE") == "LIQUIDATION":
        unit = Decimal(LIQUIDATION_UNIT_CENTS)
    else:
        unit = Decimal(ledger["unit_cost_cents"])
    raw = Decimal(qty) * unit * rate
    return round_half_up_int(raw)


# ---------------------------------------------------------------------------
# Attic ledger initial values
# ---------------------------------------------------------------------------

def attic_initial_quantity(total_components: int) -> int:
    return math.ceil(Decimal(total_components) * ATTIC_STOCK_PCT)


def attic_unit_cost(kit_total_cost_cents: int, total_components: int) -> int:
    raw = Decimal(kit_total_cost_cents) / Decimal(total_components)
    return round_half_up_int(raw)


def reorder_required(quantity_on_hand: int, reorder_point: int) -> bool:
    return quantity_on_hand <= reorder_point
