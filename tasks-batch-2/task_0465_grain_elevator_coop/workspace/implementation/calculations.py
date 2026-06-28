"""Deterministic calculation rules (SCAFFOLD §1.3 / PRD §3). All precision per
PRD §2.7: bushels 4 dp half-up, dollars 2 dp half-up, cash floored to cents."""
from decimal import Decimal
from datetime import timedelta

from common import D, round2, round4, floor2

# --- Constants (SCAFFOLD calculations.constants) ---
STORAGE_RATE_PER_BU_PER_DAY = Decimal("0.0005")
GRACE_DAYS = 30
INITIAL_MARGIN_PER_CONTRACT = Decimal("2000")
MAINTENANCE_MARGIN_PER_CONTRACT = Decimal("1500")


# ---------------------------------------------------------------------------
# grade_in (PRD §3.2) — evaluation order is PINNED: dockage FIRST, then shrink.
# ---------------------------------------------------------------------------
def grade_in(ticket, commodity):
    gross = D(ticket["gross_weight_lbs"])
    tare = D(ticket["tare_weight_lbs"])
    dockage_pct = D(ticket["dockage_pct"])
    moisture_pct = D(ticket["moisture_pct"])

    test_weight = D(commodity["test_weight_lbs_per_bushel"])
    base_moisture = D(commodity["base_moisture_pct"])
    shrink_per_point = D(commodity["shrink_pct_per_point"])
    drying_cents = D(commodity["drying_cents_per_point_per_bushel"])

    net_weight = gross - tare
    dockage_lbs = net_weight * (dockage_pct / D(100))
    clean_weight = net_weight - dockage_lbs  # dockage removed FIRST

    moisture_points = moisture_pct - base_moisture
    if moisture_points < 0:
        moisture_points = D(0)

    wet_bushels = round4(clean_weight / test_weight)

    # shrink applied AFTER dockage, on the clean weight
    dry_weight = clean_weight * (D(1) - (shrink_per_point / D(100)) * moisture_points)
    net_dry_bushels = round4(dry_weight / test_weight)

    drying_charge = round2(
        D(net_dry_bushels) * moisture_points * drying_cents / D(100))

    return {
        "net_weight_lbs": float(net_weight),
        "clean_weight_lbs": float(clean_weight),
        "moisture_points": float(moisture_points),
        "wet_bushels": wet_bushels,
        "net_dry_bushels": net_dry_bushels,
        "drying_charge_dollars": drying_charge,
    }


# ---------------------------------------------------------------------------
# contract_net_price (PRD §3.4) — net_price carried to 4 dp.
# ---------------------------------------------------------------------------
def net_price(futures_leg, basis_leg):
    return round4(D(futures_leg) + D(basis_leg))


# ---------------------------------------------------------------------------
# storage_charge (PRD §3.6)
# ---------------------------------------------------------------------------
def whole_days_between(start_dt, end_dt):
    """Whole calendar days from start to end (floor of the elapsed span)."""
    delta = end_dt - start_dt
    days = delta.days  # timedelta.days is floored toward negative infinity
    return days


def storage_charge(position, priced_bushels, storage_basis, clock_dt):
    if position["program"] == "WAREHOUSE_RECEIPT":
        return round2(0)

    # DELAYED_PRICE
    start = position["_storage_start_dt"]
    grace_end = start + timedelta(days=GRACE_DAYS)
    chargeable_calendar_days = whole_days_between(grace_end, clock_dt)
    if chargeable_calendar_days < 0:
        chargeable_calendar_days = 0

    if storage_basis == "ESTIMATE":
        chargeable_days = chargeable_calendar_days
    else:  # ACTUAL
        chargeable_days = chargeable_calendar_days - position["frozen_days"]
        if chargeable_days < 0:
            chargeable_days = 0

    charge = D(priced_bushels) * STORAGE_RATE_PER_BU_PER_DAY * D(chargeable_days)
    return round2(charge)


# ---------------------------------------------------------------------------
# margin_mark_to_market (PRD §3.8)
# ---------------------------------------------------------------------------
def margin_totals(contracts):
    initial = INITIAL_MARGIN_PER_CONTRACT * D(contracts)
    maintenance = MAINTENANCE_MARGIN_PER_CONTRACT * D(contracts)
    return initial, maintenance


def compute_pnl(side, entry, mark, contract_bushels, contracts):
    if side == "SHORT":
        raw = (D(entry) - D(mark)) * D(contract_bushels) * D(contracts)
    else:  # LONG
        raw = (D(mark) - D(entry)) * D(contract_bushels) * D(contracts)
    return round2(raw)


# ---------------------------------------------------------------------------
# interval_overlap (PRD §3.2 dryer, §3.7 bay)
# ---------------------------------------------------------------------------
def bay_conflict(new_start, new_end, existing_start, existing_end):
    """Half-open [start, end): conflict iff new_start < existing_end AND
    new_end > existing_start. Touching does not conflict."""
    return new_start < existing_end and new_end > existing_start


def dryer_conflict(new_start, new_end, existing_start, existing_end, buffer_minutes):
    """Closed interval with buffer B: conflict iff new_start <= existing_end + B
    AND new_end + B >= existing_start. Touching/within-buffer is rejected."""
    b = timedelta(minutes=buffer_minutes)
    return new_start <= existing_end + b and new_end + b >= existing_start
