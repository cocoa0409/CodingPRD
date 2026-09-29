"""Reprojections and cascades (PRD 2.9, 3.2-3.9).

Every derived field is a full reprojection over the current input set, never an
incremental adjustment.
"""
from decimal import Decimal

import calc
from calc import ZERO2, dec, q2
from db import create_row, order_key, sorted_rows, store


# ---------------------------------------------------------------------------
# collection selectors
# ---------------------------------------------------------------------------
def work_orders_of_outage(outage_id):
    return sorted_rows([w for w in store.work_orders.values()
                        if w["outage_id"] == outage_id])


def activities_of_outage(outage_id):
    return sorted_rows([a for a in store.schedule_activities.values()
                        if a["outage_id"] == outage_id])


def activities_of_work_order(work_order_id):
    return sorted_rows([a for a in store.schedule_activities.values()
                        if a["work_order_id"] == work_order_id])


def rwps_of_outage(outage_id):
    return sorted_rows([p for p in store.rwps.values()
                        if p["outage_id"] == outage_id])


def rwps_of_work_order(work_order_id):
    return sorted_rows([p for p in store.rwps.values()
                        if p["work_order_id"] == work_order_id])


def patterns_of_outage(outage_id):
    return sorted_rows([p for p in store.core_load_patterns.values()
                        if p["outage_id"] == outage_id])


def reservations_of_pool(pool_id):
    return sorted_rows([r for r in store.pool_cell_reservations.values()
                        if r["spent_fuel_pool_id"] == pool_id])


def workers_of_outage(outage_id):
    return sorted_rows([w for w in store.supplemental_workers.values()
                        if w["outage_id"] == outage_id])


def startup_tests_of_outage(outage_id):
    return sorted_rows([t for t in store.startup_tests.values()
                        if t["outage_id"] == outage_id])


def emergent_items_of_work_order(work_order_id):
    return sorted_rows([i for i in store.emergent_items.values()
                        if i["discovered_from_work_order_id"] == work_order_id])


def dose_transactions_of_rwp(rwp_id):
    return sorted_rows([t for t in store.dose_transactions.values()
                        if t["rwp_id"] == rwp_id])


def touch_row(row):
    """Bump a row's own version and refresh updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        from clock import clock
        row["updated_at"] = clock.now_iso()
    return row


# ---------------------------------------------------------------------------
# pool_cell_ledger
# ---------------------------------------------------------------------------
def recompute_pool(pool):
    consumed = 0
    reserved = 0
    for r in reservations_of_pool(pool["id"]):
        if r["status"] == "CONSUMED":
            consumed += r["cells_requested"]
        elif r["status"] == "RESERVED":
            reserved += r["cells_requested"]
    pool["cells_occupied"] = pool["cells_baseline_occupied"] + consumed
    pool["cells_reserved"] = reserved
    pool["cells_available"] = (pool["cells_total"] - pool["cells_occupied"]
                               - pool["cells_reserved"])
    pool["protected_cells_available"] = (pool["cells_available"]
                                         - pool["full_core_offload_reserve_cells"])
    return pool


# ---------------------------------------------------------------------------
# outage_badging_rollup
# ---------------------------------------------------------------------------
def recompute_badged_count(outage):
    outage["badged_worker_count"] = sum(
        1 for w in workers_of_outage(outage["id"]) if w["status"] == "BADGED")
    return outage


# ---------------------------------------------------------------------------
# outage_emergent_hours_rollup
# ---------------------------------------------------------------------------
def recompute_emergent_hours(outage):
    total = Decimal(0)
    for item in store.emergent_items.values():
        if item["status"] != "APPROVED":
            continue
        wo = store.work_orders.get(item["discovered_from_work_order_id"])
        if wo is None or wo["outage_id"] != outage["id"]:
            continue
        total += dec(item["estimated_hours"])
    outage["approved_emergent_hours"] = q2(total)
    return outage


# ---------------------------------------------------------------------------
# outage_scope_cost_rollup
# ---------------------------------------------------------------------------
COST_BASE_STATUSES = ("APPROVED", "EXECUTING", "COMPLETE")


def recompute_scope_cost(outage):
    total = Decimal(0)
    for wo in work_orders_of_outage(outage["id"]):
        if wo["status"] in COST_BASE_STATUSES:
            total += dec(wo["estimated_cost_usd"])
    base, contingency, grand = calc.scope_cost_rollup(total)
    outage["approved_scope_cost_usd"] = base
    outage["scope_contingency_usd"] = contingency
    outage["total_scope_cost_usd"] = grand
    return outage


# ---------------------------------------------------------------------------
# outage_critical_path
# ---------------------------------------------------------------------------
def _risk_factor(activity):
    if activity["work_order_id"] is None:
        return calc.UNLINKED_CONTINGENCY_PCT
    wo = store.work_orders.get(activity["work_order_id"])
    if wo is None:
        return calc.UNLINKED_CONTINGENCY_PCT
    return calc.CONTINGENCY_BY_PRIORITY[wo["priority"]]


def _assign_lengths(activity, pred):
    base_len = ZERO2 if pred is None else dec(pred["path_length_hours"])
    base_risk = ZERO2 if pred is None else dec(pred["risk_adjusted_path_length_hours"])
    duration = dec(activity["planned_duration_hours"])
    activity["path_length_hours"] = q2(base_len + duration)
    activity["risk_adjusted_path_length_hours"] = q2(
        base_risk + duration * (Decimal(1) + _risk_factor(activity)))


def recompute_critical_path(outage):
    every = activities_of_outage(outage["id"])
    for a in every:
        a["is_critical_path"] = False
    in_set = [a for a in every if a["execution_status"] != "CANCELLED"]
    by_id = dict((a["id"], a) for a in in_set)

    resolved = set()
    remaining = list(in_set)
    while remaining:
        progressed = False
        still = []
        for a in remaining:
            pid = a["predecessor_activity_id"]
            pred = by_id.get(pid) if pid else None
            if pred is None or pred["id"] in resolved:
                _assign_lengths(a, pred)
                resolved.add(a["id"])
                progressed = True
            else:
                still.append(a)
        remaining = still
        if not progressed:
            # Defensive only: the graph is kept acyclic by validation.
            for a in remaining:
                _assign_lengths(a, None)
                resolved.add(a["id"])
            remaining = []

    if not in_set:
        outage["projected_duration_hours"] = ZERO2
        outage["risk_adjusted_duration_hours"] = ZERO2
        outage["critical_path_activity_id"] = None
        return outage

    winner = None
    best_len = None
    best_risk = None
    for a in in_set:  # already ascending created_at
        length = dec(a["path_length_hours"])
        risk = dec(a["risk_adjusted_path_length_hours"])
        if best_len is None or length > best_len:
            best_len = length
            winner = a
        if best_risk is None or risk > best_risk:
            best_risk = risk

    outage["projected_duration_hours"] = q2(best_len)
    outage["risk_adjusted_duration_hours"] = q2(best_risk)
    outage["critical_path_activity_id"] = winner["id"]

    node = winner
    guard = 0
    while node is not None and guard <= len(in_set):
        node["is_critical_path"] = True
        pid = node["predecessor_activity_id"]
        node = by_id.get(pid) if pid else None
        guard += 1
    return outage


# ---------------------------------------------------------------------------
# outage_schedule_posture
# ---------------------------------------------------------------------------
def recompute_schedule_posture(outage):
    outage["schedule_posture"] = calc.schedule_posture(
        outage["projected_duration_hours"], outage["duration_target_hours"])
    return outage


def recompute_schedule(outage):
    recompute_critical_path(outage)
    recompute_schedule_posture(outage)
    return outage


# ---------------------------------------------------------------------------
# dose ledger (append-only; always replayed, never adjusted)
# ---------------------------------------------------------------------------
def append_dose_transaction(rwp, direction, amount_mrem, reason):
    return create_row(store.dose_transactions, {
        "rwp_id": rwp["id"],
        "direction": direction,
        "amount_mrem": q2(amount_mrem),
        "reason": reason,
    }, common=False)


def recompute_dose_ledger(outage):
    rows = []
    for txn in store.dose_transactions.values():
        permit = store.rwps.get(txn["rwp_id"])
        if permit is not None and permit["outage_id"] == outage["id"]:
            rows.append(txn)
    running = Decimal(0)
    for txn in sorted_rows(rows):
        if txn["direction"] == "COMMIT":
            running += dec(txn["amount_mrem"])
        else:
            running -= dec(txn["amount_mrem"])
    committed = q2(running)
    outage["dose_committed_mrem"] = committed
    outage["dose_budget_remaining_mrem"] = q2(
        dec(outage["dose_budget_total_mrem"]) - committed)
    return outage


# ---------------------------------------------------------------------------
# outage_alara_posture + the bidirectional hold cascade
# ---------------------------------------------------------------------------
def recompute_alara_posture(outage, previous):
    outage["alara_posture"] = calc.alara_posture(
        outage["dose_budget_remaining_mrem"], outage["dose_budget_total_mrem"])
    now = outage["alara_posture"]
    if previous == "NORMAL" and now != "NORMAL":
        for permit in rwps_of_outage(outage["id"]):
            if (permit["status"] == "DRAFT"
                    and dec(permit["committed_dose_mrem"]) > calc.ALARA_RESTRICTED_HOLD_MREM):
                permit["status"] = "HELD_FOR_ALARA"
                touch_row(permit)
    elif previous != "NORMAL" and now == "NORMAL":
        for permit in rwps_of_outage(outage["id"]):
            if permit["status"] == "HELD_FOR_ALARA":
                permit["status"] = "DRAFT"
                touch_row(permit)
    return outage


def recompute_dose(outage, previous_posture):
    recompute_dose_ledger(outage)
    recompute_alara_posture(outage, previous_posture)
    return outage


# ---------------------------------------------------------------------------
# work-order deferral cascade
# ---------------------------------------------------------------------------
def defer_work_order_cascade(work_order, void_approved_permits):
    """Hop 1 cancels NOT_STARTED activities, hop 2 voids permits.

    Returns True when at least one RELEASE ledger row was appended.
    """
    for activity in activities_of_work_order(work_order["id"]):
        if activity["execution_status"] == "NOT_STARTED":
            activity["execution_status"] = "CANCELLED"
            touch_row(activity)

    voidable = ["DRAFT", "HELD_FOR_ALARA"]
    if void_approved_permits:
        voidable.append("APPROVED")
    released = False
    for permit in rwps_of_work_order(work_order["id"]):
        if permit["status"] not in voidable:
            continue
        prior = permit["status"]
        permit["status"] = "VOIDED"
        permit["void_reason"] = "WORK_ORDER_DEFERRED"
        touch_row(permit)
        if prior == "APPROVED":
            append_dose_transaction(permit, "RELEASE",
                                    permit["committed_dose_mrem"],
                                    "WORK_ORDER_DEFERRED")
            released = True
    return released


def has_touched_activity(work_order):
    """True when any activity of the work order is IN_PROGRESS or COMPLETE."""
    for activity in activities_of_work_order(work_order["id"]):
        if activity["execution_status"] in ("IN_PROGRESS", "COMPLETE"):
            return True
    return False


# ---------------------------------------------------------------------------
# terminal-activity selector (PRD 3.8)
# ---------------------------------------------------------------------------
def terminal_activity(work_order_id):
    winner = None
    best = None
    for activity in activities_of_work_order(work_order_id):
        if activity["execution_status"] == "CANCELLED":
            continue
        finish = (dec(activity["planned_start_offset_hours"])
                  + dec(activity["planned_duration_hours"]))
        if best is None or finish > best:
            best = finish
            winner = activity
    return winner


# ---------------------------------------------------------------------------
# work-order completion bubble (PRD 3.2 / 3.4)
# ---------------------------------------------------------------------------
def maybe_complete_work_order(work_order):
    if work_order["status"] != "EXECUTING":
        return False
    activities = activities_of_work_order(work_order["id"])
    if not activities:
        return False
    saw_complete = False
    for activity in activities:
        if activity["execution_status"] == "COMPLETE":
            saw_complete = True
        elif activity["execution_status"] != "CANCELLED":
            return False
    if not saw_complete:
        return False
    work_order["status"] = "COMPLETE"
    touch_row(work_order)
    return True


# ---------------------------------------------------------------------------
# row minting shared by the operator endpoints and the emergent cascade
# ---------------------------------------------------------------------------
def mint_work_order(outage, wo_type, title, estimated_hours, estimated_cost_usd,
                    estimated_dose_mrem, regulatory_commitment, safety_function_id,
                    requires_rad_work, origin="PLANNED_SCOPE", status="SCOPED"):
    score, band = calc.work_order_priority(
        wo_type, estimated_hours, estimated_cost_usd, estimated_dose_mrem,
        regulatory_commitment, safety_function_id, outage["duration_target_hours"])
    return create_row(store.work_orders, {
        "outage_id": outage["id"],
        "wo_type": wo_type,
        "title": title,
        "estimated_hours": q2(estimated_hours),
        "estimated_cost_usd": q2(estimated_cost_usd),
        "estimated_dose_mrem": q2(estimated_dose_mrem),
        "regulatory_commitment": bool(regulatory_commitment),
        "safety_function_id": safety_function_id,
        "requires_rad_work": bool(requires_rad_work),
        "priority_score": score,
        "priority": band,
        "status": status,
        "origin": origin,
        "deferral_reason": None,
        "return_reason": None,
    })


def constraint_status_for(predecessor):
    if predecessor is None:
        return "CLEAR"
    return "CLEAR" if predecessor["execution_status"] == "COMPLETE" else "BLOCKED"


def mint_activity(outage, label, planned_start_offset_hours, planned_duration_hours,
                  work_order_id=None, predecessor_activity_id=None,
                  oos_safety_function_id=None, oos_train_label=None):
    predecessor = (store.schedule_activities.get(predecessor_activity_id)
                   if predecessor_activity_id else None)
    return create_row(store.schedule_activities, {
        "outage_id": outage["id"],
        "work_order_id": work_order_id,
        "label": label,
        "planned_start_offset_hours": q2(planned_start_offset_hours),
        "planned_duration_hours": q2(planned_duration_hours),
        "predecessor_activity_id": predecessor_activity_id,
        "oos_safety_function_id": oos_safety_function_id,
        "oos_train_label": oos_train_label,
        "execution_status": "NOT_STARTED",
        "constraint_status": constraint_status_for(predecessor),
        "path_length_hours": ZERO2,
        "risk_adjusted_path_length_hours": ZERO2,
        "is_critical_path": False,
        "started_at": None,
        "completed_at": None,
    })
