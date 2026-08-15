"""Business calculations per PRD section 3 and the scaffold calculations table.

All money math uses Decimal with ROUND_HALF_UP. Physical quantities are kept
as Decimal at the pinned precision and converted to float only for JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import db
from errors import (
    raise_err,
    ERR_POINT_OVERLOAD,
    ERR_BAY_OVERLOAD,
    ERR_GENERATOR_CAPACITY_EXCEEDED,
    ERR_HOUSE_POWER_OVERLOAD,
    ERR_PHASE_IMBALANCE,
    ERR_TRUCK_OVERLOAD,
)
from util import (
    round_half_up_int,
    round_half_up_2dp,
    round_half_up_4dp,
    to_decimal,
)

# --- rigging_point_factored_load constants ---
DYNAMIC_FACTOR = {
    "STRAIGHT": Decimal("1.10"),
    "BRIDLE": Decimal("1.10"),
    "DEAD_HANG": Decimal("1.00"),
}
MOTOR_SELF_WEIGHT_KG = Decimal("20")
BRIDLE_UNCERTAINTY = Decimal("1.15")

# --- power_distribution_sizing constants ---
FEEDER_LOSS_PCT_PER_100M = Decimal("0.03")
POWER_FACTOR = Decimal("0.9")
DERATING = Decimal("0.8")
VOLTAGE = 208
MAX_IMBALANCE_PCT = Decimal("0.15")
GENERATOR_TIERS_KVA = [45, 60, 100, 150, 200, 300, 400]

# --- crew_call_labor_cost constants ---
MEAL_WINDOW_HOURS = Decimal("6")
NON_UNION_ST_HOURS = Decimal("10")

# --- equipment_rental_billing constants ---
TIER1_DAYS = 3
TIER1_FACTOR = Decimal("1.0")
TIER2_DAYS = 7
TIER2_FACTOR = Decimal("0.5")
TIER3_FACTOR = Decimal("0.25")

# --- damage_valuation constants ---
DEPRECIATION_PER_YEAR = Decimal("0.10")
DEPRECIATION_FLOOR = Decimal("0.20")
DIMINUTION_PCT = Decimal("0.15")
DAYS_PER_YEAR_SECONDS = Decimal("31557600")  # 365.25 * 86400

# --- truck_pack_weight constants ---
DUNNAGE_PCT = Decimal("0.02")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def production_of_plot(plot: dict) -> dict:
    return db.productions.get(plot["production_id"])


def venue_of_production(production: dict) -> dict:
    return db.venues.get(production["venue_id"])


def venue_of_plot(plot: dict) -> dict:
    return venue_of_production(production_of_plot(plot))


# ---------------------------------------------------------------------------
# rigging_point_factored_load (PRD 3.3)
# ---------------------------------------------------------------------------

def compute_factored_load(hang_type: str, motor_count: int, deadweight_kg,
                          venue: dict) -> tuple[Decimal, Decimal]:
    """Return (factored_load_kg 2dp, utilization 4dp)."""
    dw = to_decimal(deadweight_kg)
    base = dw * DYNAMIC_FACTOR[hang_type]
    motors = to_decimal(motor_count) * MOTOR_SELF_WEIGHT_KG
    if hang_type == "BRIDLE":
        factored = (base + motors) * BRIDLE_UNCERTAINTY
    else:
        factored = base + motors
    factored = round_half_up_2dp(factored)
    capacity = to_decimal(venue["max_point_capacity_kg"])
    utilization = round_half_up_4dp(factored / capacity)
    return factored, utilization


def check_point_capacity(factored: Decimal, venue: dict) -> None:
    """Equality passes; strictly greater fails."""
    if factored > to_decimal(venue["max_point_capacity_kg"]):
        raise_err(ERR_POINT_OVERLOAD, "factored_load_kg exceeds venue max_point_capacity_kg")


# ---------------------------------------------------------------------------
# Plot total load
# ---------------------------------------------------------------------------

POINT_STATUSES_COUNTED_IN_PLOT_TOTAL = {"RESERVED", "UNDER_REVIEW", "APPROVED", "REJECTED"}


def recompute_plot_total(plot: dict) -> None:
    """Sum factored_load_kg over the plot's non-RELEASED-counted points.
    Bumps plot version only when the derived value actually changes."""
    total = Decimal("0")
    for point in db.rigging_points.values():
        if point["plot_id"] == plot["id"] and point["status"] in POINT_STATUSES_COUNTED_IN_PLOT_TOTAL:
            total += to_decimal(point["factored_load_kg"])
    total = round_half_up_2dp(total)
    new_val = float(total)
    if plot.get("total_factored_load_kg") != new_val:
        plot["total_factored_load_kg"] = new_val
        db.touch(plot)
    else:
        plot["total_factored_load_kg"] = new_val


# ---------------------------------------------------------------------------
# bay_aggregate_load_check (PRD 3.3)
# ---------------------------------------------------------------------------

def check_bay_aggregate_for_plot(plot: dict) -> None:
    """Plot-approval scope: for every bay used by THIS plot's non-RELEASED
    points, sum of factored loads must be <= venue.bay_aggregate_limit_kg."""
    production = production_of_plot(plot)
    venue = venue_of_production(production)
    limit = to_decimal(venue["bay_aggregate_limit_kg"])
    bay_sums: dict[int, Decimal] = {}
    for point in db.rigging_points.values():
        if point["plot_id"] != plot["id"] or point["status"] == "RELEASED":
            continue
        bay = point["bay_index"]
        bay_sums[bay] = bay_sums.get(bay, Decimal("0")) + to_decimal(point["factored_load_kg"])
    for bay, total in bay_sums.items():
        if total > limit:
            raise_err(ERR_BAY_OVERLOAD, f"bay {bay} aggregate load exceeds venue limit")


def check_bay_aggregate_for_point(point: dict) -> None:
    """Point-approval scope: production-wide sum over points with the same
    bay_index on the production's SUBMITTED/APPROVED plots, counting points in
    RESERVED/UNDER_REVIEW/APPROVED/REJECTED (RELEASED and SUPERSEDED excluded)."""
    plot = db.plots.get(point["plot_id"])
    production = production_of_plot(plot)
    venue = venue_of_production(production)
    limit = to_decimal(venue["bay_aggregate_limit_kg"])
    total = Decimal("0")
    for other in db.rigging_points.values():
        if other["bay_index"] != point["bay_index"]:
            continue
        if other["status"] == "RELEASED":
            continue
        other_plot = db.plots.get(other["plot_id"])
        if other_plot is None or other_plot["production_id"] != production["id"]:
            continue
        if other_plot["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        total += to_decimal(other["factored_load_kg"])
    if total > limit:
        raise_err(ERR_BAY_OVERLOAD, "bay aggregate load exceeds venue limit")


# ---------------------------------------------------------------------------
# power_distribution_sizing (PRD 3.4) — pinned evaluation order
# ---------------------------------------------------------------------------

def run_power_sizing(plan: dict, venue: dict) -> dict:
    """Compute sizing fields; raises the pinned errors on failure. Returns the
    computed values (persisted only when every check passes)."""
    l1 = plan["phase_l1_watts"]
    l2 = plan["phase_l2_watts"]
    l3 = plan["phase_l3_watts"]
    feeder = plan["feeder_length_m"]

    # 1. subtotal
    subtotal = Decimal(l1 + l2 + l3)
    # 2. feeder loss
    feeder_loss = subtotal * FEEDER_LOSS_PCT_PER_100M * (Decimal(feeder) / Decimal(100))
    # 3. total load
    total_load = round_half_up_2dp(subtotal + feeder_loss)

    required_kva = None
    selected_tier = None
    # 4/5. supply branch
    if plan["generator_required"]:
        required_kva = round_half_up_2dp(
            total_load / (POWER_FACTOR * DERATING * Decimal(1000))
        )
        tier = next((t for t in GENERATOR_TIERS_KVA if Decimal(t) >= required_kva), None)
        if tier is None:
            raise_err(ERR_GENERATOR_CAPACITY_EXCEEDED, "required_kva exceeds largest generator tier")
        selected_tier = tier
    else:
        per_phase_limit = Decimal(venue["house_power_amps_per_phase"]) * Decimal(VOLTAGE)
        for phase in (l1, l2, l3):
            if Decimal(phase) > per_phase_limit:
                raise_err(ERR_HOUSE_POWER_OVERLOAD, "phase load exceeds house service capacity")

    # 6. imbalance
    phases = [Decimal(l1), Decimal(l2), Decimal(l3)]
    max_phase = max(phases)
    min_phase = min(phases)
    if max_phase == 0:
        imbalance = Decimal("0")
    else:
        imbalance = round_half_up_4dp((max_phase - min_phase) / max_phase)
    if imbalance > MAX_IMBALANCE_PCT:
        raise_err(ERR_PHASE_IMBALANCE, "phase imbalance exceeds 15%")

    return {
        "total_load_watts": float(total_load),
        "required_kva": (float(required_kva) if required_kva is not None else None),
        "selected_generator_tier_kva": selected_tier,
        "max_phase_imbalance_pct": float(round_half_up_4dp(imbalance)),
    }


# ---------------------------------------------------------------------------
# crew_call_labor_cost (PRD 3.5) — per-line rounding pinned
# ---------------------------------------------------------------------------

def compute_labor_charge(technician: dict, worked_hours, venue: dict) -> int:
    """Per-assignment charge, rounded half-up to whole cents before summation."""
    worked = to_decimal(worked_hours)
    billable = max(worked, to_decimal(venue["min_call_hours"]))
    ruleset = venue["union_ruleset"]

    if ruleset in ("IATSE", "TEAMSTERS"):
        ot1_threshold = to_decimal(venue["ot1_threshold_hours"])
        ot2_threshold = to_decimal(venue["ot2_threshold_hours"])
        st_h = min(billable, ot1_threshold)
        ot1_h = min(max(billable - ot1_threshold, Decimal("0")), ot2_threshold - ot1_threshold)
        ot2_h = max(billable - ot2_threshold, Decimal("0"))
        meal_penalty_h = Decimal("2") if (ruleset == "IATSE" and worked > MEAL_WINDOW_HOURS) else Decimal("0")
        paid_hours = st_h + Decimal("1.5") * ot1_h + Decimal("2") * ot2_h + meal_penalty_h
    else:  # NON_UNION
        st_h = min(billable, NON_UNION_ST_HOURS)
        ot1_h = max(billable - NON_UNION_ST_HOURS, Decimal("0"))
        paid_hours = st_h + Decimal("1.5") * ot1_h

    rate = to_decimal(technician["hourly_rate_cents"])
    return round_half_up_int(rate * paid_hours)


# ---------------------------------------------------------------------------
# equipment_rental_billing (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_rental_charge(out_at: str, returned_at: str, daily_rate_cents: int) -> int:
    """Tiered day-rate billing; calendar dates touched, both endpoints
    inclusive; rounded half-up once per entry after summing per-day amounts."""
    out_dt = _parse_dt(out_at)
    ret_dt = _parse_dt(returned_at)
    days = (ret_dt.date() - out_dt.date()).days + 1
    if days < 1:
        days = 1
    rate = to_decimal(daily_rate_cents)
    tier1 = min(days, TIER1_DAYS)
    tier2 = min(max(days - TIER1_DAYS, 0), TIER2_DAYS - TIER1_DAYS)
    tier3 = max(days - TIER2_DAYS, 0)
    total = (
        Decimal(tier1) * rate * TIER1_FACTOR
        + Decimal(tier2) * rate * TIER2_FACTOR
        + Decimal(tier3) * rate * TIER3_FACTOR
    )
    return round_half_up_int(total)


def _parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# damage_valuation (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_damage_charge(report: dict, asset: dict) -> int:
    method = report["valuation_method"]
    if method == "DEPRECIATED":
        acquired = _parse_dt(asset["acquired_at"])
        now = db.clock_dt()
        elapsed_seconds = Decimal(str((now - acquired).total_seconds()))
        age_years = int(max(Decimal("0"), elapsed_seconds) // DAYS_PER_YEAR_SECONDS)
        factor = max(DEPRECIATION_FLOOR, Decimal("1.00") - DEPRECIATION_PER_YEAR * age_years)
        return round_half_up_int(to_decimal(asset["replacement_cost_cents"]) * factor)
    # REPAIR_QUOTE
    return round_half_up_int(to_decimal(report["repair_quote_cents"]) * (Decimal("1") + DIMINUTION_PCT))


# ---------------------------------------------------------------------------
# truck_pack_weight (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_pack_weight(schedule: dict, extra_entry: dict | None = None) -> Decimal:
    """Sum of asset weights over the schedule's OUT entries (optionally plus
    one prospective entry), uplifted by the dunnage allowance, 2dp half-up."""
    total = Decimal("0")
    for entry in db.pull_list_entries.values():
        if entry.get("load_schedule_id") != schedule["id"]:
            continue
        if entry["status"] != "OUT":
            continue
        if extra_entry is not None and entry["id"] == extra_entry["id"]:
            continue
        asset = db.assets.get(entry["asset_id"])
        if asset is not None:
            total += to_decimal(asset["weight_kg"])
    if extra_entry is not None:
        asset = db.assets.get(extra_entry["asset_id"])
        if asset is not None:
            total += to_decimal(asset["weight_kg"])
    return round_half_up_2dp(total * (Decimal("1") + DUNNAGE_PCT))


def check_truck_capacity(schedule: dict, extra_entry: dict) -> Decimal:
    """Recomputed pack including the new entry; equality passes, strictly
    greater fails with ERR_TRUCK_OVERLOAD. Returns the prospective weight."""
    truck = db.trucks.get(schedule["truck_id"])
    pack = compute_pack_weight(schedule, extra_entry)
    if truck is not None and pack > to_decimal(truck["capacity_kg"]):
        raise_err(ERR_TRUCK_OVERLOAD, "pack weight exceeds truck capacity")
    return pack


# ---------------------------------------------------------------------------
# settlement_totals (PRD 3.9)
# ---------------------------------------------------------------------------

def settlement_live_totals(production_id: str) -> dict:
    labor = 0
    for call in db.crew_calls.values():
        if call["production_id"] == production_id and call["status"] == "COMPLETED":
            labor += call.get("labor_cost_cents") or 0
    equipment = 0
    for entry in db.pull_list_entries.values():
        if entry["production_id"] == production_id and entry["status"] in ("RETURNED", "DAMAGED", "LOST"):
            equipment += entry.get("rental_charge_cents") or 0
    damage = 0
    for report in db.damage_reports.values():
        if report["production_id"] == production_id and report["status"] == "CHARGED":
            damage += report.get("assessed_charge_cents") or 0
    return {
        "labor_total_cents": labor,
        "equipment_total_cents": equipment,
        "damage_total_cents": damage,
        "grand_total_cents": labor + equipment + damage,
    }


def settlement_provisional_damage(production_id: str) -> int:
    """Snapshot at creation: assessed charges over reports then ASSESSED or
    CHARGED. Frozen thereafter."""
    total = 0
    for report in db.damage_reports.values():
        if report["production_id"] == production_id and report["status"] in ("ASSESSED", "CHARGED"):
            total += report.get("assessed_charge_cents") or 0
    return total


# ---------------------------------------------------------------------------
# production_readiness_posture (PRD 3.2)
# ---------------------------------------------------------------------------

def compute_posture(production: dict) -> str:
    approved_plot = None
    for plot in db.plots.values():
        if plot["production_id"] == production["id"] and plot["status"] == "APPROVED":
            approved_plot = plot
            break
    if approved_plot is None:
        return "BLOCKED"

    # (b) approved plot has >= 1 APPROVED point and every point is APPROVED/RELEASED
    points = [p for p in db.rigging_points.values() if p["plot_id"] == approved_plot["id"]]
    has_approved_point = any(p["status"] == "APPROVED" for p in points)
    all_points_ok = all(p["status"] in ("APPROVED", "RELEASED") for p in points)
    cond_b = has_approved_point and all_points_ok

    # (c) approved power plan
    cond_c = any(
        p["production_id"] == production["id"] and p["status"] == "APPROVED"
        for p in db.power_plans.values()
    )
    # (d) no pull entry in REQUESTED/RESERVED
    cond_d = not any(
        e["production_id"] == production["id"] and e["status"] in ("REQUESTED", "RESERVED")
        for e in db.pull_list_entries.values()
    )
    # (e) no crew call in DRAFT/PUBLISHED
    cond_e = not any(
        c["production_id"] == production["id"] and c["status"] in ("DRAFT", "PUBLISHED")
        for c in db.crew_calls.values()
    )

    if cond_b and cond_c and cond_d and cond_e:
        return "READY"
    return "PARTIAL"


def refresh_posture(production: dict | None) -> None:
    """Recompute posture; bump production version only when the derived value
    changes. A READY_FOR_LOADIN production whose posture drops below READY is
    downgraded to PLANNING. Terminal productions are not touched."""
    if production is None:
        return
    if production["status"] in ("SETTLED", "CANCELLED"):
        return
    new_posture = compute_posture(production)
    if production["status"] == "READY_FOR_LOADIN" and new_posture != "READY":
        production["status"] = "PLANNING"
        production["posture"] = new_posture
        db.touch(production)
        return
    if production.get("posture") != new_posture:
        production["posture"] = new_posture
        db.touch(production)


# ---------------------------------------------------------------------------
# waitlist_promotion (PRD 3.6)
# ---------------------------------------------------------------------------

def run_waitlist_promotion(asset: dict) -> None:
    """Promote the earliest-created REQUESTED entry for this asset whose
    production is PLANNING. No-op when the candidate set is empty."""
    candidates = [
        e
        for e in db.pull_list_entries.values()
        if e["asset_id"] == asset["id"] and e["status"] == "REQUESTED"
    ]
    candidates = [
        e
        for e in candidates
        if (db.productions.get(e["production_id"]) or {}).get("status") == "PLANNING"
    ]
    if not candidates:
        return
    candidates.sort(key=lambda e: (e["created_at"], e["id"]))
    promoted = candidates[0]
    promoted["status"] = "RESERVED"
    db.touch(promoted)
    asset["status"] = "RESERVED"
    db.touch(asset)
    production = db.productions.get(promoted["production_id"])
    refresh_posture(production)
