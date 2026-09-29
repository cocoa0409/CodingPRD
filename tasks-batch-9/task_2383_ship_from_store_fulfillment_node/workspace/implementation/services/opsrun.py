"""The seven-step operations run (PRD 3.9, POST /performance-windows/close)."""
import clock
from constants import (
    LIVE_STATUSES, MAX_CONSECUTIVE_BREACH_WINDOWS, MAX_REROUTE_ATTEMPTS,
)
from db import db, sorted_rows
from errors import ApiError
from services import notifications
from services.assignments import release_assignment
from services.derive import (
    apply_window_metrics, assignments_of_order, create_window, eligibility_score,
    open_window, recompute_all,
)
from services.routing import (
    base_generation_for, create_run, execute_run, strand_open_units,
)


def run_operations_close(marked):
    """`marked` collects rows that must take an explicit version bump."""
    if not any(w["status"] == "OPEN" for w in db.windows.values()):
        raise ApiError("ERR_NO_OPEN_WINDOW")

    instant = clock.now()

    # --- Step 1: reap assignments whose pick deadline has elapsed.
    expired = [a for a in db.assignments.values()
               if a["status"] in ("ASSIGNED", "ACCEPTED")
               and a["pick_deadline_utc"] <= instant]
    for assignment in sorted_rows(expired):
        release_assignment(assignment, "CANCELLED", "PICK_SLA_EXPIRED")
        marked.append(assignment)
    recompute_all()

    # --- Step 2: measure every open window, ascending store.created_at.
    open_windows = sorted(
        [w for w in db.windows.values() if w["status"] == "OPEN"],
        key=lambda w: db.stores[w["store_id"]]["_seq"])
    for window in open_windows:
        apply_window_metrics(window)

    # --- Step 3: decide and apply node_action, write review_score, cascade.
    deactivation_orders = set()
    for window in open_windows:
        store = db.stores[window["store_id"]]
        review, _basis = eligibility_score(store, "governance", window)
        store["review_score"] = review

        created = window["assignments_created"]
        breached = window["breached"]
        streak = store["consecutive_breach_windows"]
        if created == 0:
            action = "NONE"
        elif breached and streak + 1 >= MAX_CONSECUTIVE_BREACH_WINDOWS:
            action = "DEACTIVATION"
        elif breached and store["node_status"] == "ELIGIBLE":
            action = "PROBATION"
        elif not breached and store["node_status"] == "PROBATION":
            action = "RECOVERY"
        else:
            action = "NONE"
        window["node_action"] = action

        if created >= 1:
            store["consecutive_breach_windows"] = 0 if not breached else streak + 1

        if action == "PROBATION":
            store["node_status"] = "PROBATION"
        elif action == "RECOVERY":
            store["node_status"] = "ELIGIBLE"
            store["consecutive_breach_windows"] = 0
        elif action == "DEACTIVATION":
            store["node_status"] = "DEACTIVATED"
            store["deactivated_at_epoch"] = window["epoch"]
            victims = [a for a in db.assignments.values()
                       if a["store_id"] == store["id"] and a["status"] in LIVE_STATUSES]
            for assignment in sorted_rows(victims):
                release_assignment(assignment, "CANCELLED", "NODE_DEACTIVATED")
                marked.append(assignment)
                deactivation_orders.add(assignment["order_id"])
            recompute_all(skip_windows=True)

    # --- Step 4: close the measured windows and reset the epoch commitment.
    for window in open_windows:
        window["status"] = "CLOSED"
        window["closed_at_utc"] = instant
        marked.append(window)
    recompute_all()

    # --- Step 5: open the next epoch for nodes that are still routable.
    for window in open_windows:
        store = db.stores[window["store_id"]]
        if store["node_status"] in ("ELIGIBLE", "PROBATION"):
            create_window(store, window["epoch"] + 1)
    recompute_all()

    # --- Step 6: retry every order left at ROUTING.
    pending = sorted_rows([o for o in db.orders.values()
                           if o["routing_status"] == "ROUTING"])
    for order in pending:
        initiated_by = ("SYSTEM_DEACTIVATION" if order["id"] in deactivation_orders
                        else "SYSTEM_REROUTE")
        base = base_generation_for(order)
        run = create_run(order, "COMMIT", initiated_by, [])
        outcome = execute_run(run, order, base_generation=base)
        recompute_all()

        stranded = outcome["dc_fallback_units"]
        if (order["unassigned_units"] > 0
                and order["reroute_attempt_count"] >= MAX_REROUTE_ATTEMPTS):
            stranded += strand_open_units(order)

        notification_type = notifications.choose_type(
            "system_retry",
            dc_fallback_raised=stranded > 0,
            replacements_created=len(outcome["created"]) > 0,
            initiated_by=initiated_by)
        if stranded > 0:
            affected = stranded
        elif outcome["created"]:
            affected = sum(a["assigned_units"] for a in outcome["created"])
        else:
            affected = order["unassigned_units"]
        notifications.emit(order, None, notification_type, affected)

    # --- Step 7: refresh eligibility on the trailing-window basis.
    for store in db.stores.values():
        if store["node_status"] in ("ELIGIBLE", "PROBATION"):
            score, basis = eligibility_score(store)
            store["eligibility_score"] = score
            store["eligibility_score_basis"] = basis
    recompute_all()

    return sorted(open_windows, key=lambda w: db.stores[w["store_id"]]["_seq"])
