"""Cross-entity services: serializers, derived rollups, cascades, schedule
overlap, credit exposure, material waterfall."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import fmt_ts, fmt_dt, num_out, wall_now, next_seq
from calc import effective_cavities as calc_effective_cavities


# ---------------------------------------------------------------------------
# base entity helpers
# ---------------------------------------------------------------------------

def new_entity(fields):
    e = dict(fields)
    e["id"] = None  # caller assigns
    return e


def stamp_new(e, entity_id):
    ts = wall_now()
    e["id"] = entity_id
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["seq"] = next_seq()
    return e


def touch(e):
    """Version bump + updated_at refresh for a mutated resource."""
    e["version"] += 1
    e["updated_at"] = wall_now()


def base_out(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["seq"]))


# ---------------------------------------------------------------------------
# mold / blockout derived figures
# ---------------------------------------------------------------------------

def open_blockouts(mold_id):
    return [b for b in store.cavity_blockouts.values()
            if b["mold_id"] == mold_id and b["status"] == "OPEN"]


def mold_effective_cavities(mold):
    return calc_effective_cavities(mold["base_cavities"],
                                   len(open_blockouts(mold["id"])))


# ---------------------------------------------------------------------------
# material lot derived figures
# ---------------------------------------------------------------------------

def lot_available(lot):
    avail = lot["received_kg"] - lot["consumed_kg"] - lot["purge_wasted_kg"]
    if avail < 0:
        avail = Decimal("0")
    return avail


def matching_resin_lots(resin_type):
    """Waterfall candidates: RESIN lots of the spec's resin family in
    RELEASED/IN_USE, created_at ASC, tie lot_code ASC."""
    rows = [l for l in store.material_lots.values()
            if l["material_type"] == "RESIN"
            and l["resin_type"] == resin_type
            and l["status"] in ("RELEASED", "IN_USE")]
    return sorted(rows, key=lambda l: (l["created_at"], l["lot_code"]))


def total_available(resin_type):
    total = Decimal("0")
    for lot in matching_resin_lots(resin_type):
        total += lot_available(lot)
    return total


# ---------------------------------------------------------------------------
# production order rollups (derived on read)
# ---------------------------------------------------------------------------

def order_rollups(order):
    runs = [r for r in store.production_runs.values()
            if r["production_order_id"] == order["id"] and r["status"] != "VOIDED"]
    produced = 0
    good = 0
    scrapped = 0
    for r in runs:
        if r["status"] == "CLOSED":
            produced += (r["good_count"] or 0) + (r["scrap_count"] or 0)
            good += r["good_count"] or 0
            scrapped += r["scrap_count"] or 0
    run_ids = {r["id"] for r in runs}
    accepted = 0
    qc_scrapped = 0
    for lot in store.quality_test_lots.values():
        if lot["production_run_id"] not in run_ids:
            continue
        if lot["status"] == "ACCEPTED":
            accepted += lot["lot_size"]
        elif lot["status"] == "SCRAPPED":
            qc_scrapped += lot["lot_size"]
    reserved = 0
    shipped = 0
    for s in store.shipments.values():
        if s["production_order_id"] != order["id"]:
            continue
        if s["status"] in ("BOOKED", "LOADING", "IN_TRANSIT"):
            reserved += s["quantity"]
        elif s["status"] == "DELIVERED":
            shipped += s["quantity"]
    return {
        "quantity_produced": produced,
        "quantity_good": good,
        "quantity_scrapped": scrapped,
        "quantity_accepted": accepted,
        "quantity_qc_scrapped": qc_scrapped,
        "quantity_open_qc": good - accepted - qc_scrapped,
        "quantity_reserved": reserved,
        "quantity_shipped": shipped,
        "quantity_unallocated": accepted - reserved - shipped,
    }


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def ser_customer(c):
    out = base_out(c)
    out.update({
        "name": c["name"],
        "customer_code": c["customer_code"],
        "credit_limit_cents": c["credit_limit_cents"],
        "default_logistics_mode": c["default_logistics_mode"],
        "status": c["status"],
    })
    return out


def ser_rate_card(c):
    out = base_out(c)
    out.update({
        "lane_code": c["lane_code"],
        "tiers": [{"min_kg": num_out(t["min_kg"]),
                   "rate_cents_per_kg": num_out(t["rate_cents_per_kg"])}
                  for t in c["tiers"]],
        "status": c["status"],
    })
    return out


def spec_qualification_round(spec):
    return sum(1 for r in store.qualification_runs.values()
               if r["bottle_spec_id"] == spec["id"])


def ser_bottle_spec(s):
    out = base_out(s)
    out.update({
        "customer_id": s["customer_id"],
        "spec_code": s["spec_code"],
        "resin_type": s["resin_type"],
        "color_contrast_class": s["color_contrast_class"],
        "target_weight_g": num_out(s["target_weight_g"]),
        "weight_tolerance_pct": num_out(s["weight_tolerance_pct"]),
        "neck_finish": s["neck_finish"],
        "height_mm": num_out(s["height_mm"]),
        "diameter_mm": num_out(s["diameter_mm"]),
        "bottle_cube_cm3": s["bottle_cube_cm3"],
        "preform_cube_cm3": s["preform_cube_cm3"],
        "preform_weight_g": num_out(s["preform_weight_g"]),
        "unit_price_cents": s["unit_price_cents"],
        "label_type": s["label_type"],
        "min_cavitation_required": s["min_cavitation_required"],
        "requires_inline_labeler": s["label_type"] != "NONE",
        "content_revision": s["content_revision"],
        "qualified_revision": s["qualified_revision"],
        "rejected_revision": s["rejected_revision"],
        "qualification_round": spec_qualification_round(s),
        "status": s["status"],
    })
    return out


def ser_qualification_run(r):
    out = base_out(r)
    out.update({
        "bottle_spec_id": r["bottle_spec_id"],
        "round_no": r["round_no"],
        "spec_revision_pinned": r["spec_revision_pinned"],
        "sample_cavity_count": r["sample_cavity_count"],
        "measured_mean_weight_g": num_out(r["measured_mean_weight_g"]),
        "weight_spread_g": num_out(r["weight_spread_g"]),
        "visual_defects": r["visual_defects"],
        "weight_within_tolerance": r["weight_within_tolerance"],
        "review_note": r["review_note"],
        "status": r["status"],
    })
    return out


def ser_mold(m):
    out = base_out(m)
    opens = len(open_blockouts(m["id"]))
    out.update({
        "mold_code": m["mold_code"],
        "base_cavities": m["base_cavities"],
        "compatible_resins": list(m["compatible_resins"]),
        "reference_weight_g": num_out(m["reference_weight_g"]),
        "installed_line_id": m["installed_line_id"],
        "effective_cavities": calc_effective_cavities(m["base_cavities"], opens),
        "active_blockout_count": opens,
        "status": m["status"],
    })
    return out


def ser_blockout(b):
    out = base_out(b)
    out.update({
        "mold_id": b["mold_id"],
        "cavity_index": b["cavity_index"],
        "reason": b["reason"],
        "blocked_at": fmt_dt(b["blocked_at"]),
        "cleared_at": fmt_dt(b["cleared_at"]),
        "status": b["status"],
    })
    return out


def ser_machine_line(l):
    out = base_out(l)
    out.update({
        "line_code": l["line_code"],
        "has_inline_labeler": l["has_inline_labeler"],
        "max_bottle_diameter_mm": num_out(l["max_bottle_diameter_mm"]),
        "resident_volume_kg": num_out(l["resident_volume_kg"]),
        "last_color_class": l["last_color_class"],
        "status": l["status"],
    })
    return out


def ser_schedule_slot(s):
    out = base_out(s)
    out.update({
        "machine_line_id": s["machine_line_id"],
        "production_order_id": s["production_order_id"],
        "mold_id": s["mold_id"],
        "planned_start": fmt_dt(s["planned_start"]),
        "planned_end": fmt_dt(s["planned_end"]),
        "status": s["status"],
    })
    return out


def ser_material_lot(l):
    out = base_out(l)
    out.update({
        "material_type": l["material_type"],
        "resin_type": l["resin_type"],
        "color_code": l["color_code"],
        "lot_code": l["lot_code"],
        "received_kg": num_out(l["received_kg"]),
        "available_kg": num_out(lot_available(l)),
        "consumed_kg": num_out(l["consumed_kg"]),
        "purge_wasted_kg": num_out(l["purge_wasted_kg"]),
        "status": l["status"],
    })
    return out


def ser_production_order(o):
    out = base_out(o)
    out.update({
        "bottle_spec_id": o["bottle_spec_id"],
        "customer_id": o["customer_id"],
        "logistics_mode": o["logistics_mode"],
        "quantity_ordered": o["quantity_ordered"],
        "planned_weight_g": num_out(o["planned_weight_g"]),
        "spec_revision_baseline": o["spec_revision_baseline"],
        "status": o["status"],
    })
    out.update(order_rollups(o))
    return out


def ser_production_run(r):
    out = base_out(r)
    out.update({
        "production_order_id": r["production_order_id"],
        "machine_line_id": r["machine_line_id"],
        "mold_id": r["mold_id"],
        "material_lot_id": r["material_lot_id"],
        "colorant_lot_id": r["colorant_lot_id"],
        "cavities_active_at_start": r["cavities_active_at_start"],
        "started_at": fmt_dt(r["started_at"]),
        "ended_at": fmt_dt(r["ended_at"]),
        "cycles_completed": r["cycles_completed"],
        "good_count": r["good_count"],
        "scrap_count": r["scrap_count"],
        "actual_drawdown_kg": num_out(r["actual_drawdown_kg"]),
        "provisional_consumption_kg": num_out(r["provisional_consumption_kg"]),
        "consumption_variance_pct": num_out(r["consumption_variance_pct"]),
        "variance_alert": r["variance_alert"],
        "purge_kg": num_out(r["purge_kg"]),
        "status": r["status"],
    })
    return out


def ser_quality_test_lot(l):
    out = base_out(l)
    out.update({
        "production_run_id": l["production_run_id"],
        "lot_size": l["lot_size"],
        "sample_size_n": l["sample_size_n"],
        "accept_number_leak": l["accept_number_leak"],
        "accept_number_drop": l["accept_number_drop"],
        "leak_failures": l["leak_failures"],
        "drop_failures": l["drop_failures"],
        "retest_count": l["retest_count"],
        "recorded_by_user_id": l["recorded_by_user_id"],
        "dispositioned_by_user_id": l["dispositioned_by_user_id"],
        "status": l["status"],
    })
    return out


def ser_shipment(s):
    out = base_out(s)
    out.update({
        "production_order_id": s["production_order_id"],
        "customer_id": s["customer_id"],
        "shipment_mode": s["shipment_mode"],
        "quantity": s["quantity"],
        "pallets": s["pallets"],
        "volume_cm3": s["volume_cm3"],
        "dim_weight_kg": num_out(s["dim_weight_kg"]),
        "actual_weight_kg": num_out(s["actual_weight_kg"]),
        "chargeable_weight_kg": num_out(s["chargeable_weight_kg"]),
        "freight_cost_cents": s["freight_cost_cents"],
        "booked_appointment_id": s["booked_appointment_id"],
        "status": s["status"],
    })
    return out


def ser_dock_appointment(a):
    out = base_out(a)
    out.update({
        "shipment_id": a["shipment_id"],
        "dock_door": a["dock_door"],
        "window_start": fmt_dt(a["window_start"]),
        "window_end": fmt_dt(a["window_end"]),
        "status": a["status"],
    })
    return out


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------

def cancel_slots_for_order(order):
    for s in store.schedule_slots.values():
        if (s["production_order_id"] == order["id"]
                and s["status"] in ("CONFIRMED", "IN_PROGRESS")):
            s["status"] = "CANCELLED"
            touch(s)


def cancel_order(order):
    """Order -> CANCELLED with its active slots. Caller checks the
    transition is permitted from the order's current state."""
    order["status"] = "CANCELLED"
    touch(order)
    cancel_slots_for_order(order)


def hold_order(order):
    """RUNNING -> HELD with slot cancellation and line fallback."""
    # identify the occupied line BEFORE cancelling the slots
    line = None
    for l in store.machine_lines.values():
        if l["status"] == "RUNNING" and occupying_order_id(l) == order["id"]:
            line = l
            break
    order["status"] = "HELD"
    touch(order)
    cancel_slots_for_order(order)
    if line is not None and line["status"] == "RUNNING":
        line["status"] = "CHANGEOVER"
        touch(line)


def occupying_order_id(line):
    """The order currently occupying a RUNNING line: via IN_PROGRESS slot
    first, else via an OPEN run on the line."""
    for s in store.schedule_slots.values():
        if s["machine_line_id"] == line["id"] and s["status"] == "IN_PROGRESS":
            return s["production_order_id"]
    for r in store.production_runs.values():
        if r["machine_line_id"] == line["id"] and r["status"] == "OPEN":
            return r["production_order_id"]
    return None


# ---------------------------------------------------------------------------
# scheduling checks
# ---------------------------------------------------------------------------

def installed_mold_on_line(line_id):
    for m in store.molds.values():
        if m["installed_line_id"] == line_id and m["status"] == "INSTALLED":
            return m
    return None


def schedule_conflict(line_id, new_start, new_end, new_mold_id, exclude_slot_ids):
    """Half-open window intersection plus mold-change buffer: 0 min when
    both slots carry the same mold snapshot, else 90 min."""
    for s in store.schedule_slots.values():
        if s["machine_line_id"] != line_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        if s["id"] in exclude_slot_ids:
            continue
        # half-open [start, end) intersection
        if new_start < s["planned_end"] and s["planned_start"] < new_end:
            return True
        buffer = (timedelta(0) if s["mold_id"] == new_mold_id
                  else timedelta(minutes=90))
        if new_end <= s["planned_start"]:
            if s["planned_start"] - new_end < buffer:
                return True
        elif s["planned_end"] <= new_start:
            if new_start - s["planned_end"] < buffer:
                return True
    return False


def credit_check(customer, this_order, this_spec):
    """Sum over the customer's orders in SCHEDULED/RELEASED/RUNNING/HELD of
    quantity_ordered * spec.unit_price_cents, plus this order's value, must
    be <= credit_limit_cents (equal allowed)."""
    total = this_order["quantity_ordered"] * this_spec["unit_price_cents"]
    for o in store.production_orders.values():
        if o["id"] == this_order["id"]:
            continue
        if o["customer_id"] != customer["id"]:
            continue
        if o["status"] not in ("SCHEDULED", "RELEASED", "RUNNING", "HELD"):
            continue
        o_spec = store.bottle_specs.get(o["bottle_spec_id"])
        if o_spec is None:
            continue
        total += o["quantity_ordered"] * o_spec["unit_price_cents"]
    return total <= customer["credit_limit_cents"]


def create_slot(order, line, planned_start, planned_end):
    mold = installed_mold_on_line(line["id"])
    slot = {
        "machine_line_id": line["id"],
        "production_order_id": order["id"],
        "mold_id": mold["id"] if mold else None,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "status": "CONFIRMED",
    }
    from util import new_id
    stamp_new(slot, new_id())
    store.schedule_slots[slot["id"]] = slot
    return slot


def maybe_advance_spec(spec):
    """First successful schedule against a QUALIFIED spec -> PRODUCTION_ACTIVE."""
    if spec["status"] == "QUALIFIED":
        spec["status"] = "PRODUCTION_ACTIVE"
        touch(spec)


# ---------------------------------------------------------------------------
# material waterfall (run close) and reversal (run void)
# ---------------------------------------------------------------------------

def waterfall_debit(spec, actual_drawdown_kg, purge_kg):
    """All-or-nothing FIFO debit across matching RELEASED/IN_USE resin lots.
    Returns (ledger, None) on success or (None, total_available) when the
    pool cannot cover actual + purge. Ledger entries: (lot, purge, consumed)."""
    required = Decimal(actual_drawdown_kg) + Decimal(purge_kg)
    candidates = matching_resin_lots(spec["resin_type"])
    total = Decimal("0")
    for lot in candidates:
        total += lot_available(lot)
    if total < required:
        return None, total
    remaining_purge = Decimal(purge_kg)
    remaining_cons = Decimal(actual_drawdown_kg)
    ledger = []
    for lot in candidates:
        if remaining_purge <= 0 and remaining_cons <= 0:
            break
        avail = lot_available(lot)
        if avail <= 0:
            continue
        take_purge = min(avail, remaining_purge)
        lot["purge_wasted_kg"] += take_purge
        remaining_purge -= take_purge
        avail -= take_purge
        take_cons = min(avail, remaining_cons)
        lot["consumed_kg"] += take_cons
        remaining_cons -= take_cons
        avail -= take_cons
        if take_purge > 0 or take_cons > 0:
            ledger.append((lot, take_purge, take_cons))
            if lot_available(lot) == 0:
                lot["status"] = "DEPLETED"
            elif lot["status"] == "RELEASED":
                lot["status"] = "IN_USE"
            touch(lot)
    return ledger, total


def reverse_debits(run):
    """Void: credit back every debit this run's close made, exactly."""
    for lot, purge_amt, cons_amt in run.get("_debits", []):
        lot["purge_wasted_kg"] -= purge_amt
        lot["consumed_kg"] -= cons_amt
        if lot["status"] not in ("QUARANTINED", "REJECTED"):
            if lot_available(lot) == 0:
                lot["status"] = "DEPLETED"
            elif lot["consumed_kg"] + lot["purge_wasted_kg"] > 0:
                lot["status"] = "IN_USE"
            else:
                lot["status"] = "RELEASED"
        touch(lot)


def recompute_line_color(line):
    """last_color_class from the most recent remaining non-VOIDED closed
    run on the line; null when none remains."""
    runs = [r for r in store.production_runs.values()
            if r["machine_line_id"] == line["id"] and r["status"] == "CLOSED"]
    runs = sorted_rows(runs)
    new_color = runs[-1].get("_color_class_at_close") if runs else None
    if line["last_color_class"] != new_color:
        line["last_color_class"] = new_color
        touch(line)
