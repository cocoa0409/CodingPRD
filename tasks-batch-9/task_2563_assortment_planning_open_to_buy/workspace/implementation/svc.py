"""Service layer: reserve events, month recomputation, postures, cascades."""
from common import fail, rhu, retail_to_cost, trunc, now_iso
import calc
import store
from store import db, make_row, touch


# ---------------------------------------------------------------------------
# Month recomputation
# ---------------------------------------------------------------------------
def recompute_month_buckets(month, plan=None, bump=True):
    """Recompute only committed/received/open.  The reserve is NOT touched (§3.4)."""
    committed, received = calc.month_buckets(month["id"])
    month["otb_committed_cents"] = committed
    month["otb_received_cents"] = received
    month["otb_open_cents"] = month["otb_planned_cents"] - committed - received
    if bump:
        touch(month)
    return month


def reserve_event(month, plan, basis, bump=True):
    """The only two callers are DRAFT->LOCKED_PLAN and an actuals post (§3.4)."""
    projected = calc.projected_figures(month, plan)
    reserve = calc.markdown_reserve(month, plan, basis, projected)
    month["provisional_sell_through_bps"] = reserve["provisional_sell_through_bps"]
    month["reserve_rate_bps"] = reserve["reserve_rate_bps"]
    month["markdown_reserve_cents"] = reserve["markdown_reserve_cents"]
    month["otb_planned_cents"] = calc.otb_planned(
        month, plan, basis, reserve["markdown_reserve_cents"], projected)
    recompute_month_buckets(month, plan, bump=False)
    if bump:
        touch(month)
    return month


# ---------------------------------------------------------------------------
# Plan posture / variance
# ---------------------------------------------------------------------------
def recompute_plan_posture(plan, bump=True):
    ratio, posture = calc.compute_posture(plan)
    was_frozen = plan["otb_posture"] == "FROZEN"
    plan["open_ratio_bps"] = ratio
    plan["otb_posture"] = posture
    if bump:
        touch(plan)
    return was_frozen, posture


def apply_freeze_deferrals(plan):
    """§3.6: a posture landing on FROZEN demotes every PROPOSED item of the plan."""
    if plan["otb_posture"] != "FROZEN":
        return 0
    count = 0
    for item in store.plan_items(plan["id"]):
        if item["status"] == "PROPOSED":
            item["status"] = "DEFERRED"
            touch(item)
            count += 1
    return count


def apply_conditional_restore(plan):
    """Cascade A link 4: only CARRYOVER and CORE deferrals come back."""
    if plan["otb_posture"] == "FROZEN":
        return 0
    count = 0
    for item in store.plan_items(plan["id"]):
        if item["status"] == "DEFERRED" and item["lifecycle_stage"] in ("CARRYOVER", "CORE"):
            item["status"] = "PROPOSED"
            touch(item)
            count += 1
    return count


def recompute_variance(plan, bump=True):
    variance, status = calc.variance_verdict(plan)
    plan["sales_variance_bps"] = variance
    plan["variance_status"] = status
    if bump:
        touch(plan)
    return status


# ---------------------------------------------------------------------------
# Size-curve allocation (§3.3) — shared by the PUT and by cascade B link 5
# ---------------------------------------------------------------------------
def run_size_allocation(cell, persist_target, rows=None):
    cluster = db.clusters.get(cell["store_cluster_id"])
    size_cells = rows if rows is not None else store.optionplan_sizecells(cell["id"])
    if not size_cells:
        return None
    target, allocation = calc.cluster_size_allocation(cell, cluster, size_cells)
    for entry in allocation:
        if entry["allocated"] <= 0:
            fail("ERR_SIZE_CURVE_ZERO_CELL",
                 "size %s resolves to zero allocated units" % entry["cell"]["size_label"])
    for entry in allocation:
        entry["cell"]["raw_units_x10000"] = entry["raw"]
        entry["cell"]["allocated_units"] = entry["allocated"]
    if persist_target:
        cell["target_units_per_option"] = target
    return target


# ---------------------------------------------------------------------------
# Item forecasting (§3.5)
# ---------------------------------------------------------------------------
def resolve_item_forecast(item):
    item["effective_overlay_multiplier_bps"] = calc.overlay_effective_multiplier(item)
    basis, value = calc.item_sell_through_forecast(item)
    item["sell_through_basis"] = basis
    item["sell_through_bps"] = value
    return item


# ---------------------------------------------------------------------------
# Cascade B — plan approval (§3.4)
# ---------------------------------------------------------------------------
def cascade_b(plan, user_id, budget):
    # Link 1: the plan's own approval and receipt-budget pinning.
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    plan["receipt_budget_cents"] = budget
    touch(plan)

    # Link 2: DRAFT months -> LOCKED_PLAN with reserve and planned-basis OTB.
    for month in store.plan_months(plan["id"]):
        if month["status"] == "DRAFT":
            month["status"] = "LOCKED_PLAN"
            reserve_event(month, plan, calc.PLANNED_BASIS)

    # Link 3: posture recomputation over the newly locked months.
    recompute_plan_posture(plan)

    # Link 4: OPEN cells with at least one size row -> SLOTTED, unless FROZEN.
    if plan["otb_posture"] == "FROZEN":
        return
    for cell in store.plan_optionplans(plan["id"]):
        if cell["status"] != "OPEN":
            continue
        rows = store.optionplan_sizecells(cell["id"])
        if not rows:
            continue
        cluster = db.clusters.get(cell["store_cluster_id"])
        total = calc.option_slot_capacity(cell, plan, cluster)
        cell["status"] = "SLOTTED"
        cell["option_slots_total"] = total
        cell["option_slots_open"] = total - cell["option_slots_assigned"]
        # Link 5: the cluster-and-size allocation re-runs and pins the unit target.
        run_size_allocation(cell, True, rows)
        touch(cell)


# ---------------------------------------------------------------------------
# Plan rejection unwind (§3.4)
# ---------------------------------------------------------------------------
def unwind_plan(plan):
    for month in store.plan_months(plan["id"]):
        if month["status"] == "LOCKED_PLAN":
            month["status"] = "DRAFT"
            month["otb_planned_cents"] = 0
            month["otb_open_cents"] = 0
            month["markdown_reserve_cents"] = 0
            month["provisional_sell_through_bps"] = 0
            month["reserve_rate_bps"] = 0
            touch(month)
    for cell in store.plan_optionplans(plan["id"]):
        if cell["status"] == "SLOTTED":
            cell["status"] = "OPEN"
            cell["option_slots_total"] = None
            cell["option_slots_open"] = None
            cell["target_units_per_option"] = None
            touch(cell)


# ---------------------------------------------------------------------------
# Plan closure cascade (§3.9)
# ---------------------------------------------------------------------------
def close_plan_cascade(plan):
    plan["status"] = "CLOSED"
    for month in store.plan_months(plan["id"]):
        if month["status"] in ("DRAFT", "LOCKED_PLAN", "IN_SEASON"):
            month["status"] = "CLOSED"
            touch(month)
    for cell in store.plan_optionplans(plan["id"]):
        if cell["status"] in ("OPEN", "SLOTTED"):
            cell["status"] = "CLOSED"
            touch(cell)
    for cycle in store.plan_cycles(plan["id"]):
        if cycle["status"] != "OPEN":
            continue
        cycle["status"] = "ABANDONED"
        touch(cycle)
        for decision in store.cycle_decisions(cycle["id"]):
            if decision["status"] == "PROPOSED":
                decision["status"] = "REJECTED"
                decision["approved_units"] = 0
                touch(decision)
    touch(plan)


# ---------------------------------------------------------------------------
# Reforecast cycle helpers (§3.8)
# ---------------------------------------------------------------------------
def open_cycle(plan, trigger_reason):
    plan["status"] = "REFORECAST_OPEN"
    plan["reforecast_round"] = plan["reforecast_round"] + 1
    touch(plan)
    cycle = make_row(
        category_plan_id=plan["id"],
        round_index=plan["reforecast_round"],
        trigger_reason=trigger_reason,
        opened_at_utc=store.clock_iso(),
        snapshot_sales_variance_bps=plan["sales_variance_bps"],
        status="OPEN",
    )
    db.cycles[cycle["id"]] = cycle
    # Opening a round invalidates localization.
    for overlay in store.plan_overlays(plan["id"]):
        if overlay["status"] == "ACTIVE":
            overlay["status"] = "SUPERSEDED"
            touch(overlay)
    return cycle


def bubble_cycle(cycle):
    """OPEN -> DECIDED as soon as no decision of the cycle is still PROPOSED."""
    if cycle["status"] != "OPEN":
        return False
    decisions = store.cycle_decisions(cycle["id"])
    if not decisions:
        return False
    if any(d["status"] == "PROPOSED" for d in decisions):
        return False
    cycle["status"] = "DECIDED"
    touch(cycle)
    return True


# ---------------------------------------------------------------------------
# Overlays (§3.5)
# ---------------------------------------------------------------------------
def overlay_affected_items(overlay):
    out = []
    for cell in store.plan_optionplans(overlay["category_plan_id"]):
        if cell["store_cluster_id"] != overlay["store_cluster_id"]:
            continue
        for item in store.optionplan_items(cell["id"]):
            if item["status"] in ("ADOPTED", "IN_SEASON"):
                out.append(item)
    return store.by_seq(out)


def reresolve_overlay_items(overlay):
    for item in overlay_affected_items(overlay):
        resolve_item_forecast(item)
        touch(item)


def expire_overlays_for_clock():
    """Repositioning the clock strictly past an ACTIVE overlay's end expires it."""
    now = store.clock()
    expired = []
    for overlay in store.by_seq(list(db.overlays.values())):
        if overlay["status"] != "ACTIVE":
            continue
        end = store.dt(overlay["effective_end"])
        if end is not None and now > end:
            overlay["status"] = "EXPIRED"
            touch(overlay)
            expired.append(overlay)
    seen = {}
    for overlay in expired:
        for item in overlay_affected_items(overlay):
            seen[item["id"]] = item
    for item in store.by_seq(list(seen.values())):
        resolve_item_forecast(item)
        touch(item)
    return len(expired)


# ---------------------------------------------------------------------------
# Chase-or-cancel waterfall (§3.8)
# ---------------------------------------------------------------------------
def _new_commitment(month, item, vendor, units, start, end, origin, commit_status):
    row = make_row(
        plan_month_id=month["id"],
        assortment_item_id=item["id"],
        vendor_id=vendor["id"],
        units=units,
        unit_cost_cents=item["unit_cost_cents"],
        ship_window_start=start,
        ship_window_end=end,
        origin=origin,
        commit_status=commit_status,
        fulfillment_status="AWAITING_SHIP",
        received_units=0,
        cancelled_units=0,
        cost_cents=units * item["unit_cost_cents"],
        open_cost_cents=units * item["unit_cost_cents"],
        received_cost_cents=0,
    )
    db.commitments[row["id"]] = row
    return row


def chase_allocation(plan, item, requested_units):
    from common import iso_ms
    vendor = db.vendors.get(item["vendor_id"])
    now = store.clock()
    earliest = now + calc.days(vendor["lead_time_days"])
    candidates = []
    for month in store.plan_months(plan["id"]):
        if month["status"] not in ("LOCKED_PLAN", "IN_SEASON"):
            continue
        if month["otb_open_cents"] <= 0:
            continue
        first = store.dt(month["first_receipt_date"])
        if first is None or first < earliest:
            continue
        candidates.append(month)
    remaining = requested_units
    touched = []
    for month in candidates:
        if remaining <= 0:
            break
        fundable = trunc(month["otb_open_cents"], item["unit_cost_cents"])
        window_start = store.dt(month["first_receipt_date"])
        window_end = window_start + calc.days(calc.CHASE_WINDOW_DAYS)
        headroom = vendor["weekly_unit_capacity"] - calc.window_load(
            vendor["id"], window_start, window_end)
        take = min(remaining, fundable, headroom)
        if take > 0:
            _new_commitment(month, item, vendor, take,
                            iso_ms(window_start), iso_ms(window_end),
                            "CHASE_DECISION", "COMMITTED")
            remaining -= take
            touched.append(month)
    return requested_units - remaining, touched


def cancel_allocation(item, requested_units):
    rows = []
    for rc in store.item_commitments(item["id"]):
        if rc["commit_status"] != "COMMITTED":
            continue
        open_units = rc["units"] - rc["received_units"] - rc["cancelled_units"]
        if open_units <= 0:
            continue
        month = db.months.get(rc["plan_month_id"])
        rows.append((-(month["month_index"] if month else 0), rc["_seq"], rc, open_units))
    rows.sort(key=lambda t: (t[0], t[1]))
    remaining = requested_units
    touched = {}
    for _, _, rc, open_units in rows:
        if remaining <= 0:
            break
        take = min(remaining, open_units)
        rc["cancelled_units"] = rc["cancelled_units"] + take
        remaining -= take
        still_open = rc["units"] - rc["received_units"] - rc["cancelled_units"]
        rc["open_cost_cents"] = still_open * rc["unit_cost_cents"]
        if still_open <= 0:
            rc["commit_status"] = "CANCELLED"
        touch(rc)
        month = db.months.get(rc["plan_month_id"])
        if month is not None:
            touched[month["id"]] = month
    return requested_units - remaining, store.by_seq(list(touched.values()))
