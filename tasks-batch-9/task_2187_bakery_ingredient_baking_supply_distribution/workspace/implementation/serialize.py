"""Entity -> JSON serialisers. Field sets follow SCAFFOLD §entities."""
import store
from store import iso, iso_sec, out_num, out_qty


def _common(rec, out, versioned=True):
    out["id"] = rec["id"]
    out["created_at"] = iso(rec["created_at"])
    if versioned:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def customer(rec):
    return _common(rec, {
        "legal_name": rec["legal_name"],
        "status": rec["status"],
        "allergen_program": rec["allergen_program"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "open_exposure_cents": rec["open_exposure_cents"],
        "min_drop_cents": rec["min_drop_cents"],
        "allergen_risk_score": out_num(rec["allergen_risk_score"], 2),
        "risk_tier": rec["risk_tier"],
    })


def product(rec):
    return _common(rec, {
        "sku": rec["sku"],
        "category": rec["category"],
        "allergen_class": rec["allergen_class"],
        "bulk_capable": rec["bulk_capable"],
        "shelf_life_days": rec["shelf_life_days"],
        "index_code": rec["index_code"],
        "list_price_cents_per_lb": rec["list_price_cents_per_lb"],
        "min_rotation_days": rec["min_rotation_days"],
    })


def quote(rec):
    return _common(rec, {
        "index_code": rec["index_code"],
        "effective_on": iso_sec(rec["effective_on"]),
        "price_cents_per_lb": rec["price_cents_per_lb"],
    }, versioned=False)


def contract(rec):
    return _common(rec, {
        "customer_id": rec["customer_id"],
        "status": rec["status"],
        "authored_by_user_id": rec["authored_by_user_id"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "negotiation_round": rec["negotiation_round"],
        "term_start_on": iso_sec(rec["term_start_on"]),
        "term_end_on": iso_sec(rec["term_end_on"]),
        "pricing_mode": rec["pricing_mode"],
        "committed_volume_lb": out_qty(rec["committed_volume_lb"]),
        "drawn_volume_lb": out_qty(rec["drawn_volume_lb"]),
    })


def contract_line(rec):
    return _common(rec, {
        "contract_id": rec["contract_id"],
        "product_id": rec["product_id"],
        "volume_committed_lb": out_qty(rec["volume_committed_lb"]),
        "volume_drawn_lb": out_qty(rec["volume_drawn_lb"]),
        "basis_cents_per_lb": rec["basis_cents_per_lb"],
        "cap_cents_per_lb": rec["cap_cents_per_lb"],
    })


def zone(rec):
    return _common(rec, {
        "zone_code": rec["zone_code"],
        "allergen_class": rec["allergen_class"],
        "status": rec["status"],
        "lockout_start_at": iso_sec(rec["lockout_start_at"]),
        "lockout_end_at": iso_sec(rec["lockout_end_at"]),
        "on_hand_lb": out_qty(rec["on_hand_lb"]),
    })


def lot(rec):
    return _common(rec, {
        "lot_code": rec["lot_code"],
        "product_id": rec["product_id"],
        "zone_id": rec["zone_id"],
        "manufactured_on": iso_sec(rec["manufactured_on"]),
        "expires_on": iso_sec(rec["expires_on"]),
        "quantity_received_lb": out_qty(rec["quantity_received_lb"]),
        "quantity_on_hand_lb": out_qty(rec["quantity_on_hand_lb"]),
        "quantity_reserved_lb": out_qty(rec["quantity_reserved_lb"]),
        "quantity_consumed_lb": out_qty(rec["quantity_consumed_lb"]),
        "status": rec["status"],
        "quarantine_reason": rec["quarantine_reason"],
    })


def silo(rec):
    return _common(rec, {
        "silo_code": rec["silo_code"],
        "customer_id": rec["customer_id"],
        "product_id": rec["product_id"],
        "capacity_lb": out_qty(rec["capacity_lb"]),
        "residual_lb": out_qty(rec["residual_lb"]),
        "min_fill_lb": out_qty(rec["min_fill_lb"]),
        "last_fill_window_start_at": iso_sec(rec["last_fill_window_start_at"]),
        "last_fill_window_end_at": iso_sec(rec["last_fill_window_end_at"]),
    })


def order(rec):
    return _common(rec, {
        "customer_id": rec["customer_id"],
        "contract_id": rec["contract_id"],
        "delivery_mode": rec["delivery_mode"],
        "requested_delivery_on": iso_sec(rec["requested_delivery_on"]),
        "fulfillment_status": rec["fulfillment_status"],
        "pricing_status": rec["pricing_status"],
        "order_placed_on": iso_sec(rec["order_placed_on"]),
        "delivered_on": iso_sec(rec["delivered_on"]),
        "subtotal_cents": rec["subtotal_cents"],
        "fuel_surcharge_cents": rec["fuel_surcharge_cents"],
        "tech_attach_fee_cents": rec["tech_attach_fee_cents"],
        "volume_rebate_cents": rec["volume_rebate_cents"],
        "total_cents": rec["total_cents"],
        "surge_window": rec["surge_window"],
        "short_ship_lb": out_qty(rec["short_ship_lb"]),
    })


def order_line(rec):
    return _common(rec, {
        "order_id": rec["order_id"],
        "product_id": rec["product_id"],
        "substituted_from_product_id": rec["substituted_from_product_id"],
        "lot_id": rec["lot_id"],
        "silo_id": rec["silo_id"],
        "quantity_lb": out_qty(rec["quantity_lb"]),
        "allocation_status": rec["allocation_status"],
        "unit_price_cents": rec["unit_price_cents"],
        "extended_cents": rec["extended_cents"],
        "contract_line_id": rec["contract_line_id"],
    })


def substitution(rec):
    return _common(rec, {
        "order_line_id": rec["order_line_id"],
        "proposed_product_id": rec["proposed_product_id"],
        "status": rec["status"],
        "requested_by_user_id": rec["requested_by_user_id"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "revision_round": rec["revision_round"],
        "rationale": rec["rationale"],
    })


def route(rec):
    return _common(rec, {
        "route_code": rec["route_code"],
        "service_on": iso_sec(rec["service_on"]),
        "vehicle_capacity_lb": out_qty(rec["vehicle_capacity_lb"]),
        "allergen_class_lock": rec["allergen_class_lock"],
        "service_buffer_minutes": rec["service_buffer_minutes"],
        "status": rec["status"],
        "planned_load_lb": out_qty(rec["planned_load_lb"]),
        "utilization_pct": out_num(rec["utilization_pct"], 2),
        "stop_count": rec["stop_count"],
    })


def route_stop(rec):
    return _common(rec, {
        "route_id": rec["route_id"],
        "order_id": rec["order_id"],
        "window_start_at": iso_sec(rec["window_start_at"]),
        "window_end_at": iso_sec(rec["window_end_at"]),
        "sequence_no": rec["sequence_no"],
        "status": rec["status"],
    })


def engagement(rec):
    return _common(rec, {
        "customer_id": rec["customer_id"],
        "product_id": rec["product_id"],
        "order_id": rec["order_id"],
        "status": rec["status"],
        "hours_logged": out_qty(rec["hours_logged"], 1),
        "attach_fee_cents": rec["attach_fee_cents"],
        "assigned_specialist_user_id": rec["assigned_specialist_user_id"],
    })


def pricing_summary(rec, lines, quote_for_line):
    data = order(rec)
    data["lines"] = []
    for ln in lines:
        item = order_line(ln)
        q = quote_for_line.get(ln["id"])
        item["index_quote"] = quote(q) if q is not None else None
        data["lines"].append(item)
    return data
