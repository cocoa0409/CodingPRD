"""Entity serializers — expose exactly the scaffold fields plus common fields.

created_at / updated_at are stored as already-formatted logical-clock strings;
business datetimes are stored as datetimes under private _*_dt keys.
"""
from db import fmt_dt
import services


def customer_account(a):
    return {
        "id": a["id"],
        "account_name": a["account_name"],
        "account_type": a["account_type"],
        "fleet_tier": a["fleet_tier"],
        "credit_limit_cents": a["credit_limit_cents"],
        "open_ar_cents": a["open_ar_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def factory_build_slot(s):
    return {
        "id": s["id"],
        "build_month": s["build_month"],
        "vocation_group": s["vocation_group"],
        "capacity": s["capacity"],
        "held_count": s["held_count"],
        "committed_count": s["committed_count"],
        "slots_available": services.slots_available(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def factory_order(o):
    return {
        "id": o["id"],
        "customer_account_id": o["customer_account_id"],
        "factory_build_slot_id": o["factory_build_slot_id"],
        "chassis_model": o["chassis_model"],
        "engine_option": o["engine_option"],
        "axle_config": o["axle_config"],
        "vocation_group": o["vocation_group"],
        "upfit_lines": [dict(l) for l in o["upfit_lines"]],
        "hold_expires_at": fmt_dt(o.get("_hold_expires_dt")),
        "provisional_total_cents": o["provisional_total_cents"],
        "committed_total_cents": o["committed_total_cents"],
        "received_unit_id": o["received_unit_id"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def unit(u):
    days = services.days_in_stock(u)
    return {
        "id": u["id"],
        "vin": u["vin"],
        "unit_kind": u["unit_kind"],
        "factory_order_id": u["factory_order_id"],
        "trade_appraisal_id": u["trade_appraisal_id"],
        "status": u["status"],
        "invoice_cost_cents": u["invoice_cost_cents"],
        "stocking_date": u["stocking_date"],
        "days_in_stock": days,
        "aging_bucket": services.aging_bucket(days),
        "floorplan_active": u["floorplan_active"],
        "apr_bp": u["apr_bp"],
        "floorplan_balance_cents": u["floorplan_balance_cents"],
        "last_accrual_date": u["last_accrual_date"],
        "curtailment_due_cents": services.curtailment_due(u, days),
        "recondition_count": u["recondition_count"],
        "sold_price_cents": u["sold_price_cents"],
        "sold_at": fmt_dt(u.get("_sold_at_dt")),
        "wholesale_price_cents": u["wholesale_price_cents"],
        "wholesale_loss_cents": u["wholesale_loss_cents"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def floor_plan_entry(e):
    return {
        "id": e["id"],
        "unit_id": e["unit_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "entry_date": e["entry_date"],
        "note": e["note"],
        "resulting_balance_cents": e["resulting_balance_cents"],
        "created_at": e["created_at"],
    }


def trade_appraisal(a):
    return {
        "id": a["id"],
        "customer_account_id": a["customer_account_id"],
        "trade_vin": a["trade_vin"],
        "model_year": a["model_year"],
        "mileage": a["mileage"],
        "condition_grade": a["condition_grade"],
        "base_book_value_cents": a["base_book_value_cents"],
        "book_estimate_cents": a["book_estimate_cents"],
        "market_index_bp": a["market_index_bp"],
        "offer_acv_cents": a["offer_acv_cents"],
        "offered_allowance_cents": a["offered_allowance_cents"],
        "offer_expires_at": fmt_dt(a.get("_offer_expires_dt")),
        "offer_round": a["offer_round"],
        "created_unit_id": a["created_unit_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def service_bay(b):
    return {
        "id": b["id"],
        "bay_code": b["bay_code"],
        "bay_type": b["bay_type"],
        "open_hour": b["open_hour"],
        "close_hour": b["close_hour"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def mobile_service_unit(m):
    return {
        "id": m["id"],
        "unit_code": m["unit_code"],
        "default_travel_minutes": m["default_travel_minutes"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def repair_order(r):
    return {
        "id": r["id"],
        "customer_account_id": r["customer_account_id"],
        "unit_id": r["unit_id"],
        "external_vin": r["external_vin"],
        "concern": r["concern"],
        "promised_ready_at": fmt_dt(r.get("_promised_dt")),
        "labor_rate_cents": r["labor_rate_cents"],
        "auth_status": r["auth_status"],
        "work_status": r["work_status"],
        "labor_sum_cents": r["labor_sum_cents"],
        "parts_sum_cents": r["parts_sum_cents"],
        "discount_cents": r["discount_cents"],
        "shop_supplies_fee_cents": r["shop_supplies_fee_cents"],
        "warranty_covered_cents": r["warranty_covered_cents"],
        "customer_due_cents": r["customer_due_cents"],
        "downtime_penalty_cents": r["downtime_penalty_cents"],
        "work_started_at": fmt_dt(r.get("_work_started_dt")),
        "completed_at": fmt_dt(r.get("_completed_dt")),
        "sla_breached": r["sla_breached"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def repair_order_line(l):
    return {
        "id": l["id"],
        "repair_order_id": l["repair_order_id"],
        "line_type": l["line_type"],
        "part_id": l["part_id"],
        "description": l["description"],
        "hours": l["hours"],
        "quantity": l["quantity"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "warranty_eligible": l["warranty_eligible"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def service_booking(b):
    return {
        "id": b["id"],
        "repair_order_id": b["repair_order_id"],
        "service_bay_id": b["service_bay_id"],
        "mobile_service_unit_id": b["mobile_service_unit_id"],
        "start_at": fmt_dt(b.get("_start_dt")),
        "end_at": fmt_dt(b.get("_end_dt")),
        "travel_minutes": b["travel_minutes"],
        "status": b["status"],
        "checked_in_at": fmt_dt(b.get("_checked_in_dt")),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def warranty_claim(c):
    return {
        "id": c["id"],
        "repair_order_id": c["repair_order_id"],
        "claimed_labor_cents": c["claimed_labor_cents"],
        "claimed_parts_cents": c["claimed_parts_cents"],
        "approved_labor_cents": c["approved_labor_cents"],
        "approved_parts_cents": c["approved_parts_cents"],
        "paid_cents": c["paid_cents"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "submitted_at": fmt_dt(c.get("_submitted_dt")),
        "adjudicated_at": fmt_dt(c.get("_adjudicated_dt")),
        "denial_reason": c["denial_reason"],
        "appeal_notes": c["appeal_notes"],
        "appeal_count": c["appeal_count"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def part(p):
    return {
        "id": p["id"],
        "sku": p["sku"],
        "part_name": p["part_name"],
        "list_price_cents": p["list_price_cents"],
        "cost_cents": p["cost_cents"],
        "on_hand": p["on_hand"],
        "has_core_charge": p["has_core_charge"],
        "core_charge_cents": p["core_charge_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def parts_sale(s):
    return {
        "id": s["id"],
        "customer_account_id": s["customer_account_id"],
        "lines": [dict(l) for l in s["lines"]],
        "subtotal_cents": s["subtotal_cents"],
        "core_total_cents": s["core_total_cents"],
        "total_cents": s["total_cents"],
        "sold_at": fmt_dt(s.get("_sold_at_dt")),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def parts_sale_line(l):
    return {
        "id": l["id"],
        "parts_sale_id": l["parts_sale_id"],
        "part_id": l["part_id"],
        "quantity": l["quantity"],
        "unit_net_price_cents": l["unit_net_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "returned_quantity": l["returned_quantity"],
        "return_credit_cents": l["return_credit_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }
