"""Public representations — exactly the scaffold entity fields plus the
common fields (id/created_at/updated_at/version; Part: id/created_at only)."""
from domain import (
    batch_assigned_door_count,
    line_slotted_qty,
    order_hold_status,
    route_orders,
    route_reserved_cu_ft,
)
from util import fmt_ts


def _common(r):
    return {
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_dealer(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "dealer_code": d["dealer_code"],
        "price_level": d["price_level"],
        "credit_limit_cents": d["credit_limit_cents"],
        **_common(d),
    }


def ser_door_style(s):
    return {
        "id": s["id"],
        "style_code": s["style_code"],
        "name": s["name"],
        "construction": s["construction"],
        "base_list_price_cents": s["base_list_price_cents"],
        "active": s["active"],
        **_common(s),
    }


def ser_finish_spec(f):
    return {
        "id": f["id"],
        "finish_code": f["finish_code"],
        "color_name": f["color_name"],
        "sheen": f["sheen"],
        "upcharge_pct": f["upcharge_pct"],
        "delta_e_tolerance": f["delta_e_tolerance"],
        "active": f["active"],
        **_common(f),
    }


def ser_component(c):
    return {
        "id": c["id"],
        "sku": c["sku"],
        "description": c["description"],
        "kind": c["kind"],
        "sheet_width_in": c["sheet_width_in"],
        "sheet_height_in": c["sheet_height_in"],
        "on_hand_qty": c["on_hand_qty"],
        "reserved_qty": c["reserved_qty"],
        "available_qty": c["on_hand_qty"] - c["reserved_qty"],
        "reorder_level": c["reorder_level"],
        **_common(c),
    }


def ser_order(o):
    return {
        "id": o["id"],
        "dealer_id": o["dealer_id"],
        "price_level_snapshot": o["price_level_snapshot"],
        "status": o["status"],
        "hold_status": order_hold_status(o["id"]),
        "cube_ft": float(o["cube_ft"]),
        "provisional_merchandise_cents": o["provisional_merchandise_cents"],
        "provisional_discount_cents": o["provisional_discount_cents"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_merchandise_cents": o["final_merchandise_cents"],
        "final_discount_cents": o["final_discount_cents"],
        "freight_cents": o["freight_cents"],
        "grand_total_cents": o["grand_total_cents"],
        "delivery_route_id": o["delivery_route_id"],
        "route_stop_seq": o["route_stop_seq"],
        "submitted_at": fmt_ts(o["submitted_at"]) if o["submitted_at"] else None,
        "shipped_at": fmt_ts(o["shipped_at"]) if o["shipped_at"] else None,
        **_common(o),
    }


def ser_order_line(l):
    return {
        "id": l["id"],
        "order_id": l["order_id"],
        "line_type": l["line_type"],
        "door_style_id": l["door_style_id"],
        "finish_id": l["finish_id"],
        "width_in": l["width_in"],
        "height_in": l["height_in"],
        "depth_in": l["depth_in"],
        "qty": l["qty"],
        "unit_list_price_cents": l["unit_list_price_cents"],
        "finish_upcharge_pct_snapshot": l["finish_upcharge_pct_snapshot"],
        "line_list_cents": l["line_list_cents"],
        "finish_upcharge_cents": l["finish_upcharge_cents"],
        "mod_surcharge_cents": l["mod_surcharge_cents"],
        "provisional_net_cents": l["provisional_net_cents"],
        "final_net_cents": l["final_net_cents"],
        "finish_batch_id": l["finish_batch_id"],
        "required_sheen_lot_no": l["required_sheen_lot_no"],
        "status": l["status"],
        "slotted_qty": line_slotted_qty(l["id"]),
        **_common(l),
    }


def ser_modification(m):
    return {
        "id": m["id"],
        "order_line_id": m["order_line_id"],
        "mod_code": m["mod_code"],
        "new_dimension_in": m["new_dimension_in"],
        "surcharge_cents": m["surcharge_cents"],
        "revision": m["revision"],
        "status": m["status"],
        "reviewer_note": m["reviewer_note"],
        **_common(m),
    }


def ser_finish_batch(b):
    return {
        "id": b["id"],
        "finish_id": b["finish_id"],
        "sheen_lot_no": b["sheen_lot_no"],
        "capacity_doors": b["capacity_doors"],
        "measured_delta_e": b["measured_delta_e"],
        "assigned_door_count": batch_assigned_door_count(b["id"]),
        "remix_count": b["remix_count"],
        "status": b["status"],
        **_common(b),
    }


def ser_nesting_station(s):
    return {
        "id": s["id"],
        "station_code": s["station_code"],
        "changeover_minutes": s["changeover_minutes"],
        "active": s["active"],
        **_common(s),
    }


def ser_nesting_run(r):
    return {
        "id": r["id"],
        "station_id": r["station_id"],
        "sheet_component_id": r["sheet_component_id"],
        "door_line_ids": list(r["door_line_ids"]),
        "scheduled_date": r["scheduled_date"],
        "start_minute": r["start_minute"],
        "end_minute": r["end_minute"],
        "status": r["status"],
        "total_blank_area_in2": r["total_blank_area_in2"],
        "sheets_required": r["sheets_required"],
        "utilization_pct": r["utilization_pct"],
        **_common(r),
    }


def ser_part(p):
    # Immutable generated record: id + created_at only, NO updated_at/version.
    return {
        "id": p["id"],
        "nesting_run_id": p["nesting_run_id"],
        "order_line_id": p["order_line_id"],
        "component_id": p["component_id"],
        "part_kind": p["part_kind"],
        "width_in": p["width_in"],
        "height_in": p["height_in"],
        "qty": p["qty"],
        "part_seq": p["part_seq"],
        "created_at": fmt_ts(p["created_at"]),
    }


def ser_assembly_line(a):
    return {
        "id": a["id"],
        "line_code": a["line_code"],
        "capacity_minutes_per_day": a["capacity_minutes_per_day"],
        "standard_minutes_per_box": a["standard_minutes_per_box"],
        "setup_minutes_per_sub_lot": a["setup_minutes_per_sub_lot"],
        "active": a["active"],
        **_common(a),
    }


def ser_sub_lot(s):
    return {
        "id": s["id"],
        "order_id": s["order_id"],
        "order_line_id": s["order_line_id"],
        "assembly_line_id": s["assembly_line_id"],
        "scheduled_date": s["scheduled_date"],
        "start_minute": s["start_minute"],
        "qty": s["qty"],
        "work_minutes": s["work_minutes"],
        "end_minute": s["end_minute"],
        "status": s["status"],
        **_common(s),
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "dealer_id": c["dealer_id"],
        "original_order_line_id": c["original_order_line_id"],
        "claim_type": c["claim_type"],
        "qty": c["qty"],
        "credit_basis_cents": c["credit_basis_cents"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "final_credit_cents": c["final_credit_cents"],
        "replacement_charge_cents": c["replacement_charge_cents"],
        "status": c["status"],
        "adjudicator_note": c["adjudicator_note"],
        **_common(c),
    }


def ser_route(r):
    orders = route_orders(r["id"])
    return {
        "id": r["id"],
        "route_code": r["route_code"],
        "route_date": r["route_date"],
        "capacity_cu_ft": r["capacity_cu_ft"],
        "reserved_cu_ft": float(route_reserved_cu_ft(r["id"])),
        "assigned_order_count": len(orders),
        "status": r["status"],
        **_common(r),
    }


def ser_hold(h):
    return {
        "id": h["id"],
        "order_id": h["order_id"],
        "component_id": h["component_id"],
        "reason": h["reason"],
        "shortfall_qty": h["shortfall_qty"],
        "status": h["status"],
        **_common(h),
    }
