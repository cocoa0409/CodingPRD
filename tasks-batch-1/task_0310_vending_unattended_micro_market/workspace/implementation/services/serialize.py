"""Serializers: produce the public JSON shape for each entity."""
from db import public


def _base(obj, common=True):
    out = {"id": obj["id"], "created_at": obj["created_at"]}
    if common:
        out["updated_at"] = obj["updated_at"]
        out["version"] = obj["version"]
    return out


def host_site(o):
    out = _base(o)
    out.update({
        "name": o["name"],
        "contact_email": o["contact_email"],
        "commission_model": o["commission_model"],
        "flat_commission_pct": o["flat_commission_pct"],
        "monthly_guarantee_cents": o["monthly_guarantee_cents"],
        "lifetime_commission_cents": o["lifetime_commission_cents"],
        "status": o["status"],
    })
    return out


def product(o):
    out = _base(o)
    out.update({
        "sku": o["sku"],
        "name": o["name"],
        "category": o["category"],
        "unit_cost_cents": o["unit_cost_cents"],
        "shelf_life_days": o["shelf_life_days"],
        "status": o["status"],
    })
    return out


def machine(o):
    out = _base(o)
    out.update({
        "host_site_id": o["host_site_id"],
        "asset_tag": o["asset_tag"],
        "machine_type": o["machine_type"],
        "cash_capacity_cents": o["cash_capacity_cents"],
        "cash_on_hand_cents": o["cash_on_hand_cents"],
        "cash_alert_threshold_pct": o["cash_alert_threshold_pct"],
        "par_fill_threshold_pct": o["par_fill_threshold_pct"],
        "stock_status": o["stock_status"],
        "cash_status": o["cash_status"],
        "service_status": o["service_status"],
    })
    return out


def slot(o):
    out = _base(o)
    out.update({
        "machine_id": o["machine_id"],
        "product_id": o["product_id"],
        "slot_code": o["slot_code"],
        "capacity": o["capacity"],
        "par_level": o["par_level"],
        "price_cents": o["price_cents"],
        "on_hand": o["on_hand"],
        "status": o["status"],
    })
    return out


def lot(o):
    out = _base(o)
    out.update({
        "slot_id": o["slot_id"],
        "machine_id": o["machine_id"],
        "filled_units": o["filled_units"],
        "unit_cost_cents": o["unit_cost_cents"],
        "remaining_units": o["remaining_units"],
        "expiration_date": o["expiration_date"],
        "restock_visit_id": o["restock_visit_id"],
        "status": o["status"],
    })
    return out


def driver(o):
    out = _base(o)
    out.update({
        "full_name": o["full_name"],
        "employee_code": o["employee_code"],
        "status": o["status"],
    })
    return out


def route(o):
    out = _base(o)
    out.update({
        "driver_id": o["driver_id"],
        "service_date": o["service_date"],
        "status": o["status"],
    })
    return out


def stop(o):
    out = _base(o)
    out.update({
        "route_id": o["route_id"],
        "machine_id": o["machine_id"],
        "window_start_min": o["window_start_min"],
        "window_end_min": o["window_end_min"],
        "prekit_json": o["prekit_json"],
        "status": o["status"],
    })
    return out


def visit(o):
    out = _base(o)
    out.update({
        "route_stop_id": o["route_stop_id"],
        "machine_id": o["machine_id"],
        "counted_lines": o["counted_lines"],
        "total_shrink_units": o["total_shrink_units"],
        "shrink_value_cents": o["shrink_value_cents"],
        "expected_machine_version": o["expected_machine_version"],
        "status": o["status"],
    })
    return out


def sale(o):
    # Sale is an immutable event: only id + created_at (PRD 2.4)
    out = _base(o, common=False)
    out.update({
        "machine_id": o["machine_id"],
        "slot_id": o["slot_id"],
        "lot_consumption_json": o["lot_consumption_json"],
        "quantity": o["quantity"],
        "unit_price_cents": o["unit_price_cents"],
        "gross_cents": o["gross_cents"],
        "provisional_cogs_cents": o["provisional_cogs_cents"],
        "payment_method": o["payment_method"],
        "settlement_status": o["settlement_status"],
    })
    return out


def statement(o):
    from services.commission import recompute_amounts
    # While OPEN, amounts are recomputed live on every read (PRD 3.7).
    if o["status"] == "OPEN":
        recompute_amounts(o)
    out = _base(o)
    out.update({
        "host_site_id": o["host_site_id"],
        "period_start": o["period_start"],
        "period_end": o["period_end"],
        "gross_sales_cents": o["gross_sales_cents"],
        "shrink_chargeback_cents": o["shrink_chargeback_cents"],
        "gross_commission_cents": o["gross_commission_cents"],
        "net_commission_cents": o["net_commission_cents"],
        "status": o["status"],
    })
    return out


def ticket(o):
    out = _base(o)
    out.update({
        "machine_id": o["machine_id"],
        "issue_type": o["issue_type"],
        "blocking": o["blocking"],
        "status": o["status"],
    })
    return out
