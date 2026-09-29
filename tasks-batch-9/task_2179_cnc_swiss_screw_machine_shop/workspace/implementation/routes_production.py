"""Work orders, SPC subgroups and secondary routing steps."""
from flask import Blueprint, request

import calc
import services
from core import (db, dec, fail, now, now_iso, public, respond_list, respond_object,
                  sorted_rows, stamp_new, touch)
from guards import (ALL_ROLES, active_operator, authenticate, body, ensure_unique, f_dt,
                    f_enum, f_int, f_num, f_num_list, f_str, lookup, paginate, pagination)

bp = Blueprint("production", __name__)

MACHINING_STATUSES = ("SCHEDULED", "RUNNING", "INTERRUPTED", "MACHINING_COMPLETE", "CANCELLED")


# ==========================================================================
# work orders — scheduling
# ==========================================================================
@bp.post("/swiss-shop/work-orders")
def create_work_order():
    authenticate(("ShopPlanner",))
    payload = body()
    release_id = f_str(payload, "release_id")
    machine_id = f_str(payload, "machine_id")
    bar_lot_id = f_str(payload, "bar_lot_id")
    qty_ordered = f_int(payload, "qty_ordered", minimum=1)
    scheduled_start_at, start_dt = f_dt(payload, "scheduled_start_at")
    scheduled_end_at, end_dt = f_dt(payload, "scheduled_end_at")
    expected_machine_version = f_int(payload, "expected_machine_version")
    lights_out_hours = f_num(payload, "lights_out_hours", required=False, default=dec(0), minimum=0)
    if end_dt <= start_dt:
        fail("ERR_INVALID_REQUEST", "scheduled_end_at must be strictly after scheduled_start_at.")

    # priority 45 — body foreign keys, in entity declaration order
    release = lookup("kanban_releases", release_id)
    machine = lookup("machines", machine_id)
    lot = lookup("bar_stock_lots", bar_lot_id)

    # priority 55 — optimistic concurrency on the shared machine calendar
    if expected_machine_version != int(machine["version"]):
        fail("ERR_STALE_MACHINE_VERSION")

    order = db.blanket_pos.get(release["blanket_po_id"])
    if order is None:
        fail("ERR_BLANKET_PO_NOT_FOUND")
    part = db.parts.get(order["part_id"])
    if part is None:
        fail("ERR_PART_NOT_FOUND")

    # priority 61
    if order["status"] != "ACTIVE":
        fail("ERR_PO_NOT_ACTIVE")
    # priority 74 / 75 / 76 — material fit
    if dec(lot["bar_diameter_mm"]) != dec(part["bar_diameter_mm"]) or \
            dec(lot["bar_diameter_mm"]) > dec(machine["max_bar_diameter_mm"]):
        fail("ERR_BAR_DIAMETER_MISMATCH")
    if lot["alloy_code"] != part["alloy_code"]:
        fail("ERR_ALLOY_MISMATCH")
    if lights_out_hours > 0 and (not part["lights_out_eligible"] or not machine["lights_out_certified"]):
        fail("ERR_LIGHTS_OUT_NOT_PERMITTED")
    # priority 78 / 80 — occupancy
    if calc.machine_window_conflict(machine["id"], start_dt, end_dt, part):
        fail("ERR_MACHINE_WINDOW_CONFLICT")
    if calc.bar_lot_feeder_conflict(lot, start_dt, end_dt):
        fail("ERR_BAR_LOT_FEEDER_CONFLICT")
    # priority 91 — release quantity
    sibling_qty = sum(int(w["qty_ordered"]) for w in services.work_orders_of_release(release["id"])
                      if w["machining_status"] != "CANCELLED")
    if qty_ordered + sibling_qty > int(release["qty"]):
        fail("ERR_RELEASE_QTY_EXCEEDED")
    # priority 92 — material on the rack
    required_length_mm, bars_reserved, reserved_length_mm = calc.reservation(part, lot, qty_ordered)
    if reserved_length_mm > dec(lot["available_length_mm"]):
        fail("ERR_BAR_STOCK_INSUFFICIENT")

    row = stamp_new({
        "release_id": release_id,
        "machine_id": machine_id,
        "bar_lot_id": bar_lot_id,
        "part_id": part["id"],
        "machinist_operator_id": None,
        "qty_ordered": qty_ordered,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "lights_out_hours": lights_out_hours,
        "required_length_mm": required_length_mm,
        "bars_reserved": bars_reserved,
        "reserved_length_mm": reserved_length_mm,
        "actual_run_seconds": None,
        "qty_good": 0,
        "qty_scrap": 0,
        "chip_kg": dec(0),
        "machining_status": "SCHEDULED",
        "quality_status": "PENDING_INSPECTION",
        "cancel_reason": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.work_orders[row["id"]] = row

    lot["available_length_mm"] = dec(lot["available_length_mm"]) - reserved_length_mm
    lot["reserved_length_mm"] = dec(lot["reserved_length_mm"]) + reserved_length_mm
    touch(lot)
    touch(machine)
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/work-orders/<wid>")
def get_work_order(wid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("work_orders", wid)))


@bp.get("/swiss-shop/work-orders")
def list_work_orders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    machining_status = request.args.get("machining_status")
    if machining_status is not None and machining_status not in MACHINING_STATUSES:
        fail("ERR_INVALID_REQUEST", "machining_status filter is not a legal enum member.")
    rows = list(db.work_orders.values())
    for key in ("release_id", "machine_id", "bar_lot_id", "part_id", "machinist_operator_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    if machining_status:
        rows = [r for r in rows if r["machining_status"] == machining_status]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


# ==========================================================================
# work orders — production dimension
# ==========================================================================
@bp.post("/swiss-shop/work-orders/<wid>/start")
def start_work_order(wid):
    user_id, _role = authenticate(("Machinist",))
    work_order = lookup("work_orders", wid)
    operator = active_operator(user_id)

    origin = work_order["machining_status"]
    if origin not in ("SCHEDULED", "INTERRUPTED"):
        fail("ERR_INVALID_STATE")
    machine = db.machines.get(work_order["machine_id"])
    if machine is None:
        fail("ERR_MACHINE_NOT_FOUND")
    if machine["status"] != "AVAILABLE":
        fail("ERR_MACHINE_NOT_AVAILABLE")
    if origin == "SCHEDULED":
        lot = db.bar_stock_lots.get(work_order["bar_lot_id"])
        if lot is None:
            fail("ERR_BAR_LOT_NOT_FOUND")
        if lot["status"] != "CERTIFIED":
            fail("ERR_BAR_LOT_NOT_CERTIFIED")
    if services.held_stations(machine["id"]):
        fail("ERR_TOOL_LIFE_EXPIRED")
    if origin == "SCHEDULED" and dec(work_order["lights_out_hours"]) > 0:
        if "LIGHTS_OUT" not in (operator.get("certifications") or []):
            fail("ERR_OPERATOR_NOT_CERTIFIED")

    work_order["machining_status"] = "RUNNING"
    work_order["machinist_operator_id"] = user_id
    touch(work_order)

    machine["status"] = "RUNNING"
    machine["current_work_order_id"] = work_order["id"]
    touch(machine)

    release = db.kanban_releases.get(work_order["release_id"])
    if release is not None and release["status"] == "RELEASED":
        release["status"] = "IN_PRODUCTION"
        touch(release)

    if origin == "INTERRUPTED":
        services.unblock_steps(work_order["id"])

    return respond_object(public(work_order))


@bp.post("/swiss-shop/work-orders/<wid>/complete-machining")
def complete_machining(wid):
    user_id, _role = authenticate(("Machinist",))
    payload = body()
    qty_good = f_int(payload, "qty_good", minimum=0)
    qty_scrap = f_int(payload, "qty_scrap", minimum=0)
    actual_run_seconds = f_num(payload, "actual_run_seconds", minimum=0)
    work_order = lookup("work_orders", wid)
    active_operator(user_id)

    if work_order["machining_status"] != "RUNNING":
        fail("ERR_INVALID_STATE")
    if qty_good + qty_scrap > int(work_order["qty_ordered"]):
        fail("ERR_QTY_EXCEEDS_ORDERED")

    work_order["qty_good"] = qty_good
    work_order["qty_scrap"] = qty_scrap
    work_order["actual_run_seconds"] = actual_run_seconds
    work_order["machining_status"] = "MACHINING_COMPLETE"

    lot = db.bar_stock_lots.get(work_order["bar_lot_id"])
    if lot is not None:
        moved = dec(work_order["reserved_length_mm"])
        lot["reserved_length_mm"] = dec(lot["reserved_length_mm"]) - moved
        lot["consumed_length_mm"] = dec(lot["consumed_length_mm"]) + moved
        if dec(lot["available_length_mm"]) == 0 and dec(lot["reserved_length_mm"]) == 0:
            lot["status"] = "DEPLETED"
        touch(lot)

    machine = db.machines.get(work_order["machine_id"])
    part = db.parts.get(work_order["part_id"])
    if machine is not None and lot is not None and part is not None:
        work_order["chip_kg"] = calc.chip_and_coolant(work_order, lot, part, machine)
    touch(work_order)

    if machine is not None:
        machine["status"] = "AVAILABLE"
        machine["current_work_order_id"] = None
        touch(machine)

    return respond_object(public(work_order))


@bp.post("/swiss-shop/work-orders/<wid>/cancel")
def cancel_work_order(wid):
    authenticate(("ShopPlanner",))
    payload = body()
    reason = f_str(payload, "reason")
    work_order = lookup("work_orders", wid)
    if work_order["machining_status"] not in ("SCHEDULED", "INTERRUPTED"):
        fail("ERR_INVALID_STATE")

    work_order["machining_status"] = "CANCELLED"
    work_order["cancel_reason"] = reason
    touch(work_order)

    lot = db.bar_stock_lots.get(work_order["bar_lot_id"])
    if lot is not None:
        moved = dec(work_order["reserved_length_mm"])
        lot["reserved_length_mm"] = dec(lot["reserved_length_mm"]) - moved
        lot["available_length_mm"] = dec(lot["available_length_mm"]) + moved
        touch(lot)

    services.block_steps(work_order["id"], ("PENDING", "BLOCKED", "IN_PROGRESS"),
                         "WORK_ORDER_CANCELLED")

    machine = db.machines.get(work_order["machine_id"])
    if machine is not None and machine.get("current_work_order_id") == work_order["id"]:
        machine["status"] = "AVAILABLE"
        machine["current_work_order_id"] = None
        touch(machine)

    return respond_object(public(work_order))


# ==========================================================================
# work orders — quality dimension
# ==========================================================================
@bp.post("/swiss-shop/work-orders/<wid>/disposition")
def disposition_work_order(wid):
    authenticate(("QualityManager",))
    payload = body()
    decision = f_enum(payload, "decision", ("ACCEPT", "REJECT", "RELEASE_HOLD"))
    f_str(payload, "note", required=False, default=None, min_len=None)
    work_order = lookup("work_orders", wid)
    quality = work_order["quality_status"]

    if decision == "RELEASE_HOLD":
        if quality != "QUALITY_HOLD":
            fail("ERR_INVALID_STATE")
        work_order["quality_status"] = "IN_SPC"
        touch(work_order)
        return respond_object(public(work_order))

    if decision == "ACCEPT":
        if quality != "IN_SPC" or work_order["machining_status"] != "MACHINING_COMPLETE":
            fail("ERR_INVALID_STATE")
        summary = calc.sampling_summary(work_order)
        if not summary["_complete"]:
            fail("ERR_SPC_SAMPLING_INCOMPLETE")
        for value in summary["_ppk_values"]:
            if value < calc.PPK_MIN_ACCEPT:
                fail("ERR_CAPABILITY_BELOW_MINIMUM")

        work_order["quality_status"] = "ACCEPTED"
        touch(work_order)

        release = db.kanban_releases.get(work_order["release_id"])
        if release is not None and release["status"] == "IN_PRODUCTION":
            release["fulfilled_qty"] = int(work_order["qty_good"])
            release["status"] = "FULFILLED"
            touch(release)
            order = db.blanket_pos.get(release["blanket_po_id"])
            if order is not None:
                services.po_credit_fulfilment(order, release["qty"], work_order["qty_good"])

        part = db.parts.get(work_order["part_id"])
        if part is not None:
            calc.recompute_observed_cycle_time(part)
            touch(part)
        return respond_object(public(work_order))

    # decision == REJECT
    if quality not in ("IN_SPC", "QUALITY_HOLD") or work_order["machining_status"] != "MACHINING_COMPLETE":
        fail("ERR_INVALID_STATE")
    work_order["quality_status"] = "REJECTED"
    touch(work_order)
    release = db.kanban_releases.get(work_order["release_id"])
    if release is not None and release["status"] == "IN_PRODUCTION":
        release["status"] = "SHORT_CLOSED"
        release["close_reason"] = "WORK_ORDER_REJECTED"
        touch(release)
        order = db.blanket_pos.get(release["blanket_po_id"])
        if order is not None:
            services.po_return_quantity(order, release["qty"])
    return respond_object(public(work_order))


@bp.get("/swiss-shop/work-orders/<wid>/quality-summary")
def quality_summary(wid):
    authenticate(ALL_ROLES)
    work_order = lookup("work_orders", wid)
    characteristic_id = request.args.get("characteristic_id") or None
    summary = calc.sampling_summary(work_order, characteristic_id)
    return respond_object({
        "work_order_id": summary["work_order_id"],
        "characteristic_count": summary["characteristic_count"],
        "sample_count": summary["sample_count"],
        "required_sample_count": summary["required_sample_count"],
        "out_of_spec_count": summary["out_of_spec_count"],
        "cpk_short_term_min": summary["cpk_short_term_min"],
        "ppk_long_term_min": summary["ppk_long_term_min"],
    })


# ==========================================================================
# SPC subgroups
# ==========================================================================
@bp.post("/swiss-shop/spc-samples")
def create_spc_sample():
    user_id, _role = authenticate(("Inspector",))
    payload = body()
    work_order_id = f_str(payload, "work_order_id")
    characteristic_id = f_str(payload, "characteristic_id")
    gauge_id = f_str(payload, "gauge_id")
    piece_index = f_int(payload, "piece_index", minimum=1)
    measurements = f_num_list(payload, "measurements")

    work_order = lookup("work_orders", work_order_id)
    characteristic = lookup("characteristics", characteristic_id)
    gauge = lookup("gauges", gauge_id)
    active_operator(user_id)

    # priority 70 — instrument must be in service after lazy re-evaluation
    services.refresh_gauge(gauge)
    if gauge["status"] != "IN_SERVICE":
        fail("ERR_GAUGE_NOT_IN_SERVICE")
    # priority 72 — segregation of duties
    if work_order.get("machinist_operator_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    # priority 81 / 85 / 86
    if len(measurements) != int(characteristic["subgroup_size"]):
        fail("ERR_SUBGROUP_SIZE_MISMATCH")
    if characteristic["part_id"] != work_order["part_id"]:
        fail("ERR_CHARACTERISTIC_PART_MISMATCH")
    if gauge["gauge_type"] != characteristic["required_gauge_type"]:
        fail("ERR_GAUGE_TYPE_MISMATCH")

    stats = calc.subgroup_stats(measurements, characteristic)
    row = {
        "id": None,
        "work_order_id": work_order_id,
        "characteristic_id": characteristic_id,
        "gauge_id": gauge_id,
        "inspector_operator_id": user_id,
        "piece_index": piece_index,
        "measurements": measurements,
    }
    row.update(stats)
    from core import new_id
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["_seq"] = db.next_seq()
    db.spc_samples[row["id"]] = row

    quality = work_order["quality_status"]
    disposition = stats["disposition"]
    transitioned = False
    if disposition == "ACCEPT":
        if quality == "PENDING_INSPECTION":
            work_order["quality_status"] = "IN_SPC"
            transitioned = True
    else:
        if quality in ("PENDING_INSPECTION", "IN_SPC"):
            work_order["quality_status"] = "QUALITY_HOLD"
            transitioned = True
    if transitioned:
        touch(work_order)
        if disposition == "REJECT":
            machine = db.machines.get(work_order["machine_id"])
            if machine is not None:
                machine["status"] = "DOWN"
                machine["current_work_order_id"] = None
                touch(machine)

    return respond_object(public(row), 201)


@bp.get("/swiss-shop/spc-samples/<sid>")
def get_spc_sample(sid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("spc_samples", sid)))


@bp.get("/swiss-shop/spc-samples")
def list_spc_samples():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.spc_samples.values())
    for key in ("work_order_id", "characteristic_id", "gauge_id", "inspector_operator_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


# ==========================================================================
# secondary routing steps
# ==========================================================================
@bp.post("/swiss-shop/routing-steps")
def create_routing_step():
    authenticate(("ShopPlanner",))
    payload = body()
    work_order_id = f_str(payload, "work_order_id")
    sequence = f_int(payload, "sequence", minimum=1)
    operation = f_enum(payload, "operation", calc.OPERATIONS)
    predecessor_step_id = f_str(payload, "predecessor_step_id", required=False, default=None)

    lookup("work_orders", work_order_id)
    predecessor = None
    if predecessor_step_id is not None:
        predecessor = lookup("routing_steps", predecessor_step_id)

    if predecessor is not None:
        if predecessor["work_order_id"] != work_order_id or int(predecessor["sequence"]) >= sequence:
            fail("ERR_PREDECESSOR_STEP_INVALID")
    ensure_unique("routing_steps", "sequence", sequence, "work_order_id", work_order_id)

    row = stamp_new({
        "work_order_id": work_order_id,
        "predecessor_step_id": predecessor_step_id,
        "sequence": sequence,
        "operation": operation,
        "status": "PENDING",
        "blocked_reason": None,
    })
    db.routing_steps[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/routing-steps/<rsid>")
def get_routing_step(rsid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("routing_steps", rsid)))


@bp.get("/swiss-shop/routing-steps")
def list_routing_steps():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.routing_steps.values())
    for key in ("work_order_id", "predecessor_step_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


@bp.post("/swiss-shop/routing-steps/<rsid>/advance")
def advance_routing_step(rsid):
    user_id, _role = authenticate(("Machinist",))
    payload = body()
    to_status = f_enum(payload, "to_status", ("IN_PROGRESS", "COMPLETE"))
    step = lookup("routing_steps", rsid)
    active_operator(user_id)

    if to_status == "IN_PROGRESS":
        if step["status"] != "PENDING":
            fail("ERR_INVALID_STATE")
        work_order = db.work_orders.get(step["work_order_id"])
        if work_order is None or work_order["machining_status"] != "MACHINING_COMPLETE":
            fail("ERR_INVALID_STATE")
        if step.get("predecessor_step_id"):
            predecessor = db.routing_steps.get(step["predecessor_step_id"])
            if predecessor is None or predecessor["status"] != "COMPLETE":
                fail("ERR_INVALID_STATE")
        step["status"] = "IN_PROGRESS"
    else:
        if step["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE")
        step["status"] = "COMPLETE"
    touch(step)
    return respond_object(public(step))
