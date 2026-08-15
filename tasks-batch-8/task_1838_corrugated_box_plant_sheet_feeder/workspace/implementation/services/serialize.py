"""Entity serializers: convert internal dict records (with Decimal fields) to JSON-safe dicts."""
from util import d2f


def _base(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_customer(c):
    out = _base(c)
    out.update({
        "account_name": c["account_name"],
        "ship_to_city": c["ship_to_city"],
        "distance_miles_from_plant": d2f(c["distance_miles_from_plant"]),
        "credit_limit_dollars": d2f(c["credit_limit_dollars"]),
        "credit_exposure_dollars": d2f(c["credit_exposure_dollars"]),
    })
    return out


def serialize_board_grade(g):
    out = _base(g)
    out.update({
        "grade_code": g["grade_code"],
        "liner_combo": g["liner_combo"],
        "flute": g["flute"],
        "ect_rating_lbs_per_in": g["ect_rating_lbs_per_in"],
        "burst_rating_psi": g["burst_rating_psi"],
        "basis_weight_lbs_per_msf": d2f(g["basis_weight_lbs_per_msf"]),
        "status": g["status"],
    })
    return out


def serialize_work_shift(s):
    out = _base(s)
    out.update({
        "machine_code": s["machine_code"],
        "shift_date": s["shift_date"],
        "start_minute": s["start_minute"],
        "end_minute": s["end_minute"],
        "capacity_minutes": s["capacity_minutes"],
        "scheduled_minutes": s["scheduled_minutes"],
        "available_minutes": s["available_minutes"],
        "status": s["status"],
    })
    return out


def serialize_corrugator_run(r):
    out = _base(r)
    out.update({
        "work_shift_id": r["work_shift_id"],
        "board_grade_id": r["board_grade_id"],
        "start_minute": r["start_minute"],
        "end_minute": r["end_minute"],
        "web_width_in": d2f(r["web_width_in"]),
        "consumed_width_in": d2f(r["consumed_width_in"]),
        "trim_waste_in": d2f(r["trim_waste_in"]),
        "trim_waste_pct": d2f(r["trim_waste_pct"]),
        "status": r["status"],
    })
    return out


def serialize_box_order(o):
    out = _base(o)
    out.update({
        "customer_id": o["customer_id"],
        "board_grade_id": o["board_grade_id"],
        "routing_type": o["routing_type"],
        "board_source": o["board_source"],
        "sheet_supplier_name": o["sheet_supplier_name"],
        "quantity": o["quantity"],
        "blank_width_in": d2f(o["blank_width_in"]),
        "blank_length_in": d2f(o["blank_length_in"]),
        "min_ect_required": o["min_ect_required"],
        "ink_colors": list(o["ink_colors"]),
        "color_count": o["color_count"],
        "corrugator_run_id": o["corrugator_run_id"],
        "area_sqft_per_box": d2f(o["area_sqft_per_box"]),
        "committed_value_dollars": d2f(o["committed_value_dollars"]),
        "produced_qty": o["produced_qty"],
        "invoice_billable_msf": d2f(o["invoice_billable_msf"]),
        "invoice_merchandise_dollars": d2f(o["invoice_merchandise_dollars"]),
        "invoice_discount_dollars": d2f(o["invoice_discount_dollars"]),
        "invoice_freight_dollars": d2f(o["invoice_freight_dollars"]),
        "invoice_total_dollars": d2f(o["invoice_total_dollars"]),
        "status": o["status"],
    })
    return out


def serialize_price_quote(q):
    out = _base(q)
    out.update({
        "order_id": q["order_id"],
        "unit_price_per_msf": d2f(q["unit_price_per_msf"]),
        "expires_on": q["expires_on"],
        "billable_msf": d2f(q["billable_msf"]),
        "freight_tier": q["freight_tier"],
        "merchandise_total_dollars": d2f(q["merchandise_total_dollars"]),
        "discount_pct": d2f(q["discount_pct"]),
        "discount_dollars": d2f(q["discount_dollars"]),
        "freight_charge_dollars": d2f(q["freight_charge_dollars"]),
        "quote_total_dollars": d2f(q["quote_total_dollars"]),
        "status": q["status"],
    })
    return out


def serialize_converting_booking(b):
    out = _base(b)
    out.update({
        "work_shift_id": b["work_shift_id"],
        "box_order_id": b["box_order_id"],
        "start_minute": b["start_minute"],
        "end_minute": b["end_minute"],
        "ink_colors": list(b["ink_colors"]),
        "status": b["status"],
    })
    return out


def serialize_inventory_program(p):
    out = _base(p)
    out.update({
        "customer_id": p["customer_id"],
        "board_grade_id": p["board_grade_id"],
        "program_name": p["program_name"],
        "routing_type": p["routing_type"],
        "blank_width_in": d2f(p["blank_width_in"]),
        "blank_length_in": d2f(p["blank_length_in"]),
        "reorder_point": p["reorder_point"],
        "replenishment_qty": p["replenishment_qty"],
        "on_hand_qty": p["on_hand_qty"],
        "committed_qty": p["committed_qty"],
        "available_qty": p["available_qty"],
        "status": p["status"],
    })
    return out


def serialize_release_order(r):
    out = _base(r)
    out.update({
        "program_id": r["program_id"],
        "qty": r["qty"],
        "requested_ship_date": r["requested_ship_date"],
        "status": r["status"],
    })
    return out


def serialize_quality_claim(c):
    out = _base(c)
    out.update({
        "box_order_id": c["box_order_id"],
        "claim_type": c["claim_type"],
        "defective_qty_claimed": c["defective_qty_claimed"],
        "measured_warp_pct": d2f(c["measured_warp_pct"]),
        "per_box_price_dollars": d2f(c["per_box_price_dollars"]),
        "provisional_credit_dollars": d2f(c["provisional_credit_dollars"]),
        "defective_qty_verified": c["defective_qty_verified"],
        "actual_return_freight_dollars": d2f(c["actual_return_freight_dollars"]),
        "final_credit_dollars": d2f(c["final_credit_dollars"]),
        "filed_by_user_id": c["filed_by_user_id"],
        "adjudicated_by_user_id": c["adjudicated_by_user_id"],
        "status": c["status"],
    })
    return out
