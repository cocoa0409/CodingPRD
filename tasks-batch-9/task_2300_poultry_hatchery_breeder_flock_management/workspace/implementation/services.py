"""Domain services: derived-field refresh, state cascades, aggregates."""

from datetime import timedelta
from decimal import Decimal

import calc
from store import store


# ---------------------------------------------------------------------------
# BreederFlock — forecast chain (PRD §3.2)
# ---------------------------------------------------------------------------
def refresh_flock(flock):
    """Recompute age_weeks and the whole forecast chain against the clock.

    Never touches updated_at or version (PRD §2.4: reads recompute without a
    version bump).
    """
    program = store.flock_programs.get(flock["program_id"])
    age_weeks = calc.age_weeks_of(flock["hatch_date"], store.clock)
    flock["age_weeks"] = age_weeks

    if program is None:
        photoperiod = calc.BASE_PHOTOPERIOD_HOURS
        feed = calc.TARGET_FEED_G
    else:
        photoperiod = calc.step_lookup(program["lighting_steps"], age_weeks,
                                       "photoperiod_hours", calc.BASE_PHOTOPERIOD_HOURS)
        feed = calc.step_lookup(program["feed_steps"], age_weeks,
                                "feed_grams_per_hen_day", calc.TARGET_FEED_G)
    flock["photoperiod_hours"] = calc.dec(photoperiod)
    flock["feed_grams_per_hen_day"] = calc.dec(feed)
    flock["lighting_factor"] = calc.lighting_factor_for(photoperiod)
    flock["nutrition_factor"] = calc.nutrition_factor_for(feed)

    if flock["status"] == "DEPLETED":
        # Depletion pins both economic fields to zero (PRD §3.2).
        flock["production_rate_pct"] = Decimal("0.0")
        flock["settable_forecast"] = 0
        return flock

    production = calc.production_rate_for(age_weeks)
    flock["production_rate_pct"] = calc.rnd(production, 1)
    flock["settable_forecast"] = calc.settable_forecast(
        flock["hen_count"], production, flock["lighting_factor"],
        flock["nutrition_factor"], flock["corrective_action_count"])
    return flock


# ---------------------------------------------------------------------------
# EggLot — age of egg (PRD §3.4)
# ---------------------------------------------------------------------------
def refresh_lot(lot):
    lot["effective_age_days"] = calc.effective_age_days(
        lot["collected_at"], lot["stored_at"], lot["storage_temp_c"],
        lot["sanitation_cycle_count"], store.clock)
    return lot


def lot_effective_age(lot):
    return calc.effective_age_days(
        lot["collected_at"], lot["stored_at"], lot["storage_temp_c"],
        lot["sanitation_cycle_count"], store.clock)


# ---------------------------------------------------------------------------
# SetterLoad aggregates
# ---------------------------------------------------------------------------
def items_of_load(load_id, active_only=False):
    rows = [i for i in store.sorted_rows("setter_load_items")
            if i["setter_load_id"] == load_id]
    if active_only:
        rows = [i for i in rows if i["item_status"] == "ACTIVE"]
    return rows


def items_of_lot(lot_id, active_only=False):
    rows = [i for i in store.sorted_rows("setter_load_items")
            if i["egg_lot_id"] == lot_id]
    if active_only:
        rows = [i for i in rows if i["item_status"] == "ACTIVE"]
    return rows


def recompute_load_aggregates(load):
    active = items_of_load(load["id"], active_only=True)
    load["total_eggs_set"] = sum(i["eggs_taken"] for i in active)
    load["weighted_age_days"] = calc.weighted_age_days(
        [(i["eggs_taken"], i["effective_age_days_at_set"]) for i in active])
    return load


def contributing_lots(load_id, active_only=True):
    lots = []
    seen = set()
    for item in items_of_load(load_id, active_only=active_only):
        if item["egg_lot_id"] in seen:
            continue
        seen.add(item["egg_lot_id"])
        lot = store.egg_lots.get(item["egg_lot_id"])
        if lot is not None:
            lots.append(lot)
    return lots


def readings_of_load(load_id):
    rows = [r for r in store.environment_readings.values()
            if r["setter_load_id"] == load_id]
    rows.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def release_unit(unit):
    """Return a machine to FREE.  A no-op — and therefore no version bump —
    when the machine is already FREE, which is the case for a PLANNED load."""
    if unit is not None and unit["occupancy_status"] != "FREE":
        unit["occupancy_status"] = "FREE"
        store.touch(unit)
    return unit


def void_active_items_of_lot(lot):
    """PRD §3.4 — condemning an ALLOCATED lot voids its draws and may empty loads."""
    for item in items_of_lot(lot["id"], active_only=True):
        item["item_status"] = "VOIDED"
        store.touch(item)
        load = store.setter_loads.get(item["setter_load_id"])
        if load is None:
            continue
        recompute_load_aggregates(load)
        if load["status"] == "PLANNED" and load["total_eggs_set"] == 0:
            load["status"] = "ABORTED"
            load["abort_reason"] = "EGG_LOTS_CONDEMNED"
            release_unit(store.incubation_units.get(load["unit_id"]))
        store.touch(load)


def condemn_lot(lot, reason):
    was_allocated = lot["status"] == "ALLOCATED"
    lot["status"] = "CONDEMNED"
    lot["condemned_reason"] = reason
    lot["eggs_remaining"] = 0
    store.touch(lot)
    if was_allocated:
        void_active_items_of_lot(lot)


def run_flock_egg_hold_cascade(flock):
    """PRD §3.3 — every IN_STORAGE or ALLOCATED lot of the flock is condemned."""
    for lot in store.sorted_rows("egg_lots"):
        if lot["flock_id"] != flock["id"]:
            continue
        if lot["status"] not in ("IN_STORAGE", "ALLOCATED"):
            continue
        condemn_lot(lot, "FLOCK_EGG_HOLD")


# ---------------------------------------------------------------------------
# Rolling hatchability + corrective action (PRD §3.9)
# ---------------------------------------------------------------------------
def rolling_window_for_flock(flock_id):
    entries = []
    for batch in store.sorted_rows("chick_batches"):
        if batch["primary_flock_id"] != flock_id or batch["status"] != "BOXED":
            continue
        hatcher = store.hatcher_loads.get(batch["hatcher_load_id"])
        if hatcher is None:
            continue
        load = store.setter_loads.get(hatcher["setter_load_id"])
        if load is None or load["status"] == "ABORTED":
            continue
        entries.append((load, batch))
    entries.sort(key=lambda e: (e[0]["set_at"], e[0]["created_at"], e[0]["_seq"]),
                 reverse=True)
    return entries[:calc.ROLLING_WINDOW_SETS]


def recompute_flock_hatchability(flock):
    window = rolling_window_for_flock(flock["id"])
    if not window:
        return None
    numerator = sum(b["saleable_count"] or 0 for _, b in window)
    set_basis = sum(l["total_eggs_set"] or 0 for l, _ in window)
    fertile_basis = sum(l["fertile_count"] or 0 for l, _ in window)
    flock["hatchability_rolling_pct"] = calc.pooled_pct(numerator, set_basis)
    flock["hatchability_fertile_pct"] = calc.pooled_pct(numerator, fertile_basis)
    return flock["hatchability_rolling_pct"]


def open_corrective_action(flock, trigger_reason, observed_pct, user_id):
    action = store.new_record(
        flock_id=flock["id"],
        trigger_reason=trigger_reason,
        observed_hatchability_pct=observed_pct,
        opened_at=store.clock,
        opened_by_user_id=user_id,
        implementation_note=None,
        verification_round=1,
        status="OPEN",
    )
    store.corrective_actions[action["id"]] = action
    flock["corrective_action_count"] = flock["corrective_action_count"] + 1
    refresh_flock(flock)
    return action


# ---------------------------------------------------------------------------
# Orders / assignments
# ---------------------------------------------------------------------------
def recompute_order_allocation(order):
    allocated = 0
    for assignment in store.delivery_assignments.values():
        if assignment["placement_order_id"] != order["id"]:
            continue
        if assignment["status"] in ("ASSIGNED", "DELIVERED"):
            allocated += assignment["chicks_assigned"]
    order["allocated_chicks"] = allocated
    order["remaining_need"] = order["requested_chicks"] - allocated
    return order


def cycle_of(order):
    start = order["requested_placement_date"]
    return start, start + timedelta(days=calc.FARM_CYCLE_DAYS)


def date_diff_days(a, b):
    return abs((a.date() - b.date()).days)
