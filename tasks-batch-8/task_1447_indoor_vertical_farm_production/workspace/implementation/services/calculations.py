"""Calculation services (SCAFFOLD calculations table / PRD §3)."""

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import raise_error
from services.core import (
    FIXTURE_KW_PER_TOWER, ENERGY_RATE_CENTS_PER_KWH,
    DEMAND_TIER1_LIMIT_KW, DEMAND_RATE_T1_CENTS_PER_KW, DEMAND_RATE_T2_CENTS_PER_KW,
    PRODUCTIVITY, SHIFT_LENGTH_HOURS, OT_MULTIPLIER,
    ESCALATION_MULTIPLIER, WEEKDAYS,
    active_allocations_of_batch, week_bounds_for_contract, logical_now,
)
from util import q2, q4, q0


# ------------------------------------------------------------- yield_projection
def yield_factor_for_rate(rate):
    r = Decimal(rate)
    if r >= Decimal("95.0"):
        return Decimal("1.00"), False
    if r >= Decimal("85.0"):
        return Decimal("0.90"), False
    if r >= Decimal("75.0"):
        return Decimal("0.75"), False
    return Decimal("0.50"), True


def recompute_projected_yield(batch):
    recipe = store.recipes.get(batch.get("recipe_id"))
    if recipe is None:
        return
    tower_count = len(active_allocations_of_batch(batch["id"]))
    # After release cascades there are no ACTIVE allocations; keep tower count pinned
    # from the batch creation for projection stability.
    if tower_count == 0:
        tower_count = batch.get("tower_count_pin", 0)
    factor = Decimal(str(batch.get("yield_factor") or Decimal("1.00")))
    batch["projected_yield_lb"] = q2(
        Decimal(tower_count) * Decimal(str(recipe["expected_yield_lb_per_tower"])) * factor
    )


# ------------------------------------------------------------- energy_cost_per_pound
def provisional_cost_per_pound(batch):
    """PROVISIONAL variant; available once seeded (needs projected_yield_lb)."""
    recipe = store.recipes.get(batch.get("recipe_id"))
    if recipe is None or batch.get("projected_yield_lb") in (None, 0):
        return None
    tower_count = batch.get("tower_count_pin") or len(active_allocations_of_batch(batch["id"]))
    kwh_prov = (Decimal(tower_count)
                * Decimal(recipe["light_hours_per_day"])
                * Decimal(recipe["days_to_harvest"])
                * FIXTURE_KW_PER_TOWER)
    energy_cents = kwh_prov * ENERGY_RATE_CENTS_PER_KWH
    py = Decimal(str(batch["projected_yield_lb"]))
    if py == 0:
        return None
    return q2(energy_cents / py)


def _half_open_intersection_days(a_start, a_end, b_start, b_end):
    """Days (as Decimal, fractional) in the intersection of two half-open intervals."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return Decimal("0")
    return Decimal(str((end - start).total_seconds())) / Decimal("86400")


def actual_cost_allocation(batch, reading):
    """Compute (energy_alloc_cents, demand_alloc_cents, actual_cost_per_pound_cents) for a batch
    covered by a FACILITY reading. Returns None when the reading doesn't cover the batch."""
    if batch.get("seeded_at") is None or batch.get("projected_harvest_at") is None:
        return None
    grow_start = batch["seeded_at"]
    grow_end = batch["projected_harvest_at"]
    p_start = reading["period_start_at"]
    p_end = reading["period_end_at"]
    # Covering requires period covers [seeded_at, projected_harvest_at)
    if not (p_start <= grow_start and p_end >= grow_end):
        return None

    recipe = store.recipes.get(batch.get("recipe_id"))
    if recipe is None:
        return None

    def light_hours(b):
        r = store.recipes.get(b.get("recipe_id"))
        if r is None or b.get("seeded_at") is None or b.get("projected_harvest_at") is None:
            return Decimal("0")
        tc = b.get("tower_count_pin") or len(active_allocations_of_batch(b["id"]))
        days = _half_open_intersection_days(b["seeded_at"], b["projected_harvest_at"], p_start, p_end)
        return Decimal(tc) * Decimal(r["light_hours_per_day"]) * days

    batch_light = light_hours(batch)
    total_light = Decimal("0")
    for b in store.batches.values():
        if b["production_status"] == "PLANNED":
            continue
        if b.get("seeded_at") is None or b.get("projected_harvest_at") is None:
            continue
        # intersects period?
        if b["seeded_at"] < p_end and p_start < b["projected_harvest_at"]:
            total_light += light_hours(b)
    if total_light == 0:
        return None
    share = batch_light / total_light

    kwh = Decimal(str(reading["kwh_consumed"]))
    peak = Decimal(str(reading["peak_demand_kw"]))
    energy_charge = kwh * ENERGY_RATE_CENTS_PER_KWH
    t1 = min(peak, DEMAND_TIER1_LIMIT_KW) * DEMAND_RATE_T1_CENTS_PER_KW
    t2 = max(Decimal("0"), peak - DEMAND_TIER1_LIMIT_KW) * DEMAND_RATE_T2_CENTS_PER_KW
    demand_charge = t1 + t2

    energy_alloc = q0(energy_charge * share)
    demand_alloc = q0(demand_charge * share)

    if batch["production_status"] in ("HARVESTED", "PACKED") and batch.get("harvested_total_lb") is not None:
        basis = Decimal(str(batch["harvested_total_lb"]))
    else:
        basis = Decimal(str(batch.get("projected_yield_lb") or 0))
    if basis == 0:
        return int(energy_alloc), int(demand_alloc), None
    actual = q2((energy_alloc + demand_alloc) / basis)
    return int(energy_alloc), int(demand_alloc), actual


def recompute_actual_costs_for_reading(reading):
    """After a FACILITY reading is posted, recompute covered batches' actual cost."""
    if reading["scope_type"] != "FACILITY":
        return
    for b in store.batches.values():
        result = actual_cost_allocation(b, reading)
        if result is None:
            continue
        _, _, actual = result
        b["actual_cost_per_pound_cents"] = actual
        b["_actual_reading_id"] = reading["id"]


def recompute_actual_costs_for_batch(batch):
    """On-demand: find a covering FACILITY reading and recompute the batch's actual cost."""
    if batch.get("seeded_at") is None or batch.get("projected_harvest_at") is None:
        return None
    grow_start = batch["seeded_at"]
    grow_end = batch["projected_harvest_at"]
    for r in store.energy_readings.values():
        if r["scope_type"] != "FACILITY":
            continue
        if r["period_start_at"] <= grow_start and r["period_end_at"] >= grow_end:
            result = actual_cost_allocation(batch, r)
            if result is not None:
                _, _, actual = result
                batch["actual_cost_per_pound_cents"] = actual
                batch["_actual_reading_id"] = r["id"]
            return batch.get("actual_cost_per_pound_cents")
    return batch.get("actual_cost_per_pound_cents")


# ------------------------------------------------------------- contract weeks
def first_week_start_on_or_after(week_start_day, start_date):
    anchor = WEEKDAYS[week_start_day]
    delta = (anchor - start_date.weekday()) % 7
    return start_date + timedelta(days=delta)


def week_stats(contract, week_start):
    """(shipped_lb, reserved_lb) for the half-open week [week_start, +7d)."""
    week_end = week_start + timedelta(days=7)
    shipped = Decimal("0")
    reserved = Decimal("0")
    for s in store.shipments.values():
        if s["contract_id"] != contract["id"]:
            continue
        sd = s["ship_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if not (week_start <= sd < week_end):
            continue
        if s["shipment_status"] == "SHIPPED":
            shipped += Decimal(str(s.get("shipped_lb") or 0))
        elif s["shipment_status"] in ("RESERVED", "PACKED"):
            reserved += Decimal(str(s.get("reserved_lb") or 0))
    return q2(shipped), q2(reserved)


def fill_rates(contract, week_start):
    shipped, reserved = week_stats(contract, week_start)
    commitment = Decimal(contract["weekly_commitment_lb"])
    provisional = q4((shipped + reserved) / commitment) if commitment else Decimal("0")
    final = q4(shipped / commitment) if commitment else Decimal("0")
    return shipped, reserved, provisional, final


def penalty_for_week(contract, shipped_lb):
    """Return penalty_cents for a settled week (uses contract's CURRENT consecutive_short_weeks)."""
    commitment = Decimal(contract["weekly_commitment_lb"])
    short_lb = max(Decimal("0"), commitment - Decimal(str(shipped_lb)))
    final_rate = q4(Decimal(str(shipped_lb)) / commitment) if commitment else Decimal("0")
    threshold = Decimal(str(contract["fill_rate_threshold"]))
    if final_rate < threshold:
        multiplier = ESCALATION_MULTIPLIER if contract.get("consecutive_short_weeks", 0) >= 1 else Decimal("1.0")
        penalty = q0(short_lb * Decimal(contract["penalty_cents_per_short_lb"]) * multiplier)
        return int(penalty), True
    return 0, False


# ------------------------------------------------------------- harvest_labor_cost
def compute_projected_labor_cost(shift):
    """HARVEST_CREW shifts only; other roles -> 0."""
    if shift["role_type"] != "HARVEST_CREW":
        shift["projected_labor_cost_cents"] = 0
        return
    sd = shift["shift_date"]
    if isinstance(sd, str):
        sd = date.fromisoformat(sd)
    batch_hours = Decimal("0")
    for b in store.batches.values():
        if b["production_status"] not in ("GROWING", "AT_RISK", "HARVEST_READY"):
            continue
        ph = b.get("projected_harvest_at")
        if ph is None:
            continue
        if ph.date() != sd:
            continue
        crop = store.crops.get(b["crop_id"])
        if crop is None:
            continue
        prod = PRODUCTIVITY[crop["category"]]
        py = Decimal(str(b.get("projected_yield_lb") or 0))
        batch_hours += py / prod
    # required crew hours: batch_hours ceiled to integer
    import math
    required_crew_hours = Decimal(math.ceil(float(batch_hours)))
    capacity = SHIFT_LENGTH_HOURS * Decimal(shift.get("headcount_assigned", 0))
    regular = min(required_crew_hours, capacity)
    overtime = max(Decimal("0"), required_crew_hours - capacity)
    rate = Decimal(shift["planned_hourly_rate_cents"])
    cost = q0(regular * rate + overtime * rate * OT_MULTIPLIER)
    shift["projected_labor_cost_cents"] = int(cost)


# ------------------------------------------------------------- replant_priority_score
def compute_replant_priority(failure, failed_batch):
    crop = store.crops.get(failed_batch["crop_id"])
    if crop is None:
        return Decimal("0.00")
    # (1) reference week: earliest week_start among crop's ACTIVE contracts
    contracts = [c for c in store.contracts.values()
                 if c["crop_id"] == crop["id"] and c["contract_status"] == "ACTIVE"]
    ph = failed_batch.get("projected_harvest_at") or logical_now()
    ph_date = ph.date() if isinstance(ph, datetime) else ph
    if contracts:
        week_starts = []
        for c in contracts:
            anchor = WEEKDAYS[c["week_start_day"]]
            delta = (ph_date.weekday() - anchor) % 7
            week_starts.append(ph_date - timedelta(days=delta))
        week_start = min(week_starts)
    else:
        # no active contracts: use ISO week of the projected harvest
        week_start = ph_date - timedelta(days=ph_date.weekday())
    week_end = week_start + timedelta(days=7)
    # (2) projected supply
    supply = Decimal("0")
    for b in store.batches.values():
        if b["crop_id"] != crop["id"]:
            continue
        if b["production_status"] not in ("SEEDED", "GROWING", "AT_RISK", "HARVEST_READY"):
            continue
        bh = b.get("projected_harvest_at")
        if bh is None:
            continue
        bh_date = bh.date() if isinstance(bh, datetime) else bh
        if week_start <= bh_date < week_end:
            supply += Decimal(str(b.get("projected_yield_lb") or 0))
    # (3) commitment
    commitment = sum((Decimal(c["weekly_commitment_lb"]) for c in contracts), Decimal("0"))
    # (4) shortfall
    shortfall = max(Decimal("0"), commitment - supply)
    # (5) urgency
    created = failure["created_at_dt"]
    delta_days = (ph - created).total_seconds() / 86400.0
    urgency = Decimal("2.0") if delta_days <= 14 else Decimal("1.0")
    # (6) score
    score = q2(shortfall * Decimal(crop["margin_cents_per_lb"]) * urgency)
    return score


# ------------------------------------------------------------- tower_allocation_selector
def select_towers_for_replant(towers_needed, days_to_harvest):
    """Best-fit defragmentation tower selection. Returns list of Tower rows or None."""
    now = logical_now()
    window_end = now + timedelta(days=days_to_harvest)
    eligible_by_rack = {}
    for t in store.towers.values():
        rack = store.racks.get(t["rack_id"])
        if rack is None or rack["rack_posture"] != "OPERATING":
            continue
        loop = store.water_loops.get(rack["water_loop_id"])
        if loop is None:
            continue
        from services.core import loop_posture
        if loop_posture(loop) not in ("IN_SERVICE", "SANITATION_DUE"):
            continue
        # no ACTIVE allocation overlapping [now, window_end)
        conflict = False
        for a in store.allocations.values():
            if a["tower_id"] != t["id"] or a["allocation_status"] != "ACTIVE":
                continue
            if now < a["occupied_to_at"] and a["occupied_from_at"] < window_end:
                conflict = True
                break
        if conflict:
            continue
        eligible_by_rack.setdefault(rack["id"], []).append(t)
    # candidate racks: idle_count >= towers_needed
    candidates = []
    for rack_id, towers in eligible_by_rack.items():
        if len(towers) >= towers_needed:
            rack = store.racks[rack_id]
            candidates.append((len(towers) - towers_needed, rack["created_at"], rack_id, towers))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    chosen = candidates[0][3]
    chosen.sort(key=lambda t: t["tower_index"])
    return chosen[:towers_needed]
