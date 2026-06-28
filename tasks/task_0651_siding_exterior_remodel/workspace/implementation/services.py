"""Cross-entity business logic: contract-total recompute, cascades, scheduling
overlap checks. Kept separate from the route layer (app.py) so the state-machine
side effects live in one place.
"""
from datetime import timedelta

import calculations as calc
import helpers
from db import db

SITE_BUFFER = timedelta(hours=24)


# ----------------------------------------------------------------------------
# Estimate totals recompute (after a line item is added/adjusted)
# ----------------------------------------------------------------------------
def recompute_estimate_totals(estimate):
    items = [li for li in db.line_items.values() if li["estimate_id"] == estimate["id"]]
    subtotal = calc.estimate_subtotal(items)
    tax, total = calc.estimate_total(subtotal)
    estimate["line_subtotal_cents"] = subtotal
    estimate["tax_cents"] = tax
    estimate["estimate_total_cents"] = total
    helpers.touch(estimate)


# ----------------------------------------------------------------------------
# Project contract total recompute (baseline + sum APPROVED change-order deltas)
# This is a mutation of the project: touches updated_at + version (PRD 2.4).
# ----------------------------------------------------------------------------
def recompute_contract_total(project):
    baseline = _baseline_estimate(project["id"])
    baseline_total = baseline["estimate_total_cents"] if baseline else 0
    approved_deltas = [
        co["delta_cents"]
        for co in db.change_orders.values()
        if co["project_id"] == project["id"] and co["status"] == "APPROVED"
    ]
    project["contract_total_cents"] = calc.realized_contract_total(baseline_total, approved_deltas)
    helpers.touch(project)


def _baseline_estimate(project_id):
    for e in db.estimates.values():
        if e["project_id"] == project_id and e["status"] == "BASELINE":
            return e
    return None


def baseline_estimate(project_id):
    return _baseline_estimate(project_id)


# ----------------------------------------------------------------------------
# Scheduling overlap helpers
# ----------------------------------------------------------------------------
def crew_overlap(candidate, crew_id):
    """Half-open [start, end) overlap against other CONFIRMED windows for the
    same crew. Adjacency (end == next start) does NOT collide; no buffer."""
    cs = helpers.parse_dt(candidate["window_start_iso"], "window_start_iso")
    ce = helpers.parse_dt(candidate["window_end_iso"], "window_end_iso")
    for w in db.work_schedules.values():
        if w["id"] == candidate["id"]:
            continue
        if w["crew_id"] != crew_id:
            continue
        if w["status"] != "CONFIRMED":
            continue
        ws = helpers.parse_dt(w["window_start_iso"], "window_start_iso")
        we = helpers.parse_dt(w["window_end_iso"], "window_end_iso")
        # half-open overlap: cs < we and ws < ce
        if cs < we and ws < ce:
            return True
    return False


def site_window_conflict(candidate, project_id):
    """Closed interval expanded by +/-24h against other CONFIRMED windows for the
    same project. Touching (end == start after buffer) DOES collide."""
    cs = helpers.parse_dt(candidate["window_start_iso"], "window_start_iso") - SITE_BUFFER
    ce = helpers.parse_dt(candidate["window_end_iso"], "window_end_iso") + SITE_BUFFER
    for w in db.work_schedules.values():
        if w["id"] == candidate["id"]:
            continue
        if w["project_id"] != project_id:
            continue
        if w["status"] != "CONFIRMED":
            continue
        ws = helpers.parse_dt(w["window_start_iso"], "window_start_iso")
        we = helpers.parse_dt(w["window_end_iso"], "window_end_iso")
        # closed-interval overlap-or-touch: cs <= we and ws <= ce
        if cs <= we and ws <= ce:
            return True
    return False


def project_material_order_delivered(project_id):
    """True if the project has a MaterialOrder whose status == DELIVERED."""
    for mo in db.material_orders.values():
        if mo["project_id"] == project_id and mo["status"] == "DELIVERED":
            return True
    return False


# ----------------------------------------------------------------------------
# Cascades
# ----------------------------------------------------------------------------
def cancel_work_schedule_cascade(ws):
    """Set WorkSchedule -> CANCELLED and cascade any REQUESTED/APPROVED draw on
    it to REJECTED. Each touched resource gets its own version/updated_at bump."""
    ws["status"] = "CANCELLED"
    helpers.touch(ws)
    for draw in db.progress_draws.values():
        if draw["work_schedule_id"] == ws["id"] and draw["status"] in ("REQUESTED", "APPROVED"):
            draw["status"] = "REJECTED"
            helpers.touch(draw)


def cancel_material_order_cascade(mo):
    """Set MaterialOrder -> CANCELLED and cascade every PROPOSED/CONFIRMED
    WorkSchedule for the project to CANCELLED (which itself cascades draws)."""
    mo["status"] = "CANCELLED"
    helpers.touch(mo)
    for ws in db.work_schedules.values():
        if ws["project_id"] == mo["project_id"] and ws["status"] in ("PROPOSED", "CONFIRMED"):
            cancel_work_schedule_cascade(ws)


def cancel_project_cascade(project):
    """Depth-3 cascade: project -> material orders -> work schedules -> draws.
    Voids PENDING warranties. Bumps project version once (caller already touched
    or will touch — here we set status, run cascade, void warranties, bump)."""
    project["workflow_status"] = "CANCELLED"
    # Cascade is chained strictly through material-order cancellation (PRD 3.8 /
    # scaffold project-cancel side_effects): every non-terminal material order
    # (PLACED, CONFIRMED, BACKORDERED) -> CANCELLED, and THAT cancellation sets
    # every PROPOSED/CONFIRMED WorkSchedule -> CANCELLED (which in turn rejects
    # its REQUESTED/APPROVED draws). A terminal (DELIVERED/already-CANCELLED)
    # material order does not trigger schedule cancellation — do not add an
    # independent schedule-cancel path; that would deviate from the literal chain.
    for mo in db.material_orders.values():
        if mo["project_id"] == project["id"] and mo["status"] in ("PLACED", "CONFIRMED", "BACKORDERED"):
            cancel_material_order_cascade(mo)
    # void all PENDING warranty rows
    for wty in db.warranties.values():
        if wty["project_id"] == project["id"] and wty["status"] == "PENDING":
            wty["status"] = "VOID"
            helpers.touch(wty)
    # increments Project.version by 1 (also refreshes updated_at)
    helpers.touch(project)
