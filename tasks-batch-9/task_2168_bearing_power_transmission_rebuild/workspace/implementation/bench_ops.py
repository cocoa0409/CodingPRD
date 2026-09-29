"""Bench capacity cascades shared by orders, cores and reservations."""

import calc
import store


def free_capacity(bench):
    """Recompute minutes, promote at most one queued window, recompute again."""
    if bench is None:
        return
    calc.recompute_committed_minutes(bench)
    winner = calc.queue_promotion(bench)
    if winner is not None:
        calc.recompute_committed_minutes(bench)


def release_order_reservations(order, statuses=("QUEUED", "HELD", "CONFIRMED")):
    """CASCADE B hops 1-4."""
    touched = []
    for res in calc.reservations_of_order(order["id"]):
        if res["status"] in statuses:
            res["status"] = "RELEASED"
            store.touch(res)
            if res["bench_id"] not in touched:
                touched.append(res["bench_id"])
    for bench_id in touched:
        free_capacity(store.get("benches", bench_id))


def consume_order_reservations(order):
    """CASCADE C hops 1-3."""
    touched = []
    for res in calc.reservations_of_order(order["id"]):
        if res["status"] == "CONFIRMED":
            res["status"] = "CONSUMED"
            store.touch(res)
            if res["bench_id"] not in touched:
                touched.append(res["bench_id"])
    for bench_id in touched:
        free_capacity(store.get("benches", bench_id))
