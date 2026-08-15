"""seasonal_build_projection (PRD §3.4): recomputed on every event that could
move it; every recompute increments the window's version (PRD §2.11).

confirmed_build_units = sum of qty_on_hand over ACTIVE lots whose run belongs
                        to the window
projected_build_units = confirmed + sum of planned_units over runs in
                        {PLANNED, IN_PROGRESS, ON_HOLD}
coverage_pct          = round_half_up(100 * confirmed / target_units, 1)
shortfall             = confirmed < target_units
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store, touch

PIPELINE_STATUSES = ("PLANNED", "IN_PROGRESS", "ON_HOLD")


def recompute_window(window):
    confirmed = 0
    for lot in store.lots.values():
        if lot["status"] != "ACTIVE":
            continue
        run = store.production_runs.get(lot["run_id"])
        if run is not None and run["window_id"] == window["id"]:
            confirmed += lot["qty_on_hand"]
    pipeline = 0
    for run in store.production_runs.values():
        if run["window_id"] == window["id"] and run["status"] in PIPELINE_STATUSES:
            pipeline += run["planned_units"]
    window["confirmed_build_units"] = confirmed
    window["projected_build_units"] = confirmed + pipeline
    pct = (Decimal(100 * confirmed) / Decimal(window["target_units"])).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)
    window["coverage_pct"] = float(pct)
    window["shortfall"] = confirmed < window["target_units"]
    touch(window)


def recompute_window_of_lot(lot):
    """Recompute the projection of the window containing the lot's run."""
    run = store.production_runs.get(lot["run_id"])
    if run is not None:
        window = store.seasonal_windows.get(run["window_id"])
        if window is not None:
            recompute_window(window)
