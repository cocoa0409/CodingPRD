"""Entity serializers — exact field sets per SCAFFOLD §1.1. Internal fields
(prefixed _) are never exposed. Event-log entities carry only id/created_at.
"""


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_distributor(d):
    out = _common(d)
    out.update({
        "name": d["name"],
        "license_number": d["license_number"],
        "credit_terms_days": d["credit_terms_days"],
    })
    return out


def serialize_route(r):
    out = _common(r)
    out.update({
        "distributor_id": r["distributor_id"],
        "route_code": r["route_code"],
        "name": r["name"],
        "service_weekdays": list(r["service_weekdays"]),
        "credit_price_basis": r["credit_price_basis"],
        "status": r["status"],
    })
    return out


def serialize_driver(d):
    out = _common(d)
    out.update({
        "distributor_id": d["distributor_id"],
        "name": d["name"],
        "cdl_class": d["cdl_class"],
    })
    return out


def serialize_store(s):
    out = _common(s)
    out.update({
        "route_id": s["route_id"],
        "store_code": s["store_code"],
        "name": s["name"],
        "credit_limit_cents": s["credit_limit_cents"],
        "pull_window_days": s["pull_window_days"],
        "crate_deposit_cents": s["crate_deposit_cents"],
        "merchandising_rate_cents_per_min": s["merchandising_rate_cents_per_min"],
        "free_merchandising_minutes": s["free_merchandising_minutes"],
        "dock_open_min": s["dock_open_min"],
        "dock_close_min": s["dock_close_min"],
        "status": s["status"],
        "crate_balance": s["crate_balance"],
        "open_ar_cents": s["open_ar_cents"],
        "deposit_liability_cents": s["deposit_liability_cents"],
    })
    return out


def serialize_product(p):
    out = _common(p)
    out.update({
        "sku": p["sku"],
        "name": p["name"],
        "units_per_case": p["units_per_case"],
        "weight_lbs_per_unit": p["weight_lbs_per_unit"],
        "shelf_life_days": p["shelf_life_days"],
        "regulated": p["regulated"],
        "list_price_cents": p["list_price_cents"],
        "margin_cents_per_unit": p["margin_cents_per_unit"],
        "status": p["status"],
    })
    return out


def serialize_par(p):
    out = _common(p)
    out.update({
        "store_id": p["store_id"],
        "product_id": p["product_id"],
        "par_mon": p["par_mon"],
        "par_tue": p["par_tue"],
        "par_wed": p["par_wed"],
        "par_thu": p["par_thu"],
        "par_fri": p["par_fri"],
        "par_sat": p["par_sat"],
        "par_sun": p["par_sun"],
        "status": p["status"],
    })
    return out


def serialize_pricing_period(p):
    out = _common(p)
    out.update({
        "month": p["month"],
        "status": p["status"],
        "current_provisional_id": p["current_provisional_id"],
        "current_final_id": p["current_final_id"],
    })
    return out


def serialize_announcement(a):
    out = _common(a)
    out.update({
        "pricing_period_id": a["pricing_period_id"],
        "kind": a["kind"],
        "class_i_base_cents_per_cwt": a["class_i_base_cents_per_cwt"],
        "processor_assessment_cents_per_cwt": a["processor_assessment_cents_per_cwt"],
        "hauling_cents_per_cwt": a["hauling_cents_per_cwt"],
        "diesel_index_cents": a["diesel_index_cents"],
        "supersedes_announcement_id": a["supersedes_announcement_id"],
        "status": a["status"],
    })
    return out


def serialize_trip(t):
    out = _common(t)
    out.update({
        "route_id": t["route_id"],
        "driver_id": t["driver_id"],
        "service_date": t["service_date"],
        "truck_plate": t["truck_plate"],
        "case_capacity": t["case_capacity"],
        "planned_depart_at": t["planned_depart_at"],
        "planned_return_at": t["planned_return_at"],
        "status": t["status"],
        "excursion_minutes": t["excursion_minutes"],
        "cold_chain_breach": t["cold_chain_breach"],
        "loaded_cases": t["loaded_cases"],
        "delivered_cases": t["delivered_cases"],
    })
    return out


def serialize_reading(r):
    # Event-log entity: id and created_at only (no updated_at / version).
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "trip_id": r["trip_id"],
        "recorded_at": r["recorded_at"],
        "temp_tenths_f": r["temp_tenths_f"],
        "zone": r["zone"],
    }


def _serialize_line(line):
    out = {
        "product_id": line["product_id"],
        "quantity_units": line["quantity_units"],
    }
    # `cases` is gained at creation for manual orders and at confirm for
    # generated orders; delivery-phase fields are gained at deliver time only.
    for k in ("cases", "delivered_units", "scanned_code_date", "unit_price_cents",
              "line_amount_cents", "cold_chain_flag"):
        if k in line:
            out[k] = line[k]
    return out


def serialize_order(o):
    out = _common(o)
    out.update({
        "store_id": o["store_id"],
        "trip_id": o["trip_id"],
        "service_date": o["service_date"],
        "source": o["source"],
        "lines": [_serialize_line(l) for l in o["lines"]],
        "delivery_window_start": o["delivery_window_start"],
        "delivery_window_end": o["delivery_window_end"],
        "fulfillment_status": o["fulfillment_status"],
        "payment_status": o["payment_status"],
        "subtotal_cents": o["subtotal_cents"],
    })
    return out


def serialize_invoice(inv):
    out = _common(inv)
    out.update({
        "order_id": inv["order_id"],
        "store_id": inv["store_id"],
        "invoice_month": inv["invoice_month"],
        "pricing_basis": inv["pricing_basis"],
        "subtotal_cents": inv["subtotal_cents"],
        "discount_cents": inv["discount_cents"],
        "total_cents": inv["total_cents"],
        "credits_applied_cents": inv["credits_applied_cents"],
        "payments_applied_cents": inv["payments_applied_cents"],
        "amount_due_cents": inv["amount_due_cents"],
        "true_up_delta_cents": inv["true_up_delta_cents"],
        "status": inv["status"],
    })
    return out


def serialize_return(r):
    out = _common(r)
    out.update({
        "order_id": r["order_id"],
        "store_id": r["store_id"],
        "pickup_trip_id": r["pickup_trip_id"],
        "product_id": r["product_id"],
        "quantity_units": r["quantity_units"],
        "reason_code": r["reason_code"],
        "scanned_code_date": r["scanned_code_date"],
        "days_to_expiry_at_scan": r["days_to_expiry_at_scan"],
        "credit_pct": r["credit_pct"],
        "unit_credit_cents": r["unit_credit_cents"],
        "credit_amount_cents": r["credit_amount_cents"],
        "status": r["status"],
    })
    return out


def serialize_credit_memo(m):
    out = _common(m)
    out.update({
        "return_id": m["return_id"],
        "store_id": m["store_id"],
        "invoice_id": m["invoice_id"],
        "amount_cents": m["amount_cents"],
        "applied_cents": m["applied_cents"],
        "remaining_cents": m["remaining_cents"],
        "status": m["status"],
    })
    return out


def serialize_crate_tx(c):
    # Event-log entity: id and created_at only.
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "store_id": c["store_id"],
        "kind": c["kind"],
        "crate_count": c["crate_count"],
        "service_date": c["service_date"],
        "note": c["note"],
    }


def serialize_session(s):
    out = _common(s)
    out.update({
        "trip_id": s["trip_id"],
        "store_id": s["store_id"],
        "driver_id": s["driver_id"],
        "check_in_at": s["check_in_at"],
        "check_out_at": s["check_out_at"],
        "minutes": s["minutes"],
        "billable_minutes": s["billable_minutes"],
        "labor_charge_cents": s["labor_charge_cents"],
        "status": s["status"],
    })
    return out


def serialize_listing(l):
    out = _common(l)
    out.update({
        "route_id": l["route_id"],
        "seller_distributor_id": l["seller_distributor_id"],
        "asking_price_cents": l["asking_price_cents"],
        "trailing_weeks": l["trailing_weeks"],
        "territory_value_cents": l["territory_value_cents"],
        "buyer_distributor_id": l["buyer_distributor_id"],
        "offer_price_cents": l["offer_price_cents"],
        "status": l["status"],
    })
    return out
