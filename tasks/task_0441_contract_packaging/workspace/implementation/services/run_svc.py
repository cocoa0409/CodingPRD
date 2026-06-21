"""ProductionRun lifecycle business logic (PRD §3.3-§3.7).

Scheduling, start (changeover/expiry/material/FEFO/lot-code/CMR), complete
(run rate, waste, scrap CMR), release, quarantine, and cancel compensation.
"""
from datetime import timedelta

import clock
import db
import errors
import util
from services import calc, inventory, recipe_svc

LIVE_RUN_STATES = {"SCHEDULED", "RUNNING", "PENDING_QA"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def bom_lines_for_run(run):
    return recipe_svc.bom_lines_for_recipe(run["recipe_id"])


def consumptions_for_run(run_id):
    return [lc for lc in db.lot_consumptions.values() if lc["production_run_id"] == run_id]


def _fefo_candidates(component_id, include_expired):
    """AVAILABLE lots of the component ordered FEFO (expiration ASC, _seq ASC).

    include_expired toggles whether expired lots are kept in the candidate list.
    """
    now = clock.now()
    lots = []
    for lot in db.component_lots.values():
        if lot["component_id"] != component_id:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if not include_expired and lot["_expiration_dt"] <= now:
            continue
        lots.append(lot)
    lots.sort(key=lambda l: (l["_expiration_dt"], l.get("_seq", 0)))
    return lots


# ---------------------------------------------------------------------------
# Scheduling (overlap checks + reservation)
# ---------------------------------------------------------------------------
def overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap: a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def overlaps_closed(a_start, a_end, b_start, b_end):
    """Closed [start,end] overlap: a_start <= b_end and b_start <= a_end."""
    return a_start <= b_end and b_start <= a_end


def check_line_overlap(line_id, start, end):
    """Half-open line window must not overlap a non-terminal run on the line."""
    for run in db.production_runs.values():
        if run["line_id"] != line_id:
            continue
        if run["status"] not in LIVE_RUN_STATES:
            continue
        if overlaps_half_open(start, end, run["_scheduled_start_dt"], run["_scheduled_end_dt"]):
            raise errors.line_overlap()


def check_crew_overlap(crew, start, end):
    """Buffer-padded closed crew window must not overlap a non-terminal run on
    the crew. Back-to-back rejected (closed interval includes endpoints)."""
    buf = timedelta(minutes=crew["rest_buffer_minutes"])
    pad_start = start - buf
    pad_end = end + buf
    for run in db.production_runs.values():
        if run["crew_id"] != crew["id"]:
            continue
        if run["status"] not in LIVE_RUN_STATES:
            continue
        if overlaps_closed(pad_start, pad_end, run["_scheduled_start_dt"], run["_scheduled_end_dt"]):
            raise errors.crew_overlap()


def reserve_material(run, recipe):
    """Raise each BOM component's reserved_qty by the line's scrap-inflated
    required_qty; recompute on_hand. Each affected component is mutated."""
    planned = run["planned_units"]
    touched = {}
    for line in recipe_svc.bom_lines_for_recipe(recipe["id"]):
        comp = db.components.get(line["component_id"])
        if comp is None:
            continue
        required = calc.required_qty_for_line(line, planned)
        touched.setdefault(comp["id"], 0)
        touched[comp["id"]] += required
    for cid, qty in touched.items():
        comp = db.components[cid]
        inventory.add_reserved(comp, qty)
        db.touch(comp)


def release_reservation(run, recipe):
    """Release reserved_qty held for this run on every BOM component."""
    planned = run["planned_units"]
    touched = {}
    for line in recipe_svc.bom_lines_for_recipe(recipe["id"]):
        comp = db.components.get(line["component_id"])
        if comp is None:
            continue
        required = calc.required_qty_for_line(line, planned)
        touched.setdefault(comp["id"], 0)
        touched[comp["id"]] += required
    for cid, qty in touched.items():
        comp = db.components[cid]
        inventory.release_reserved(comp, qty)
        db.touch(comp)


# ---------------------------------------------------------------------------
# Start: validate then consume
# ---------------------------------------------------------------------------
def check_allergen_changeover(line, recipe):
    """Line residue must not carry an allergen absent from recipe profile,
    unless sanitized since the last started run."""
    residue = set(line.get("current_allergen_residue", []))
    profile = set(recipe.get("allergen_profile", []))
    extra = residue - profile
    if extra and not line.get("_sanitized_since_last_run", False):
        raise errors.allergen_changeover_required()


def check_expiry_and_material(run, recipe):
    """Run the expiry gate (priority 22) then material sufficiency (priority 23).

    Returns a consumption plan: list of (bom_line, lot, qty) to apply on commit.
    """
    planned = run["planned_units"]
    now = clock.now()
    lines = recipe_svc.bom_lines_for_recipe(recipe["id"])

    # Simulate draws across a shared per-lot residual map so multiple BOM lines
    # sharing a component don't double-count the same physical stock.
    sim_remaining = {}  # lot_id -> remaining used in simulation

    def remaining_of(lot):
        return sim_remaining.get(lot["id"], lot["remaining_qty"])

    # ---- Expiry gate (priority 22) ----
    # For each line, draw FEFO across ALL available lots (expired included). If
    # the draw would touch an expired lot, the start is blocked. If non-expired
    # stock covers the requirement, no expired lot is "selected".
    expiry_sim = {}

    def expiry_remaining(lot):
        return expiry_sim.get(lot["id"], lot["remaining_qty"])

    for line in lines:
        required = calc.required_qty_for_line(line, planned)
        residual = util.to_decimal(required)
        candidates = _fefo_candidates(line["component_id"], include_expired=True)
        for lot in candidates:
            if residual <= 0:
                break
            avail = util.to_decimal(expiry_remaining(lot))
            if avail <= 0:
                continue
            draw = avail if avail < residual else residual
            if lot["_expiration_dt"] <= now:
                # an expired lot would be drawn -> blocked
                raise errors.lot_expired()
            expiry_sim[lot["id"]] = float(avail - draw)
            residual -= draw

    # ---- Material sufficiency (priority 23) + build the real plan ----
    plan = []
    for line in lines:
        required = calc.required_qty_for_line(line, planned)
        residual = util.to_decimal(required)
        candidates = _fefo_candidates(line["component_id"], include_expired=False)
        for lot in candidates:
            if residual <= 0:
                break
            avail = util.to_decimal(remaining_of(lot))
            if avail <= 0:
                continue
            draw = avail if avail < residual else residual
            draw_f = util.round_half_up(draw, 3)
            plan.append((line, lot, draw_f))
            sim_remaining[lot["id"]] = float(avail - util.to_decimal(draw_f))
            residual -= util.to_decimal(draw_f)
        if residual > 0:
            raise errors.insufficient_material()
    return plan


def mint_lot_code(run, recipe, customer, pack_date):
    """Compute the run's sequence within (customer, pack day) and assemble code."""
    pack_yyyymmdd = "{:04d}{:02d}{:02d}".format(pack_date.year, pack_date.month, pack_date.day)
    reached_running = {"RUNNING", "PENDING_QA", "RELEASED", "QUARANTINED"}
    seq = 1
    for other in db.production_runs.values():
        if other["id"] == run["id"]:
            continue
        if other["status"] not in reached_running:
            continue
        o_recipe = db.recipes.get(other["recipe_id"])
        if o_recipe is None or o_recipe["customer_id"] != recipe["customer_id"]:
            continue
        o_pack = other.get("_pack_date_dt")
        if o_pack is None:
            continue
        o_yyyymmdd = "{:04d}{:02d}{:02d}".format(o_pack.year, o_pack.month, o_pack.day)
        if o_yyyymmdd == pack_yyyymmdd:
            seq += 1
    return calc.assign_lot_code(customer["code"], pack_date, recipe["name"], seq)


def apply_start(run, recipe, line, customer, plan):
    """Apply the atomic start cascade once all preconditions have passed."""
    now = clock.now()
    run["pack_date"] = clock.to_iso_millis(now)
    run["_pack_date_dt"] = now
    run["status"] = "RUNNING"
    run["lot_code"] = mint_lot_code(run, recipe, customer, now)

    # Consume FEFO: create LotConsumption rows, decrement remaining_qty,
    # DEPLETE at 0. Aggregate consumed per component for CMR + on_hand recompute.
    consumed_by_component = {}  # component_id -> total consumed_qty
    touched_components = {}
    for bom_line, lot, qty in plan:
        comp = db.components[bom_line["component_id"]]
        lc = db.new_append_record({
            "production_run_id": run["id"],
            "component_lot_id": lot["id"],
            "bom_line_id": bom_line["id"],
            "consumed_qty": qty,
            "customer_owned": bool(comp["customer_owned"]),
        })
        db.lot_consumptions[lc["id"]] = lc

        new_remaining = util.round_half_up(
            util.to_decimal(lot["remaining_qty"]) - util.to_decimal(qty), 3)
        if new_remaining < 0:
            new_remaining = 0
        lot["remaining_qty"] = new_remaining
        if new_remaining == 0:
            lot["status"] = "DEPLETED"
        db.touch(lot)

        consumed_by_component.setdefault(comp["id"], 0)
        consumed_by_component[comp["id"]] = util.round_half_up(
            consumed_by_component[comp["id"]] + qty, 3)
        touched_components[comp["id"]] = comp

    # release this run's reservation, recompute on_hand for affected components.
    release_reservation(run, recipe)
    for comp in touched_components.values():
        inventory.recompute_component_on_hand(comp)
        db.touch(comp)

    # set line residue; reset the sanitized flag (this is now the last run);
    # bump line version.
    line["current_allergen_residue"] = list(recipe.get("allergen_profile", []))
    line["_sanitized_since_last_run"] = False
    db.touch(line)

    # CMR CONSUME entries for customer-owned components (negative delta).
    for cid, total in consumed_by_component.items():
        comp = db.components[cid]
        if comp["customer_owned"]:
            entry = db.new_append_record({
                "customer_id": comp["customer_id"],
                "component_id": cid,
                "production_run_id": run["id"],
                "delta_qty": util.round_half_up(-total, 3),
                "reason": "CONSUME",
            })
            db.cmr_ledger_entries[entry["id"]] = entry

    db.touch(run)


# ---------------------------------------------------------------------------
# Complete: run rate + waste + scrap CMR
# ---------------------------------------------------------------------------
def apply_complete(run, recipe, actual_good, actual_scrapped):
    run["actual_units_good"] = actual_good
    run["actual_units_scrapped"] = actual_scrapped

    # run rate
    now = clock.now()
    pack_dt = run["_pack_date_dt"]
    elapsed_hours = (now - pack_dt).total_seconds() / 3600.0
    total_units = actual_good + actual_scrapped
    run["run_rate_units_per_hour"] = calc.run_rate(total_units, elapsed_hours)

    run["status"] = "PENDING_QA"

    # SCRAP_WASTE CMR entries per customer-owned component, using actual waste.
    consumptions = consumptions_for_run(run["id"])
    # group consumed_qty by bom_line
    consumed_by_line = {}
    for lc in consumptions:
        consumed_by_line.setdefault(lc["bom_line_id"], 0)
        consumed_by_line[lc["bom_line_id"]] = util.round_half_up(
            consumed_by_line[lc["bom_line_id"]] + lc["consumed_qty"], 3)

    waste_by_component = {}
    for bom_line in recipe_svc.bom_lines_for_recipe(recipe["id"]):
        consumed_line = consumed_by_line.get(bom_line["id"], 0)
        if bom_line["id"] not in consumed_by_line:
            continue
        actual_waste = calc.actual_waste_line(
            consumed_line, bom_line["qty_per_unit"], actual_good)
        comp = db.components.get(bom_line["component_id"])
        if comp is None:
            continue
        waste_by_component.setdefault(comp["id"], 0)
        waste_by_component[comp["id"]] = util.round_half_up(
            waste_by_component[comp["id"]] + actual_waste, 3)

    for cid, waste in waste_by_component.items():
        comp = db.components[cid]
        if comp["customer_owned"]:
            entry = db.new_append_record({
                "customer_id": comp["customer_id"],
                "component_id": cid,
                "production_run_id": run["id"],
                "delta_qty": util.round_half_up(-waste, 3),
                "reason": "SCRAP_WASTE",
            })
            db.cmr_ledger_entries[entry["id"]] = entry

    db.touch(run)


# ---------------------------------------------------------------------------
# Release / Quarantine
# ---------------------------------------------------------------------------
def apply_release(run, recipe):
    pack_dt = run["_pack_date_dt"]
    fg_exp = pack_dt + timedelta(days=recipe["shelf_life_days"])
    run["fg_expiration_date"] = clock.to_iso_millis(fg_exp)
    run["status"] = "RELEASED"
    db.touch(run)


def apply_quarantine(run):
    consumptions = consumptions_for_run(run["id"])
    affected_components = {}
    for lc in consumptions:
        lot = db.component_lots.get(lc["component_lot_id"])
        if lot is None:
            continue
        if lot["status"] != "QUARANTINED":
            lot["status"] = "QUARANTINED"
            db.touch(lot)
        comp = db.components.get(lot["component_id"])
        if comp is not None:
            affected_components[comp["id"]] = comp
    for comp in affected_components.values():
        inventory.recompute_component_on_hand(comp)
        db.touch(comp)
    run["status"] = "QUARANTINED"
    db.touch(run)


# ---------------------------------------------------------------------------
# Cancel (SCHEDULED release reservations, RUNNING compensation)
# ---------------------------------------------------------------------------
def apply_cancel_scheduled(run, recipe):
    release_reservation(run, recipe)
    run["status"] = "CANCELLED"
    db.touch(run)


def apply_cancel_running(run, recipe):
    consumptions = consumptions_for_run(run["id"])
    affected_components = {}
    returned_by_component = {}
    for lc in consumptions:
        lot = db.component_lots.get(lc["component_lot_id"])
        if lot is not None:
            new_remaining = util.round_half_up(
                util.to_decimal(lot["remaining_qty"]) + util.to_decimal(lc["consumed_qty"]), 3)
            lot["remaining_qty"] = new_remaining
            if lot["status"] == "DEPLETED" and new_remaining > 0:
                lot["status"] = "AVAILABLE"
            db.touch(lot)
            comp = db.components.get(lot["component_id"])
            if comp is not None:
                affected_components[comp["id"]] = comp
        comp = db.components.get(_component_of_lot_consumption(lc))
        if comp is not None and comp["customer_owned"]:
            returned_by_component.setdefault(comp["id"], 0)
            returned_by_component[comp["id"]] = util.round_half_up(
                returned_by_component[comp["id"]] + lc["consumed_qty"], 3)

    for comp in affected_components.values():
        inventory.recompute_component_on_hand(comp)
        db.touch(comp)

    # RETURN_ON_CANCEL entries net the CMR balance to zero per component.
    for cid, total in returned_by_component.items():
        comp = db.components[cid]
        entry = db.new_append_record({
            "customer_id": comp["customer_id"],
            "component_id": cid,
            "production_run_id": run["id"],
            "delta_qty": util.round_half_up(total, 3),
            "reason": "RETURN_ON_CANCEL",
        })
        db.cmr_ledger_entries[entry["id"]] = entry

    run["status"] = "CANCELLED"
    db.touch(run)


def _component_of_lot_consumption(lc):
    lot = db.component_lots.get(lc["component_lot_id"])
    if lot is None:
        return None
    return lot["component_id"]


# ---------------------------------------------------------------------------
# Summary (computed read)
# ---------------------------------------------------------------------------
def compute_summary(run, recipe):
    """lot_code, run_rate, reject_rate, planned_waste_total, actual_waste_total.

    Waste totals: round each per-line figure to 3 decimals FIRST, then sum;
    the sum is not re-rounded.
    """
    samples = [s for s in db.checkweigh_samples.values() if s["production_run_id"] == run["id"]]
    reject_rate = calc.checkweigh_reject_rate(samples) if samples else 0.0

    planned = run["planned_units"]
    actual_good = run["actual_units_good"]

    consumptions = consumptions_for_run(run["id"])
    consumed_by_line = {}
    for lc in consumptions:
        consumed_by_line.setdefault(lc["bom_line_id"], 0)
        consumed_by_line[lc["bom_line_id"]] = util.round_half_up(
            consumed_by_line[lc["bom_line_id"]] + lc["consumed_qty"], 3)

    planned_total = 0.0
    actual_total = 0.0
    for bom_line in recipe_svc.bom_lines_for_recipe(recipe["id"]):
        planned_waste = calc.planned_waste_line(bom_line, planned)
        planned_total += util.round_half_up(planned_waste, 3)
        if bom_line["id"] in consumed_by_line:
            actual_waste = calc.actual_waste_line(
                consumed_by_line[bom_line["id"]], bom_line["qty_per_unit"], actual_good)
            actual_total += util.round_half_up(actual_waste, 3)

    return {
        "lot_code": run["lot_code"],
        "run_rate_units_per_hour": run["run_rate_units_per_hour"],
        "reject_rate": reject_rate,
        "planned_waste_total": planned_total,
        "actual_waste_total": actual_total,
    }
