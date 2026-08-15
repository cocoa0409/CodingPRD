"""Business logic: derived (computed) fields, window/buffer checks, cascades,
and the calculation rules of SCAFFOLD §1.3 / PRD §3.

Design rule: every field declared `source: computed` in the scaffold is derived
on read from base records (runs, cycles, complaints, withdrawal events). Ledger
fields such as order.releasable_cases and order.billed_amount_cents are pure
functions of lot state, so cascade side effects never drift.
"""

from datetime import timedelta
from decimal import Decimal

from db import STORE, bump, logical_now
from errors import ApiError
from util import (
    ALLERGEN_CHANGEOVER_MINUTES,
    CASE_UNITS,
    CORE_TARGET_C,
    DEFAULT_CHANGEOVER_MINUTES,
    HIGH_TEMP_FACTOR,
    LOT_QUARANTINE_THRESHOLD,
    METERS_PER_UNIT,
    MIN_DWELL_HOURS,
    RATE_DEN,
    RATE_NUM,
    REQUIRED_LINE_TYPE,
    VERIFY_GRACE_HOURS,
    WASTE_FACTOR,
    WINDOW_DAYS,
    ceil_dec,
    ceil_div,
    q0,
    q2,
    q3,
)

BATCH_TERMINAL = {"COMPLETED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Collection lookups
# ---------------------------------------------------------------------------

def components_of_recipe(recipe_id):
    return [c for c in STORE["components"].values() if c["recipe_id"] == recipe_id]


def orders_of_recipe(recipe_id):
    return [o for o in STORE["orders"].values() if o["recipe_id"] == recipe_id]


def batches_of_order(order_id):
    return [b for b in STORE["batches"].values() if b["order_id"] == order_id]


def cycles_of_batch(batch_id):
    return [c for c in STORE["cycles"].values() if c["batch_id"] == batch_id]


def cycles_of_cell(cell_id):
    return [c for c in STORE["cycles"].values() if c["cell_id"] == cell_id]


def runs_of_batch(batch_id):
    return [r for r in STORE["runs"].values() if r["batch_id"] == batch_id]


def runs_of_line(line_id):
    return [r for r in STORE["runs"].values() if r["line_id"] == line_id]


def runs_of_film_lot(film_lot_id):
    return [r for r in STORE["runs"].values() if r["film_lot_id"] == film_lot_id]


def lots_of_batch(batch_id):
    return [l for l in STORE["lots"].values() if l["batch_id"] == batch_id]


def checks_of_batch(batch_id):
    return [c for c in STORE["ccp_checks"].values() if c["batch_id"] == batch_id]


def complaints_of_lot(lot_id):
    return [c for c in STORE["complaints"].values() if c["lot_id"] == lot_id]


def get_batch(batch_id):
    return STORE["batches"].get(batch_id)


def get_order(order_id):
    return STORE["orders"].get(order_id)


def order_of_batch(batch):
    return STORE["orders"].get(batch["order_id"])


def order_of_run(run):
    batch = STORE["batches"].get(run["batch_id"])
    return STORE["orders"].get(batch["order_id"]) if batch else None


def order_of_lot(lot):
    batch = STORE["batches"].get(lot["batch_id"])
    return STORE["orders"].get(batch["order_id"]) if batch else None


def recipe_of_order(order):
    return STORE["recipes"].get(order["recipe_id"])


def recipe_of_batch(batch):
    order = order_of_batch(batch)
    return recipe_of_order(order) if order else None


def recipe_of_lot(lot):
    order = order_of_lot(lot)
    return recipe_of_order(order) if order else None


# ---------------------------------------------------------------------------
# Derived fields (SCAFFOLD entities, source: computed)
# ---------------------------------------------------------------------------

def batch_units_packed(batch):
    return sum(
        r["units_packed"] or 0
        for r in runs_of_batch(batch["id"])
        if r["status"] == "COMPLETED"
    )


def batch_yield_pct(batch):
    """pack_out_math: round_half_up(units_packed_total / units_planned * 100, 2);
    null until the first completed run."""
    runs = [r for r in runs_of_batch(batch["id"]) if r["status"] == "COMPLETED"]
    if not runs:
        return None
    total = sum(r["units_packed"] or 0 for r in runs)
    return q2(Decimal(total) / Decimal(batch["units_planned"]) * Decimal(100))


def order_units_packed(order):
    total = 0
    for b in batches_of_order(order["id"]):
        total += batch_units_packed(b)
    return total


def film_meters(lot):
    """film_reservation aggregation (SCAFFOLD §1.3): per-run reservations were
    rounded to whole meters at booking; sums here aggregate those integers."""
    received = lot["rolls_received"] * lot["meters_per_roll"]
    reserved = sum(
        r["reserved_film_m"]
        for r in runs_of_film_lot(lot["id"])
        if r["status"] in ("SCHEDULED", "IN_PROGRESS")
    )
    consumed = sum(
        r["film_meters_consumed"] or 0
        for r in runs_of_film_lot(lot["id"])
        if r["status"] == "COMPLETED"
    )
    return received, reserved, consumed, received - reserved - consumed


def cell_status(cell):
    in_use = any(
        c["status"] in ("RESERVED", "IN_PROGRESS") for c in cycles_of_cell(cell["id"])
    )
    return "IN_USE" if in_use else "IDLE"


def slot_occupied(slot_id):
    return sum(
        l["stored_cases"] for l in STORE["lots"].values() if l["slot_id"] == slot_id
    )


def lot_cases_on_hand(lot):
    return lot["cases_produced"] - lot["withdrawn_total"]


def lot_valid_complaint_count(lot):
    return sum(1 for c in complaints_of_lot(lot["id"]) if c["status"] == "RESOLVED_VALID")


def order_releasable_cases(order):
    """Sum of cases_on_hand over lots of this order whose release_status == RELEASED."""
    total = 0
    for b in batches_of_order(order["id"]):
        for l in lots_of_batch(b["id"]):
            if l["release_status"] == "RELEASED":
                total += lot_cases_on_hand(l)
    return total


def order_billed_amount_cents(order):
    """copack_billing (SCAFFOLD §1.3). House orders -> null. PER_KG rounds once
    on the aggregate, never per lot."""
    cust_id = order["copack_customer_id"]
    if cust_id is None:
        return None
    cust = STORE["customers"].get(cust_id)
    if cust is None:
        return None
    released = []
    for b in batches_of_order(order["id"]):
        for l in lots_of_batch(b["id"]):
            if l["release_status"] == "RELEASED":
                released.append(l)
    if not released:
        # billing is computed at lot release; an order with no released lots
        # has never been billed (PRD §3.2: new orders start with null)
        return None
    if cust["billing_method"] == "PER_CASE":
        return sum(l["cases_produced"] for l in released) * cust["case_rate_cents"]
    total_kg = sum((l["net_weight_kg"] for l in released), Decimal("0"))
    return int(q0(total_kg * Decimal(cust["kg_rate_cents"])))


def latest_verified_cycle(batch_id):
    """The VERIFIED FreezingCycle of the batch, latest by created_at if several."""
    verified = [c for c in cycles_of_batch(batch_id) if c["status"] == "VERIFIED"]
    if not verified:
        return None
    return max(verified, key=lambda c: c["_seq"])


def latest_check(batch_id, check_type):
    checks = [c for c in checks_of_batch(batch_id) if c["check_type"] == check_type]
    if not checks:
        return None
    return max(checks, key=lambda c: c["_seq"])


def lot_expiry_dates(lot):
    """shelf_life_expiry (SCAFFOLD §1.3): provisional anchored to the verified
    cycle's planned_start; final anchored to its actual_end. Whole ISO dates."""
    recipe = recipe_of_lot(lot)
    cyc = latest_verified_cycle(lot["batch_id"])
    if recipe is None or cyc is None:
        return None, None
    days = timedelta(days=recipe["shelf_life_days"])
    provisional = (cyc["planned_start"].date() + days).isoformat()
    final = (cyc["actual_end"].date() + days).isoformat()
    return provisional, final


def complaint_days_before_expiry(complaint):
    lot = STORE["lots"].get(complaint["lot_id"])
    if lot is None:
        return None
    _, final = lot_expiry_dates(lot)
    if final is None:
        return None
    from datetime import date as date_cls

    y, m, d = (int(x) for x in final.split("-"))
    expiry = date_cls(y, m, d)
    return (expiry - complaint["reported_at"].date()).days


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def freezer_cycle_hours(cell, load_kg, entry_temp_c):
    """freezer_cycle_duration: ceil(load / pull_down); x1.25 (ceil again) when
    entry_temp_c > 0; floor of MIN_DWELL_HOURS."""
    base = ceil_div(load_kg, cell["pull_down_kg_per_hour"])
    if entry_temp_c > 0:
        base = ceil_dec(Decimal(base) * HIGH_TEMP_FACTOR)
    return max(MIN_DWELL_HOURS, base)


def film_reservation_m(units_planned, pack_format):
    """film_reservation per-run rounding (pinned): round_half_up to whole meters
    for THIS run before any lot-level aggregation."""
    raw = Decimal(units_planned) * METERS_PER_UNIT[pack_format] * WASTE_FACTOR
    return int(q0(raw))


def run_duration_minutes(line, units_planned):
    return ceil_div(units_planned, line["rate_units_per_minute"])


def pack_out_cases(units_packed, pack_format):
    return ceil_div(units_packed, CASE_UNITS[pack_format])


def pack_out_net_weight_kg(units_packed, portion_weight_g):
    return q3(Decimal(units_packed) * portion_weight_g / Decimal(1000))


def cycle_verified(cycle, actual_end, final_core_temp_c):
    """VERIFIED iff final_core_temp_c <= -18 AND elapsed <= required_hours + 2h."""
    if final_core_temp_c > CORE_TARGET_C:
        return False
    elapsed = actual_end - cycle["planned_start"]
    limit = timedelta(hours=cycle["required_hours"] + VERIFY_GRACE_HOURS)
    return elapsed <= limit


# ---------------------------------------------------------------------------
# Window / buffer discipline (PRD §2.10) — half-open windows
# ---------------------------------------------------------------------------

def cell_window_conflict(cell, start, end, exclude_ids=()):
    """Buffered window: each cycle occupies [planned_start, planned_end +
    sanitation_minutes) against other RESERVED/IN_PROGRESS cycles on the cell."""
    san = timedelta(minutes=cell["sanitation_minutes"])
    for cyc in cycles_of_cell(cell["id"]):
        if cyc["status"] not in ("RESERVED", "IN_PROGRESS"):
            continue
        if cyc["id"] in exclude_ids:
            continue
        s2, e2 = cyc["planned_start"], cyc["planned_end"]
        if start < e2 + san and s2 < end + san:
            return True
    return False


def recipe_has_allergen(recipe_id):
    return any(c["allergen_tag"] is not None for c in components_of_recipe(recipe_id))


def _changeover_gap_minutes(later_customer_id, earlier_recipe_id):
    """Gap required when a run of `later_customer_id` follows a run that packed
    `earlier_recipe_id` (PRD §2.10). Caller guarantees the customers differ."""
    cust = STORE["customers"].get(later_customer_id) if later_customer_id else None
    base = cust["base_changeover_minutes"] if cust else DEFAULT_CHANGEOVER_MINUTES
    if cust and cust["requires_allergen_changeover"] and earlier_recipe_id:
        if recipe_has_allergen(earlier_recipe_id):
            return ALLERGEN_CHANGEOVER_MINUTES
    return base


def line_window_conflict(line, new_customer_id, new_recipe_id, start, end):
    """Half-open overlap, plus customer/allergen changeover buffers between runs
    of different co-pack customers (PRD §2.10)."""
    for run in runs_of_line(line["id"]):
        if run["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        s2, e2 = run["planned_start"], run["planned_end"]
        if start < e2 and s2 < end:
            return True
        old_order = order_of_run(run)
        old_customer = old_order["copack_customer_id"] if old_order else None
        if new_customer_id == old_customer:
            continue
        if start >= e2:
            # new run follows the existing one
            gap = _changeover_gap_minutes(new_customer_id, old_order["recipe_id"] if old_order else None)
            if start < e2 + timedelta(minutes=gap):
                return True
        elif s2 >= end:
            # existing run follows the new one
            gap = _changeover_gap_minutes(old_customer, new_recipe_id)
            if s2 < end + timedelta(minutes=gap):
                return True
    return False


# ---------------------------------------------------------------------------
# Cell auto-select (SCAFFOLD §1.3 cell_auto_select)
# ---------------------------------------------------------------------------

def auto_select_cell(load_kg, entry_temp_c, planned_start, exclude_cycle_ids):
    candidates = []
    for cell in STORE["cells"].values():
        if not (cell["capacity_kg"] >= load_kg >= cell["min_load_kg"]):
            continue
        hours = freezer_cycle_hours(cell, load_kg, entry_temp_c)
        end = planned_start + timedelta(hours=hours)
        if cell_window_conflict(cell, planned_start, end, exclude_cycle_ids):
            continue
        candidates.append((cell, hours, end))
    if not candidates:
        return None
    # rank: capacity_kg ASC (best fit); tie-break created_at ASC, then cell_code ASC
    candidates.sort(key=lambda t: (t[0]["capacity_kg"], t[0]["created_at"], t[0]["cell_code"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Cascades (PRD §2.11, §3)
# ---------------------------------------------------------------------------

def order_completion_check(order):
    """IN_PROGRESS -> COMPLETED when every batch is in {COMPLETED, CANCELLED}
    and at least one is COMPLETED."""
    if order["status"] != "IN_PROGRESS":
        return
    batches = batches_of_order(order["id"])
    if not batches:
        return
    if all(b["status"] in BATCH_TERMINAL for b in batches) and any(
        b["status"] == "COMPLETED" for b in batches
    ):
        order["status"] = "COMPLETED"
        bump(order)


def cancel_scheduled_run(run):
    """SCHEDULED -> CANCELLED; the film reservation release is derived (the run
    leaves the {SCHEDULED, IN_PROGRESS} reservation set)."""
    run["status"] = "CANCELLED"
    bump(run)


def void_reserved_cycle(cycle):
    cycle["status"] = "VOIDED"
    bump(cycle)


def ccp_fail_cascade(batch, check_type):
    """PRD §3.6: FAIL while FROZEN or PACKED -> ON_HOLD with CCP_FAIL:<type>
    marker; every SCHEDULED run of the batch CANCELLED (film release derived).
    FAIL while COMPLETED or ON_HOLD: no hold."""
    if batch["status"] not in ("FROZEN", "PACKED"):
        return
    batch["hold_origin_state"] = batch["status"]
    batch["hold_reason"] = "CCP_FAIL:%s" % check_type
    batch["status"] = "ON_HOLD"
    bump(batch)
    for run in runs_of_batch(batch["id"]):
        if run["status"] == "SCHEDULED":
            cancel_scheduled_run(run)


def complaint_contagion(complaint):
    """complaint_contagion (SCAFFOLD §1.3, PRD §3.8) — invoked after a complaint
    transitions to RESOLVED_VALID. The lot's valid_complaint_count is derived,
    so hop 1 is already visible when this runs."""
    lot = STORE["lots"].get(complaint["lot_id"])
    if lot is None:
        return
    # Hop 2: inclusive lot threshold
    if (
        lot_valid_complaint_count(lot) >= LOT_QUARANTINE_THRESHOLD
        and lot["release_status"] == "RELEASED"
    ):
        lot["release_status"] = "QUARANTINED"
        bump(lot)
    # Hop 3: recipe-level rate over the trailing 90 days, exact rational compare
    recipe = recipe_of_lot(lot)
    if recipe is None:
        return
    now = logical_now()
    window_lo = now - timedelta(days=WINDOW_DAYS)
    recipe_lots = []
    for order in orders_of_recipe(recipe["id"]):
        for b in batches_of_order(order["id"]):
            recipe_lots.extend(lots_of_batch(b["id"]))
    lot_ids = {l["id"] for l in recipe_lots}
    shipped = 0
    for l in recipe_lots:
        for ev in l["_ship_events"]:
            if window_lo < ev["at"] <= now:
                shipped += ev["cases"]
    affected = 0
    for c in STORE["complaints"].values():
        if (
            c["lot_id"] in lot_ids
            and c["status"] == "RESOLVED_VALID"
            and window_lo < c["reported_at"] <= now
        ):
            affected += c["units_affected"]
    if shipped > 0 and RATE_DEN * affected >= RATE_NUM * shipped:
        for l in recipe_lots:
            if l["release_status"] == "RELEASED":
                l["release_status"] = "QUARANTINED"
                bump(l)


# ---------------------------------------------------------------------------
# Validation helpers shared by routes
# ---------------------------------------------------------------------------

def not_found(what):
    return ApiError("ERR_NOT_FOUND", "%s does not exist" % what)


def require_record(collection, rec_id, what):
    rec = STORE[collection].get(rec_id)
    if rec is None:
        raise not_found(what)
    return rec


def assert_customer_scope(user_id, order):
    """Pipeline stage 4: CoPackCustomer callers may only touch their own chain."""
    customer_id = order["copack_customer_id"] if order else None
    if customer_id is None or customer_id != user_id:
        raise ApiError(
            "ERR_CROSS_CUSTOMER_ACCESS",
            "Resource is outside the caller's co-pack customer scope",
        )
