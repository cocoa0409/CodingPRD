"""Shared operations: serializers, credit evaluation, cross-aggregate cascades."""
from datetime import timedelta

from constants import MIN_REPLENISHMENT_GAP_HOURS
from db import store
from services import calc
from util import (
    clock_now,
    created_now,
    fmt_date,
    fmt_instant,
    new_id,
    num_out,
    touch,
)


# ---------------- serializers ----------------

def plant_out(p):
    return {
        "id": p["id"],
        "plant_name": p["plant_name"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def tank_out(t):
    return {
        "id": t["id"],
        "plant_id": t["plant_id"],
        "product_code": t["product_code"],
        "capacity_liters": t["capacity_liters"],
        "initial_level_liters": t["initial_level_liters"],
        "reorder_point_liters": t["reorder_point_liters"],
        "current_level_liters": num_out(calc.tank_current_level(t)),
        "reserved_liters": num_out(t["reserved_liters"]),
        "drawn_liters": num_out(t["drawn_liters"]),
        "low_level_flag": calc.tank_low_level_flag(t),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def reading_out(r):
    return {
        "id": r["id"],
        "tank_id": r["tank_id"],
        "installation_id": r["installation_id"],
        "measured_level_liters": num_out(r["measured_level_liters"]),
        "measured_at": fmt_instant(r["measured_at_dt"]),
        "source": r["source"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "created_at": r["created_at"],
    }


def cylinder_out(c):
    return {
        "id": c["id"],
        "serial_number": c["serial_number"],
        "size_code": c["size_code"],
        "service_gas": c["service_gas"],
        "water_capacity_liters": c["water_capacity_liters"],
        "last_hydro_date": fmt_date(c["last_hydro_date_d"]),
        "hydro_due_date": fmt_date(c["hydro_due_date_d"]),
        "hydro_status": calc.hydro_status(c),
        "status": c["status"],
        "current_fill_lot_id": c["current_fill_lot_id"],
        "last_fill_lot_id": c["last_fill_lot_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def fill_lot_out(lot):
    return {
        "id": lot["id"],
        "tank_id": lot["tank_id"],
        "product_code": lot["product_code"],
        "target_fill_pressure_bar": lot["target_fill_pressure_bar"],
        "draw_estimate_liters": num_out(lot["draw_estimate_liters"]),
        "draw_actual_liters": (None if lot["draw_actual_liters"] is None else num_out(lot["draw_actual_liters"])),
        "completed_by_user_id": lot["completed_by_user_id"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def analysis_out(a):
    return {
        "id": a["id"],
        "subject_type": a["subject_type"],
        "fill_lot_id": a["fill_lot_id"],
        "blend_order_id": a["blend_order_id"],
        "readings": a["readings"],
        "result": a["result"],
        "recorded_by_user_id": a["recorded_by_user_id"],
        "overridden_by_user_id": a["overridden_by_user_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def customer_out(c):
    return {
        "id": c["id"],
        "account_name": c["account_name"],
        "billing_variant": c["billing_variant"],
        "free_days": c["free_days"],
        "credit_limit_cents": c["credit_limit_cents"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "recall_flag": c["recall_flag"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def rental_out(r):
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "cylinder_id": r["cylinder_id"],
        "daily_rate_cents": r["daily_rate_cents"],
        "planned_days": r["planned_days"],
        "out_date": fmt_date(r["out_date_d"]),
        "due_date": fmt_date(r["due_date_d"]),
        "return_date": (None if r["return_date_d"] is None else fmt_date(r["return_date_d"])),
        "billed_through_date": fmt_date(r["billed_through_date_d"]),
        "demurrage_billed_cents": r["demurrage_billed_cents"],
        "final_charge_cents": r["final_charge_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def driver_out(d):
    return {
        "id": d["id"],
        "driver_name": d["driver_name"],
        "cdl_class": d["cdl_class"],
        "hazmat_endorsements": [
            {"endorsement_class": e["endorsement_class"], "expiry_date": fmt_date(e["expiry_date_d"])}
            for e in d["hazmat_endorsements"]
        ],
        "medical_card_expiry": fmt_date(d["medical_card_expiry_d"]),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def route_out(r):
    return {
        "id": r["id"],
        "route_date": fmt_date(r["route_date_d"]),
        "window_start_hour": r["window_start_hour"],
        "window_end_hour": r["window_end_hour"],
        "stops": r["stops"],
        "driver_id": r["driver_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def installation_out(i):
    return {
        "id": i["id"],
        "customer_id": i["customer_id"],
        "product_code": i["product_code"],
        "capacity_liters": i["capacity_liters"],
        "initial_level_liters": i["initial_level_liters"],
        "reorder_point_liters": i["reorder_point_liters"],
        "max_order_qty_liters": i["max_order_qty_liters"],
        "current_level_liters": num_out(calc.installation_current_level(i)),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def repl_order_out(o):
    return {
        "id": o["id"],
        "installation_id": o["installation_id"],
        "scheduled_delivery_at": fmt_instant(o["scheduled_delivery_at_dt"]),
        "requested_qty_liters": num_out(o["requested_qty_liters"]),
        "delivered_at": (None if o["delivered_at_dt"] is None else fmt_instant(o["delivered_at_dt"])),
        "superseded_by_order_id": o["superseded_by_order_id"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def blend_out(b):
    components = []
    for comp in b["components"]:
        out = {
            "product_code": comp["product_code"],
            "target_pct": num_out(comp["target_pct"]),
            "tolerance_pct": num_out(comp["tolerance_pct"]),
            "unit_cost_cents_per_liter": comp["unit_cost_cents_per_liter"],
        }
        if comp.get("selected_tank_id") is not None:
            out["selected_tank_id"] = comp["selected_tank_id"]
        components.append(out)
    return {
        "id": b["id"],
        "customer_id": b["customer_id"],
        "batch_qty_liters": b["batch_qty_liters"],
        "components": components,
        "component_cost_cents": b["component_cost_cents"],
        "service_fee_cents": b["service_fee_cents"],
        "total_price_cents": b["total_price_cents"],
        "blended_by_user_id": b["blended_by_user_id"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def billing_run_out(r):
    return {
        "id": r["id"],
        "period_start": fmt_date(r["period_start_d"]),
        "period_end": fmt_date(r["period_end_d"]),
        "charge_lines": r["charge_lines"],
        "total_charges_cents": r["total_charges_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------- shared record factory ----------------

def base_record():
    return {
        "id": new_id(),
        "_seq": store.next_seq(),
        "created_at": created_now(),
        "updated_at": created_now(),
        "version": 1,
    }


def post_reading(tank_id, installation_id, level, measured_at_dt, source, recorded_by):
    r = {
        "id": new_id(),
        "_seq": store.next_seq(),
        "created_at": created_now(),
        "tank_id": tank_id,
        "installation_id": installation_id,
        "measured_level_liters": level,
        "measured_at_dt": measured_at_dt,
        "source": source,
        "recorded_by_user_id": recorded_by,
    }
    store.readings[r["id"]] = r
    return r


# ---------------- credit evaluation + cascades ----------------

def credit_evaluate(customer, touched):
    """Hysteresis rule (credit_hold_evaluation). `touched` tracks resources already
    version-bumped by this operation so each resource bumps at most once."""
    if customer["status"] == "ACTIVE" and customer["outstanding_balance_cents"] > customer["credit_limit_cents"]:
        customer["status"] = "CREDIT_HOLD"
        if customer["id"] not in touched:
            touch(customer)
            touched.add(customer["id"])
        # cascade link 3: ACTIVE installations of this customer -> PAUSED
        for inst in store.installations.values():
            if inst["customer_id"] == customer["id"] and inst["status"] == "ACTIVE":
                inst["status"] = "PAUSED"
                if inst["id"] not in touched:
                    touch(inst)
                    touched.add(inst["id"])
    elif customer["status"] == "CREDIT_HOLD":
        threshold = calc.credit_hold_release_threshold(customer["credit_limit_cents"])
        if customer["outstanding_balance_cents"] <= threshold:
            customer["status"] = "ACTIVE"
            if customer["id"] not in touched:
                touch(customer)
                touched.add(customer["id"])


def release_fill_lot(lot, touched):
    """AWAITING_ANALYSIS -> RELEASED; cylinders RESERVED -> FILLED with provenance."""
    lot["status"] = "RELEASED"
    for c in calc.lot_reserved_cylinders(lot):
        c["status"] = "FILLED"
        c["current_fill_lot_id"] = None
        c["last_fill_lot_id"] = lot["id"]
        if c["id"] not in touched:
            touch(c)
            touched.add(c["id"])
    if lot["id"] not in touched:
        touch(lot)
        touched.add(lot["id"])


def fail_fill_lot(lot, touched):
    """AWAITING_ANALYSIS -> ANALYSIS_FAILED; cylinders RESERVED -> QUARANTINED."""
    lot["status"] = "ANALYSIS_FAILED"
    for c in calc.lot_reserved_cylinders(lot):
        c["status"] = "QUARANTINED"
        if c["id"] not in touched:
            touch(c)
            touched.add(c["id"])
    if lot["id"] not in touched:
        touch(lot)
        touched.add(lot["id"])


def release_subject(analysis, touched):
    """Release the analysis subject exactly as a PASS would."""
    if analysis["subject_type"] == "FILL_LOT":
        lot = store.fill_lots.get(analysis["fill_lot_id"])
        if lot is not None and lot["status"] == "AWAITING_ANALYSIS":
            release_fill_lot(lot, touched)
    else:
        blend = store.blends.get(analysis["blend_order_id"])
        if blend is not None and blend["status"] == "AWAITING_ANALYSIS":
            blend["status"] = "RELEASED"
            if blend["id"] not in touched:
                touch(blend)
                touched.add(blend["id"])


def unassign_driver_routes(driver_id, touched):
    for route in store.routes.values():
        if route["driver_id"] == driver_id and route["status"] in ("DRIVER_ASSIGNED", "DISPATCHED"):
            route["status"] = "PLANNED"
            route["driver_id"] = None
            if route["id"] not in touched:
                touch(route)
                touched.add(route["id"])


def auto_replenishment_if_low(installation, touched):
    """Low-telemetry auto order (PRD §3.1): level <= reorder and no PENDING order."""
    if calc.installation_current_level(installation) > calc.dec(installation["reorder_point_liters"]):
        return
    for o in store.repl_orders.values():
        if o["installation_id"] == installation["id"] and o["status"] == "PENDING":
            return
    qty = calc.replenishment_qty(installation)
    if qty <= 0:
        return
    order = base_record()
    order.update(
        {
            "installation_id": installation["id"],
            "scheduled_delivery_at_dt": clock_now() + timedelta(hours=MIN_REPLENISHMENT_GAP_HOURS),
            "requested_qty_liters": qty,
            "delivered_at_dt": None,
            "superseded_by_order_id": None,
            "status": "PENDING",
        }
    )
    store.repl_orders[order["id"]] = order
    if installation["id"] not in touched:
        touch(installation)
        touched.add(installation["id"])
